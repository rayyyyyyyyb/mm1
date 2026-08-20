#!/usr/bin/env python3
"""Issue the final R3 conference-reproduction readiness decision.

This command deliberately delegates every substantive decision to the single
canonical validator.  It can unguard the ready configuration only after that
validator has accepted the complete evidence chain, including the one allowed
real-data preflight.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils.canonical_readiness import validate_canonical_readiness


READY_STATUS = "READY_FOR_CONFERENCE_REPRO"
BLOCKED_STATUS = "BLOCKED_BEFORE_CONFERENCE_REPRO"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_config(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise RuntimeError("configuration must be a YAML mapping")
    return dict(value)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw_temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _generated_at(output_path: Path, stable_payload: Mapping[str, Any]) -> str:
    if output_path.is_file():
        try:
            previous = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = None
        if isinstance(previous, Mapping):
            prior_without_time = dict(previous)
            previous_time = prior_without_time.pop("generated_at_utc", None)
            if prior_without_time == dict(stable_payload) and isinstance(previous_time, str):
                return previous_time
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_and_write(
    *,
    config_path: str | Path,
    output_path: str | Path,
    ready_config_path: str | Path,
) -> dict[str, Any]:
    config_path = Path(config_path).resolve()
    output_path = Path(output_path).resolve()
    ready_config_path = Path(ready_config_path).resolve()
    canonical_receipt: dict[str, Any] | None = None
    blockers: list[str] = []

    try:
        config = _load_config(config_path)
        observed = validate_canonical_readiness(config)
        if not isinstance(observed, Mapping) or observed.get("status") != "ready":
            raise RuntimeError("canonical validator did not return status=ready")
        canonical_receipt = dict(observed)
    except Exception as exc:  # fail closed and serialize the exact blocker
        config = None
        blockers.append(f"{type(exc).__name__}: {exc}")

    ready = canonical_receipt is not None and not blockers
    ready_config_removed = False
    if ready:
        ready_config = copy.deepcopy(config)
        reproduction = ready_config.get("reproduction")
        if not isinstance(reproduction, dict):
            raise RuntimeError("canonical validator accepted a config without reproduction mapping")
        reproduction["full_run_blocked"] = False
        _atomic_write_text(ready_config_path, yaml.safe_dump(ready_config, sort_keys=False))
    elif ready_config_path.is_file():
        # A stale unguarded configuration must not survive a later blocked audit.
        ready_config_path.unlink()
        ready_config_removed = True

    stable_payload: dict[str, Any] = {
        "schema_version": 1,
        "status": READY_STATUS if ready else BLOCKED_STATUS,
        "ready": ready,
        "config_path": str(config_path),
        "config_sha256": _sha256(config_path) if config_path.is_file() else None,
        "canonical_evidence_chain": ready,
        "canonical_receipt": canonical_receipt,
        "blockers": blockers,
        "ready_config_path": str(ready_config_path),
        "ready_config_created": ready,
        "ready_config_removed_as_stale": ready_config_removed,
        "full_run_started": False,
    }
    receipt = dict(stable_payload)
    receipt["generated_at_utc"] = _generated_at(output_path, stable_payload)
    _atomic_write_text(
        output_path,
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    )
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate final R3 conference-reproduction readiness")
    parser.add_argument("--config", default="configs/ov_orthkd_mm26_repro.yaml")
    parser.add_argument("--output", default="reports/mm26_conference_readiness.json")
    parser.add_argument(
        "--ready-config",
        default="configs/ov_orthkd_mm26_repro_ready.yaml",
        help="created only after the complete canonical evidence chain passes",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    receipt = validate_and_write(
        config_path=args.config,
        output_path=args.output,
        ready_config_path=args.ready_config,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if receipt["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
