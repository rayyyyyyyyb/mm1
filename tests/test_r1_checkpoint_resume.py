from __future__ import annotations

import copy
import random
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
import torch
from torch import nn
from torch.optim import SGD
from torch.optim.lr_scheduler import StepLR
from torch.utils.data import DataLoader, TensorDataset

import scripts.train_ov_orthkd as train_module
from scripts.train_ov_orthkd import checkpoint_payload, maybe_resume
from src.utils.reproduction_fingerprint import (
    build_reproduction_fingerprint,
    capture_rng_state,
    restore_rng_state,
)


def _fingerprint(value: str) -> dict[str, Any]:
    return {"schema_version": 1, "sha256": value, "components": {}}


def test_reproduction_fingerprint_changes_with_manifest_bytes(tmp_path: Path) -> None:
    manifest = tmp_path / "train.jsonl"
    manifest.write_text('{"id":"a"}\n', encoding="utf-8")
    config = {
        "seed": 7,
        "data": {"path_root": str(tmp_path), "train_manifest": manifest.name},
        "logging": {"log_dir": str(tmp_path / "first-output")},
    }

    first = build_reproduction_fingerprint(config)
    config["logging"]["log_dir"] = str(tmp_path / "second-output")
    output_only_change = build_reproduction_fingerprint(config)
    manifest.write_text('{"id":"b"}\n', encoding="utf-8")
    data_change = build_reproduction_fingerprint(config)

    assert first["sha256"] == output_only_change["sha256"]
    assert first["sha256"] != data_change["sha256"]
    assert first["components"]["manifests"]["train"]["sha256"] != data_change["components"]["manifests"]["train"]["sha256"]


def test_rng_and_loader_generator_states_round_trip() -> None:
    random.seed(11)
    np.random.seed(12)
    torch.manual_seed(13)
    loader_generator = torch.Generator().manual_seed(14)
    state = capture_rng_state({"train": loader_generator})

    expected = (
        random.random(),
        float(np.random.rand()),
        torch.rand(3),
        torch.randperm(8, generator=loader_generator),
    )
    restore_rng_state(state, {"train": loader_generator})
    actual = (
        random.random(),
        float(np.random.rand()),
        torch.rand(3),
        torch.randperm(8, generator=loader_generator),
    )

    assert expected[0] == actual[0]
    assert expected[1] == actual[1]
    assert torch.equal(expected[2], actual[2])
    assert torch.equal(expected[3], actual[3])


def _training_objects(initial_state: dict[str, torch.Tensor], generator_seed: int):
    model = nn.Linear(1, 1)
    model.load_state_dict(initial_state)
    loss_module = nn.Identity()
    optimizer = SGD(model.parameters(), lr=0.05)
    scheduler = StepLR(optimizer, step_size=1, gamma=0.9)
    generator = torch.Generator().manual_seed(generator_seed)
    ids = torch.arange(8, dtype=torch.float32)
    loader = DataLoader(
        TensorDataset(ids[:, None], (ids * 0.25 + 1.0)[:, None], ids.to(torch.int64)),
        batch_size=2,
        shuffle=True,
        generator=generator,
        num_workers=0,
    )
    return model, loss_module, optimizer, scheduler, generator, loader


def _run_epoch(model: nn.Module, optimizer: SGD, scheduler: StepLR, loader: DataLoader):
    batch_ids: list[int] = []
    losses: list[float] = []
    for features, targets, ids in loader:
        batch_ids.extend(int(value) for value in ids.tolist())
        optimizer.zero_grad(set_to_none=True)
        rng_probe = random.random() + float(np.random.rand()) + float(torch.rand(()))
        loss = ((model(features) - targets) ** 2).mean() + rng_probe * 1e-4
        loss.backward()
        optimizer.step()
        losses.append(float(loss.detach()))
    scheduler.step()
    return batch_ids, losses


def test_epoch_boundary_resume_matches_uninterrupted_ids_losses_and_parameters(tmp_path: Path) -> None:
    torch.manual_seed(99)
    initial = nn.Linear(1, 1)
    initial_state = copy.deepcopy(initial.state_dict())
    train_module.set_seed(123, deterministic=True)
    model, loss_module, optimizer, scheduler, generator, loader = _training_objects(initial_state, 456)
    _run_epoch(model, optimizer, scheduler, loader)
    payload = checkpoint_payload(
        epoch=0,
        global_step=4,
        best_metric=0.5,
        student=model,
        loss_module=loss_module,
        optimizer=optimizer,
        scheduler=scheduler,
        scaler=None,
        config={"reproduction": {"implementation_mode": "test"}},
        reproduction_fingerprint=_fingerprint("same"),
        loader_generators={"train": generator},
    )
    checkpoint = tmp_path / "resume.pt"
    torch.save(payload, checkpoint)
    expected_ids, expected_losses = _run_epoch(model, optimizer, scheduler, loader)
    expected_parameters = copy.deepcopy(model.state_dict())

    resumed_model, resumed_loss, resumed_optimizer, resumed_scheduler, resumed_generator, resumed_loader = _training_objects(
        initial_state, 456
    )
    start_epoch, best_metric, global_step, early_stop_counter = maybe_resume(
        student=resumed_model,
        loss_module=resumed_loss,
        optimizer=resumed_optimizer,
        scheduler=resumed_scheduler,
        scaler=None,
        resume_path=str(checkpoint),
        expected_fingerprint=_fingerprint("same"),
        loader_generators={"train": resumed_generator},
    )
    actual_ids, actual_losses = _run_epoch(
        resumed_model, resumed_optimizer, resumed_scheduler, resumed_loader
    )

    assert (start_epoch, best_metric, global_step, early_stop_counter) == (1, 0.5, 4, 0)
    assert actual_ids == expected_ids
    assert actual_losses == expected_losses
    for name, value in expected_parameters.items():
        assert torch.equal(resumed_model.state_dict()[name], value), name


def test_incompatible_resume_fingerprint_is_rejected_before_state_load(tmp_path: Path) -> None:
    model = nn.Linear(1, 1)
    loss_module = nn.Identity()
    optimizer = SGD(model.parameters(), lr=0.1)
    scheduler = StepLR(optimizer, step_size=1)
    payload = checkpoint_payload(
        epoch=0,
        global_step=1,
        best_metric=0.0,
        student=model,
        loss_module=loss_module,
        optimizer=optimizer,
        scheduler=scheduler,
        scaler=None,
        config={},
        reproduction_fingerprint=_fingerprint("checkpoint"),
        loader_generators={},
    )
    checkpoint = tmp_path / "resume.pt"
    torch.save(payload, checkpoint)

    with pytest.raises(RuntimeError, match=r"fingerprint.*checkpoint.*current"):
        maybe_resume(
            student=model,
            loss_module=loss_module,
            optimizer=optimizer,
            scheduler=scheduler,
            scaler=None,
            resume_path=str(checkpoint),
            expected_fingerprint=_fingerprint("current"),
            loader_generators={},
        )


def test_explicit_incompatible_resume_override_writes_marker(tmp_path: Path) -> None:
    model = nn.Linear(1, 1)
    loss_module = nn.Identity()
    optimizer = SGD(model.parameters(), lr=0.1)
    scheduler = StepLR(optimizer, step_size=1)
    checkpoint = tmp_path / "resume.pt"
    torch.save(
        checkpoint_payload(
            epoch=0,
            global_step=1,
            best_metric=0.0,
            student=model,
            loss_module=loss_module,
            optimizer=optimizer,
            scheduler=scheduler,
            scaler=None,
            config={},
            reproduction_fingerprint=_fingerprint("checkpoint"),
            loader_generators={},
        ),
        checkpoint,
    )
    marker = tmp_path / "INCOMPATIBLE_RESUME.txt"

    maybe_resume(
        student=model,
        loss_module=loss_module,
        optimizer=optimizer,
        scheduler=scheduler,
        scaler=None,
        resume_path=str(checkpoint),
        expected_fingerprint=_fingerprint("current"),
        loader_generators={},
        allow_incompatible=True,
        incompatible_marker_path=marker,
    )

    text = marker.read_text(encoding="utf-8")
    assert "NON-CANONICAL INCOMPATIBLE RESUME" in text
    assert "checkpoint" in text
    assert "current" in text


def test_eval_only_main_never_constructs_scheduler(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = {
        "seed": 1,
        "reproduction": {"full_run_blocked": False},
        "data": {},
        "training": {"scheduler": {"type": "UNRESOLVED"}},
        "logging": {"log_dir": str(tmp_path)},
    }
    args = SimpleNamespace(
        config="unused.yaml",
        resume=None,
        eval_only=True,
        output_dir=None,
        max_train_steps=None,
        max_batches_per_epoch=None,
        max_optimizer_steps=None,
        max_eval_batches=1,
        epochs=None,
        early_stop_patience=None,
        early_stop_min_delta=None,
        allow_blocked_reproduction=False,
        allow_incompatible_resume=False,
    )
    student = nn.Linear(1, 1)
    loss_module = nn.Linear(1, 1)
    monkeypatch.setattr(train_module, "parse_args", lambda: args)
    monkeypatch.setattr(train_module, "load_config", lambda _: config)
    monkeypatch.setattr(train_module, "set_seed", lambda *args, **kwargs: None)
    monkeypatch.setattr(train_module, "write_runtime_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(train_module, "write_static_run_evidence", lambda *args, **kwargs: None)
    loader = SimpleNamespace(generator=None)
    monkeypatch.setattr(train_module, "create_ov_avel_data_loaders", lambda _: (loader, loader, None))
    monkeypatch.setattr(train_module, "build_model_and_loss", lambda *args: (student, loss_module))
    monkeypatch.setattr(
        train_module,
        "build_scheduler",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("scheduler called in eval-only")),
    )
    predictions = {"labels": np.asarray([0.0]), "probabilities": np.asarray([0.25])}
    monkeypatch.setattr(train_module, "evaluate_with_predictions", lambda *args, **kwargs: (predictions, {}))
    monkeypatch.setattr(train_module, "save_evaluation_artifacts", lambda *args, **kwargs: {"validation": {}})

    train_module.main()

    assert (tmp_path / "final_metrics.json").exists()
