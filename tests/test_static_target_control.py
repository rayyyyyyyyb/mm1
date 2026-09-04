from pathlib import Path

import yaml

from scripts.run_static_target_control import (
    apply_overlay,
    evaluate_800_gates,
    validate_control_config,
)


def test_c0_and_c1_overlays_differ_only_in_strong_mode() -> None:
    root = Path(__file__).resolve().parents[1]
    c0 = yaml.safe_load((root / "configs/diagnostics/recovery/ov_orthkd_visual_only_sum_feature_seed42_c0_800.yaml").read_text())
    c1 = yaml.safe_load((root / "configs/diagnostics/recovery/ov_orthkd_visual_only_sum_feature_seed42_c1_static_800.yaml").read_text())
    base = yaml.safe_load((root / c0["base_config"]).read_text())
    merged0 = apply_overlay(base, c0["overrides"])
    merged1 = apply_overlay(base, c1["overrides"])
    assert merged0["loss"]["weak_teacher_projector_update_mode"] == merged1["loss"]["weak_teacher_projector_update_mode"]
    assert merged0["loss"]["text_teacher_projector_update_mode"] == merged1["loss"]["text_teacher_projector_update_mode"]
    assert merged0["loss"]["strong_teacher_projector_update_mode"] != merged1["loss"]["strong_teacher_projector_update_mode"]


def test_control_rejects_test_evaluation_and_requires_800_steps() -> None:
    valid = {
        "control": {"evaluate_test": False, "applied_optimizer_steps": 800},
        "overrides": {
            "loss": {
                "strong_teacher_projector_update_mode": "trainable",
                "weak_teacher_projector_update_mode": "trainable",
                "text_teacher_projector_update_mode": "trainable",
            }
        },
    }
    validate_control_config(valid)
    try:
        invalid = dict(valid)
        invalid["control"] = {"evaluate_test": True, "applied_optimizer_steps": 800}
        validate_control_config(invalid)
    except ValueError as exc:
        assert "test" in str(exc)
    else:
        raise AssertionError("test evaluation must be rejected")


def test_800_gate_requires_every_preregistered_condition() -> None:
    metrics = {
        "strong_projector_hash_unchanged": True,
        "projected_target_temporal_std": 0.16,
        "decision_temporal_std": 0.004,
        "projected_to_decision_distance_correlation": 0.25,
        "decision_centered_to_total_l2_ratio": 0.006,
        "mixed_validation_concordance_gain_over_c0": 0.03,
        "validation_ap_c0": 0.75,
        "validation_ap_c1": 0.74,
        "unexplained_amp_skips": 0,
        "clip_receipts_complete": True,
    }
    result = evaluate_800_gates(metrics)
    assert result["all_passed"] is True
    metrics["decision_temporal_std"] = 0.001
    failed = evaluate_800_gates(metrics)
    assert failed["all_passed"] is False
    assert failed["gates"]["decision_temporal_std"]["passed"] is False
