from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import torch
from PIL import Image

from src.data import QueryConditionedOVAvelDataset, create_ov_avel_data_loaders


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def base_record(record_id: str = "sample_0") -> dict[str, Any]:
    return {
        "id": record_id,
        "query": "dog barking",
        "frame_paths": [],
        "spectrogram_paths": [],
        "segment_labels": [1, 0],
        "domain": "unit",
    }


def build_dataset(manifest: Path, root: Path, **overrides: Any) -> QueryConditionedOVAvelDataset:
    kwargs: dict[str, Any] = {
        "manifest_path": str(manifest),
        "path_root": str(root),
        "image_size": 32,
        "max_segments": 2,
        "augment": False,
        "allow_missing_modalities": True,
        "strict_alignment": True,
        "required_artifacts": [],
        "strong_teacher_dim": 3,
        "weak_teacher_dim": 4,
        "strong_teacher_logit_dim": 1,
        "weak_teacher_logit_dim": 1,
        "text_dim": 5,
    }
    kwargs.update(overrides)
    return QueryConditionedOVAvelDataset(**kwargs)


def test_missing_required_weak_feature_names_field_and_record(tmp_path: Path) -> None:
    manifest = tmp_path / "data.jsonl"
    record = base_record()
    record["weak_teacher_features_path"] = "teacher/missing.npy"
    write_jsonl(manifest, [record])
    dataset = build_dataset(
        manifest,
        tmp_path,
        required_artifacts=["weak_teacher_features"],
    )

    with pytest.raises(FileNotFoundError, match=r"weak_teacher_features.*sample_0"):
        _ = dataset[0]


def test_permissive_missing_weak_feature_returns_zero_canonical_mask(tmp_path: Path) -> None:
    manifest = tmp_path / "data.jsonl"
    record = base_record()
    record["weak_teacher_features_path"] = "teacher/missing.npy"
    write_jsonl(manifest, [record])
    dataset = build_dataset(manifest, tmp_path)

    sample = dataset[0]

    assert sample["weak_teacher_feature_mask"].sum().item() == 0.0
    assert torch.equal(sample["weak_teacher_feature_mask"], sample["weak_teacher_mask"])
    assert sample["weak_teacher_features"].shape == (2, 4)


def test_dataset_and_collate_preserve_seen_unseen_split_type(tmp_path: Path) -> None:
    manifest = tmp_path / "data.jsonl"
    record = base_record()
    record["split_type"] = "seen"
    write_jsonl(manifest, [record])
    dataset = build_dataset(manifest, tmp_path)

    sample = dataset[0]
    assert sample["split_type"] == "seen"

    train_loader, _, _ = create_ov_avel_data_loaders(loader_config(manifest, tmp_path, seed=42))
    batch = next(iter(train_loader))
    assert batch["split_type"] == ["seen"]


def test_relative_artifact_and_modality_paths_use_path_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "assets"
    (root / "frames").mkdir(parents=True)
    (root / "specs").mkdir()
    (root / "teacher").mkdir()
    frame_path = root / "frames" / "frame.png"
    spec_path = root / "specs" / "spec.png"
    Image.new("RGB", (16, 16), color=(10, 20, 30)).save(frame_path)
    Image.new("RGB", (16, 16), color=(30, 20, 10)).save(spec_path)
    np.save(root / "teacher" / "strong.npy", np.ones((1, 3), dtype=np.float32))
    np.save(root / "teacher" / "weak.npy", np.ones((1, 4), dtype=np.float32))
    np.save(root / "teacher" / "text.npy", np.ones(5, dtype=np.float32))

    manifest = tmp_path / "data.jsonl"
    write_jsonl(
        manifest,
        [
            {
                "id": "sample_relative",
                "query": "dog barking",
                "frame_paths": ["frames/frame.png"],
                "spectrogram_paths": ["specs/spec.png"],
                "segment_labels": [1],
                "strong_teacher_features_path": "teacher/strong.npy",
                "weak_teacher_features_path": "teacher/weak.npy",
                "text_embedding_path": "teacher/text.npy",
            }
        ],
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    dataset = build_dataset(
        manifest,
        root,
        required_artifacts=[
            "strong_teacher_features",
            "weak_teacher_features",
            "text_embedding",
        ],
    )

    sample = dataset[0]

    assert sample["frame_valid"].tolist() == [1.0]
    assert sample["audio_valid"].tolist() == [1.0]
    assert sample["strong_teacher_feature_mask"].tolist() == [1.0]
    assert sample["weak_teacher_feature_mask"].tolist() == [1.0]
    assert sample["text_valid"].item() == 1.0


def test_invalid_required_teacher_dimension_names_artifact(tmp_path: Path) -> None:
    (tmp_path / "teacher").mkdir()
    np.save(tmp_path / "teacher" / "weak.npy", np.ones((2, 3), dtype=np.float32))
    manifest = tmp_path / "data.jsonl"
    record = base_record("sample_bad_dim")
    record["weak_teacher_features_path"] = "teacher/weak.npy"
    write_jsonl(manifest, [record])
    dataset = build_dataset(
        manifest,
        tmp_path,
        required_artifacts=["weak_teacher_features"],
    )

    with pytest.raises(ValueError, match="weak_teacher_features"):
        _ = dataset[0]


def loader_config(manifest: Path, root: Path, seed: int) -> dict[str, Any]:
    return {
        "seed": seed,
        "data": {
            "path_root": str(root),
            "train_manifest": str(manifest),
            "val_manifest": str(manifest),
            "test_manifest": str(manifest),
            "image_size": 16,
            "batch_size": 2,
            "num_workers": 0,
            "pin_memory": False,
            "max_segments": 2,
            "allow_missing_modalities": True,
            "strict_alignment": True,
            "required_artifacts": [],
            "strong_teacher_dim": 3,
            "weak_teacher_dim": 4,
            "strong_teacher_logit_dim": 1,
            "weak_teacher_logit_dim": 1,
            "text_dim": 5,
            "train_augment": False,
        },
    }


def collect_ids(loader: torch.utils.data.DataLoader) -> list[str]:
    return [sample_id for batch in loader for sample_id in batch["id"]]


def test_loader_order_is_reproducible_and_split_generators_are_independent(tmp_path: Path) -> None:
    manifest = tmp_path / "data.jsonl"
    records = [
        {
            **base_record(f"sample_{index}"),
            "segment_labels": [index % 2],
        }
        for index in range(8)
    ]
    write_jsonl(manifest, records)
    config = loader_config(manifest, tmp_path, seed=1234)

    train_a, _, _ = create_ov_avel_data_loaders(config)
    order_a = collect_ids(train_a)

    train_b, val_b, test_b = create_ov_avel_data_loaders(config)
    assert test_b is not None
    _ = collect_ids(val_b)
    _ = collect_ids(test_b)
    order_b = collect_ids(train_b)

    assert order_a == order_b
    assert sorted(order_a) == [f"sample_{index}" for index in range(8)]
