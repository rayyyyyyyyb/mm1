#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping

import torch


SECRET_KEY_PATTERN = re.compile(
    r"(^|[_-])(token|secret|password|passwd|api[_-]?key|access[_-]?key|private[_-]?key)($|[_-])",
    re.IGNORECASE,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _looks_absolute_path(value: str) -> bool:
    if not value:
        return False
    return Path(value).expanduser().is_absolute() or PureWindowsPath(value).is_absolute()


def _redact_config(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "<redacted-secret>"
            if SECRET_KEY_PATTERN.search(str(key))
            else _redact_config(child)
            for key, child in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_config(child) for child in value]
    if isinstance(value, str):
        if _looks_absolute_path(value) or re.match(r"^[A-Za-z]:[\\/]", value):
            return "<redacted-absolute-path>"
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if torch.is_tensor(value):
        return {"type": "tensor", "dtype": str(value.dtype), "shape": list(value.shape)}
    return {"type": type(value).__name__}


def _state_summary(value: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {"type": type(value).__name__}
    if isinstance(value, Mapping):
        summary["keys"] = sorted(str(key) for key in value.keys())
        state = value.get("state")
        param_groups = value.get("param_groups")
        if isinstance(state, Mapping):
            summary["state_entries"] = len(state)
        if isinstance(param_groups, (list, tuple)):
            summary["param_groups"] = len(param_groups)
    return summary


def _model_parameter_shapes(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    for key in ("student_state_dict", "model_state_dict", "state_dict", "model"):
        state = payload.get(key)
        if not isinstance(state, Mapping):
            continue
        tensors = {
            str(name): {"dtype": str(value.dtype), "shape": list(value.shape)}
            for name, value in state.items()
            if torch.is_tensor(value)
        }
        if tensors:
            return dict(sorted(tensors.items()))
    return {}


def inspect_checkpoint(checkpoint_path: str | Path) -> dict[str, Any]:
    path = Path(checkpoint_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Trusted local checkpoint not found: {path}")
    payload = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(payload, Mapping):
        raise ValueError("Checkpoint top level must be a mapping")
    optimizer = payload.get("optimizer_state_dict", payload.get("optimizer"))
    scheduler = payload.get("scheduler_state_dict", payload.get("scheduler"))
    config = payload.get("config", {})
    return {
        "schema_version": 1,
        "filename": path.name,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "top_level_keys": sorted(str(key) for key in payload.keys()),
        "top_level_types": {
            str(key): type(value).__name__
            for key, value in sorted(payload.items(), key=lambda item: str(item[0]))
        },
        "config": _redact_config(config),
        "model_parameters": _model_parameter_shapes(payload),
        "optimizer_state": _state_summary(optimizer),
        "scheduler_state": _state_summary(scheduler),
        "epoch": payload.get("epoch"),
        "global_step": payload.get("global_step"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Safely inventory one trusted local historical checkpoint without tensor values"
    )
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--output", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = inspect_checkpoint(args.checkpoint)
    payload = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    print(payload, end="")


if __name__ == "__main__":
    main()
