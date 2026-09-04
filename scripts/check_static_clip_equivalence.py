"""Check the ten-step frozen-target/positive-LR clipping equivalence receipt."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import torch


_STUDENT_FIELDS = (
    "target",
    "loss",
    "pre_clip_student_grad",
    "post_clip_student_grad",
    "student_parameters",
)


def _array(value: Any) -> np.ndarray:
    if isinstance(value, torch.Tensor):
        return value.detach().cpu().numpy()
    return np.asarray(value)


def compare_equivalence(
    positive_lr_static_steps: Sequence[Mapping[str, Any]],
    frozen_no_grad_steps: Sequence[Mapping[str, Any]],
    *,
    atol: float = 1e-6,
    rtol: float = 1e-5,
) -> dict[str, Any]:
    """Compare exactly ten receipts, allowing only projector receipt changes."""

    if len(positive_lr_static_steps) != 10 or len(frozen_no_grad_steps) != 10:
        raise ValueError("equivalence requires exactly ten steps per trajectory")
    mismatches: list[str] = []
    projector_differences = 0
    for index, (static, frozen) in enumerate(zip(positive_lr_static_steps, frozen_no_grad_steps)):
        for field in _STUDENT_FIELDS:
            if field not in static or field not in frozen:
                raise ValueError(f"step {index}: missing equivalence field {field}")
            if not np.allclose(_array(static[field]), _array(frozen[field]), atol=atol, rtol=rtol):
                mismatches.append(field)
        static_projector = static.get("projector_receipt")
        frozen_projector = frozen.get("projector_receipt")
        if static_projector is None or frozen_projector is None:
            raise ValueError(f"step {index}: projector receipt is required")
        if not np.allclose(_array(static_projector), _array(frozen_projector), atol=atol, rtol=rtol):
            projector_differences += 1
    unique_mismatches = sorted(set(mismatches))
    return {
        "pass": not unique_mismatches,
        "steps": 10,
        "mismatches": unique_mismatches,
        "projector_receipt_differences": projector_differences,
        "allowed_difference": "projector_receipt_only",
        "atol": atol,
        "rtol": rtol,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static", type=Path, required=True)
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    static = json.loads(args.static.read_text(encoding="utf-8"))
    frozen = json.loads(args.frozen.read_text(encoding="utf-8"))
    payload = compare_equivalence(static["steps"], frozen["steps"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    if not payload["pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
