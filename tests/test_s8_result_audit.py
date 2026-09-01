from __future__ import annotations

import copy

import pytest
import torch

from scripts.audit_s8_results import (
    audit_inactive_checkpoint_states,
    extract_s8_primary_metrics,
    validate_identity_fixed_control_pair,
    validate_s8_training_diagnostics,
)


def _state(step: int) -> dict[str, torch.Tensor]:
    return {
        "temporal_encoder.weight": torch.tensor([1.0, 2.0]),
        "modality_gate.0.weight": torch.tensor([[3.0, 4.0]]),
        "token_fusion.1.weight": torch.tensor([[5.0, 6.0]]),
        "segment_head.weight": torch.tensor([[float(step), 0.0]]),
    }


def _diagnostics() -> list[dict[str, object]]:
    return [
        {
            "global_step_before_update": step,
            "gradient_l2_before_clip": {
                "student_temporal_encoder": 0.0,
                "student_modality_gate": 0.0,
                "student_token_fusion": 0.0,
                "student_visual_encoder": 1.0 / (step + 1.0),
            },
        }
        for step in (0, 400, 800)
    ]


def _ae_report() -> dict[str, object]:
    mixed_modes = {
        "content_original": {"ap": 0.71, "auroc": 0.68},
        "content_visual_zero": {"ap": 0.61, "auroc": 0.57},
    }
    return {
        "protocol": {"task_segments": 10, "expected_gate_mode": "fixed_equal"},
        "sources": {"best_checkpoint": {"global_step": 1200}},
        "intervention_metrics": {
            "strata": {"mixed": {"sample_count": 10, "modes": mixed_modes}},
            "mixed_only_shuffle": {
                "content_original": {
                    "ap": {"baseline": 0.71, "mean_drop": 0.08},
                    "auroc": {"baseline": 0.68, "mean_drop": 0.09},
                }
            },
            "mixed_pairwise_concordance": {
                "content_original": {
                    "pairs": 40,
                    "pair_weighted": 0.73,
                    "video_macro_mean": 0.70,
                }
            },
        },
        "timeline": {
            "step_001200": {
                "visual_timeline": {
                    "paths": {
                        "visual_backbone_features": {
                            "within_sample_temporal_std_mean": 0.12
                        },
                        "visual_projected_tokens": {
                            "within_sample_temporal_std_mean": 0.08
                        },
                    }
                },
                "fusion_input_blocks": {
                    "block_order": ["visual", "audio", "query"],
                    "blocks": {
                        "visual": {"frobenius_l2": 4.0},
                        "audio": {"frobenius_l2": 5.0},
                        "query": {"frobenius_l2": 6.0},
                    },
                },
                "first_test_batch_input_jacobians": {
                    "l2": {"visual": 0.3, "audio": 0.4, "query": 0.5}
                },
            }
        },
    }


def test_inactive_temporal_and_gate_states_must_equal_reconstructed_initial() -> None:
    initial = _state(0)
    checkpoints = {step: _state(step) for step in (400, 800, 1200)}

    result = audit_inactive_checkpoint_states(checkpoints, initial)

    assert result["temporal_encoder_unchanged_from_initial"] is True
    assert result["modality_gate_unchanged_from_initial"] is True
    assert result["active_segment_head_changed_across_steps"] is True

    tampered = copy.deepcopy(checkpoints)
    tampered[800]["modality_gate.0.weight"][0, 0] += 1.0
    with pytest.raises(ValueError, match="modality_gate"):
        audit_inactive_checkpoint_states(tampered, initial)


def test_additive_mode_requires_token_fusion_to_remain_at_initial_state() -> None:
    initial = _state(0)
    checkpoints = {step: _state(step) for step in (400, 800, 1200)}

    result = audit_inactive_checkpoint_states(
        checkpoints,
        initial,
        expected_fusion_mode="paper_additive_query_conditioned",
    )

    assert result["token_fusion_unchanged_from_initial"] is True
    tampered = copy.deepcopy(checkpoints)
    tampered[1200]["token_fusion.1.weight"][0, 0] += 1.0
    with pytest.raises(ValueError, match="token_fusion"):
        audit_inactive_checkpoint_states(
            tampered,
            initial,
            expected_fusion_mode="paper_additive_query_conditioned",
        )


def test_s8_diagnostics_require_zero_inactive_gradients() -> None:
    result = validate_s8_training_diagnostics(_diagnostics())
    assert result["visual_encoder_gradient_l2"] == [1.0, 1.0 / 401.0, 1.0 / 801.0]

    tampered = _diagnostics()
    gradients = tampered[1]["gradient_l2_before_clip"]
    assert isinstance(gradients, dict)
    gradients["student_modality_gate"] = 1e-5
    with pytest.raises(ValueError, match="modality_gate"):
        validate_s8_training_diagnostics(tampered)


def test_s9_diagnostics_require_zero_inactive_token_fusion_gradient() -> None:
    result = validate_s8_training_diagnostics(
        _diagnostics(),
        expected_fusion_mode="paper_additive_query_conditioned",
    )
    assert result["token_fusion_gradient_exact_zero"] is True

    tampered = _diagnostics()
    gradients = tampered[2]["gradient_l2_before_clip"]
    assert isinstance(gradients, dict)
    gradients["student_token_fusion"] = 1e-6
    with pytest.raises(ValueError, match="token_fusion"):
        validate_s8_training_diagnostics(
            tampered,
            expected_fusion_mode="paper_additive_query_conditioned",
        )


def test_s9_config_pair_contract_rejects_every_nonfusion_scientific_change() -> None:
    baseline = {
        "data": {"num_segments": 10, "train_augment": True},
        "student": {
            "fusion_mode": "concat_mlp_query_conditioned",
            "gate_mode": "fixed_equal",
            "temporal_path_mode": "identity_passthrough",
            "pretrained": False,
        },
        "training": {"epochs": 3, "max_batches_per_epoch": 400},
        "loss": {"alpha_strong_logit": 0.0},
        "reproduction": {"variant": "s8"},
        "logging": {"log_dir": "s8"},
    }
    candidate = copy.deepcopy(baseline)
    candidate["student"]["fusion_mode"] = "paper_additive_query_conditioned"
    candidate["reproduction"]["variant"] = "s9"
    candidate["logging"]["log_dir"] = "s9"

    result = validate_identity_fixed_control_pair(
        baseline,
        candidate,
        expected_fusion_mode="paper_additive_query_conditioned",
    )
    assert result["sole_scientific_change"] == "student.fusion_mode"

    tampered = copy.deepcopy(candidate)
    tampered["student"]["pretrained"] = True
    with pytest.raises(ValueError, match="student.fusion_mode"):
        validate_identity_fixed_control_pair(
            baseline,
            tampered,
            expected_fusion_mode="paper_additive_query_conditioned",
        )


def test_primary_metrics_are_extracted_without_inventing_a_success_threshold() -> None:
    result = extract_s8_primary_metrics(_ae_report(), _diagnostics())

    assert result["mixed_visual_zero"]["ap_drop"] == pytest.approx(0.10)
    assert result["mixed_visual_zero"]["auroc_drop"] == pytest.approx(0.11)
    assert result["mixed_temporal_shuffle"]["ap_mean_drop"] == 0.08
    assert result["visual_path"]["projected_temporal_std"] == 0.08
    assert result["best_checkpoint_step"] == 1200
    assert result["timeline"]["step_001200"]["visual_path"][
        "projected_temporal_std"
    ] == 0.08
    assert result["fusion_input_jacobian_l2"]["visual"] == 0.3
    assert result["scientific_outcome_threshold_preregistered"] is False
    assert result["automatic_scientific_success_claimed"] is False

    tampered = _ae_report()
    tampered["protocol"]["expected_gate_mode"] = "learned_softmax"  # type: ignore[index]
    with pytest.raises(ValueError, match="fixed_equal"):
        extract_s8_primary_metrics(tampered, _diagnostics())
