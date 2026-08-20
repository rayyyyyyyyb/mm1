from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scripts.preflight_ov_orthkd import (
    _claim_real_preflight_invocation,
    _expected_temporal_length,
    _real_preflight_report_path,
)


def test_real_preflight_uses_r3_configured_receipt_and_single_invocation_marker(
    tmp_path: Path,
) -> None:
    report = tmp_path / "reports/runtime/r3_real_preflight.json"
    config = {
        "reproduction": {
            "project_root": str(tmp_path),
            "readiness": {"real_preflight": str(report)},
        }
    }

    assert _real_preflight_report_path(config) == report.resolve()
    marker = _claim_real_preflight_invocation(config, optimizer_steps=1)
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["status"] == "started"
    assert payload["invocation_count_this_stage"] == 1
    assert payload["optimizer_steps_planned"] == 1

    with pytest.raises(RuntimeError, match="already been claimed"):
        _claim_real_preflight_invocation(config, optimizer_steps=1)


def test_real_preflight_reads_temporal_length_from_readiness_data_lock(
    tmp_path: Path,
) -> None:
    lock = tmp_path / "configs/locks/data.yaml"
    lock.parent.mkdir(parents=True)
    lock.write_text(
        yaml.safe_dump({"official_metadata": {"segment_length_histogram": {10: 24800}}}),
        encoding="utf-8",
    )
    config = {
        "reproduction": {
            "project_root": str(tmp_path),
            "readiness": {"data_lock": str(lock)},
        }
    }

    assert _expected_temporal_length(config) == 10
