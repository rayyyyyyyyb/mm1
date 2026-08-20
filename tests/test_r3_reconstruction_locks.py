from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK_ROOT = PROJECT_ROOT / "configs/locks"


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _config_value(config: dict, dotted_path: str):
    value = config
    for component in dotted_path.split("."):
        value = value[component]
    return value


def test_nine_archival_facts_are_user_approved_and_exactly_bound_to_config() -> None:
    config = _yaml(PROJECT_ROOT / "configs/ov_orthkd_mm26_repro.yaml")
    lock = _yaml(LOCK_ROOT / "mm26_archival_facts.yaml")
    approval = PROJECT_ROOT / "reports/archival/R3_USER_APPROVED_RECONSTRUCTION.md"
    approval_hash = hashlib.sha256(approval.read_bytes()).hexdigest()

    assert lock["schema_version"] == 2
    assert lock["status"] == "resolved"
    assert lock["claim_level"] == "paper_specified_reconstruction"
    assert len(lock["facts"]) == 9
    for fact in lock["facts"].values():
        assert fact["status"] == "approved_reconstruction_assumption"
        assert fact["approved_by"] == "user"
        assert fact["evidence"] == [
            {
                "kind": "user_approval",
                "approved_by": "user",
                "path": "reports/archival/R3_USER_APPROVED_RECONSTRUCTION.md",
                "sha256": approval_hash,
            }
        ]
        binding_map = {item["path"]: item["value"] for item in fact["config_bindings"]}
        assert fact["selected_value"] == binding_map
        for path, value in binding_map.items():
            assert _config_value(config, path) == value


def test_preprocessing_lock_freezes_taskbook_visual_audio_and_raw_video_semantics() -> None:
    config = _yaml(PROJECT_ROOT / "configs/ov_orthkd_mm26_repro.yaml")
    lock = _yaml(LOCK_ROOT / "mm26_preprocessing_lock.yaml")

    assert lock["schema_version"] == 1
    assert lock["status"] == "resolved"
    assert lock["mode"] == config["data"]["preprocessing_mode"]
    assert lock["frame_policy"] == config["data"]["frame_policy"]
    assert lock["visual"] == config["data"]["visual_preprocessing"]
    assert lock["audio"] == config["data"]["audio_preprocessing"]
    assert lock["internvideo2"] == config["teacher_export"]["internvideo2"] | {
        "checkpoint_identity_included": True
    }


def test_evaluator_lock_resolves_only_the_two_taskbook_mappings() -> None:
    config = _yaml(PROJECT_ROOT / "configs/ov_orthkd_mm26_repro.yaml")
    lock = _yaml(LOCK_ROOT / "mm26_evaluator_lock.yaml")

    assert lock["status"] == "resolved"
    assert lock["source"]["path"] == (
        "external/OV-AVEL/proposed_method/ImageBind-main/utils/eval_metrics.py"
    )
    assert lock["paper_f1_at_0_5_mapping"] == {
        "status": "resolved",
        "value": config["evaluation"]["paper_f1_at_0_5_mapping"],
        "config_path": "evaluation.paper_f1_at_0_5_mapping",
    }
    assert lock["validation_calibrated_f1_mapping"] == {
        "status": "resolved",
        "value": config["evaluation"]["validation_calibrated_f1_mapping"],
        "config_path": "evaluation.validation_calibrated_f1_mapping",
    }
    assert lock["event_f1_policy"] == "supplemental_only_not_paper_f1"


def test_hash_locked_text_evidence_is_checked_out_with_lf_bytes() -> None:
    evidence_paths = [
        "reports/archival/R3_USER_APPROVED_RECONSTRUCTION.md",
        "tests/fixtures/official_ovavel_metric_cases.json",
        "reports/evaluation/mm26_official_evaluator_parity_receipt.json",
    ]

    for path in evidence_paths:
        completed = subprocess.run(
            ["git", "check-attr", "eol", "--", path],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        assert completed.stdout.strip().endswith(": eol: lf")
