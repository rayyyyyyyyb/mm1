#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.ovavel_metrics import compute_thresholded_ovavel_metrics


REQUIRED_FIELDS = {
    "ids",
    "queries",
    "split_types",
    "sample_offsets",
    "segment_indices",
    "labels",
    "logits",
    "probabilities",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_prediction_npz(path: str | Path) -> dict[str, np.ndarray]:
    source = Path(path)
    with np.load(source, allow_pickle=False) as payload:
        missing = sorted(REQUIRED_FIELDS.difference(payload.files))
        if missing:
            raise KeyError(f"Prediction NPZ missing fields: {missing}")
        return {name: payload[name] for name in REQUIRED_FIELDS}


def _validate_payload(
    predictions: Mapping[str, np.ndarray], expected_segments: int | None = None
) -> None:
    missing = sorted(REQUIRED_FIELDS.difference(predictions))
    if missing:
        raise KeyError(f"Prediction payload missing fields: {missing}")
    sample_count = int(np.asarray(predictions["ids"]).size)
    offsets = np.asarray(predictions["sample_offsets"], dtype=np.int64).reshape(-1)
    if offsets.size != sample_count + 1 or offsets[0] != 0 or np.any(np.diff(offsets) <= 0):
        raise ValueError("sample_offsets are malformed")
    segment_count = int(offsets[-1])
    for name in ("segment_indices", "labels", "logits", "probabilities"):
        if np.asarray(predictions[name]).size != segment_count:
            raise ValueError(f"{name} does not match sample_offsets")
    logits = np.asarray(predictions["logits"], dtype=np.float64)
    probabilities = np.asarray(predictions["probabilities"], dtype=np.float64)
    labels = np.asarray(predictions["labels"], dtype=np.int64)
    if not np.isfinite(logits).all():
        raise ValueError("logits contain NaN/Inf")
    if not np.isfinite(probabilities).all() or np.any((probabilities < 0) | (probabilities > 1)):
        raise ValueError("probabilities must be finite within [0, 1]")
    if not np.isin(labels, (0, 1)).all():
        raise ValueError("labels must be binary")
    if expected_segments is not None:
        counts = np.diff(offsets)
        if np.any(counts != int(expected_segments)):
            raise ValueError(f"expected {expected_segments} segments per sample, got {counts.tolist()}")
        expected = np.arange(int(expected_segments), dtype=np.int64)
        indices = np.asarray(predictions["segment_indices"], dtype=np.int64)
        for start, end in zip(offsets[:-1], offsets[1:]):
            if not np.array_equal(indices[int(start) : int(end)], expected):
                raise ValueError("segment indices do not preserve the official order")


def _distribution(values: np.ndarray) -> dict[str, Any]:
    array = np.asarray(values, dtype=np.float64).reshape(-1)
    if array.size == 0:
        return {"count": 0, "mean": None, "std": None, "quantiles": {}}
    return {
        "count": int(array.size),
        "mean": float(array.mean()),
        "std": float(array.std()),
        "quantiles": {
            str(q): float(np.quantile(array, q))
            for q in (0.0, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 1.0)
        },
    }


def _subset_payload(
    predictions: Mapping[str, np.ndarray], sample_mask: np.ndarray
) -> dict[str, np.ndarray]:
    source_offsets = np.asarray(predictions["sample_offsets"], dtype=np.int64)
    offsets = [0]
    parts: dict[str, list[np.ndarray]] = {
        name: [] for name in ("segment_indices", "labels", "logits", "probabilities")
    }
    for index in np.flatnonzero(sample_mask):
        start, end = int(source_offsets[index]), int(source_offsets[index + 1])
        for name in parts:
            parts[name].append(np.asarray(predictions[name])[start:end])
        offsets.append(offsets[-1] + end - start)
    result = {
        name: np.asarray(predictions[name])[sample_mask]
        for name in ("ids", "queries", "split_types")
    }
    result["sample_offsets"] = np.asarray(offsets, dtype=np.int64)
    for name, chunks in parts.items():
        result[name] = np.concatenate(chunks) if chunks else np.asarray([], dtype=np.float64)
    return result


def _safe_ap(labels: np.ndarray, probabilities: np.ndarray) -> float:
    return float(average_precision_score(labels, probabilities)) if np.any(labels == 1) else 0.0


def _sample_macro_ap(predictions: Mapping[str, np.ndarray]) -> dict[str, Any]:
    labels = np.asarray(predictions["labels"], dtype=np.int64)
    probabilities = np.asarray(predictions["probabilities"], dtype=np.float64)
    offsets = np.asarray(predictions["sample_offsets"], dtype=np.int64)
    values: list[float] = []
    positive_values: list[float] = []
    for start, end in zip(offsets[:-1], offsets[1:]):
        y = labels[int(start) : int(end)]
        score = _safe_ap(y, probabilities[int(start) : int(end)])
        values.append(score)
        if np.any(y == 1):
            positive_values.append(score)
    return {
        "definition": "mean per-sample segment AP; all-negative samples contribute zero",
        "sample_count": len(values),
        "positive_sample_count": len(positive_values),
        "ap": float(np.mean(values)),
        "ap_positive_samples_only": float(np.mean(positive_values)) if positive_values else None,
    }


def _query_macro_ap(predictions: Mapping[str, np.ndarray]) -> dict[str, Any]:
    queries = np.asarray(predictions["queries"]).astype(str)
    labels = np.asarray(predictions["labels"], dtype=np.int64)
    probabilities = np.asarray(predictions["probabilities"], dtype=np.float64)
    offsets = np.asarray(predictions["sample_offsets"], dtype=np.int64)
    values: list[float] = []
    for query in np.unique(queries):
        segment_mask = np.zeros(labels.size, dtype=bool)
        for index in np.flatnonzero(queries == query):
            segment_mask[int(offsets[index]) : int(offsets[index + 1])] = True
        values.append(_safe_ap(labels[segment_mask], probabilities[segment_mask]))
    return {
        "definition": "mean AP across query/category groups; segments pooled within query",
        "query_count": len(values),
        "ap": float(np.mean(values)),
    }


def audit_prediction_payload(
    predictions: Mapping[str, np.ndarray],
    *,
    threshold: float,
    expected_segments: int | None = None,
) -> dict[str, Any]:
    _validate_payload(predictions, expected_segments=expected_segments)
    labels = np.asarray(predictions["labels"], dtype=np.int64)
    probabilities = np.asarray(predictions["probabilities"], dtype=np.float64)
    logits = np.asarray(predictions["logits"], dtype=np.float64)
    split_types = np.char.lower(np.asarray(predictions["split_types"]).astype(str))
    groups: dict[str, Any] = {}
    for name, mask in {
        "total": np.ones(split_types.size, dtype=bool),
        "seen": split_types == "seen",
        "unseen": split_types == "unseen",
    }.items():
        subset = _subset_payload(predictions, mask)
        if subset["labels"].size == 0:
            groups[name] = {"sample_count": 0, "segment_count": 0}
            continue
        y = np.asarray(subset["labels"], dtype=np.int64)
        p = np.asarray(subset["probabilities"], dtype=np.float64)
        groups[name] = {
            "sample_count": int(mask.sum()),
            "segment_count": int(y.size),
            "global_segment_micro_ap": _safe_ap(y, p),
            "global_segment_micro_auroc": (
                float(roc_auc_score(y, p)) if np.unique(y).size == 2 else None
            ),
            "per_query_macro_ap": _query_macro_ap(subset)["ap"],
            **compute_thresholded_ovavel_metrics(
                y, p, subset["sample_offsets"], threshold=threshold
            ),
            "predicted_positive_rate_at_threshold": float(np.mean(p >= threshold)),
        }

    offsets = np.asarray(predictions["sample_offsets"], dtype=np.int64)
    within_sample_std = np.asarray(
        [
            np.std(logits[int(start) : int(end)])
            for start, end in zip(offsets[:-1], offsets[1:])
        ],
        dtype=np.float64,
    )
    return {
        "threshold": float(threshold),
        "aggregation": {
            "global_segment_micro": {
                "definition": "all valid segments pooled once",
                "ap": _safe_ap(labels, probabilities),
                "auroc": float(roc_auc_score(labels, probabilities)),
            },
            "per_sample_macro": _sample_macro_ap(predictions),
            "per_query_macro": _query_macro_ap(predictions),
        },
        "groups": groups,
        "thresholded_metrics": compute_thresholded_ovavel_metrics(
            labels,
            probabilities,
            predictions["sample_offsets"],
            threshold=threshold,
        ),
        "logit_distribution": {
            "all": _distribution(logits),
            "positive_label": _distribution(logits[labels == 1]),
            "negative_label": _distribution(logits[labels == 0]),
            "within_sample_std": _distribution(within_sample_std),
        },
    }


def best_binary_f1_threshold(labels: np.ndarray, probabilities: np.ndarray) -> float:
    precision, recall, thresholds = precision_recall_curve(labels, probabilities)
    if thresholds.size == 0:
        return 0.5
    scores = 2.0 * precision[:-1] * recall[:-1] / np.clip(
        precision[:-1] + recall[:-1], 1e-12, None
    )
    return float(thresholds[int(np.argmax(scores))])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only audit of saved OV-OrthKD predictions")
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--test", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-segments", type=int, default=10)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    validation = load_prediction_npz(args.validation)
    test = load_prediction_npz(args.test)
    threshold = best_binary_f1_threshold(
        np.asarray(validation["labels"]), np.asarray(validation["probabilities"])
    )
    report = {
        "schema_version": 1,
        "status": "PASS",
        "metric_claim": "diagnostic_aggregations_not_archival_evaluator_recovery",
        "validation_selected_threshold": threshold,
        "sources": {
            "validation": {
                "filename": args.validation.name,
                "sha256": _sha256(args.validation),
            },
            "test": {"filename": args.test.name, "sha256": _sha256(args.test)},
        },
        "validation": audit_prediction_payload(
            validation, threshold=threshold, expected_segments=args.expected_segments
        ),
        "test": audit_prediction_payload(
            test, threshold=threshold, expected_segments=args.expected_segments
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
