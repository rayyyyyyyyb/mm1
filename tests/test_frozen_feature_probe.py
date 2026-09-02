from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml

from scripts.audit_frozen_feature_probes import _validate_protocol
from src.utils.frozen_feature_probe import (
    ALPHA_GRID,
    build_probe_designs,
    choose_alpha,
    mixed_metrics,
    shuffle_metrics,
    summarize_probe_outcome,
)


def _fixture_features() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    visual = np.array(
        [[[1.0, 2.0], [3.0, 4.0]], [[5.0, 6.0], [7.0, 8.0]]], dtype=np.float32
    )
    audio = visual + 10.0
    query = np.full_like(visual, 20.0)
    position = np.array([[[0.5, 1.5], [2.5, 3.5]]], dtype=np.float32)
    return visual, audio, query, position


def test_build_probe_designs_zero_pads_qp_and_equalizes_capacity() -> None:
    visual, audio, query, position = _fixture_features()
    designs = build_probe_designs(visual, audio, query, position)

    assert set(designs) == {"qp", "vqp", "aqp"}
    assert all(value.shape == (2, 2, 8) for value in designs.values())
    # QP is [zero, q, zero, p], not a shorter two-block feature vector.
    np.testing.assert_allclose(designs["qp"][0, 0], [0, 0, 20, 20, 0, 0, 0.5, 1.5])
    np.testing.assert_allclose(
        designs["vqp"][0, 0], [1, 2, 20, 20, 20, 40, 0.5, 1.5]
    )
    np.testing.assert_allclose(
        designs["aqp"][0, 0], [11, 12, 20, 20, 220, 240, 0.5, 1.5]
    )


def test_build_probe_designs_rejects_temporal_or_nonfinite_mismatch() -> None:
    visual, audio, query, position = _fixture_features()
    with pytest.raises(ValueError, match="same shape"):
        build_probe_designs(visual, audio[:, :1], query, position)
    bad_query = query.copy()
    bad_query[0, 0, 0] = np.nan
    with pytest.raises(ValueError, match="finite"):
        build_probe_designs(visual, audio, bad_query, position)


def test_mixed_metrics_and_shuffle_are_deterministic() -> None:
    labels = np.array([0, 1, 0, 1, 1, 0], dtype=np.int64)
    scores = np.array([0.1, 0.9, 0.8, 0.7, 0.2, 0.3], dtype=np.float64)
    offsets = np.array([0, 2, 6], dtype=np.int64)
    metrics = mixed_metrics(labels, scores, offsets)
    assert metrics["videos"] == 2
    assert metrics["pairs"] == 5
    assert 0.0 <= metrics["mixed_pair_weighted"] <= 1.0
    first = shuffle_metrics(labels, scores, offsets, repeats=7, seed=19)
    second = shuffle_metrics(labels, scores, offsets, repeats=7, seed=19)
    assert first == second
    assert first["repeats"] == 7


def test_choose_alpha_uses_validation_tie_break_order_and_fixed_grid() -> None:
    assert ALPHA_GRID == (1e-5, 1e-4, 1e-3, 1e-2)
    results = {
        1e-5: {"mixed_pair_weighted": 0.80, "mixed_ap": 0.70, "mixed_auroc": 0.60},
        1e-4: {"mixed_pair_weighted": 0.80, "mixed_ap": 0.70, "mixed_auroc": 0.60},
        1e-3: {"mixed_pair_weighted": 0.80, "mixed_ap": 0.69, "mixed_auroc": 0.61},
        1e-2: {"mixed_pair_weighted": 0.79, "mixed_ap": 0.99, "mixed_auroc": 0.99},
    }
    assert choose_alpha(results) == 1e-4


def test_probe_outcome_requires_positive_control_before_visual_claim() -> None:
    base = {
        "mixed_pair_weighted": 0.50,
        "mixed_ap": 0.50,
        "mixed_auroc": 0.50,
    }
    aqp = {"mixed_pair_weighted": 0.53, "mixed_ap": 0.510, "mixed_auroc": 0.504}
    vqp = {"mixed_pair_weighted": 0.53, "mixed_ap": 0.512, "mixed_auroc": 0.501}
    result = summarize_probe_outcome(base, vqp, aqp)
    assert result["status"] == "VISUAL_INFORMATION_DECODABLE"
    assert result["positive_control_pass"] is True

    invalid = summarize_probe_outcome(base, vqp, base)
    assert invalid["status"] == "INVALID_POSITIVE_CONTROL"
    assert invalid["positive_control_pass"] is False


def test_published_protocol_file_matches_runtime_guards() -> None:
    path = Path("configs/diagnostics/recovery/ov_orthkd_frozen_feature_probe.yaml")
    protocol = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert protocol["task_segments"] == 10
    assert protocol["alpha_grid"] == [1e-5, 1e-4, 1e-3, 1e-2]
    assert protocol["test_evaluation_count"] == 1
    assert protocol["guards"]["formal_full_authorized"] is False
    assert _validate_protocol(path, shuffle_repeats=100, shuffle_seed=42)
