from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

import src.utils.canonical_readiness as readiness_module
from scripts.train_ov_orthkd import validate_repro_config
from src.utils.reproduction_fingerprint import build_reproduction_fingerprint

try:
    from src.utils.canonical_readiness import (
        canonical_experiment_config_sha256,
        validate_canonical_readiness,
    )
except ModuleNotFoundError:
    canonical_experiment_config_sha256 = None
    validate_canonical_readiness = None


OFFICIAL_COUNTS = {"train": 13182, "val": 5798, "test": 5820}


@pytest.fixture(autouse=True)
def _bind_derived_code_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(readiness_module, "CODE_ROOT", tmp_path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_yaml(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def _file_evidence(root: Path, name: str, contents: str) -> dict[str, Any]:
    path = root / "evidence" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    return {"path": path.relative_to(root).as_posix(), "sha256": _sha256(path)}


def _resolved_fixture(root: Path) -> tuple[dict[str, Any], dict[str, Path]]:
    archive = _file_evidence(root, "official.zip", "official archive")
    archive_listing = _file_evidence(root, "official_archive_listing.txt", "listing")
    manifests = {
        split: {
            **_file_evidence(root, f"{split}.jsonl", f"{split}\n"),
            "count": count,
        }
        for split, count in OFFICIAL_COUNTS.items()
    }
    for value in manifests.values():
        value["bytes"] = (root / value["path"]).stat().st_size
    split_types = {
        "train": {"seen": 13182, "unseen": 0},
        "val": {"seen": 1651, "unseen": 4147},
        "test": {"seen": 1664, "unseen": 4156},
    }

    archival_paths = {
        "temporal_protocol": ("data.max_segments", "task.label_mode"),
        "internvideo_identity": (
            "teacher_export.strong_visual_backend",
            "teacher_export.internvideo2.declared_model_class",
        ),
        "scheduler_and_early_stop": (
            "training.epochs",
            "training.scheduler",
            "training.early_stop_patience",
            "training.early_stop_min_delta",
        ),
        "student_initialization_and_augmentation": ("student.pretrained", "data.train_augment"),
        "visual_l2_reduction": ("loss.visual_l2_reduction",),
        "query_aware_fusion": ("student.fusion_mode",),
        "frame_sampling": (
            "teacher_export.internvideo2.num_frames",
            "teacher_export.internvideo2.frame_sampling",
            "teacher_export.internvideo2.short_clip_policy",
        ),
        "student_audio_preprocessing": ("data.audio_preprocessing",),
        "evaluator_mapping": (
            "evaluation.paper_f1_at_0_5_mapping",
            "evaluation.validation_calibrated_f1_mapping",
        ),
    }
    locked_values = {
        "data.max_segments": 10,
        "task.label_mode": "query_conditioned_binary",
        "teacher_export.strong_visual_backend": "internvideo2_clip_b14",
        "teacher_export.internvideo2.declared_model_class": "InternVideo2_CLIP_small",
        "training.scheduler": {"type": "cosine", "interval": "epoch"},
        "training.epochs": 30,
        "training.early_stop_patience": 5,
        "training.early_stop_min_delta": 0.0,
        "student.pretrained": True,
        "data.train_augment": False,
        "loss.visual_l2_reduction": "mean",
        "student.fusion_mode": "query_aware_additive_transformer",
        "teacher_export.internvideo2.num_frames": 10,
        "teacher_export.internvideo2.frame_sampling": "natural_sorted_no_repeat",
        "teacher_export.internvideo2.short_clip_policy": "error",
        "data.audio_preprocessing": {"sample_rate": 16000, "representation": "waveform"},
        "evaluation.paper_f1_at_0_5_mapping": "segment",
        "evaluation.validation_calibrated_f1_mapping": "binary",
    }
    facts = {}
    for name in archival_paths:
        binding_map = {path: locked_values[path] for path in archival_paths[name]}
        evidence = _file_evidence(root, f"archival_{name}.txt", f"direct evidence for {name}\n")
        facts[name] = {
            "status": "resolved",
            "selected_value": binding_map,
            "evidence": [{"kind": "file", **evidence}],
            "config_bindings": [
                {"path": path, "value": locked_values[path]}
                for path in archival_paths[name]
            ],
        }
    archival_lock = {"schema_version": 2, "status": "resolved", "facts": facts}

    checkpoint_hashes: list[str] = []
    checkpoint_paths: dict[tuple[str, str], Path] = {}
    teachers = {}
    teacher_defs = {
        "internvideo2": ("InternVideo2_CLIP_small", ("vision", "text", "extra_clip")),
        "beats": ("BEATs", ("encoder",)),
        "clap": ("CLAP_Module", ("text_encoder",)),
    }
    for name, (class_name, roles) in teacher_defs.items():
        checkpoint_files = []
        for role in roles:
            checkpoint = _file_evidence(root, f"{name}_{role}.pt", f"checkpoint {name} {role}")
            checkpoint_path = root / checkpoint["path"]
            checkpoint_paths[(name, role)] = checkpoint_path
            checkpoint_hashes.append(checkpoint["sha256"])
            checkpoint_files.append(
                {
                    "role": role,
                    "source_url_or_archive": "https://example.invalid/checkpoint",
                    "filename": checkpoint_path.name,
                    "bytes": checkpoint_path.stat().st_size,
                    "sha256": checkpoint["sha256"],
                    "top_level_keys": ["model"],
                    "pretrained_or_finetuned": "pretrained",
                }
            )
        teachers[name] = {
            "status": "resolved",
            "repository": f"https://example.invalid/{name}.git",
            "commit": "1" * 40,
            "working_tree_clean": True,
            "module": f"{name}.module",
            "imported_class": class_name,
            "preprocessing": "locked preprocessing",
            "output_dim": {"internvideo2": 512, "beats": 768, "clap": 1024}[name],
            "determinism_tolerance": 0.0,
            "checkpoint_files": checkpoint_files,
        }
    cache_root_sha256 = "a" * 64
    teacher_lock = {
        "schema_version": 1,
        "status": "ready",
        "teachers": teachers,
        "real_smoke": {"status": "passed"},
        "full_export": {
            "status": "passed",
            "records": 24800,
            "errors": 0,
            "cache_root_sha256": cache_root_sha256,
            **{
                f"{split}_manifest_sha256": value["sha256"]
                for split, value in manifests.items()
            },
        },
    }

    preprocessing_lock = {
        "schema_version": 1,
        "status": "resolved",
        "mode": "canonical_official_jpg_wav",
        "path_mode": "relative_to_path_root",
        "frame_policy": "natural_sorted_no_repeat",
        "canonical_visual_extension": ".jpg",
        "config_bindings": [
            {"path": "data.preprocessing_mode", "value": "canonical_official_jpg_wav"},
            {"path": "data.frame_policy", "value": "natural_sorted_no_repeat"},
            {"path": "data.canonical_visual_extension", "value": ".jpg"},
        ],
    }
    evaluator_source = _file_evidence(root, "eval_metrics.py", "official evaluator")
    evaluator_fixture = _file_evidence(root, "evaluator_fixture.json", "fixture")
    evaluator_receipt = _file_evidence(root, "evaluator_receipt.json", "receipt")
    evaluator_lock = {
        "schema_version": 1,
        "status": "resolved",
        "repository": "https://github.com/jasongief/OV-AVEL.git",
        "commit": "b5fe1d685d0c6d0d6fd80312b5ccde79f9b73ea6",
        "source": evaluator_source,
        "parity": {
            "status": "passed",
            "fixture_path": evaluator_fixture["path"],
            "fixture_sha256": evaluator_fixture["sha256"],
            "receipt_path": evaluator_receipt["path"],
            "receipt_sha256": evaluator_receipt["sha256"],
        },
        "paper_f1_at_0_5_mapping": {
            "status": "resolved",
            "value": "segment",
            "config_path": "evaluation.paper_f1_at_0_5_mapping",
        },
        "validation_calibrated_f1_mapping": {
            "status": "resolved",
            "value": "binary",
            "config_path": "evaluation.validation_calibrated_f1_mapping",
        },
    }

    paths = {
        "data_lock": root / "locks" / "data.yaml",
        "archival_lock": root / "locks" / "archival.yaml",
        "teacher_lock": root / "locks" / "teacher.yaml",
        "preprocessing_lock": root / "locks" / "preprocessing.yaml",
        "evaluator_lock": root / "locks" / "evaluator.yaml",
        "archive_receipt": root / "reports" / "archive.json",
        "layout_discovery": root / "reports" / "layout.json",
        "source_audit": root / "reports" / "source_audit.json",
        "teacher_identity": root / "reports" / "teacher_identity.json",
        "smoke_repeatability": root / "reports" / "repeatability.json",
        "exported_audit": root / "reports" / "exported_audit.json",
        "real_preflight": root / "reports" / "real_preflight.json",
    }
    source_audit = {
        "schema_version": 1,
        "status": "passed",
        "stage": "source",
        "artifact_scan": "none",
        "record_count": 24800,
        "split_counts": OFFICIAL_COUNTS,
        "split_seen_unseen_counts": split_types,
        "source_manifest_sha256": {split: value["sha256"] for split, value in manifests.items()},
        "manifest_bytes": {split: value["bytes"] for split, value in manifests.items()},
        "errors": [],
        "warnings": [],
    }
    paths["source_audit"].parent.mkdir(parents=True, exist_ok=True)
    paths["source_audit"].write_text(json.dumps(source_audit), encoding="utf-8")
    source_audit_evidence = {
        "path": paths["source_audit"].relative_to(root).as_posix(),
        "sha256": _sha256(paths["source_audit"]),
    }
    data_lock = {
        "schema_version": 2,
        "status": "ready",
        "official_archive": archive,
        "source_manifests": {"status": "passed", **manifests},
        "source_audit": {"status": "passed", **source_audit_evidence},
    }
    for key, value in (
        ("data_lock", data_lock),
        ("archival_lock", archival_lock),
        ("teacher_lock", teacher_lock),
        ("preprocessing_lock", preprocessing_lock),
        ("evaluator_lock", evaluator_lock),
    ):
        _write_yaml(paths[key], value)
    paths["archive_receipt"].write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "passed",
                "extraction_status": "passed",
                "archive_test": "passed",
                "content_magic_valid": True,
                "archive_listing": archive_listing,
                "archive": archive["path"],
                "archive_sha256": archive["sha256"],
            }
        ),
        encoding="utf-8",
    )
    paths["layout_discovery"].write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "passed",
                "split_counts": OFFICIAL_COUNTS,
                "metadata_bijection_verified": True,
                "missing_clip_ids": {split: [] for split in OFFICIAL_COUNTS},
                "extra_clip_ids": {split: [] for split in OFFICIAL_COUNTS},
                "duplicate_clip_ids": [],
                "duplicate_basenames": [],
                "duplicate_logical_basenames": [],
                "zero_byte_files": [],
                "errors": [],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    paths["teacher_identity"].write_text(
        json.dumps({"schema_version": 1, "status": "pass", "errors": [], "smoke": {"status": "pass"}}),
        encoding="utf-8",
    )
    paths["smoke_repeatability"].write_text(
        json.dumps({"schema_version": 1, "status": "pass", "all_finite": True}),
        encoding="utf-8",
    )
    paths["exported_audit"].write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "passed",
                "stage": "exported",
                "artifact_scan": "full",
                "errors": [],
                "warnings": [],
                "record_count": 24800,
                "split_counts": OFFICIAL_COUNTS,
                "split_seen_unseen_counts": split_types,
                "exported_manifest_sha256": {
                    split: value["sha256"] for split, value in manifests.items()
                },
                "manifest_bytes": {
                    split: value["bytes"] for split, value in manifests.items()
                },
                "cache_root_sha256": cache_root_sha256,
                "teacher_checkpoint_sha256": sorted(checkpoint_hashes),
            }
        ),
        encoding="utf-8",
    )
    paths["real_preflight"].write_text(
        json.dumps(
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
            }
        ),
        encoding="utf-8",
    )
    config = {
        "reproduction": {
            "claim_level": "archival_exact",
            "full_run_blocked": False,
            "implementation_mode": "camera_ready_explicit_paths",
            "project_root": str(root),
            "archival_parameters": {},
            "readiness": {key: path.relative_to(root).as_posix() for key, path in paths.items()},
        },
        "data": {
            "path_root": str(root),
            "max_segments": locked_values["data.max_segments"],
            "train_augment": locked_values["data.train_augment"],
            "audio_preprocessing": locked_values["data.audio_preprocessing"],
            "preprocessing_mode": "canonical_official_jpg_wav",
            "frame_policy": "natural_sorted_no_repeat",
            "canonical_visual_extension": ".jpg",
            **{f"{split}_manifest": value["path"] for split, value in manifests.items()},
        },
        "task": {"label_mode": locked_values["task.label_mode"]},
        "student": {
            "path_mode": "explicit_projected",
            "pretrained": locked_values["student.pretrained"],
            "fusion_mode": locked_values["student.fusion_mode"],
        },
        "loss": {"visual_l2_reduction": locked_values["loss.visual_l2_reduction"]},
        "training": {
            "epochs": locked_values["training.epochs"],
            "scheduler": locked_values["training.scheduler"],
            "early_stop_patience": locked_values["training.early_stop_patience"],
            "early_stop_min_delta": locked_values["training.early_stop_min_delta"],
            "max_batches_per_epoch": None,
            "max_optimizer_steps": None,
        },
        "evaluation": {
            "paper_f1_at_0_5_mapping": locked_values["evaluation.paper_f1_at_0_5_mapping"],
            "validation_calibrated_f1_mapping": locked_values[
                "evaluation.validation_calibrated_f1_mapping"
            ],
        },
        "teacher_export": {
            "strong_visual_backend": locked_values["teacher_export.strong_visual_backend"],
            "internvideo2": {
                "declared_model_class": locked_values[
                    "teacher_export.internvideo2.declared_model_class"
                ],
                "num_frames": locked_values["teacher_export.internvideo2.num_frames"],
                "frame_sampling": locked_values[
                    "teacher_export.internvideo2.frame_sampling"
                ],
                "short_clip_policy": locked_values[
                    "teacher_export.internvideo2.short_clip_policy"
                ],
                "vision_ckpt_path": str(checkpoint_paths[("internvideo2", "vision")]),
                "vision_ckpt_sha256": teachers["internvideo2"]["checkpoint_files"][0]["sha256"],
                "text_ckpt_path": str(checkpoint_paths[("internvideo2", "text")]),
                "text_ckpt_sha256": teachers["internvideo2"]["checkpoint_files"][1]["sha256"],
                "extra_ckpt_path": str(checkpoint_paths[("internvideo2", "extra_clip")]),
                "extra_ckpt_sha256": teachers["internvideo2"]["checkpoint_files"][2]["sha256"],
            },
            "beats": {
                "checkpoint_path": str(checkpoint_paths[("beats", "encoder")]),
                "checkpoint_sha256": teachers["beats"]["checkpoint_files"][0]["sha256"],
            },
            "clap": {
                "checkpoint_path": str(checkpoint_paths[("clap", "text_encoder")]),
                "checkpoint_sha256": teachers["clap"]["checkpoint_files"][0]["sha256"],
            },
        },
    }
    archival_lock["canonical_experiment_config_sha256"] = canonical_experiment_config_sha256(
        config
    )
    _write_yaml(paths["archival_lock"], archival_lock)
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "fixture@example.invalid"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "R2 Fixture"],
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "-m", "fixture"],
        check=True,
        capture_output=True,
    )
    return config, paths


def test_archival_exact_claim_cannot_bypass_gate_with_false_boolean(tmp_path: Path) -> None:
    config = {
        "reproduction": {
            "claim_level": "archival_exact",
            "full_run_blocked": False,
            "readiness": {},
        },
        "data": {"path_root": str(tmp_path)},
    }

    with pytest.raises(RuntimeError, match="Canonical readiness gate failed"):
        validate_repro_config(config, allow_blocked=False, preflight=False)


def test_resolved_locks_and_exported_audit_pass_content_validation(tmp_path: Path) -> None:
    assert validate_canonical_readiness is not None, "R2 canonical readiness validator is missing"
    config, _ = _resolved_fixture(tmp_path)

    receipt = validate_canonical_readiness(config)

    assert receipt["status"] == "ready"
    assert receipt["official_counts"] == {"test": 5820, "train": 13182, "val": 5798}
    assert receipt["cache_root_sha256"] == "a" * 64
    assert receipt["errors"] == []


def test_resolved_evidence_cannot_bypass_full_run_block(tmp_path: Path) -> None:
    config, _ = _resolved_fixture(tmp_path)
    config["reproduction"]["full_run_blocked"] = True

    with pytest.raises(RuntimeError, match="full run is blocked"):
        validate_repro_config(config, allow_blocked=False, preflight=False)


def test_paper_reconstruction_claim_cannot_skip_readiness(tmp_path: Path) -> None:
    config = {
        "reproduction": {
            "claim_level": "paper_specified_reconstruction",
            "full_run_blocked": False,
            "readiness": {},
        },
        "data": {"path_root": str(tmp_path)},
    }

    with pytest.raises(RuntimeError, match="Canonical readiness gate failed"):
        validate_repro_config(config, allow_blocked=False, preflight=False)


def test_unknown_formal_claim_level_is_rejected() -> None:
    config = {
        "reproduction": {
            "claim_level": "invented_formal_claim",
            "full_run_blocked": False,
        }
    }

    with pytest.raises(RuntimeError, match="Unsupported formal reproduction claim_level"):
        validate_repro_config(config, allow_blocked=False, preflight=False)


def test_formal_train_entry_rejects_partial_evaluation_batches() -> None:
    config = {"reproduction": {"claim_level": "archival_exact"}}

    with pytest.raises(RuntimeError, match="partial formal evaluation"):
        validate_repro_config(
            config,
            allow_blocked=False,
            preflight=False,
            max_eval_batches=1,
        )


def test_formal_eval_only_requires_a_checkpoint_before_readiness_or_outputs() -> None:
    config = {"reproduction": {"claim_level": "archival_exact"}}

    with pytest.raises(RuntimeError, match="eval-only requires --resume"):
        validate_repro_config(
            config,
            allow_blocked=False,
            preflight=False,
            eval_only=True,
            resume_path=None,
        )


def test_formal_claim_rejects_incompatible_resume_override() -> None:
    config = {"reproduction": {"claim_level": "archival_exact"}}

    with pytest.raises(RuntimeError, match="incompatible resume"):
        validate_repro_config(
            config,
            allow_blocked=False,
            preflight=False,
            allow_incompatible_resume=True,
        )


@pytest.mark.parametrize(
    ("training_patch", "deprecated_limit"),
    [
        ({"max_batches_per_epoch": 1}, None),
        ({"max_optimizer_steps": 1}, None),
        ({}, 1),
    ],
)
def test_formal_claim_rejects_truncated_training(
    training_patch: dict[str, Any],
    deprecated_limit: int | None,
) -> None:
    config = {
        "reproduction": {"claim_level": "archival_exact"},
        "training": training_patch,
    }

    with pytest.raises(RuntimeError, match="truncated formal training"):
        validate_repro_config(
            config,
            allow_blocked=False,
            preflight=False,
            max_train_steps=deprecated_limit,
        )


def test_gate_detects_evidence_tampering_after_lock_creation(tmp_path: Path) -> None:
    assert validate_canonical_readiness is not None, "R2 canonical readiness validator is missing"
    config, _ = _resolved_fixture(tmp_path)
    (tmp_path / "evidence" / "internvideo2_vision.pt").write_text("tampered", encoding="utf-8")

    with pytest.raises(RuntimeError, match="SHA256 mismatch"):
        validate_canonical_readiness(config)


@pytest.mark.parametrize(
    ("path", "tampered_value"),
    [
        (("training", "scheduler"), {"type": "step", "interval": "batch"}),
        (("student", "fusion_mode"), "concat_mlp"),
        (("teacher_export", "internvideo2", "frame_sampling"), "uniform_repeat"),
        (("data", "audio_preprocessing"), {"sample_rate": 48000}),
        (("evaluation", "paper_f1_at_0_5_mapping"), "event"),
    ],
)
def test_archival_and_evaluator_values_are_bound_to_runtime_config(
    tmp_path: Path,
    path: tuple[str, ...],
    tampered_value: Any,
) -> None:
    config, _ = _resolved_fixture(tmp_path)
    target = config
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = tampered_value

    with pytest.raises(RuntimeError, match="config binding mismatch"):
        validate_canonical_readiness(config)


def test_preprocessing_values_are_bound_to_runtime_config(tmp_path: Path) -> None:
    config, _ = _resolved_fixture(tmp_path)
    config["data"]["frame_policy"] = "lexicographic_repeat"

    with pytest.raises(RuntimeError, match="config binding mismatch"):
        validate_canonical_readiness(config)


def test_canonical_git_check_uses_project_root_and_fails_closed(tmp_path: Path) -> None:
    config, _ = _resolved_fixture(tmp_path)
    non_repository = tmp_path / "external-code-copy"
    non_repository.mkdir()
    config["reproduction"]["project_root"] = str(non_repository)

    with pytest.raises(RuntimeError, match="project_root must resolve to the actual code root"):
        validate_canonical_readiness(config)


def test_project_root_cannot_point_to_an_unrelated_clean_repository(tmp_path: Path) -> None:
    config, _ = _resolved_fixture(tmp_path)
    unrelated = tmp_path / "unrelated-clean-repo"
    unrelated.mkdir()
    subprocess.run(["git", "init", "-q", str(unrelated)], check=True, capture_output=True)
    config["reproduction"]["project_root"] = str(unrelated)

    with pytest.raises(RuntimeError, match="project_root must resolve to the actual code root"):
        validate_canonical_readiness(config)


def test_full_normalized_experiment_config_is_hash_locked(tmp_path: Path) -> None:
    config, _ = _resolved_fixture(tmp_path)
    config["seed"] = 999

    with pytest.raises(RuntimeError, match="canonical experiment config SHA256 mismatch"):
        validate_canonical_readiness(config)


def test_archival_evidence_must_be_structured_and_recomputable(tmp_path: Path) -> None:
    config, paths = _resolved_fixture(tmp_path)
    archival = yaml.safe_load(paths["archival_lock"].read_text(encoding="utf-8"))
    archival["facts"]["temporal_protocol"]["evidence"] = ["trust me"]
    _write_yaml(paths["archival_lock"], archival)

    with pytest.raises(RuntimeError, match="structured file or Git locator"):
        validate_canonical_readiness(config)


def test_archival_selected_value_must_equal_binding_map(tmp_path: Path) -> None:
    config, paths = _resolved_fixture(tmp_path)
    archival = yaml.safe_load(paths["archival_lock"].read_text(encoding="utf-8"))
    archival["facts"]["query_aware_fusion"]["selected_value"] = {"claim": "unrelated"}
    _write_yaml(paths["archival_lock"], archival)

    with pytest.raises(RuntimeError, match="selected_value must equal config binding map"):
        validate_canonical_readiness(config)


def test_archival_exact_resolved_fact_rejects_user_approval_evidence(tmp_path: Path) -> None:
    config, paths = _resolved_fixture(tmp_path)
    approval = _file_evidence(tmp_path, "approval.txt", "approved by user\n")
    archival = yaml.safe_load(paths["archival_lock"].read_text(encoding="utf-8"))
    archival["facts"]["temporal_protocol"]["evidence"] = [
        {"kind": "user_approval", "approved_by": "user", **approval}
    ]
    _write_yaml(paths["archival_lock"], archival)

    with pytest.raises(RuntimeError, match="only valid for an explicitly approved"):
        validate_canonical_readiness(config)


def test_archival_git_locator_must_reproduce_commit_path_bytes(tmp_path: Path) -> None:
    config, paths = _resolved_fixture(tmp_path)
    archival = yaml.safe_load(paths["archival_lock"].read_text(encoding="utf-8"))
    archival["facts"]["temporal_protocol"]["evidence"] = [
        {
            "kind": "git",
            "repository": "https://example.invalid/forged",
            "checkout_root": ".",
            "commit": "f" * 40,
            "path": "nonexistent/history.yaml",
            "blob_sha256": "e" * 64,
        }
    ]
    _write_yaml(paths["archival_lock"], archival)

    with pytest.raises(RuntimeError, match="Git locator bytes/repository cannot be reproduced"):
        validate_canonical_readiness(config)


def test_paper_reconstruction_allows_explicit_user_approval_file(tmp_path: Path) -> None:
    config, paths = _resolved_fixture(tmp_path)
    config["reproduction"]["claim_level"] = "paper_specified_reconstruction"
    approval = _file_evidence(tmp_path, "approval.txt", "approved by user\n")
    archival = yaml.safe_load(paths["archival_lock"].read_text(encoding="utf-8"))
    fact = archival["facts"]["temporal_protocol"]
    fact["status"] = "approved_reconstruction_assumption"
    fact["approved_by"] = "user"
    fact["evidence"] = [
        {"kind": "user_approval", "approved_by": "user", **approval}
    ]
    archival["canonical_experiment_config_sha256"] = canonical_experiment_config_sha256(config)
    _write_yaml(paths["archival_lock"], archival)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-q", "-m", "approved assumption"],
        check=True,
        capture_output=True,
    )

    receipt = validate_canonical_readiness(config)

    assert receipt["claim_level"] == "paper_specified_reconstruction"


def test_paper_reconstruction_recomputes_user_approval_file_hash(tmp_path: Path) -> None:
    config, paths = _resolved_fixture(tmp_path)
    config["reproduction"]["claim_level"] = "paper_specified_reconstruction"
    approval = _file_evidence(tmp_path, "approval.txt", "approved by user\n")
    archival = yaml.safe_load(paths["archival_lock"].read_text(encoding="utf-8"))
    fact = archival["facts"]["temporal_protocol"]
    fact["status"] = "approved_reconstruction_assumption"
    fact["approved_by"] = "user"
    fact["evidence"] = [
        {"kind": "user_approval", "approved_by": "user", **approval}
    ]
    archival["canonical_experiment_config_sha256"] = canonical_experiment_config_sha256(config)
    _write_yaml(paths["archival_lock"], archival)
    (tmp_path / approval["path"]).write_text("tampered approval\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-q", "-m", "tampered approval"],
        check=True,
        capture_output=True,
    )

    with pytest.raises(RuntimeError, match="archival_lock: SHA256 mismatch"):
        validate_canonical_readiness(config)


def test_external_data_root_does_not_rebase_repository_evidence(tmp_path: Path) -> None:
    config, paths = _resolved_fixture(tmp_path)
    external_data_root = tmp_path / "external-data-volume"
    external_data_root.mkdir()
    config["data"]["path_root"] = str(external_data_root)
    data_lock = yaml.safe_load(paths["data_lock"].read_text(encoding="utf-8"))
    for split in OFFICIAL_COUNTS:
        manifest_path = tmp_path / data_lock["source_manifests"][split]["path"]
        data_lock["source_manifests"][split]["path"] = str(manifest_path)
        config["data"][f"{split}_manifest"] = str(manifest_path)
    _write_yaml(paths["data_lock"], data_lock)
    archive = json.loads(paths["archive_receipt"].read_text(encoding="utf-8"))
    archive["archive"] = str(tmp_path / archive["archive"])
    paths["archive_receipt"].write_text(json.dumps(archive), encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-q", "-m", "external data root"],
        check=True,
        capture_output=True,
    )

    receipt = validate_canonical_readiness(config)

    assert receipt["status"] == "ready"


def test_teacher_checkpoint_roles_must_be_exact_and_unique(tmp_path: Path) -> None:
    config, paths = _resolved_fixture(tmp_path)
    teacher_lock = yaml.safe_load(paths["teacher_lock"].read_text(encoding="utf-8"))
    vision = teacher_lock["teachers"]["internvideo2"]["checkpoint_files"][0]
    teacher_lock["teachers"]["internvideo2"]["checkpoint_files"] = [dict(vision) for _ in range(3)]
    _write_yaml(paths["teacher_lock"], teacher_lock)
    exported = json.loads(paths["exported_audit"].read_text(encoding="utf-8"))
    other_hashes = [
        teacher_lock["teachers"]["beats"]["checkpoint_files"][0]["sha256"],
        teacher_lock["teachers"]["clap"]["checkpoint_files"][0]["sha256"],
    ]
    exported["teacher_checkpoint_sha256"] = sorted([vision["sha256"]] * 3 + other_hashes)
    paths["exported_audit"].write_text(json.dumps(exported), encoding="utf-8")

    with pytest.raises(RuntimeError, match="checkpoint roles"):
        validate_canonical_readiness(config)


def test_fingerprint_binds_locks_audit_git_mode_and_variant(tmp_path: Path) -> None:
    config, paths = _resolved_fixture(tmp_path)
    lock_paths = {key: value for key, value in paths.items() if key.endswith("_lock")}
    first = build_reproduction_fingerprint(
        config,
        lock_paths=lock_paths,
        evidence_paths={"exported_audit": paths["exported_audit"]},
        git_state={"commit": "2" * 40, "dirty": False},
        run_mode="train",
        variant="conference_baseline",
    )
    evaluator = yaml.safe_load(paths["evaluator_lock"].read_text(encoding="utf-8"))
    evaluator["parity"]["fixture_sha256"] = "c" * 64
    _write_yaml(paths["evaluator_lock"], evaluator)
    second = build_reproduction_fingerprint(
        config,
        lock_paths=lock_paths,
        evidence_paths={"exported_audit": paths["exported_audit"]},
        git_state={"commit": "2" * 40, "dirty": False},
        run_mode="train",
        variant="conference_baseline",
    )

    assert first["sha256"] != second["sha256"]
    assert first["components"]["git_state"] == {"commit": "2" * 40, "dirty": False}
    assert first["components"]["run_mode"] == "train"
    assert first["components"]["variant"] == "conference_baseline"
    assert first["components"]["evidence"]["exported_audit"]["exists"] is True


def test_committed_blocked_receipts_fail_closed_without_internal_type_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(readiness_module, "CODE_ROOT", project_root)
    config = yaml.safe_load(
        (project_root / "configs" / "ov_orthkd_mm26_repro.yaml").read_text(encoding="utf-8")
    )

    with pytest.raises(RuntimeError, match="Canonical readiness gate failed"):
        validate_canonical_readiness(config)
