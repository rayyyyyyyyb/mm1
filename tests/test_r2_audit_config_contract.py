from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from scripts.audit_mm26_reproduction import audit_reproduction


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


def _record(root: Path, split: str, split_type: str, *, resampled: bool) -> dict[str, Any]:
    record_id = f"{split}-record"
    record_root = root / split / record_id
    record_root.mkdir(parents=True)
    frame = record_root / "frame.png"
    frame.write_bytes(b"png")
    np.save(record_root / "strong.npy", np.ones((2, 3), dtype=np.float32), allow_pickle=False)
    np.save(record_root / "logits.npy", np.ones((2,), dtype=np.float32), allow_pickle=False)
    np.save(record_root / "weak.npy", np.ones((2, 4), dtype=np.float32), allow_pickle=False)
    np.save(record_root / "text.npy", np.ones((5,), dtype=np.float32), allow_pickle=False)
    rel = record_root.relative_to(root)
    return {
        "id": record_id,
        "query": f"query-{split}",
        "split_type": split_type,
        "segment_labels": [0, 1],
        "frame_paths": [[str(rel / "frame.png")], [str(rel / "frame.png")]],
        "strong_teacher_features_path": str(rel / "strong.npy"),
        "strong_teacher_logits_path": str(rel / "logits.npy"),
        "weak_teacher_features_path": str(rel / "weak.npy"),
        "text_embedding_path": str(rel / "text.npy"),
        "meta": {
            "preprocessing_evidence": {
                "temporal_resampling_performed": resampled,
                "audio_resampling_performed": False,
            }
        },
    }


def _manifests(root: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for split, split_type, resampled in (
        ("train", "seen", False),
        ("val", "unseen", True),
        ("test", "unseen", False),
    ):
        paths[split] = root / f"{split}.jsonl"
        _write_jsonl(paths[split], [_record(root, split, split_type, resampled=resampled)])
    return paths


def test_audit_uses_config_dimensions_and_per_record_resampling_evidence(tmp_path: Path) -> None:
    manifests = _manifests(tmp_path)
    config = {
        "data": {
            "max_segments": 2,
            "strong_teacher_dim": 3,
            "weak_teacher_dim": 4,
            "text_dim": 5,
        }
    }

    report = audit_reproduction(
        train_manifest=manifests["train"],
        val_manifest=manifests["val"],
        test_manifest=manifests["test"],
        path_root=tmp_path,
        stage="exported",
        artifact_scan="full",
        sample_count=10,
        expected_segments="auto",
        config=config,
    )

    assert report["errors"] == []
    assert report["configured_task_segments"] == 2
    assert "configured_max_segments" not in report
    assert report["configured_artifact_dimensions"] == {
        "strong_teacher_features": 3,
        "weak_teacher_features": 4,
        "text_embedding": 5,
    }
    assert report["resampling_performed_by_dataset"] is True
    assert report["resampling_evidence"] == {
        "records_with_resampling": 1,
        "records_without_resampling": 2,
        "records_missing_evidence": 0,
    }
    assert report["split_seen_unseen_counts"] == {
        "train": {"seen": 1, "unseen": 0},
        "val": {"seen": 0, "unseen": 1},
        "test": {"seen": 0, "unseen": 1},
    }
    assert report["source_manifest_sha256"] is None
    assert report["exported_manifest_sha256"] == report["manifest_sha256"]


def test_audit_rejects_npz_with_unexpected_or_multiple_keys(tmp_path: Path) -> None:
    manifests = _manifests(tmp_path)
    bad = tmp_path / "train" / "train-record" / "strong.npz"
    np.savez(bad, surprise=np.ones((2, 3)), extra=np.ones(1))
    records = [json.loads(manifests["train"].read_text(encoding="utf-8"))]
    records[0]["strong_teacher_features_path"] = str(bad.relative_to(tmp_path))
    _write_jsonl(manifests["train"], records)

    report = audit_reproduction(
        train_manifest=manifests["train"],
        val_manifest=manifests["val"],
        test_manifest=manifests["test"],
        path_root=tmp_path,
        stage="exported",
        artifact_scan="full",
        sample_count=10,
        expected_segments="auto",
        config={"data": {"max_segments": 2, "strong_teacher_dim": 3, "weak_teacher_dim": 4, "text_dim": 5}},
    )

    assert any(item["code"] == "artifact_load" and "arr_0" in item["message"] for item in report["errors"])


def test_formal_audit_rejects_wrong_official_seen_unseen_matrix(tmp_path: Path) -> None:
    manifests = _manifests(tmp_path)

    report = audit_reproduction(
        train_manifest=manifests["train"],
        val_manifest=manifests["val"],
        test_manifest=manifests["test"],
        path_root=tmp_path,
        stage="source",
        artifact_scan="none",
        sample_count=10,
        expected_segments="auto",
        config={
            "reproduction": {"claim_level": "archival_exact"},
            "data": {"num_segments": 10, "temporal_resampling": False},
        },
    )

    codes = {item["code"] for item in report["errors"]}
    assert "official_split_count_mismatch" in codes
    assert "official_seen_unseen_count_mismatch" in codes
