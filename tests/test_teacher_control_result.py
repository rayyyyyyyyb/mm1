from __future__ import annotations

import json

import numpy as np

from scripts.audit_teacher_control_result import audit_control_result


def test_control_result_audit_fails_boundary_gate_for_static_logits(tmp_path) -> None:
    prediction_path = tmp_path / "predictions.npz"
    labels = np.tile(np.asarray([1, 0] * 5, dtype=np.float64), 2)
    logits = np.zeros(20, dtype=np.float64)
    np.savez(
        prediction_path,
        sample_offsets=np.asarray([0, 10, 20]),
        labels=labels,
        logits=logits,
        probabilities=np.full(20, 0.5),
    )
    summary_path = tmp_path / "steps.json"
    summary_path.write_text(json.dumps({"attempted_steps": 803, "applied_steps": 800}), encoding="utf-8")
    result = audit_control_result(prediction_path, summary_path)
    assert result["status"] == "FAIL"
    assert result["scientific_status"] == "D1_CENTERED_VISUAL_CONTROL_FAIL"
    assert result["gates"]["applied_steps_exactly_800"] is True
    assert result["metrics"]["mixed_validation_tie_aware_concordance"] == 0.5
