import numpy as np
import pytest

from scripts.audit_static_target_fixed_budget import summarize_fixed_budget


def _payload() -> dict[str, np.ndarray]:
    logits = np.asarray(
        [
            2.0, -1.0, -2.0, -2.0, -2.0, -2.0, -2.0, -2.0, -2.0, -2.0,
            -2.0, 2.0, -1.0, -2.0, -2.0, -2.0, -2.0, -2.0, -2.0, -2.0,
        ]
    )
    return {
        "ids": np.asarray(["a", "b"]),
        "queries": np.asarray(["q1", "q2"]),
        "split_types": np.asarray(["seen", "unseen"]),
        "sample_offsets": np.asarray([0, 10, 20]),
        "segment_indices": np.tile(np.arange(10), 2),
        "labels": np.asarray([1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0]),
        "logits": logits,
        "probabilities": 1.0 / (1.0 + np.exp(-logits)),
    }


def test_fixed_budget_summary_validates_and_is_deterministic() -> None:
    first = summarize_fixed_budget(_payload())
    second = summarize_fixed_budget(_payload())
    assert first == second
    assert first["samples"] == 2
    assert first["segments"] == 20
    assert first["mixed_pair_weighted_concordance"] == pytest.approx(1.0)
    assert first["temporal_shuffle"]["repeats"] == 100


def test_fixed_budget_summary_rejects_non_ten_offsets() -> None:
    payload = _payload()
    payload["sample_offsets"] = np.asarray([0, 2, 6])
    with pytest.raises(ValueError, match="10 task segments"):
        summarize_fixed_budget(payload)
