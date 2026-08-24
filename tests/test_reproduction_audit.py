from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from scripts.audit_mm26_reproduction import audit_exit_code, audit_reproduction


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def write_exported_record(
    root: Path,
    split: str,
    record_id: str,
    split_type: str,
    *,
    labels: list[int] | None = None,
    weak_dim: int = 768,
    strong_has_nan: bool = False,
    missing_frame: bool = False,
) -> dict[str, Any]:
    record_root = root / split / record_id
    record_root.mkdir(parents=True)
    frame = record_root / "frame.jpg"
    spectrogram = record_root / "spec.jpg"
    frame.write_bytes(b"frame")
    spectrogram.write_bytes(b"spec")
    segment_labels = labels or [index % 2 for index in range(10)]
    segment_count = len(segment_labels)

    strong = np.ones((segment_count, 512), dtype=np.float32)
    if strong_has_nan:
        strong[0, 0] = np.nan
    np.save(record_root / "strong.npy", strong)
    np.save(record_root / "strong_logits.npy", np.linspace(-1.0, 1.0, segment_count, dtype=np.float32))
    np.save(record_root / "weak.npy", np.ones((segment_count, weak_dim), dtype=np.float32))
    np.save(record_root / "text.npy", np.ones(1024, dtype=np.float32))

    relative_root = record_root.relative_to(root)
    frame_path = relative_root / ("missing.jpg" if missing_frame else "frame.jpg")
    return {
        "id": record_id,
        "query": f"query_{record_id}",
        "category": f"query_{record_id}",
        "split_type": split_type,
        "segment_labels": segment_labels,
        "frame_paths": [str(frame_path)] * segment_count,
        "spectrogram_paths": [str(relative_root / "spec.jpg")] * segment_count,
        "strong_teacher_features_path": str(relative_root / "strong.npy"),
        "strong_teacher_logits_path": str(relative_root / "strong_logits.npy"),
        "weak_teacher_features_path": str(relative_root / "weak.npy"),
        "text_embedding_path": str(relative_root / "text.npy"),
    }


def write_valid_manifests(root: Path) -> tuple[Path, Path, Path]:
    train = root / "train.jsonl"
    val = root / "val.jsonl"
    test = root / "test.jsonl"
    write_jsonl(train, [write_exported_record(root, "train", "train_0", "seen")])
    write_jsonl(val, [write_exported_record(root, "val", "val_0", "seen")])
    write_jsonl(test, [write_exported_record(root, "test", "test_0", "unseen")])
    return train, val, test


def test_valid_exported_t10_audit_reports_reproduction_facts(tmp_path: Path) -> None:
    train, val, test = write_valid_manifests(tmp_path)

    report = audit_reproduction(
        train_manifest=train,
        val_manifest=val,
        test_manifest=test,
        path_root=tmp_path,
        stage="exported",
        artifact_scan="full",
        sample_count=10,
        expected_segments="10",
    )

    assert report["errors"] == []
    assert report["warnings"] == []
    assert report["split_counts"] == {"train": 1, "val": 1, "test": 1}
    assert report["segment_length_histogram"] == {"10": 3}
    assert report["configured_task_segments"] == 10
    assert "configured_max_segments" not in report
    assert report["resampling_performed_by_dataset"] is False
    assert report["seen_classes"] == 2
    assert report["unseen_classes"] == 1
    assert set(report["manifest_sha256"]) == {"train", "val", "test"}
    assert all(len(value) == 64 for value in report["manifest_sha256"].values())
    assert audit_exit_code(report, fail_on_warning=False) == 0


def test_audit_catches_duplicate_overlap_labels_paths_shapes_and_nan(tmp_path: Path) -> None:
    train = tmp_path / "train.jsonl"
    val = tmp_path / "val.jsonl"
    test = tmp_path / "test.jsonl"
    duplicate = write_exported_record(tmp_path, "train", "shared_id", "seen")
    write_jsonl(train, [duplicate, duplicate])
    write_jsonl(
        val,
        [
            write_exported_record(
                tmp_path,
                "val",
                "shared_id",
                "seen",
                labels=[0, 2] + [0] * 8,
            )
        ],
    )
    write_jsonl(
        test,
        [
            write_exported_record(
                tmp_path,
                "test",
                "test_bad",
                "unseen",
                weak_dim=7,
                strong_has_nan=True,
                missing_frame=True,
            )
        ],
    )

    report = audit_reproduction(
        train_manifest=train,
        val_manifest=val,
        test_manifest=test,
        path_root=tmp_path,
        stage="exported",
        artifact_scan="full",
        sample_count=10,
        expected_segments="auto",
    )
    error_codes = {item["code"] for item in report["errors"]}

    assert {
        "duplicate_id",
        "split_overlap",
        "non_binary_label",
        "missing_path",
        "artifact_dimension",
        "non_finite_artifact",
    } <= error_codes
    assert audit_exit_code(report, fail_on_warning=False) == 1


def test_expected_segment_warning_is_optional_failure(tmp_path: Path) -> None:
    train, val, test = write_valid_manifests(tmp_path)

    report = audit_reproduction(
        train_manifest=train,
        val_manifest=val,
        test_manifest=test,
        path_root=tmp_path,
        stage="exported",
        artifact_scan="none",
        sample_count=1,
        expected_segments="16",
    )

    assert report["errors"] == []
    assert any(item["code"] == "unexpected_segment_count" for item in report["warnings"])
    assert audit_exit_code(report, fail_on_warning=False) == 0
    assert audit_exit_code(report, fail_on_warning=True) == 1
