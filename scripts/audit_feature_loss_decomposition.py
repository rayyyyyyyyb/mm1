"""Audit the exact mean/temporal decomposition on a fixed batch or NPZ file."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import torch

from src.utils.feature_loss import decompose_temporal_squared_error


def audit_arrays(
    student: np.ndarray,
    target: np.ndarray,
    mask: np.ndarray,
    labels: np.ndarray | None = None,
) -> dict[str, Any]:
    result = decompose_temporal_squared_error(
        torch.from_numpy(np.asarray(student)),
        torch.from_numpy(np.asarray(target)),
        torch.from_numpy(np.asarray(mask)),
        None if labels is None else torch.from_numpy(np.asarray(labels)),
    )
    payload: dict[str, Any] = {
        "student_shape": list(np.asarray(student).shape),
        "target_shape": list(np.asarray(target).shape),
        "mask_shape": list(np.asarray(mask).shape),
        "mean_term": float(result["mean_term"]),
        "temporal_term": float(result["temporal_term"]),
        "total": float(result["total"]),
        "identity_abs_error": abs(float(result["total"]) - float(result["mean_term"]) - float(result["temporal_term"])),
    }
    if labels is not None:
        payload["groups"] = result["groups"]
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="NPZ with student, target, mask, and optional labels arrays")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with np.load(args.input, allow_pickle=False) as data:
        required = {"student", "target", "mask"}
        missing = required - set(data.files)
        if missing:
            raise ValueError(f"input NPZ missing arrays: {sorted(missing)}")
        labels = data["labels"] if "labels" in data.files else None
        result = audit_arrays(data["student"], data["target"], data["mask"], labels)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
