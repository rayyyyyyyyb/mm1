"""Read-only fixed-budget validation summary for C0/C1 last checkpoints."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score

from scripts.diagnose_formal_predictions import load_prediction_npz
from src.utils.zero_training_diagnostics import (
    _mixed_shuffle_summary,
    mixed_pairwise_concordance,
    validate_t10_predictions,
)


def _classification_summary(labels: np.ndarray, probabilities: np.ndarray) -> dict[str, Any]:
    labels = np.asarray(labels, dtype=np.int64).reshape(-1)
    probabilities = np.asarray(probabilities, dtype=np.float64).reshape(-1)
    if labels.size == 0 or labels.size != probabilities.size:
        raise ValueError("labels and probabilities must be non-empty and aligned")
    if not np.isfinite(probabilities).all():
        raise ValueError("probabilities contain NaN/Inf")
    return {
        "ap": float(average_precision_score(labels, probabilities)),
        "auroc": float(roc_auc_score(labels, probabilities)),
        "predicted_positive_rate": float(np.mean(probabilities >= 0.5)),
        "label_positive_rate": float(np.mean(labels)),
    }


def summarize_fixed_budget(
    predictions: Mapping[str, np.ndarray],
    *,
    shuffle_repeats: int = 100,
    shuffle_seed: int = 42,
) -> dict[str, Any]:
    """Summarize one official-T=10 prediction archive without model execution."""

    slices = validate_t10_predictions(predictions)
    labels = np.asarray(predictions["labels"], dtype=np.int64).reshape(-1)
    probabilities = np.asarray(predictions["probabilities"], dtype=np.float64).reshape(-1)
    offsets = np.asarray(predictions["sample_offsets"], dtype=np.int64).reshape(-1)
    mixed_indices = [
        index
        for index, sample in enumerate(slices)
        if 0 < int(labels[sample].sum()) < 10
    ]
    if not mixed_indices:
        raise ValueError("fixed-budget summary requires mixed-label samples")
    mixed_labels = np.concatenate([labels[slices[index]] for index in mixed_indices])
    mixed_probabilities = np.concatenate(
        [probabilities[slices[index]] for index in mixed_indices]
    )
    mixed_offsets = np.asarray(
        [0, *np.cumsum([10] * len(mixed_indices))], dtype=np.int64
    )
    return {
        "samples": len(slices),
        "segments": int(labels.size),
        "task_segments": 10,
        "classification": _classification_summary(labels, probabilities),
        "mixed_label_samples": len(mixed_indices),
        "mixed_label_segments": int(mixed_labels.size),
        "mixed_pair_weighted_concordance": mixed_pairwise_concordance(
            mixed_labels, mixed_probabilities, mixed_offsets
        )["pair_weighted"],
        "mixed_pairwise_concordance": mixed_pairwise_concordance(
            mixed_labels, mixed_probabilities, mixed_offsets
        ),
        "temporal_shuffle": _mixed_shuffle_summary(
            mixed_labels,
            mixed_probabilities,
            mixed_offsets,
            repeats=int(shuffle_repeats),
            seed=int(shuffle_seed),
        ),
        "sample_offsets_sha256": __import__("hashlib").sha256(
            offsets.tobytes(order="C")
        ).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = summarize_fixed_budget(load_prediction_npz(args.input))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
