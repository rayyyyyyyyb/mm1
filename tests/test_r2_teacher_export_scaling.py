from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import src.teachers.pipeline as pipeline_module
from src.teachers import TeacherExportBundle
from src.teachers.common import load_records, strong_teacher_artifact_paths
from src.teachers.pipeline import export_manifest_records

try:
    from src.teachers.common import record_artifact_dir
except ImportError:
    record_artifact_dir = None


class _TextTeacher:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def encode_queries(self, queries: list[str]) -> np.ndarray:
        self.calls += 1
        if self.fail:
            raise RuntimeError("text teacher should not run during receipt resume")
        assert queries == ["shared query"]
        return np.asarray([[1.0, 2.0, 3.0]], dtype=np.float32)


def _records(count: int) -> list[dict[str, object]]:
    return [
        {"id": f"clip_{index:03d}", "query": "shared query", "segment_labels": [1, 0]}
        for index in range(count)
    ]


def test_artifact_paths_are_split_safe_and_reject_unsupported_split(tmp_path: Path) -> None:
    assert record_artifact_dir is not None, "split-safe record artifact helper is missing"
    train_dir = record_artifact_dir(tmp_path, "train", "clip")
    val_dir = record_artifact_dir(tmp_path, "val", "clip")

    assert train_dir == tmp_path / "train" / "clip"
    assert val_dir == tmp_path / "val" / "clip"
    assert strong_teacher_artifact_paths(tmp_path, "clip", split="train")[0].parent == train_dir
    with pytest.raises(ValueError, match="Unsupported split"):
        record_artifact_dir(tmp_path, "unknown", "clip")


def test_export_writes_each_receipt_once_and_shares_query_embedding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aggregate_receipt = tmp_path / "all_receipts.jsonl"
    real_atomic_write_jsonl = pipeline_module.atomic_write_jsonl
    aggregate_writes = 0

    def counting_real_writer(path: str | Path, rows: object) -> None:
        nonlocal aggregate_writes
        if Path(path).resolve() == aggregate_receipt.resolve():
            aggregate_writes += 1
        real_atomic_write_jsonl(path, rows)

    monkeypatch.setattr(pipeline_module, "atomic_write_jsonl", counting_real_writer)
    teacher = _TextTeacher()
    summary = export_manifest_records(
        records=_records(40),
        artifact_dir=tmp_path / "cache",
        output_manifest=tmp_path / "train.jsonl",
        teachers=TeacherExportBundle(text_teacher=teacher),
        receipt_jsonl=aggregate_receipt,
        source_manifest_sha256="source-a",
        teacher_lock_sha256="lock-a",
        split="train",
        progress_path=tmp_path / "progress/train.json",
    )

    record_receipts = sorted((tmp_path / "cache" / "receipts" / "train").glob("*.json"))
    text_arrays = sorted((tmp_path / "cache" / "text_by_query").glob("*.npy"))
    exported = load_records(tmp_path / "train.jsonl")
    first_receipt = json.loads(record_receipts[0].read_text(encoding="utf-8"))

    assert aggregate_writes == 1
    assert len(record_receipts) == 40
    assert len(load_records(aggregate_receipt)) == 40
    assert len(text_arrays) == 1
    assert teacher.calls == 1
    assert len({record["text_embedding_path"] for record in exported}) == 1
    assert first_receipt["query"] == "shared query"
    assert len(first_receipt["query_sha256"]) == 64
    progress = json.loads((tmp_path / "progress/train.json").read_text(encoding="utf-8"))
    assert progress["status"] == "completed"
    assert progress["completed"] == 40
    assert progress["total"] == 40
    assert progress["current_record_id"] is None
    assert summary["unique_queries_encoded"] == 1


def test_resume_scans_per_record_receipts_without_aggregate_jsonl(tmp_path: Path) -> None:
    aggregate_receipt = tmp_path / "all_receipts.jsonl"
    first_teacher = _TextTeacher()
    export_manifest_records(
        records=_records(3),
        artifact_dir=tmp_path / "cache",
        output_manifest=tmp_path / "train.jsonl",
        teachers=TeacherExportBundle(text_teacher=first_teacher),
        receipt_jsonl=aggregate_receipt,
        source_manifest_sha256="source-a",
        teacher_lock_sha256="lock-a",
        split="train",
    )
    aggregate_receipt.unlink()
    should_not_run = _TextTeacher(fail=True)

    summary = export_manifest_records(
        records=_records(3),
        artifact_dir=tmp_path / "cache",
        output_manifest=tmp_path / "train.jsonl",
        teachers=TeacherExportBundle(text_teacher=should_not_run),
        receipt_jsonl=aggregate_receipt,
        source_manifest_sha256="source-a",
        teacher_lock_sha256="lock-a",
        split="train",
        resume=True,
    )

    assert summary["records_resumed"] == 3
    assert should_not_run.calls == 0
    assert len(load_records(aggregate_receipt)) == 3
