#!/usr/bin/env python3

from __future__ import annotations

import math
from typing import Any, Mapping


TASK_SEGMENTS = 10
ADDITIVE_FUSION_MODE = "paper_additive_query_conditioned"


def _mapping(value: Any, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"S9 evidence is missing {location}")
    return value


def _finite_float(value: Any, location: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"S9 evidence has a non-finite value at {location}")
    return result


def extract_s9_scientific_metrics(ae_report: Mapping[str, Any]) -> dict[str, Any]:
    protocol = _mapping(ae_report.get("protocol"), "protocol")
    if int(protocol.get("task_segments", -1)) != TASK_SEGMENTS:
        raise ValueError("S9 evidence must preserve official T=10")
    if protocol.get("expected_gate_mode") != "fixed_equal":
        raise ValueError("S9 evidence must explicitly bind fixed_equal gate mode")
    if protocol.get("expected_fusion_mode") != ADDITIVE_FUSION_MODE:
        raise ValueError("S9 evidence must explicitly bind paper-additive fusion")

    intervention = _mapping(
        ae_report.get("intervention_metrics"), "intervention_metrics"
    )
    strata = _mapping(intervention.get("strata"), "intervention_metrics.strata")
    mixed = _mapping(strata.get("mixed"), "intervention_metrics.strata.mixed")
    modes = _mapping(mixed.get("modes"), "mixed modes")
    original = _mapping(modes.get("content_original"), "mixed content_original")
    visual_zero = _mapping(
        modes.get("content_visual_zero"), "mixed content_visual_zero"
    )
    concordances = _mapping(
        intervention.get("mixed_pairwise_concordance"),
        "mixed_pairwise_concordance",
    )
    original_concordance = _mapping(
        concordances.get("content_original"), "original concordance"
    )
    visual_zero_concordance = _mapping(
        concordances.get("content_visual_zero"), "visual-zero concordance"
    )
    forced_visual_concordance = _mapping(
        concordances.get("gate_v100_a000_original"),
        "forced-visual concordance",
    )
    shuffles = _mapping(
        intervention.get("mixed_only_shuffle"), "mixed_only_shuffle"
    )
    original_shuffle = _mapping(
        shuffles.get("content_original"), "original temporal shuffle"
    )
    original_shuffle_ap = _mapping(
        original_shuffle.get("ap"), "original temporal shuffle AP"
    )
    forced_visual_shuffle = _mapping(
        shuffles.get("gate_v100_a000_original"),
        "forced-visual temporal shuffle",
    )
    forced_visual_shuffle_ap = _mapping(
        forced_visual_shuffle.get("ap"), "forced-visual temporal shuffle AP"
    )

    original_ap = _finite_float(original.get("ap"), "mixed original AP")
    original_auroc = _finite_float(
        original.get("auroc"), "mixed original AUROC"
    )
    visual_zero_ap = _finite_float(
        visual_zero.get("ap"), "mixed visual-zero AP"
    )
    visual_zero_auroc = _finite_float(
        visual_zero.get("auroc"), "mixed visual-zero AUROC"
    )
    original_c = _finite_float(
        original_concordance.get("pair_weighted"),
        "mixed original pairwise concordance",
    )
    visual_zero_c = _finite_float(
        visual_zero_concordance.get("pair_weighted"),
        "mixed visual-zero pairwise concordance",
    )
    result = {
        "mixed_sample_count": int(mixed.get("sample_count", -1)),
        "visual_causal_effects": {
            "mixed_ap_drop": original_ap - visual_zero_ap,
            "mixed_auroc_drop": original_auroc - visual_zero_auroc,
            "mixed_pairwise_concordance_drop": original_c - visual_zero_c,
        },
        "noncollapse_protection": {
            "mixed_original_ap": original_ap,
            "mixed_original_pairwise_concordance": original_c,
            "mixed_temporal_shuffle_ap_drop": _finite_float(
                original_shuffle_ap.get("mean_drop"),
                "mixed temporal-shuffle AP drop",
            ),
        },
        "supporting_forced_visual_pairwise_concordance": _finite_float(
            forced_visual_concordance.get("pair_weighted"),
            "forced-visual pairwise concordance",
        ),
        "supporting_forced_visual_temporal_shuffle_ap_drop": _finite_float(
            forced_visual_shuffle_ap.get("mean_drop"),
            "forced-visual temporal-shuffle AP drop",
        ),
    }
    if result["mixed_sample_count"] < 1:
        raise ValueError("S9 mixed sample count must be positive")
    return result


def classify_s9_outcome(
    *,
    delta_concordance: float,
    delta_ap: float,
    delta_auroc: float,
    mixed_ap: float,
    mixed_concordance: float,
    mixed_shuffle_ap_drop: float,
    implementation_integrity_passed: bool,
) -> dict[str, Any]:
    values = {
        "delta_concordance": float(delta_concordance),
        "delta_ap": float(delta_ap),
        "delta_auroc": float(delta_auroc),
        "mixed_ap": float(mixed_ap),
        "mixed_concordance": float(mixed_concordance),
        "mixed_shuffle_ap_drop": float(mixed_shuffle_ap_drop),
    }
    if not all(math.isfinite(value) for value in values.values()):
        raise ValueError("S9 classification inputs must all be finite")

    implementation_gate = bool(implementation_integrity_passed)
    weak_effect_fail = (
        values["delta_concordance"] < 0.010
        and values["delta_ap"] < 0.005
        and values["delta_auroc"] < 0.005
    )
    nonpositive_effect_count = sum(
        value <= 0.0
        for value in (
            values["delta_concordance"],
            values["delta_ap"],
            values["delta_auroc"],
        )
    )
    causal_pass = (
        values["delta_concordance"] >= 0.020
        and (
            (
                values["delta_ap"] >= 0.010
                and values["delta_auroc"] > 0.0
            )
            or (
                values["delta_auroc"] >= 0.010
                and values["delta_ap"] > 0.0
            )
        )
    )
    protection_pass = (
        values["mixed_ap"] >= 0.640
        and values["mixed_concordance"] >= 0.650
        and values["mixed_shuffle_ap_drop"] >= 0.020
    )

    if not implementation_gate:
        classification = "FAIL"
        reason = "implementation_integrity_gate_failed"
    elif weak_effect_fail:
        classification = "FAIL"
        reason = "all_visual_effects_below_preregistered_fail_thresholds"
    elif nonpositive_effect_count >= 2:
        classification = "FAIL"
        reason = "at_least_two_visual_effects_are_nonpositive"
    elif causal_pass and protection_pass:
        classification = "PASS"
        reason = "visual_causal_and_noncollapse_gates_passed"
    else:
        classification = "INCONCLUSIVE"
        reason = "between_preregistered_pass_and_fail_regions"

    return {
        "classification": classification,
        "reason": reason,
        "inputs": values,
        "gates": {
            "implementation_integrity_passed": implementation_gate,
            "causal_pass": causal_pass,
            "noncollapse_protection_pass": protection_pass,
            "weak_effect_fail": weak_effect_fail,
            "nonpositive_effect_count": nonpositive_effect_count,
        },
        "thresholds": {
            "pass": {
                "delta_concordance_min": 0.020,
                "one_global_ranking_delta_min": 0.010,
                "other_global_ranking_delta_strictly_positive": True,
                "mixed_ap_min": 0.640,
                "mixed_concordance_min": 0.650,
                "mixed_shuffle_ap_drop_min": 0.020,
            },
            "fail": {
                "delta_concordance_below": 0.010,
                "delta_ap_below": 0.005,
                "delta_auroc_below": 0.005,
                "nonpositive_effect_count_min": 2,
            },
        },
        "next_experiment_authorized": False,
        "formal_full_training_authorized": False,
    }


def build_s9_scientific_outcome(
    ae_report: Mapping[str, Any],
    *,
    implementation_integrity_passed: bool,
) -> dict[str, Any]:
    metrics = extract_s9_scientific_metrics(ae_report)
    effects = metrics["visual_causal_effects"]
    protection = metrics["noncollapse_protection"]
    classification = classify_s9_outcome(
        delta_concordance=effects["mixed_pairwise_concordance_drop"],
        delta_ap=effects["mixed_ap_drop"],
        delta_auroc=effects["mixed_auroc_drop"],
        mixed_ap=protection["mixed_original_ap"],
        mixed_concordance=protection["mixed_original_pairwise_concordance"],
        mixed_shuffle_ap_drop=protection["mixed_temporal_shuffle_ap_drop"],
        implementation_integrity_passed=implementation_integrity_passed,
    )
    return {
        "artifact_integrity": (
            "PASS" if implementation_integrity_passed else "FAIL"
        ),
        "metrics": metrics,
        "scientific_outcome": classification,
        "scientific_outcome_threshold_preregistered": True,
        "next_experiment_authorized": False,
        "formal_full_training_authorized": False,
    }
