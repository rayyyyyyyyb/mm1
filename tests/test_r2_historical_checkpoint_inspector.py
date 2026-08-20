from __future__ import annotations

import json
from pathlib import Path

import torch

from scripts.inspect_historical_checkpoint import inspect_checkpoint


def test_checkpoint_inventory_reports_structure_without_values_or_private_paths(tmp_path: Path) -> None:
    checkpoint = tmp_path / "trusted.pt"
    private_path = str((tmp_path / "private" / "dataset").resolve())
    torch.save(
        {
            "config": {
                "data_root": private_path,
                "learning_rate": 0.25,
                "api_token": "super-secret-value",
            },
            "student_state_dict": {
                "layer.weight": torch.arange(6, dtype=torch.float32).reshape(2, 3),
                "layer.bias": torch.tensor([19.125, 23.5]),
            },
            "optimizer_state_dict": {
                "state": {0: {"momentum_buffer": torch.tensor([31.75])}},
                "param_groups": [{"lr": 0.25, "params": [0]}],
            },
            "scheduler_state_dict": {"last_epoch": 4},
            "epoch": 4,
            "global_step": 17,
        },
        checkpoint,
    )

    report = inspect_checkpoint(checkpoint)
    serialized = json.dumps(report, sort_keys=True)

    assert report["sha256"] and len(report["sha256"]) == 64
    assert report["top_level_keys"] == [
        "config",
        "epoch",
        "global_step",
        "optimizer_state_dict",
        "scheduler_state_dict",
        "student_state_dict",
    ]
    assert report["config"]["data_root"] == "<redacted-absolute-path>"
    assert report["config"]["learning_rate"] == 0.25
    assert report["config"]["api_token"] == "<redacted-secret>"
    assert report["model_parameters"]["layer.weight"] == {"dtype": "torch.float32", "shape": [2, 3]}
    assert report["optimizer_state"]["type"] == "dict"
    assert report["scheduler_state"]["type"] == "dict"
    assert report["epoch"] == 4
    assert report["global_step"] == 17
    assert private_path not in serialized
    assert "19.125" not in serialized
    assert "23.5" not in serialized
    assert "31.75" not in serialized
    assert "super-secret-value" not in serialized
