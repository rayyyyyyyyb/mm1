from __future__ import annotations

import copy

import numpy as np
import pytest

from scripts.audit_d2a_paired_early_dynamics import (
    _independent_gate,
    _validate_predictions,
)


def _payload() -> dict[str, np.ndarray]:
    logits = np.linspace(-1.0, 1.0, 20)
    return {
        "ids": np.asarray(["a", "b"]),
        "queries": np.asarray(["q1", "q2"]),
        "split_types": np.asarray(["seen", "unseen"]),
        "sample_offsets": np.asarray([0, 10, 20], dtype=np.int64),
        "segment_indices": np.tile(np.arange(10), 2),
        "labels": np.asarray([0, 0, 1, 1, 0, 0, 1, 1, 0, 0] * 2),
        "logits": logits,
        "probabilities": 1.0 / (1.0 + np.exp(-logits)),
    }


def test_independent_auditor_rejects_probability_or_timeline_tampering() -> None:
    payload = _payload()
    _validate_predictions(payload)
    changed = copy.deepcopy(payload)
    changed["probabilities"][0] += 0.01
    with pytest.raises(ValueError, match="sigmoid"):
        _validate_predictions(changed)
    changed = copy.deepcopy(payload)
    changed["segment_indices"][9] = 8
    with pytest.raises(ValueError, match="0..9"):
        _validate_predictions(changed)


def test_independent_gate_uses_step400_paths_and_all_fixed_conditions() -> None:
    raw = {
        "random": {
            "mixed_pair_weighted_concordance": 0.50,
            "validation_ap": 0.70,
        },
        "pretrained": {
            "mixed_pair_weighted_concordance": 0.53,
            "validation_ap": 0.69,
            "predicted_positive_rate": 0.5,
            "visual_zero_mixed_concordance_drop": 0.02,
            "shuffle": {"ap_drop": 0.011, "auroc_drop": 0.0},
        },
    }
    snapshot = {
        "arms": {
            "pretrained": {
                "paths": {
                    "decision_features": {
                        "within_sample_temporal_std_mean": 0.004
                    }
                }
            }
        }
    }
    gate = {
        "pretrained_minus_random_mixed_concordance_min": 0.020,
        "supporting_required_count": 2,
        "pretrained_decision_temporal_std_min": 0.003,
        "pretrained_temporal_shuffle_ap_or_auroc_drop_min": 0.010,
        "pretrained_visual_zero_mixed_concordance_drop_min": 0.010,
        "pretrained_validation_ap_floor_relative_to_random": -0.020,
        "pretrained_predicted_positive_rate_max_exclusive": 0.98,
    }
    result = _independent_gate(raw, snapshot, gate)
    assert result["pass"] is True
    assert all(result["requirements"].values())

    raw["pretrained"]["predicted_positive_rate"] = 0.98
    result = _independent_gate(raw, snapshot, gate)
    assert result["pass"] is False
    assert result["requirements"]["predicted_positive_rate"] is False
