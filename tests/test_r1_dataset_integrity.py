from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from src.data import QueryConditionedOVAvelDataset


def _write_manifest(path: Path, record: dict[str, Any]) -> None:
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")


def _record(labels: list[float] | None = None) -> dict[str, Any]:
    return {
        "id": "clip_0",
        "query": "dog barking",
        "segment_labels": [1.0, 0.0] if labels is None else labels,
        "segment_frame_paths": [],
        "spectrogram_paths": [],
    }


def _dataset(manifest: Path, **overrides: Any) -> QueryConditionedOVAvelDataset:
    kwargs: dict[str, Any] = {
        "manifest_path": str(manifest),
        "path_root": str(manifest.parent),
        "image_size": 16,
        "max_segments": 2,
        "augment": False,
        "allow_missing_modalities": True,
        "strict_alignment": True,
        "strong_teacher_dim": 3,
        "weak_teacher_dim": 4,
        "strong_teacher_logit_dim": 1,
        "weak_teacher_logit_dim": 1,
        "text_dim": 5,
    }
    kwargs.update(overrides)
    return QueryConditionedOVAvelDataset(**kwargs)


def test_canonical_temporal_overflow_fails_instead_of_sampling(tmp_path: Path) -> None:
    manifest = tmp_path / "data.jsonl"
    _write_manifest(manifest, _record([1.0, 0.0, 1.0]))

    with pytest.raises(ValueError, match=r"seq_len=3.*max_segments=2.*error"):
        _ = _dataset(manifest)[0]


def test_explicit_uniform_overflow_is_unique_monotone_and_noncanonical(tmp_path: Path) -> None:
    manifest = tmp_path / "data.jsonl"
    _write_manifest(manifest, _record([0.0, 1.0, 0.0, 1.0, 0.0]))

    sample = _dataset(manifest, max_segments=3, temporal_overflow_policy="uniform")[0]

    assert sample["selected_segment_indices"] == [0, 2, 4]
    assert sample["temporal_sampling_policy"] == "uniform"
    assert sample["noncanonical_temporal_sampling"] is True
    assert sample["segment_label"].tolist() == [0.0, 0.0, 0.0]


@pytest.mark.parametrize(
    ("field", "array", "message"),
    [
        ("strong_teacher_features_path", np.ones((1, 3), dtype=np.float32), "singleton"),
        ("strong_teacher_logits_path", np.ones((1,), dtype=np.float32), "singleton"),
        ("strong_teacher_logits_path", np.ones((1, 1), dtype=np.float32), "singleton"),
    ],
)
def test_singleton_teacher_rows_are_not_broadcast(
    tmp_path: Path,
    field: str,
    array: np.ndarray,
    message: str,
) -> None:
    artifact = tmp_path / "artifact.npy"
    np.save(artifact, array, allow_pickle=False)
    record = _record()
    record[field] = artifact.name
    manifest = tmp_path / "data.jsonl"
    _write_manifest(manifest, record)

    with pytest.raises(ValueError, match=message):
        _ = _dataset(manifest)[0]


@pytest.mark.parametrize(
    ("logits", "expected"),
    [
        (np.asarray([0.25, -0.5], dtype=np.float32), [[0.25], [-0.5]]),
        (np.asarray([[0.25], [-0.5]], dtype=np.float32), [[0.25], [-0.5]]),
    ],
)
def test_exact_feature_and_logit_shapes_are_accepted(
    tmp_path: Path,
    logits: np.ndarray,
    expected: list[list[float]],
) -> None:
    np.save(tmp_path / "features.npy", np.arange(6, dtype=np.float32).reshape(2, 3), allow_pickle=False)
    np.save(tmp_path / "logits.npy", logits, allow_pickle=False)
    record = _record()
    record["strong_teacher_features_path"] = "features.npy"
    record["strong_teacher_logits_path"] = "logits.npy"
    manifest = tmp_path / "data.jsonl"
    _write_manifest(manifest, record)

    sample = _dataset(manifest)[0]

    assert sample["strong_teacher_features"].shape == (2, 3)
    assert sample["strong_teacher_logits"].tolist() == expected


@pytest.mark.parametrize("bad_value", [np.nan, np.inf, -np.inf])
def test_nonfinite_teacher_artifact_fails_immediately(tmp_path: Path, bad_value: float) -> None:
    artifact = np.ones((2, 3), dtype=np.float32)
    artifact[1, 2] = bad_value
    np.save(tmp_path / "features.npy", artifact, allow_pickle=False)
    record = _record()
    record["strong_teacher_features_path"] = "features.npy"
    manifest = tmp_path / "data.jsonl"
    _write_manifest(manifest, record)

    with pytest.raises(ValueError, match=r"strong_teacher_features.*finite"):
        _ = _dataset(manifest)[0]


@pytest.mark.parametrize("labels", [[], [0.0, 2.0], [0.0, float("nan")]])
def test_labels_must_be_nonempty_finite_and_binary(tmp_path: Path, labels: list[float]) -> None:
    manifest = tmp_path / "data.jsonl"
    _write_manifest(manifest, _record(labels))

    with pytest.raises(ValueError, match=r"segment_labels.*(empty|finite|binary)"):
        _ = _dataset(manifest)[0]


def test_numpy_object_artifacts_are_rejected_without_pickle(tmp_path: Path) -> None:
    np.save(tmp_path / "object.npy", np.asarray([{"unsafe": True}], dtype=object), allow_pickle=True)
    record = _record()
    record["strong_teacher_features_path"] = "object.npy"
    manifest = tmp_path / "data.jsonl"
    _write_manifest(manifest, record)

    with pytest.raises(ValueError, match="Object arrays cannot be loaded"):
        _ = _dataset(manifest)[0]


def test_image_is_detached_from_file_handle(tmp_path: Path) -> None:
    frame = tmp_path / "frame.png"
    Image.new("RGB", (8, 8), color=(12, 34, 56)).save(frame)
    manifest = tmp_path / "data.jsonl"
    _write_manifest(manifest, _record())
    dataset = _dataset(manifest)

    image, valid = dataset._read_image(frame.name)
    frame.unlink()

    assert valid == 1.0
    assert image.getpixel((0, 0)) == (12, 34, 56)


def test_artifact_override_preserves_relative_hierarchy_and_avoids_basename_collision(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "old_cache"
    target_root = tmp_path / "new_cache"
    (target_root / "class_a").mkdir(parents=True)
    (target_root / "class_b").mkdir(parents=True)
    np.save(target_root / "class_a" / "shared.npy", np.ones((2, 3), dtype=np.float32), allow_pickle=False)
    np.save(target_root / "class_b" / "shared.npy", np.full((2, 3), 2.0, dtype=np.float32), allow_pickle=False)
    manifest = tmp_path / "data.jsonl"
    records = []
    for category in ("class_a", "class_b"):
        record = _record()
        record["id"] = category
        record["strong_teacher_features_path"] = str(source_root / category / "shared.npy")
        records.append(record)
    manifest.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    dataset = _dataset(
        manifest,
        teacher_path_overrides={
            "strong_teacher_features": {
                "source_root": str(source_root),
                "target_root": str(target_root),
            }
        },
    )

    assert dataset[0]["strong_teacher_features"].mean().item() == 1.0
    assert dataset[1]["strong_teacher_features"].mean().item() == 2.0


def test_artifact_override_rejects_source_root_traversal(tmp_path: Path) -> None:
    source_root = tmp_path / "old_cache"
    target_root = tmp_path / "new_cache"
    target_root.mkdir()
    outside = tmp_path / "outside.npy"
    np.save(outside, np.ones((2, 3), dtype=np.float32), allow_pickle=False)
    record = _record()
    record["strong_teacher_features_path"] = str(source_root / ".." / outside.name)
    manifest = tmp_path / "data.jsonl"
    _write_manifest(manifest, record)
    dataset = _dataset(
        manifest,
        teacher_path_overrides={
            "strong_teacher_features": {
                "source_root": str(source_root),
                "target_root": str(target_root),
            }
        },
    )

    with pytest.raises(ValueError, match="outside declared source_root"):
        _ = dataset[0]


@pytest.mark.parametrize(("official", "normalized"), [("close", "seen"), ("open", "unseen")])
def test_official_group_maps_exactly_to_seen_unseen(
    tmp_path: Path,
    official: str,
    normalized: str,
) -> None:
    record = _record()
    record["split_type"] = official
    manifest = tmp_path / "data.jsonl"
    _write_manifest(manifest, record)

    assert _dataset(manifest)[0]["split_type"] == normalized
