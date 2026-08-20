from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.utils.reproduction_locks import validate_teacher_lock


def _checkpoint(name: str) -> dict[str, Any]:
    return {
        "path": f"weights/{name}.pt",
        "source_url": f"https://official.example/{name}.pt",
        "bytes": 123,
        "sha256": "a" * 64,
    }


def _resolved_lock() -> dict[str, Any]:
    base = {
        "status": "resolved",
        "repository": "https://github.com/official/repository.git",
        "commit": "b" * 40,
        "module": "official.module",
        "imported_class": "OfficialTeacher",
        "checkpoint_files": [_checkpoint("model")],
        "preprocessing": {"sample_rate": 16000},
    }
    return {
        "schema_version": 1,
        "status": "resolved",
        "teachers": {
            "internvideo2": {**base, "declared_variant": "exact-base-b14"},
            "beats": {**base, "variant": "exact-pretrained"},
            "clap": {**base, "version": "2023", "normalize": False},
        },
    }


def test_fully_specified_resolved_teacher_lock_is_ready() -> None:
    result = validate_teacher_lock(_resolved_lock())

    assert result == {"ready": True, "errors": [], "unresolved": []}


def test_resolved_teacher_lock_fails_closed_on_missing_exact_checkpoint_hash() -> None:
    lock = _resolved_lock()
    del lock["teachers"]["beats"]["checkpoint_files"][0]["sha256"]

    result = validate_teacher_lock(lock)

    assert result["ready"] is False
    assert any("beats.checkpoint_files[0].sha256" in error for error in result["errors"])


def test_resolved_teacher_lock_fails_closed_on_class_and_variant_ambiguity() -> None:
    lock = _resolved_lock()
    lock["teachers"]["internvideo2"]["imported_class"] = None
    lock["teachers"]["internvideo2"]["declared_variant"] = None
    lock["teachers"]["clap"]["normalize"] = None

    result = validate_teacher_lock(lock)

    assert result["ready"] is False
    assert any("internvideo2.imported_class" in error for error in result["errors"])
    assert any("internvideo2.declared_variant" in error for error in result["errors"])
    assert any("clap.normalize" in error for error in result["errors"])


def test_committed_r3_lock_resolves_teachers_but_keeps_data_dependent_work_blocked() -> None:
    lock_path = Path(__file__).resolve().parents[1] / "configs" / "locks" / "mm26_teacher_lock.yaml"
    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))

    result = validate_teacher_lock(lock)

    assert result["ready"] is False
    assert result["errors"] == []
    assert result["unresolved"] == []
    assert lock["real_smoke"]["status"] == "blocked_auth_required"
    assert lock["full_export"]["status"] == "blocked_auth_required"
