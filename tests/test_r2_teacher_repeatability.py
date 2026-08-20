from __future__ import annotations

import numpy as np

from scripts.inspect_teacher_identity import compare_repeated_outputs


def test_repeatability_prefers_bitwise_identity_and_reports_max_abs_diff() -> None:
    first = {
        "visual_features": np.asarray([[1.0, 2.0]], dtype=np.float32),
        "visual_logits": np.asarray([0.5], dtype=np.float32),
    }
    second = {name: value.copy() for name, value in first.items()}

    report = compare_repeated_outputs([first, second], tolerance=0.0)

    assert report["status"] == "pass"
    assert report["repeat_count"] == 2
    assert report["outputs"]["visual_features"]["bitwise_identical"] is True
    assert report["outputs"]["visual_features"]["max_abs_diff"] == 0.0


def test_repeatability_applies_locked_tolerance_and_rejects_shape_changes() -> None:
    baseline = {"features": np.asarray([[1.0, 2.0]], dtype=np.float32)}
    close = {"features": np.asarray([[1.0, 2.00001]], dtype=np.float32)}
    changed_shape = {"features": np.asarray([1.0, 2.0], dtype=np.float32)}

    tolerated = compare_repeated_outputs([baseline, close], tolerance=2e-5)
    rejected = compare_repeated_outputs([baseline, changed_shape], tolerance=1.0)

    assert tolerated["status"] == "pass"
    assert tolerated["outputs"]["features"]["bitwise_identical"] is False
    assert 0.0 < tolerated["outputs"]["features"]["max_abs_diff"] <= 2e-5
    assert rejected["status"] == "failed"
    assert rejected["outputs"]["features"]["shape_identical"] is False
