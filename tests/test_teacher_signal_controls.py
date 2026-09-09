from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import scripts.run_teacher_signal_controls as controls
from scripts.run_teacher_signal_controls import authorize_control, validate_control_wrapper


def _wrapper(name: str = "D1_centered_visual_800") -> dict[str, object]:
    loss_overrides: dict[str, object] = {
        "strong_teacher_projector_update_mode": "static_zero_lr_keep_grad",
        "weak_teacher_projector_update_mode": "trainable",
        "text_teacher_projector_update_mode": "trainable",
    }
    student_overrides: dict[str, object] = {}
    if name == "D1_centered_visual_800":
        loss_overrides["visual_feature_centering"] = "per_sample_temporal"
    elif name == "D2_visual_pretrained_800":
        student_overrides["visual_pretrained"] = True
    elif name == "D3_visual_logit_800":
        loss_overrides.update(
            {"alpha_strong_logit": 0.25, "confidence_weighting": False}
        )
        student_overrides["path_mode"] = "explicit_projected"
    return {
        "base_config": "configs/diagnostics/recovery/ov_orthkd_visual_only_sum_feature_seed42_no_workers.yaml",
        "control": {
            "name": name,
            "registered_change": {
                "D1_centered_visual_800": "loss.visual_feature_centering",
                "D2_visual_pretrained_800": "student.visual_pretrained",
                "D3_visual_logit_800": "loss.alpha_strong_logit",
            }[name],
            "applied_optimizer_steps": 800,
            "evaluate_test": False,
        },
        "overrides": {
            "student": student_overrides,
            "loss": loss_overrides,
            "training": {"gradient_clipping": {"scope": "optimizer_groups_with_positive_lr"}},
        },
    }


def test_control_wrapper_is_fail_closed_and_exactly_800_steps() -> None:
    validate_control_wrapper(_wrapper())
    with pytest.raises(ValueError):
        validate_control_wrapper({**_wrapper(), "control": {"name": "D1", "applied_optimizer_steps": 799, "evaluate_test": False}})


def test_d1_requires_teacher_and_shortcut_gates() -> None:
    evidence = {"phase_a": {"teacher_gate_pass": True}, "phase_c": {"scientific_status": "VISUAL_MEAN_COMPONENT_DOMINANCE_CONFIRMED"}, "phase_d": {"scientific_status": "D2_BLOCKED_BY_PRETRAINED_ASSET_NOT_TESTED"}}
    assert authorize_control("D1_centered_visual_800", evidence)["authorized"] is True
    blocked = {"phase_a": {"teacher_gate_pass": False}, "phase_c": {"scientific_status": "VISUAL_MEAN_COMPONENT_DOMINANCE_CONFIRMED"}}
    assert authorize_control("D1_centered_visual_800", blocked)["authorized"] is False


def test_d2_and_d3_fail_closed_without_their_registered_gate() -> None:
    evidence = {"phase_a": {"teacher_gate_pass": True}, "phase_c": {"scientific_status": "VISUAL_MEAN_COMPONENT_DOMINANCE_CONFIRMED"}, "phase_d": {"scientific_status": "D2_BLOCKED_BY_PRETRAINED_ASSET_NOT_TESTED"}}
    assert authorize_control("D2_visual_pretrained_800", evidence)["authorized"] is False
    assert authorize_control("D3_visual_logit_800", evidence)["authorized"] is False


def test_d3_authorizes_from_phase_a_direct_logit_evidence() -> None:
    evidence = {
        "phase_a": {
            "direct_mixed_video_macro_concordance": 0.6297,
            "direct_best_temporal_shift": 0,
            "direct_shuffle_ap_drop": 0.01,
            "direct_shuffle_auroc_drop": 0.0256,
            "visual_logit_gate_pass": True,
        }
    }

    result = authorize_control("D3_visual_logit_800", evidence)

    assert result["authorized"] is True
    assert result["visual_logit_gate"]["pass"] is True


def test_d3_rejects_inconsistent_declared_direct_logit_gate() -> None:
    evidence = {
        "phase_a": {
            "direct_mixed_video_macro_concordance": 0.59,
            "direct_best_temporal_shift": 0,
            "direct_shuffle_auroc_drop": 0.03,
            "visual_logit_gate_pass": True,
        }
    }

    with pytest.raises(ValueError, match="visual_logit_gate_pass"):
        authorize_control("D3_visual_logit_800", evidence)


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
    evidence_path.write_text(json.dumps({"phase_a": {"teacher_gate_pass": True}, "phase_c": {"scientific_status": "VISUAL_MEAN_COMPONENT_DOMINANCE_CONFIRMED"}}), encoding="utf-8")
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


def test_d3_materializes_only_positive_visual_logit_weight(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    wrapper_path = tmp_path / "d3.yaml"
    wrapper_path.write_text(yaml.safe_dump(_wrapper("D3_visual_logit_800"), sort_keys=False), encoding="utf-8")

    resolved_path = controls.materialize_config(
        wrapper_path, repo_root, tmp_path / "diagnostic" / "noncanonical"
    )
    resolved = yaml.safe_load(resolved_path.read_text(encoding="utf-8"))

    assert resolved["loss"]["alpha_strong_logit"] == pytest.approx(0.25)
    assert resolved["student"]["path_mode"] == "explicit_projected"
    assert resolved["loss"]["confidence_weighting"] is False
    assert resolved["training"]["max_optimizer_steps"] == 800
    assert resolved["evaluation"]["run_test"] is False


def test_d3_wrapper_requires_positive_locked_weight_and_exact_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    invalid = _wrapper("D3_visual_logit_800")
    invalid["overrides"]["loss"]["alpha_strong_logit"] = 0.0
    with pytest.raises(ValueError, match="positive alpha_strong_logit"):
        validate_control_wrapper(invalid)

    wrapper_path = tmp_path / "d3.yaml"
    wrapper_path.write_text(
        yaml.safe_dump(_wrapper("D3_visual_logit_800"), sort_keys=False),
        encoding="utf-8",
    )
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "phase_a": {
                    "direct_mixed_video_macro_concordance": 0.63,
                    "direct_best_temporal_shift": 0,
                    "direct_shuffle_auroc_drop": 0.026,
                    "visual_logit_gate_pass": True,
                }
            }
        ),
        encoding="utf-8",
    )
    output_root = tmp_path / "diagnostic" / "noncanonical"

    class Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        assert command[-2:] == ["--max-optimizer-steps", "800"]
        output_dir = output_root / "D3_visual_logit_800"
        (output_dir / "optimizer_step_summary.json").write_text(
            json.dumps({"attempted_steps": 803, "applied_steps": 800}),
            encoding="utf-8",
        )
        return Completed()

    monkeypatch.setattr(controls.subprocess, "run", fake_run)

    result = controls.run_control(
        wrapper_path, evidence_path, repo_root, output_root
    )

    assert result["status"] == "PASS"
    assert result["receipt_ok"] is True
    assert result["applied_optimizer_steps"] == 800
    assert result["test_evaluation"] is False
    assert not (output_root / "D3_visual_logit_800" / "test_predictions.npz").exists()
