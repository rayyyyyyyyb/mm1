from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import scripts.run_teacher_signal_controls as controls
from scripts.run_teacher_signal_controls import authorize_control, validate_control_wrapper


def _wrapper(name: str = "D1_centered_visual_800") -> dict[str, object]:
    return {
        "base_config": "configs/base.yaml",
        "control": {
            "name": name,
            "registered_change": {
                "D1_centered_visual_800": "loss.visual_feature_centering",
                "D2_visual_pretrained_800": "student.visual_pretrained",
                "D3_visual_logit_800": "student.path_mode",
            }[name],
            "applied_optimizer_steps": 800,
            "evaluate_test": False,
        },
        "overrides": {
            "loss": {
                "strong_teacher_projector_update_mode": "static_zero_lr_keep_grad",
                "weak_teacher_projector_update_mode": "trainable",
                "text_teacher_projector_update_mode": "trainable",
                "visual_feature_centering": "per_sample_temporal",
            },
            "training": {"gradient_clipping": {"scope": "optimizer_groups_with_positive_lr"}},
        },
    }


def test_control_wrapper_is_fail_closed_and_exactly_800_steps() -> None:
    validate_control_wrapper(_wrapper())
    with pytest.raises(ValueError):
        validate_control_wrapper({**_wrapper(), "control": {"name": "D1", "applied_optimizer_steps": 799, "evaluate_test": False}})


def test_d1_requires_teacher_and_shortcut_gates() -> None:
    evidence = {"phase_a": {"teacher_gate_pass": True}, "phase_c": {"scientific_status": "SHORTCUT_AGREEMENT_CONFIRMED"}, "phase_d": {"scientific_status": "VISUAL_PRETRAINING_CONTROL_NOT_PASS"}}
    assert authorize_control("D1_centered_visual_800", evidence)["authorized"] is True
    blocked = {"phase_a": {"teacher_gate_pass": False}, "phase_c": {"scientific_status": "SHORTCUT_AGREEMENT_CONFIRMED"}}
    assert authorize_control("D1_centered_visual_800", blocked)["authorized"] is False


def test_d2_and_d3_fail_closed_without_their_registered_gate() -> None:
    evidence = {"phase_a": {"teacher_gate_pass": True}, "phase_c": {"scientific_status": "SHORTCUT_AGREEMENT_CONFIRMED"}, "phase_d": {"scientific_status": "VISUAL_PRETRAINING_CONTROL_NOT_PASS"}}
    assert authorize_control("D2_visual_pretrained_800", evidence)["authorized"] is False
    assert authorize_control("D3_visual_logit_800", evidence)["authorized"] is False


def test_control_result_requires_eight_hundred_applied_steps_and_no_test(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wrapper_path = tmp_path / "wrapper.yaml"
    wrapper_path.write_text(
        "base_config: configs/diagnostics/recovery/ov_orthkd_visual_only_sum_feature_seed42_no_workers.yaml\n"
        "control:\n  name: D1_centered_visual_800\n  registered_change: loss.visual_feature_centering\n"
        "  applied_optimizer_steps: 800\n  evaluate_test: false\n"
        "overrides:\n  loss:\n    strong_teacher_projector_update_mode: static_zero_lr_keep_grad\n"
        "    weak_teacher_projector_update_mode: trainable\n    text_teacher_projector_update_mode: trainable\n"
        "    visual_feature_centering: per_sample_temporal\n"
        "  training:\n    gradient_clipping:\n      scope: optimizer_groups_with_positive_lr\n",
        encoding="utf-8",
    )
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps({"phase_a": {"teacher_gate_pass": True}, "phase_c": {"scientific_status": "SHORTCUT_AGREEMENT_CONFIRMED"}}), encoding="utf-8")
    repo_root = Path(__file__).resolve().parents[1]
    output_root = tmp_path / "diagnostic" / "noncanonical"

    class Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(controls.subprocess, "run", lambda *args, **kwargs: Completed())
    result = controls.run_control(wrapper_path, evidence_path, repo_root, output_root)
    assert result["status"] == "CONTROL_RECEIPT_MISMATCH"
    assert result["receipt_ok"] is False


def test_materialize_rejects_any_unregistered_change(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    wrapper = yaml.safe_load(
        (repo_root / "configs/diagnostics/recovery/ov_orthkd_d1_centered_visual_seed42_800.yaml").read_text(encoding="utf-8")
    )
    wrapper["overrides"]["data"] = {"batch_size": 8}
    wrapper_path = tmp_path / "wrapper.yaml"
    wrapper_path.write_text(yaml.safe_dump(wrapper, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match="must differ from fixed C2 baseline only"):
        controls.materialize_config(wrapper_path, repo_root, tmp_path / "diagnostic" / "noncanonical")
