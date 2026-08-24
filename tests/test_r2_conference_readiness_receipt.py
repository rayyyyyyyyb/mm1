from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.build_conference_readiness_receipt as readiness_module
from scripts.build_conference_readiness_receipt import build_conference_readiness
from src.utils.canonical_readiness import (
    OFFICIAL_SPLIT_COUNTS,
    OFFICIAL_SPLIT_SEEN_UNSEEN_COUNTS,
    REQUIRED_ARCHIVAL_FACTS,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _ready_inputs(tmp_path: Path) -> dict[str, Path]:
    facts = {
        name: {"status": "resolved", "selected_value": name, "evidence": ["direct"]}
        for name in REQUIRED_ARCHIVAL_FACTS
    }
    checkpoint = {
        "role": "encoder",
        "source_url_or_archive": "https://example.invalid/checkpoint",
        "filename": "official.pt",
        "bytes": 1,
        "sha256": "b" * 64,
        "top_level_keys": ["model"],
        "pretrained_or_finetuned": "pretrained",
    }
    return {
        "data_lock": _write(
            tmp_path / "data-lock.json",
            {"schema_version": 2, "status": "ready", "archive_sha256": "a" * 64, "manifests": OFFICIAL_SPLIT_COUNTS},
        ),
        "preprocessing_lock": _write(
            tmp_path / "preprocessing-lock.json",
            {
                "schema_version": 1,
                "status": "resolved",
                "mode": "canonical_official_jpg_wav",
                "frame_policy": "natural_sorted_no_repeat",
                "canonical_visual_extension": ".jpg",
            },
        ),
        "archive_receipt": _write(
            tmp_path / "archive.json",
            {
                "schema_version": 1,
                "status": "passed",
                "archive_sha256": "a" * 64,
                "extraction_status": "passed",
                "archive_test": "passed",
                "content_magic_valid": True,
                "archive_listing": {"sha256": "f" * 64},
            },
        ),
        "layout_discovery": _write(
            tmp_path / "layout.json",
            {
                "schema_version": 1,
                "status": "passed",
                "split_counts": OFFICIAL_SPLIT_COUNTS,
                "metadata_bijection_verified": True,
                "missing_clip_ids": {split: [] for split in OFFICIAL_SPLIT_COUNTS},
                "extra_clip_ids": {split: [] for split in OFFICIAL_SPLIT_COUNTS},
                "duplicate_clip_ids": [],
                "duplicate_basenames": [],
                "duplicate_logical_basenames": [],
                "zero_byte_files": [],
                "errors": [],
                "warnings": [],
            },
        ),
        "source_audit": _write(
            tmp_path / "source.json",
            {
                "schema_version": 1,
                "status": "passed",
                "stage": "source",
                "artifact_scan": "none",
                "record_count": 24800,
                "split_counts": OFFICIAL_SPLIT_COUNTS,
                "source_manifest_sha256": {
                    "train": "1" * 64,
                    "val": "2" * 64,
                    "test": "3" * 64,
                },
                "manifest_bytes": {"train": 1, "val": 1, "test": 1},
                "split_seen_unseen_counts": OFFICIAL_SPLIT_SEEN_UNSEEN_COUNTS,
                "errors": [],
                "warnings": [],
            },
        ),
        "archival_lock": _write(tmp_path / "archival.json", {"schema_version": 2, "status": "resolved", "facts": facts}),
        "teacher_lock": _write(
            tmp_path / "teacher.json",
            {
                "schema_version": 1,
                "status": "ready",
                "teachers": {
                    "internvideo2": {
                        "status": "resolved",
                        "repository": "https://example.invalid/internvideo2",
                        "commit": "1" * 40,
                        "working_tree_clean": True,
                        "module": "internvideo.module",
                        "imported_class": "InternVideo2_CLIP_small",
                        "preprocessing": "locked",
                        "output_dim": 512,
                        "determinism_tolerance": 0.0,
                        "checkpoint_files": [
                            {
                                **checkpoint,
                                "role": role,
                                "filename": f"internvideo-{role}.pt",
                            }
                            for role in ("vision", "text", "extra_clip")
                        ],
                    },
                    "beats": {
                        "status": "resolved",
                        "repository": "https://example.invalid/beats",
                        "commit": "2" * 40,
                        "working_tree_clean": True,
                        "module": "beats.module",
                        "imported_class": "BEATs",
                        "preprocessing": "locked",
                        "output_dim": 768,
                        "determinism_tolerance": 0.0,
                        "checkpoint_files": [checkpoint],
                    },
                    "clap": {
                        "status": "resolved",
                        "repository": "https://example.invalid/clap",
                        "commit": "3" * 40,
                        "working_tree_clean": True,
                        "module": "clap.module",
                        "imported_class": "msclap.CLAP",
                        "preprocessing": "locked",
                        "output_dim": 1024,
                        "determinism_tolerance": 0.0,
                        "checkpoint_files": [{**checkpoint, "role": "text_encoder"}],
                    },
                },
                "real_smoke": {"status": "passed"},
                "full_export": {
                    "status": "passed",
                    "records": 24800,
                    "errors": 0,
                    "cache_root_sha256": "c" * 64,
                },
            },
        ),
        "teacher_identity": _write(
            tmp_path / "identity.json",
            {"schema_version": 1, "status": "pass", "errors": [], "smoke": {"status": "pass"}},
        ),
        "smoke_repeatability": _write(
            tmp_path / "repeat.json",
            {"schema_version": 1, "status": "pass", "all_finite": True},
        ),
        "exported_audit": _write(
            tmp_path / "exported.json",
            {
                "schema_version": 1,
                "status": "passed",
                "stage": "exported",
                "artifact_scan": "full",
                "record_count": 24800,
                "split_counts": OFFICIAL_SPLIT_COUNTS,
                "split_seen_unseen_counts": OFFICIAL_SPLIT_SEEN_UNSEEN_COUNTS,
                "errors": [],
                "warnings": [],
                "cache_root_sha256": "c" * 64,
            },
        ),
        "evaluator_lock": _write(
            tmp_path / "evaluator.json",
            {
                "schema_version": 1,
                "status": "resolved",
                "parity": {
                    "status": "passed",
                    "fixture_sha256": "d" * 64,
                    "receipt_sha256": "e" * 64,
                },
                "paper_f1_at_0_5_mapping": {"status": "resolved"},
                "validation_calibrated_f1_mapping": {"status": "resolved"},
            },
        ),
        "real_preflight": _write(
            tmp_path / "preflight.json",
            {
                "schema_version": 1,
                "status": "passed",
                "real_data": True,
                "optimizer_steps": 1,
                "invocation_count_this_stage": 1,
                "formal_metrics_emitted": False,
                "forward_completed": True,
                "backward_completed": True,
                "checkpoint_resume_completed": True,
                "losses_finite": True,
            },
        ),
        "verification": _write(
            tmp_path / "verification.json",
            {"status": "passed", "p0_p1_tests": "passed", "exact_resume": "passed"},
        ),
    }


def _config_for_inputs(tmp_path: Path, inputs: dict[str, Path]) -> dict:
    return {
        "reproduction": {
            "claim_level": "archival_exact",
            "variant": "conference_baseline",
            "full_run_blocked": True,
            "project_root": str(tmp_path),
            "readiness": {
                name: str(path)
                for name, path in inputs.items()
                if name != "verification"
            },
        },
        "data": {"path_root": str(tmp_path)},
    }


def test_builder_returns_ready_only_when_every_gate_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _ready_inputs(tmp_path)
    config = _config_for_inputs(tmp_path, inputs)
    monkeypatch.setattr(
        readiness_module,
        "validate_canonical_readiness",
        lambda value: {"status": "ready"},
    )

    report = build_conference_readiness(config, inputs)

    assert report["status"] == "READY_FOR_CONFERENCE_REPRO"
    assert report["ready"] is True
    assert all(item["passed"] for item in report["requirements"].values())


def test_builder_rejects_structurally_plausible_but_forged_receipts(tmp_path: Path) -> None:
    inputs = _ready_inputs(tmp_path)
    config = _config_for_inputs(tmp_path, inputs)

    report = build_conference_readiness(config, inputs)

    assert report["status"] == "BLOCKED_BEFORE_CONFERENCE_REPRO"
    assert report["ready"] is False
    assert report["requirements"]["canonical_evidence_chain"]["passed"] is False
    assert "canonical_evidence_chain" in report["blockers"]


def test_builder_rejects_cli_input_that_differs_from_config_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _ready_inputs(tmp_path)
    config = _config_for_inputs(tmp_path, inputs)
    replacement = _write(tmp_path / "different-source.json", {"status": "passed"})
    inputs["source_audit"] = replacement
    monkeypatch.setattr(
        readiness_module,
        "validate_canonical_readiness",
        lambda value: {"status": "ready"},
    )

    report = build_conference_readiness(config, inputs)

    assert report["requirements"]["canonical_evidence_chain"]["passed"] is False
    assert "does not match config readiness" in report["canonical_validation_error"]


def test_builder_is_blocked_when_official_archive_is_missing(tmp_path: Path) -> None:
    inputs = _ready_inputs(tmp_path)
    inputs["archive_receipt"].write_text(
        json.dumps({"status": "blocked_official_archive_not_provided", "archive_sha256": None}),
        encoding="utf-8",
    )
    config = {
        "reproduction": {
            "claim_level": "archival_exact",
            "variant": "conference_baseline",
            "full_run_blocked": True,
        }
    }

    report = build_conference_readiness(config, inputs)

    assert report["status"] == "BLOCKED_BEFORE_CONFERENCE_REPRO"
    assert report["ready"] is False
    assert report["requirements"]["official_archive_and_extraction"]["passed"] is False
    assert "official_archive_and_extraction" in report["blockers"]


def test_builder_requires_exactly_five_hashed_teacher_checkpoints(tmp_path: Path) -> None:
    inputs = _ready_inputs(tmp_path)
    teacher = json.loads(inputs["teacher_lock"].read_text(encoding="utf-8"))
    teacher["teachers"]["internvideo2"]["checkpoint_files"].pop()
    inputs["teacher_lock"].write_text(json.dumps(teacher), encoding="utf-8")
    config = {
        "reproduction": {
            "claim_level": "archival_exact",
            "variant": "conference_baseline",
            "full_run_blocked": True,
        }
    }

    report = build_conference_readiness(config, inputs)

    assert report["status"] == "BLOCKED_BEFORE_CONFERENCE_REPRO"
    assert report["requirements"]["teacher_lock_and_checkpoints"]["passed"] is False


def test_builder_requires_resolved_canonical_preprocessing_lock(tmp_path: Path) -> None:
    inputs = _ready_inputs(tmp_path)
    inputs["preprocessing_lock"].write_text(
        json.dumps({"status": "blocked", "mode": "noncanonical"}), encoding="utf-8"
    )
    config = {
        "reproduction": {
            "claim_level": "archival_exact",
            "variant": "conference_baseline",
            "full_run_blocked": True,
        }
    }

    report = build_conference_readiness(config, inputs)

    assert report["status"] == "BLOCKED_BEFORE_CONFERENCE_REPRO"
    assert report["requirements"]["preprocessing_lock"]["passed"] is False


def test_readiness_builder_is_directly_executable() -> None:
    completed = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "build_conference_readiness_receipt.py"), "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--output-json" in completed.stdout
