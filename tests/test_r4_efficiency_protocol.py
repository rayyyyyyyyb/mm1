from __future__ import annotations

import pytest

from scripts.measure_efficiency import efficiency_protocol_receipt


def test_efficiency_default_protocol_is_official_t10() -> None:
    assert efficiency_protocol_receipt(10, "canonical_official_t10") == {
        "protocol_mode": "canonical_official_t10",
        "input_segments": 10,
        "task_segments": 10,
        "paper_protocol_measurement": True,
        "temporal_resampling_performed": False,
    }


def test_t16_efficiency_is_explicitly_noncanonical_capacity_analysis() -> None:
    with pytest.raises(ValueError, match="requires --segments 10"):
        efficiency_protocol_receipt(16, "canonical_official_t10")

    receipt = efficiency_protocol_receipt(16, "synthetic_capacity_analysis")
    assert receipt["input_segments"] == 16
    assert receipt["task_segments"] == 10
    assert receipt["paper_protocol_measurement"] is False
    assert receipt["temporal_resampling_performed"] is False
