from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.preflight_ov_orthkd import _claim_real_preflight_invocation, run_preflight


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _config(name: str) -> dict:
    return yaml.safe_load((PROJECT_ROOT / "configs" / name).read_text(encoding="utf-8"))


def test_archival_exact_preflight_requires_explicit_real_data_flag() -> None:
    with pytest.raises(RuntimeError, match="--real-data"):
        run_preflight(_config("ov_orthkd_mm26_repro.yaml"), real_data=False)


def test_mock_config_cannot_be_labeled_real_data() -> None:
    with pytest.raises(RuntimeError, match="mock-only"):
        run_preflight(_config("ov_orthkd_mm26_smoke.yaml"), real_data=True)


def test_real_preflight_is_exactly_one_optimizer_step() -> None:
    with pytest.raises(ValueError, match="exactly 1"):
        run_preflight({}, real_data=True, optimizer_steps=2)


def test_completed_real_preflight_refuses_second_invocation() -> None:
    with pytest.raises(RuntimeError, match="already been claimed"):
        _claim_real_preflight_invocation(
            _config("ov_orthkd_mm26_repro.yaml"),
            optimizer_steps=1,
        )
