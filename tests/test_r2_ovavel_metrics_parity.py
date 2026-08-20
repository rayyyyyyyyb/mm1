from __future__ import annotations

import json
from pathlib import Path
import warnings

import numpy as np
import pytest

try:
    from src.evaluation.ovavel_metrics import (
        compute_ovavel_metrics,
        ovavel_event_f1,
        ovavel_segment_f1_query_background,
    )
except ModuleNotFoundError:
    compute_ovavel_metrics = None
    ovavel_event_f1 = None
    ovavel_segment_f1_query_background = None


FIXTURE = Path(__file__).parent / "fixtures" / "official_ovavel_metric_cases.json"


def test_local_segment_and_event_metrics_match_locked_official_cases() -> None:
    assert ovavel_segment_f1_query_background is not None, "R2 OV-AVEL metrics module is missing"
    assert ovavel_event_f1 is not None, "R2 OV-AVEL metrics module is missing"
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    for case in payload["cases"]:
        assert ovavel_segment_f1_query_background(case["pred_fg"], case["gt_fg"]) == pytest.approx(
            case["official_segment_f1"]
        )
        assert ovavel_event_f1(case["pred_fg"], case["gt_fg"]) == pytest.approx(
            case["official_event_f1"]
        )


def test_aggregate_metrics_restore_samples_and_use_explicit_names() -> None:
    assert compute_ovavel_metrics is not None, "R2 OV-AVEL metrics module is missing"
    pred = np.asarray(
        [
            0, 1, 1, 0, 0, 0, 0, 0, 0, 0,
            1, 1, 1, 1, 1, 1, 0, 0, 0, 0,
        ],
        dtype=np.float64,
    )
    labels = np.asarray(
        [
            0, 1, 1, 1, 0, 0, 0, 0, 0, 0,
            1, 1, 0, 0, 1, 1, 0, 0, 0, 0,
        ],
        dtype=np.float64,
    )
    probabilities = np.where(pred == 1, 0.9, 0.1)

    metrics = compute_ovavel_metrics(labels, probabilities, np.asarray([0, 10, 20]), threshold=0.5)

    assert metrics["binary_micro_f1_at_0_5"] == pytest.approx(0.8)
    assert metrics["query_fg_f1_macro_at_0_5"] == pytest.approx(0.8)
    assert metrics["ovavel_segment_f1_at_0_5"] == pytest.approx(5.0 / 6.0)
    assert metrics["ovavel_event_f1_at_0_5"] == pytest.approx(0.5)
    assert "ap" in metrics
    assert "auroc" in metrics
    assert "f1" not in metrics


def test_aggregate_metrics_reject_malformed_sample_offsets() -> None:
    assert compute_ovavel_metrics is not None, "R2 OV-AVEL metrics module is missing"
    with pytest.raises(ValueError, match="sample_offsets"):
        compute_ovavel_metrics(
            np.asarray([0, 1]),
            np.asarray([0.1, 0.9]),
            np.asarray([0, 1]),
            threshold=0.5,
        )


def test_single_class_metrics_are_explicit_without_sklearn_warnings() -> None:
    assert compute_ovavel_metrics is not None, "R2 OV-AVEL metrics module is missing"
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        metrics = compute_ovavel_metrics(
            np.zeros(10, dtype=np.int64),
            np.full(10, 0.1, dtype=np.float64),
            np.asarray([0, 10]),
        )

    assert metrics["ap"] == 0.0
    assert metrics["auroc"] is None
