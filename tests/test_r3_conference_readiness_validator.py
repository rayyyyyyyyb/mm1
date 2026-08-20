from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_conference_readiness.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("validate_conference_readiness", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_config(path: Path) -> dict:
    config = {
        "reproduction": {
            "claim_level": "paper_specified_reconstruction",
            "full_run_blocked": True,
            "readiness": {},
        }
    }
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return config


def test_blocked_validation_never_creates_ready_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_module()
    config_path = tmp_path / "config.yaml"
    _write_config(config_path)
    output_path = tmp_path / "readiness.json"
    ready_path = tmp_path / "ready.yaml"

    def fail_closed(_config):
        raise RuntimeError("teacher checkpoint strict-load failed")

    monkeypatch.setattr(module, "validate_canonical_readiness", fail_closed)
    receipt = module.validate_and_write(
        config_path=config_path,
        output_path=output_path,
        ready_config_path=ready_path,
    )

    assert receipt["status"] == "BLOCKED_BEFORE_CONFERENCE_REPRO"
    assert receipt["ready"] is False
    assert receipt["ready_config_created"] is False
    assert "strict-load failed" in receipt["blockers"][0]
    assert json.loads(output_path.read_text(encoding="utf-8")) == receipt
    assert not ready_path.exists()


def test_complete_canonical_chain_is_the_only_path_to_ready_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_module()
    config_path = tmp_path / "config.yaml"
    original = _write_config(config_path)
    output_path = tmp_path / "readiness.json"
    ready_path = tmp_path / "ready.yaml"
    canonical = {
        "schema_version": 2,
        "status": "ready",
        "cache_root_sha256": "a" * 64,
        "canonical_experiment_config_sha256": "b" * 64,
        "errors": [],
    }
    calls = []

    def pass_canonical(config):
        calls.append(config)
        return canonical

    monkeypatch.setattr(module, "validate_canonical_readiness", pass_canonical)
    receipt = module.validate_and_write(
        config_path=config_path,
        output_path=output_path,
        ready_config_path=ready_path,
    )

    assert calls == [original]
    assert receipt["status"] == "READY_FOR_CONFERENCE_REPRO"
    assert receipt["ready"] is True
    assert receipt["ready_config_created"] is True
    assert receipt["canonical_receipt"] == canonical
    ready = yaml.safe_load(ready_path.read_text(encoding="utf-8"))
    assert ready["reproduction"]["full_run_blocked"] is False
    assert original["reproduction"]["full_run_blocked"] is True


def test_non_ready_canonical_return_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_module()
    config_path = tmp_path / "config.yaml"
    _write_config(config_path)

    monkeypatch.setattr(
        module,
        "validate_canonical_readiness",
        lambda _config: {"schema_version": 2, "status": "blocked"},
    )
    receipt = module.validate_and_write(
        config_path=config_path,
        output_path=tmp_path / "readiness.json",
        ready_config_path=tmp_path / "ready.yaml",
    )

    assert receipt["status"] == "BLOCKED_BEFORE_CONFERENCE_REPRO"
    assert receipt["ready_config_created"] is False
