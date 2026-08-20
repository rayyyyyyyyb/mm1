from __future__ import annotations

import copy
import json
from pathlib import Path
import random
import subprocess
import sys

import numpy as np
import torch
from torch import nn
from torch.optim import SGD
from torch.optim.lr_scheduler import StepLR
from torch.utils.data import DataLoader, Dataset

from scripts.train_ov_orthkd import checkpoint_payload, maybe_resume, set_seed
from src.data import create_ov_avel_data_loaders
from src.data.ov_avel_dataset import seed_worker


class _AugmentedRegressionDataset(Dataset):
    def __len__(self) -> int:
        return 12

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor, int]:
        augmentation = random.random() + float(np.random.rand()) + float(torch.rand(()))
        feature = torch.tensor([float(index) + augmentation * 0.01], dtype=torch.float32)
        target = torch.tensor([float(index) * 0.2 + 1.0], dtype=torch.float32)
        return feature, target, index


def _objects(initial_state: dict[str, torch.Tensor], generator_seed: int):
    model = nn.Linear(1, 1)
    model.load_state_dict(initial_state)
    loss_module = nn.Identity()
    optimizer = SGD(model.parameters(), lr=0.01, momentum=0.9)
    scheduler = StepLR(optimizer, step_size=1, gamma=0.8)
    generator = torch.Generator().manual_seed(generator_seed)
    loader = DataLoader(
        _AugmentedRegressionDataset(),
        batch_size=3,
        shuffle=True,
        num_workers=2,
        persistent_workers=False,
        worker_init_fn=seed_worker,
        generator=generator,
    )
    return model, loss_module, optimizer, scheduler, generator, loader


def _run_epoch(model: nn.Module, optimizer: SGD, scheduler: StepLR, loader: DataLoader):
    ids: list[int] = []
    losses: list[float] = []
    for features, targets, batch_ids in loader:
        ids.extend(int(value) for value in batch_ids.tolist())
        optimizer.zero_grad(set_to_none=True)
        loss = ((model(features) - targets) ** 2).mean()
        loss.backward()
        optimizer.step()
        losses.append(float(loss.detach()))
    scheduler.step()
    return {"ids": ids, "losses": losses}


def _assert_nested_equal(left, right) -> None:
    assert type(left) is type(right)
    if isinstance(left, dict):
        assert left.keys() == right.keys()
        for key in left:
            _assert_nested_equal(left[key], right[key])
    elif isinstance(left, (list, tuple)):
        assert len(left) == len(right)
        for left_item, right_item in zip(left, right):
            _assert_nested_equal(left_item, right_item)
    elif torch.is_tensor(left):
        assert torch.equal(left, right)
    else:
        assert left == right


def test_three_epoch_worker_augmentation_resume_is_exact(tmp_path: Path) -> None:
    torch.manual_seed(44)
    initial_state = copy.deepcopy(nn.Linear(1, 1).state_dict())
    set_seed(91, deterministic=True)
    model, loss_module, optimizer, scheduler, generator, loader = _objects(initial_state, 1234)
    first_history = [_run_epoch(model, optimizer, scheduler, loader)]
    payload = checkpoint_payload(
        epoch=0,
        global_step=4,
        best_metric=0.7,
        epochs_without_improvement=3,
        student=model,
        loss_module=loss_module,
        optimizer=optimizer,
        scheduler=scheduler,
        scaler=None,
        config={"reproduction": {"implementation_mode": "test"}},
        reproduction_fingerprint={"sha256": "same"},
        loader_generators={"train": generator},
    )
    checkpoint = tmp_path / "resume.pt"
    torch.save(payload, checkpoint)
    expected_history = first_history + [
        _run_epoch(model, optimizer, scheduler, loader),
        _run_epoch(model, optimizer, scheduler, loader),
    ]
    expected_model = copy.deepcopy(model.state_dict())
    expected_optimizer = copy.deepcopy(optimizer.state_dict())
    expected_scheduler = copy.deepcopy(scheduler.state_dict())

    resumed_model, resumed_loss, resumed_optimizer, resumed_scheduler, resumed_generator, resumed_loader = _objects(
        initial_state, 1234
    )
    start_epoch, best_metric, global_step, early_stop_counter = maybe_resume(
        student=resumed_model,
        loss_module=resumed_loss,
        optimizer=resumed_optimizer,
        scheduler=resumed_scheduler,
        scaler=None,
        resume_path=str(checkpoint),
        expected_fingerprint={"sha256": "same"},
        loader_generators={"train": resumed_generator},
    )
    resumed_history = first_history + [
        _run_epoch(resumed_model, resumed_optimizer, resumed_scheduler, resumed_loader),
        _run_epoch(resumed_model, resumed_optimizer, resumed_scheduler, resumed_loader),
    ]

    assert (start_epoch, best_metric, global_step, early_stop_counter) == (1, 0.7, 4, 3)
    assert resumed_history == expected_history
    _assert_nested_equal(resumed_model.state_dict(), expected_model)
    _assert_nested_equal(resumed_optimizer.state_dict(), expected_optimizer)
    _assert_nested_equal(resumed_scheduler.state_dict(), expected_scheduler)


def test_data_loader_honors_explicit_false_persistent_workers(tmp_path: Path) -> None:
    manifest = tmp_path / "data.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "id": "sample",
                "query": "query",
                "segment_labels": [1],
                "frame_paths": [],
                "spectrogram_paths": [],
                "split_type": "seen",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    config = {
        "seed": 5,
        "data": {
            "train_manifest": str(manifest),
            "val_manifest": str(manifest),
            "path_root": str(tmp_path),
            "batch_size": 1,
            "num_workers": 2,
            "persistent_workers": False,
            "max_segments": 1,
            "allow_missing_modalities": True,
            "strict_alignment": True,
            "train_augment": True,
            "strong_teacher_dim": 3,
            "weak_teacher_dim": 4,
            "text_dim": 5,
        },
    }

    train_loader, val_loader, _ = create_ov_avel_data_loaders(config)

    assert train_loader.num_workers == 2
    assert train_loader.persistent_workers is False
    assert val_loader.persistent_workers is False


def test_training_module_sets_cublas_workspace_before_runtime_use() -> None:
    project_root = Path(__file__).resolve().parents[1]
    code = (
        "import os; "
        "os.environ.pop('CUBLAS_WORKSPACE_CONFIG', None); "
        "import scripts.train_ov_orthkd; "
        "assert os.environ.get('CUBLAS_WORKSPACE_CONFIG') == ':4096:8'"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
