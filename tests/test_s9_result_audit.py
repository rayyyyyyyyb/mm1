from __future__ import annotations

import copy

import pytest

from scripts.audit_s9_results import (
    build_s9_scientific_outcome,
    classify_s9_outcome,
    extract_s9_scientific_metrics,
)


def _ae_report() -> dict[str, object]:
    return {
        "protocol": {
            "task_segments": 10,
            "expected_gate_mode": "fixed_equal",
            "expected_fusion_mode": "paper_additive_query_conditioned",
        },
        "intervention_metrics": {
            "strata": {
                "mixed": {
                    "sample_count": 1941,
                    "modes": {
                        "content_original": {"ap": 0.670, "auroc": 0.650},
                        "content_visual_zero": {"ap": 0.655, "auroc": 0.645},
                    },
                }
            },
            "mixed_only_shuffle": {
                "content_original": {"ap": {"mean_drop": 0.030}},
                "gate_v100_a000_original": {"ap": {"mean_drop": 0.012}},
            },
            "mixed_pairwise_concordance": {
                "content_original": {"pairs": 35594, "pair_weighted": 0.680},
                "content_visual_zero": {
                    "pairs": 35594,
                    "pair_weighted": 0.655,
                },
                "gate_v100_a000_original": {
                    "pairs": 35594,
                    "pair_weighted": 0.590,
                },
            },
        },
    }


def test_s9_metrics_are_derived_from_original_minus_visual_zero() -> None:
    metrics = extract_s9_scientific_metrics(_ae_report())

    assert metrics["visual_causal_effects"] == {
        "mixed_ap_drop": pytest.approx(0.015),
        "mixed_auroc_drop": pytest.approx(0.005),
        "mixed_pairwise_concordance_drop": pytest.approx(0.025),
    }
    assert metrics["noncollapse_protection"] == {
        "mixed_original_ap": 0.670,
        "mixed_original_pairwise_concordance": 0.680,
        "mixed_temporal_shuffle_ap_drop": 0.030,
    }
    assert metrics["supporting_forced_visual_pairwise_concordance"] == 0.590
    assert metrics["supporting_forced_visual_temporal_shuffle_ap_drop"] == 0.012


def test_s9_scientific_outcome_keeps_artifact_and_scientific_status_separate() -> None:
    result = build_s9_scientific_outcome(
        _ae_report(), implementation_integrity_passed=True
    )

    assert result["artifact_integrity"] == "PASS"
    assert result["scientific_outcome"]["classification"] == "PASS"
    assert result["scientific_outcome_threshold_preregistered"] is True
    assert result["next_experiment_authorized"] is False
    assert result["formal_full_training_authorized"] is False


@pytest.mark.parametrize(
    ("effects", "protection", "integrity", "expected"),
    [
        (
            {"delta_c": 0.020, "delta_ap": 0.010, "delta_auc": 0.001},
            {"mixed_ap": 0.640, "mixed_c": 0.650, "shuffle_ap_drop": 0.020},
            True,
            "PASS",
        ),
        (
            {"delta_c": 0.021, "delta_ap": 0.001, "delta_auc": 0.010},
            {"mixed_ap": 0.650, "mixed_c": 0.660, "shuffle_ap_drop": 0.021},
            True,
            "PASS",
        ),
        (
            {"delta_c": 0.009, "delta_ap": 0.004, "delta_auc": 0.004},
            {"mixed_ap": 0.700, "mixed_c": 0.700, "shuffle_ap_drop": 0.040},
            True,
            "FAIL",
        ),
        (
            {"delta_c": 0.020, "delta_ap": 0.000, "delta_auc": -0.001},
            {"mixed_ap": 0.700, "mixed_c": 0.700, "shuffle_ap_drop": 0.040},
            True,
            "FAIL",
        ),
        (
            {"delta_c": 0.015, "delta_ap": 0.006, "delta_auc": 0.006},
            {"mixed_ap": 0.700, "mixed_c": 0.700, "shuffle_ap_drop": 0.040},
            True,
            "INCONCLUSIVE",
        ),
        (
            {"delta_c": 0.030, "delta_ap": 0.020, "delta_auc": 0.001},
            {"mixed_ap": 0.630, "mixed_c": 0.700, "shuffle_ap_drop": 0.040},
            True,
            "INCONCLUSIVE",
        ),
        (
            {"delta_c": 0.030, "delta_ap": 0.020, "delta_auc": 0.001},
            {"mixed_ap": 0.700, "mixed_c": 0.700, "shuffle_ap_drop": 0.040},
            False,
            "FAIL",
        ),
    ],
)
def test_s9_preregistered_threshold_boundaries(
    effects: dict[str, float],
    protection: dict[str, float],
    integrity: bool,
    expected: str,
) -> None:
    result = classify_s9_outcome(
        delta_concordance=effects["delta_c"],
        delta_ap=effects["delta_ap"],
        delta_auroc=effects["delta_auc"],
        mixed_ap=protection["mixed_ap"],
        mixed_concordance=protection["mixed_c"],
        mixed_shuffle_ap_drop=protection["shuffle_ap_drop"],
        implementation_integrity_passed=integrity,
    )

    assert result["classification"] == expected
    assert result["formal_full_training_authorized"] is False
    assert result["next_experiment_authorized"] is False


def test_s9_metric_extraction_rejects_unbound_or_nonofficial_evidence() -> None:
    wrong_fusion = copy.deepcopy(_ae_report())
    wrong_fusion["protocol"]["expected_fusion_mode"] = (  # type: ignore[index]
        "concat_mlp_query_conditioned"
    )
    with pytest.raises(ValueError, match="additive"):
        extract_s9_scientific_metrics(wrong_fusion)

    wrong_timeline = copy.deepcopy(_ae_report())
    wrong_timeline["protocol"]["task_segments"] = 16  # type: ignore[index]
    with pytest.raises(ValueError, match="T=10"):
        extract_s9_scientific_metrics(wrong_timeline)
