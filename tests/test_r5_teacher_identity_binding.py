from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _teacher_lock() -> dict:
    value = yaml.safe_load(
        (PROJECT_ROOT / "configs/locks/mm26_teacher_lock.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert isinstance(value, dict)
    return value


def test_teacher_identity_digest_ignores_only_mutable_export_state() -> None:
    from src.utils.reproduction_locks import teacher_identity_sha256

    original = _teacher_lock()
    completed = deepcopy(original)
    completed["status"] = "ready"
    completed["blocked_by"] = []
    completed["blockers"] = []
    completed["full_export"] = {
        "status": "passed",
        "records": 24800,
        "errors": 0,
        "cache_root_sha256": "a" * 64,
        "train_manifest_sha256": "b" * 64,
        "val_manifest_sha256": "c" * 64,
        "test_manifest_sha256": "d" * 64,
    }

    assert teacher_identity_sha256(original) == teacher_identity_sha256(completed)


def test_teacher_identity_digest_changes_for_checkpoint_or_preprocessing_mutation() -> None:
    from src.utils.reproduction_locks import teacher_identity_sha256

    original = _teacher_lock()
    checkpoint_mutation = deepcopy(original)
    checkpoint_mutation["teachers"]["internvideo2"]["checkpoint_files"][0][
        "sha256"
    ] = "f" * 64
    preprocessing_mutation = deepcopy(original)
    preprocessing_mutation["teachers"]["internvideo2"]["preprocessing"][
        "num_frames"
    ] = 16

    digest = teacher_identity_sha256(original)
    assert teacher_identity_sha256(checkpoint_mutation) != digest
    assert teacher_identity_sha256(preprocessing_mutation) != digest


def test_teacher_export_identity_is_ready_after_real_smoke_before_full_export() -> None:
    from src.utils.reproduction_locks import validate_teacher_export_identity

    result = validate_teacher_export_identity(_teacher_lock())

    assert result["ready"] is True
    assert result["errors"] == []
    assert result["unresolved"] == []
    assert len(result["teacher_identity_sha256"]) == 64


def test_teacher_export_identity_rejects_missing_or_failed_real_smoke() -> None:
    from src.utils.reproduction_locks import validate_teacher_export_identity

    lock = _teacher_lock()
    lock["real_smoke"]["status"] = "failed"

    result = validate_teacher_export_identity(lock)

    assert result["ready"] is False
    assert any("real_smoke.status must be passed" in error for error in result["errors"])


def test_teacher_export_identity_rejects_a_mismatched_declared_digest() -> None:
    from src.utils.reproduction_locks import validate_teacher_export_identity

    lock = _teacher_lock()
    lock["teacher_identity_sha256"] = "f" * 64

    result = validate_teacher_export_identity(lock)

    assert result["ready"] is False
    assert "teacher_identity_sha256 does not match teacher identities" in result["errors"]


def test_resume_receipt_binds_to_teacher_identity_not_mutable_lock_file(
    tmp_path: Path,
) -> None:
    from src.teachers.pipeline import _validate_receipt

    receipt = {
        "schema_version": 3,
        "split": "train",
        "teacher_identity_sha256": "a" * 64,
        "source_manifest_sha256": "b" * 64,
        "artifacts": {},
    }

    valid, reason = _validate_receipt(
        receipt,
        artifact_root=tmp_path,
        source_manifest_sha256="b" * 64,
        teacher_identity_sha256="a" * 64,
        split="train",
    )
    assert (valid, reason) == (True, "ok")

    valid, reason = _validate_receipt(
        receipt,
        artifact_root=tmp_path,
        source_manifest_sha256="b" * 64,
        teacher_identity_sha256="c" * 64,
        split="train",
    )
    assert valid is False
    assert reason == "teacher identity hash mismatch"


def test_full_audit_receipt_binding_rejects_wrong_teacher_identity(
    tmp_path: Path,
) -> None:
    from scripts.audit_mm26_reproduction import _validate_export_receipt_binding

    receipt_path = tmp_path / "record.json"
    receipt = {
        "schema_version": 3,
        "record_id": "record",
        "split": "train",
        "teacher_identity_sha256": "a" * 64,
        "source_manifest_sha256": "b" * 64,
        "artifacts": {},
    }
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    assert (
        _validate_export_receipt_binding(
            receipt_path,
            record_id="record",
            split="train",
            teacher_identity_sha256="a" * 64,
            source_manifest_sha256="b" * 64,
        )
        is None
    )

    receipt["teacher_identity_sha256"] = "c" * 64
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    assert _validate_export_receipt_binding(
        receipt_path,
        record_id="record",
        split="train",
        teacher_identity_sha256="a" * 64,
        source_manifest_sha256="b" * 64,
    ) == "teacher identity hash mismatch"


def test_canonical_readiness_cross_binds_full_audit_to_teacher_identity() -> None:
    from src.utils.canonical_readiness import validate_exported_audit_identity

    teacher_lock = _teacher_lock()
    from src.utils.reproduction_locks import teacher_identity_sha256

    digest = teacher_identity_sha256(teacher_lock)
    audit = {
        "artifact_scan": "full",
        "record_count": 24800,
        "artifacts_scanned": 24800,
        "receipt_bindings_checked": 24800,
        "teacher_identity_sha256": digest,
        "errors": [],
        "warnings": [],
    }

    assert validate_exported_audit_identity(audit, teacher_lock) == []

    audit["teacher_identity_sha256"] = "f" * 64
    errors = validate_exported_audit_identity(audit, teacher_lock)
    assert errors == ["exported_audit: teacher identity SHA256 mismatch"]
