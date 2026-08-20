from __future__ import annotations

from pathlib import Path

import pytest
import torch

import scripts.train_ov_orthkd as train_module
import scripts.measure_efficiency as efficiency_module
from scripts.train_ov_orthkd import (
    build_runtime_reproduction_fingerprint,
    build_scheduler,
    validate_repro_config,
)
from src.utils.canonical_readiness import validate_canonical_readiness


def test_exact_cosine_scheduler_name_and_tmax_are_executable() -> None:
    parameter = torch.nn.Parameter(torch.tensor(1.0))
    optimizer = torch.optim.AdamW([parameter], lr=0.0002, weight_decay=0.0001)

    scheduler, interval = build_scheduler(
        optimizer,
        {"scheduler": {"type": "CosineAnnealingLR", "T_max": 30, "interval": "epoch"}},
        epochs=30,
        steps_per_epoch=400,
    )

    assert isinstance(scheduler, torch.optim.lr_scheduler.CosineAnnealingLR)
    assert scheduler.T_max == 30
    assert interval == "epoch"


def test_paper_reconstruction_permits_only_taskbook_400_batch_epoch_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(train_module, "validate_canonical_readiness", lambda *args, **kwargs: {})
    config = {
        "reproduction": {
            "claim_level": "paper_specified_reconstruction",
            "full_run_blocked": False,
            "asset_download_lock_required": True,
        },
        "training": {"max_batches_per_epoch": 400, "max_optimizer_steps": None},
    }

    validate_repro_config(config, allow_blocked=False, preflight=False)

    config["training"]["max_batches_per_epoch"] = 399
    with pytest.raises(RuntimeError, match="exactly 400"):
        validate_repro_config(config, allow_blocked=False, preflight=False)


def test_download_lock_is_part_of_runtime_fingerprint(tmp_path: Path) -> None:
    lock = tmp_path / "download.yaml"
    lock.write_text("schema_version: 1\nstatus: blocked\n", encoding="utf-8")
    config = {
        "data": {"path_root": str(tmp_path)},
        "reproduction": {"readiness": {"download_lock": str(lock)}},
    }

    fingerprint = build_runtime_reproduction_fingerprint(config)

    assert fingerprint["components"]["locks"]["download_lock"]["exists"] is True


def test_r3_canonical_gate_requires_download_lock_path(tmp_path: Path) -> None:
    config = {
        "reproduction": {
            "claim_level": "paper_specified_reconstruction",
            "asset_download_lock_required": True,
            "project_root": ".",
            "readiness": {},
        },
        "data": {"path_root": str(tmp_path)},
    }

    with pytest.raises(RuntimeError, match="download_lock"):
        validate_canonical_readiness(config)


def test_cuda_latency_measurement_synchronizes_before_and_after_timed_region(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class Model:
        def eval(self):
            return self

        def to(self, _device):
            return self

        def __call__(self, *_args):
            events.append("model")

    class Event:
        instances = 0

        def __init__(self, *, enable_timing: bool):
            assert enable_timing is True
            type(self).instances += 1
            self.name = f"event{type(self).instances}"

        def record(self):
            events.append(f"{self.name}.record")

        def elapsed_time(self, _other):
            return 8.0

    monkeypatch.setattr(efficiency_module.torch, "randn", lambda *args, **kwargs: torch.zeros(1))
    monkeypatch.setattr(efficiency_module.torch, "randn_like", lambda value: torch.zeros_like(value))
    monkeypatch.setattr(efficiency_module.torch, "ones", lambda *args, **kwargs: torch.zeros(1))
    monkeypatch.setattr(efficiency_module.torch.cuda, "Event", Event)
    monkeypatch.setattr(
        efficiency_module.torch.cuda,
        "synchronize",
        lambda _device: events.append("synchronize"),
    )

    latency = efficiency_module.measure_latency(
        Model(),
        torch.device("cuda"),
        segments=1,
        image_size=1,
        text_dim=1,
        warmup=1,
        iterations=2,
    )

    assert latency == 4.0
    assert events == [
        "synchronize",
        "model",
        "synchronize",
        "event1.record",
        "model",
        "model",
        "event2.record",
        "synchronize",
    ]
