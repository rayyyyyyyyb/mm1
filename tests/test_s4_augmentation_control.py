from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
S0_PATH = (
    PROJECT_ROOT
    / "configs"
    / "diagnostics"
    / "causal"
    / "ov_orthkd_s0_learned_concat_seed42.yaml"
)
S4_PATH = (
    PROJECT_ROOT
    / "configs"
    / "diagnostics"
    / "recovery"
    / "ov_orthkd_s4_no_augment_seed42.yaml"
)


def _local_loader_config(source: Path, manifest: Path, root: Path) -> dict[str, Any]:
    config = yaml.safe_load(source.read_text(encoding="utf-8"))
    config["data"].update(
        {
            "path_root": str(root),
            "train_manifest": str(manifest),
            "val_manifest": str(manifest),
            "test_manifest": str(manifest),
            "num_workers": 0,
            "pin_memory": False,
            "allow_missing_modalities": True,
            "required_artifacts": [],
        }
    )
    return config


def _transform_names(loader: Any) -> list[str]:
    return [type(op).__name__ for op in loader.dataset.frame_transform.transforms]


def test_s4_loader_removes_only_train_spatial_augmentation(tmp_path: Path) -> None:
    # The missing S4 config is the RED condition. Imports that initialize
    # torch/torchvision stay below this assertion so RED remains diagnostic on
    # CPU-only development hosts.
    assert S4_PATH.is_file()

    from src.data import create_ov_avel_data_loaders

    manifest = tmp_path / "records.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "id": "augmentation-control",
                "query": "test event",
                "segment_labels": [0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
                "frame_paths": [],
                "spectrogram_paths": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    s0_loaders = create_ov_avel_data_loaders(
        _local_loader_config(S0_PATH, manifest, tmp_path)
    )
    s4_loaders = create_ov_avel_data_loaders(
        _local_loader_config(S4_PATH, manifest, tmp_path)
    )

    deterministic = ["Resize", "ToTensor", "Normalize"]
    assert _transform_names(s0_loaders[0]) == [
        "Resize",
        "RandomHorizontalFlip",
        "ColorJitter",
        "ToTensor",
        "Normalize",
    ]
    assert _transform_names(s4_loaders[0]) == deterministic
    assert _transform_names(s4_loaders[1]) == deterministic
    assert _transform_names(s4_loaders[2]) == deterministic
