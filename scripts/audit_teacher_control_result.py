"""Independent validation-only audit for a completed teacher-signal control."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score


def _tie_aware_concordance(scores: np.ndarray, labels: np.ndarray) -> float | None:
    positive = scores[labels > 0]
    negative = scores[labels <= 0]
    if positive.size == 0 or negative.size == 0:
        return None
    pair = positive[:, None] - negative[None, :]
    return float((pair > 0).mean() + 0.5 * (pair == 0).mean())


def audit_control_result(
    predictions_path: str | Path,
    step_summary_path: str | Path,
    *,
    test_predictions_path: str | Path | None = None,
) -> dict[str, Any]:
    """Audit shapes, step receipt and boundary recovery without touching a model."""

    predictions = np.load(predictions_path, allow_pickle=False)
    required = {"sample_offsets", "labels", "logits", "probabilities"}
    if not required <= set(predictions.files):
        raise ValueError(f"prediction receipt is missing keys: {sorted(required - set(predictions.files))}")
    offsets = np.asarray(predictions["sample_offsets"], dtype=np.int64)
    labels = np.asarray(predictions["labels"], dtype=np.float64)
    logits = np.asarray(predictions["logits"], dtype=np.float64)
    probabilities = np.asarray(predictions["probabilities"], dtype=np.float64)
    if offsets.ndim != 1 or offsets.size < 2 or offsets[0] != 0 or np.any(np.diff(offsets) != 10):
        raise ValueError("validation prediction offsets must encode exactly ten segments per sample")
    if labels.shape != logits.shape or labels.shape != probabilities.shape or labels.size != int(offsets[-1]):
        raise ValueError("labels/logits/probabilities are misaligned")
    if not (np.isfinite(labels).all() and np.isfinite(logits).all() and np.isfinite(probabilities).all()):
        raise ValueError("validation predictions contain NaN/Inf")

    step_summary = json.loads(Path(step_summary_path).read_text(encoding="utf-8"))
    if not isinstance(step_summary, Mapping):
        raise ValueError("optimizer step summary must be a mapping")
    applied_steps = int(step_summary.get("applied_steps", -1))
    attempted_steps = int(step_summary.get("attempted_steps", -1))
    mixed_concordances: list[float] = []
    temporal_stds: list[float] = []
    for start, end in zip(offsets[:-1], offsets[1:]):
        row_labels = labels[start:end]
        row_logits = logits[start:end]
        concordance = _tie_aware_concordance(row_logits, row_labels)
        if concordance is not None and 0 < row_labels.sum() < 10:
            mixed_concordances.append(concordance)
        temporal_stds.append(float(np.std(row_logits)))
    global_ap = float(average_precision_score(labels, logits))
    global_auroc = float(roc_auc_score(labels, logits))
    mixed_concordance = float(np.mean(mixed_concordances)) if mixed_concordances else None
    temporal_std = float(np.mean(temporal_stds)) if temporal_stds else None
    gates = {
        "applied_steps_exactly_800": applied_steps == 800,
        "attempted_steps_at_least_800": attempted_steps >= 800,
        "test_predictions_absent": test_predictions_path is None or not Path(test_predictions_path).exists(),
        "mixed_concordance_ge_0.60": mixed_concordance is not None and mixed_concordance >= 0.60,
        "decision_temporal_std_ge_0.003": temporal_std is not None and temporal_std >= 0.003,
    }
    passed = all(gates.values())
    return {
        "schema_version": 1,
        "status": "PASS" if passed else "FAIL",
        "scientific_status": "CENTERED_VISUAL_CONTROL_PASS" if passed else "NO_BOUNDED_CONTROL_RECOVERS_BOUNDARY",
        "protocol": {"task_segments": 10, "validation_only": True, "test_evaluation": False},
        "steps": {"attempted": attempted_steps, "applied": applied_steps, "overflow_or_skipped": attempted_steps - applied_steps},
        "metrics": {
            "validation_ap": global_ap,
            "validation_auroc": global_auroc,
            "mixed_validation_tie_aware_concordance": mixed_concordance,
            "mean_decision_temporal_std": temporal_std,
            "mixed_sample_count": len(mixed_concordances),
        },
        "gates": gates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--step-summary", type=Path, required=True)
    parser.add_argument("--test-predictions", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit_control_result(args.predictions, args.step_summary, test_predictions_path=args.test_predictions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
