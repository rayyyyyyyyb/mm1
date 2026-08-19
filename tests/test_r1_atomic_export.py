from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

import scripts.export_teacher_artifacts as export_script
import src.utils.atomic_artifacts as atomic_module
from src.teachers import TeacherExportBundle, export_manifest_file
from src.teachers.common import load_records
from src.utils.atomic_artifacts import atomic_save_array, canonical_tree_hash


class _TextTeacher:
    def __init__(self, *, fail_on_call: int | None = None) -> None:
        self.calls = 0
        self.fail_on_call = fail_on_call

    def encode_queries(self, queries: list[str]) -> np.ndarray:
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise RuntimeError("intentional teacher interruption")
        value = float(sum(ord(char) for char in queries[0]) % 17)
        return np.asarray([[value, value + 1.0, value + 2.0]], dtype=np.float32)


def _write_source(path: Path, ids: tuple[str, ...] = ("clip_0", "clip_1")) -> None:
    records = [
        {
            "id": record_id,
            "query": f"query {index}",
            "segment_labels": [1, 0],
            "segment_frame_paths": ["unused-a.jpg", "unused-b.jpg"],
            "audio_paths": ["unused-a.wav", "unused-b.wav"],
        }
        for index, record_id in enumerate(ids)
    ]
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


def _export(
    tmp_path: Path,
    teacher: _TextTeacher,
    *,
    teacher_lock_sha256: str = "lock-a",
    resume: bool = False,
) -> dict[str, Any]:
    return export_manifest_file(
        source_manifest=tmp_path / "source.jsonl",
        artifact_dir=tmp_path / "cache",
        output_manifest=tmp_path / "train.jsonl",
        teachers=TeacherExportBundle(text_teacher=teacher),
        receipt_jsonl=tmp_path / "train_receipt.jsonl",
        error_jsonl=tmp_path / "export_errors.jsonl",
        teacher_lock_sha256=teacher_lock_sha256,
        split="train",
        resume=resume,
    )


def test_interrupted_atomic_array_write_preserves_old_complete_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "artifact.npy"
    np.save(target, np.asarray([1.0, 2.0], dtype=np.float32), allow_pickle=False)
    old_bytes = target.read_bytes()

    def _interrupt(source: str | Path, destination: str | Path) -> None:
        del source, destination
        raise OSError("simulated replace interruption")

    monkeypatch.setattr(atomic_module.os, "replace", _interrupt)

    with pytest.raises(OSError, match="simulated replace interruption"):
        atomic_save_array(target, np.asarray([9.0, 9.0], dtype=np.float32), expected_shape=(2,))

    assert target.read_bytes() == old_bytes
    assert list(tmp_path.glob(".*.tmp")) == []


@pytest.mark.parametrize(
    ("array", "expected_shape", "message"),
    [
        (np.ones((2, 3), dtype=np.float32), (3, 2), "shape"),
        (np.asarray([1.0, np.nan], dtype=np.float32), (2,), "finite"),
    ],
)
def test_atomic_array_validates_shape_and_finiteness_before_publication(
    tmp_path: Path,
    array: np.ndarray,
    expected_shape: tuple[int, ...],
    message: str,
) -> None:
    target = tmp_path / "artifact.npy"

    with pytest.raises(ValueError, match=message):
        atomic_save_array(target, array, expected_shape=expected_shape)

    assert not target.exists()


def test_failed_export_keeps_old_final_manifest_and_records_error(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    _write_source(source)
    final = tmp_path / "train.jsonl"
    final.write_text('{"id":"old-complete"}\n', encoding="utf-8")
    old_bytes = final.read_bytes()

    with pytest.raises(RuntimeError, match="intentional teacher interruption"):
        _export(tmp_path, _TextTeacher(fail_on_call=2))

    assert final.read_bytes() == old_bytes
    assert not final.with_name(final.name + ".partial").exists()
    errors = load_records(tmp_path / "export_errors.jsonl")
    assert errors[0]["record_id"] == "clip_1"
    assert "intentional teacher interruption" in errors[0]["error"]


def test_successful_export_publishes_manifest_receipts_and_stable_root_hash(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    _write_source(source)

    summary = _export(tmp_path, _TextTeacher())

    final = tmp_path / "train.jsonl"
    receipts = load_records(tmp_path / "train_receipt.jsonl")
    assert len(load_records(final)) == 2
    assert len(receipts) == 2
    assert not final.with_name(final.name + ".partial").exists()
    assert all(receipt["split"] == "train" for receipt in receipts)
    assert all(receipt["teacher_lock_sha256"] == "lock-a" for receipt in receipts)
    assert all(receipt["source_manifest_sha256"] == summary["source_manifest_sha256"] for receipt in receipts)
    assert all(receipt["artifacts"]["text_embedding"]["shape"] == [3] for receipt in receipts)
    assert summary["cache_root_sha256"] == canonical_tree_hash(tmp_path / "cache")["sha256"]


def test_resume_skips_only_matching_receipts_and_rejects_changed_teacher_lock(tmp_path: Path) -> None:
    _write_source(tmp_path / "source.jsonl")
    _export(tmp_path, _TextTeacher())
    should_not_run = _TextTeacher(fail_on_call=1)

    resumed = _export(tmp_path, should_not_run, resume=True)

    assert resumed["records_resumed"] == 2
    assert should_not_run.calls == 0
    with pytest.raises(RuntimeError, match=r"stale.*teacher lock"):
        _export(tmp_path, _TextTeacher(), teacher_lock_sha256="lock-b", resume=True)


def test_sanitized_record_id_collision_fails_before_overwrite(tmp_path: Path) -> None:
    _write_source(tmp_path / "source.jsonl", ids=("a/b", "a_b"))

    with pytest.raises(ValueError, match="artifact path collision"):
        _export(tmp_path, _TextTeacher())

    assert not (tmp_path / "train.jsonl").exists()


def test_export_cli_exposes_receipt_lock_split_and_resume_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "export_teacher_artifacts.py",
            "--source-manifest",
            "source.jsonl",
            "--output-manifest",
            "train.jsonl",
            "--receipt-jsonl",
            "receipt.jsonl",
            "--error-jsonl",
            "errors.jsonl",
            "--teacher-lock",
            "teacher-lock.yaml",
            "--split",
            "train",
            "--resume",
        ],
    )

    args = export_script.parse_args()

    assert args.receipt_jsonl == "receipt.jsonl"
    assert args.error_jsonl == "errors.jsonl"
    assert args.teacher_lock == "teacher-lock.yaml"
    assert args.split == "train"
    assert args.resume is True
