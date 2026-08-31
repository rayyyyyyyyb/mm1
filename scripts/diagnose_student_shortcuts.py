#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
from sklearn.metrics import average_precision_score

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.diagnose_formal_predictions import (  # noqa: E402
    _validate_payload,
    load_prediction_npz,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_receipt(path: Path) -> dict[str, Any]:
    source = path.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    return {
        "path": str(source),
        "bytes": source.stat().st_size,
        "sha256": _sha256(source),
    }


def load_manifest(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.suffix.lower() == ".json":
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise ValueError(f"Expected a JSON list of records in {source}")
        return payload
    records: list[dict[str, Any]] = []
    with source.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {source}:{line_number}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"Expected an object at {source}:{line_number}")
            records.append(record)
    if not records:
        raise ValueError(f"Manifest is empty: {source}")
    return records


def _record_query(record: Mapping[str, Any]) -> str:
    value = record.get("query", record.get("text_query"))
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Record {record.get('id', '<unknown>')} has no non-empty query")
    return value.strip()


def _record_labels(record: Mapping[str, Any], expected_segments: int) -> np.ndarray:
    try:
        labels = np.asarray(record.get("segment_labels"), dtype=np.float64).reshape(-1)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Record {record.get('id', '<unknown>')} has invalid segment_labels"
        ) from exc
    if labels.size != expected_segments:
        raise ValueError(
            f"Record {record.get('id', '<unknown>')} must contain exactly "
            f"{expected_segments} segment_labels, got {labels.size}"
        )
    if not np.isfinite(labels).all() or not np.isin(labels, (0.0, 1.0)).all():
        raise ValueError(
            f"Record {record.get('id', '<unknown>')} segment_labels must be finite binary values"
        )
    return labels


def build_empirical_priors(
    records: Iterable[Mapping[str, Any]], *, expected_segments: int
) -> dict[str, Any]:
    task_segments = int(expected_segments)
    if task_segments <= 0:
        raise ValueError("expected_segments must be positive")
    record_count = 0
    global_positive = 0.0
    position_positive = np.zeros(task_segments, dtype=np.float64)
    query_positive: dict[str, float] = {}
    query_position_positive: dict[str, np.ndarray] = {}
    query_record_counts: dict[str, int] = {}

    for record in records:
        query = _record_query(record)
        labels = _record_labels(record, task_segments)
        record_count += 1
        global_positive += float(labels.sum())
        position_positive += labels
        query_positive[query] = query_positive.get(query, 0.0) + float(labels.sum())
        query_position_positive.setdefault(
            query, np.zeros(task_segments, dtype=np.float64)
        )
        query_position_positive[query] += labels
        query_record_counts[query] = query_record_counts.get(query, 0) + 1

    if record_count == 0:
        raise ValueError("Training manifest contains no records")

    return {
        "expected_segments": task_segments,
        "record_count": record_count,
        "segment_count": record_count * task_segments,
        "query_count": len(query_record_counts),
        "global": global_positive / (record_count * task_segments),
        "by_position": (position_positive / record_count).tolist(),
        "by_query": {
            query: query_positive[query] / (query_record_counts[query] * task_segments)
            for query in sorted(query_record_counts)
        },
        "by_query_position": {
            query: (
                query_position_positive[query] / query_record_counts[query]
            ).tolist()
            for query in sorted(query_record_counts)
        },
        "query_record_counts": {
            query: query_record_counts[query] for query in sorted(query_record_counts)
        },
    }


def _validate_predictions(
    predictions: Mapping[str, np.ndarray], expected_segments: int
) -> None:
    _validate_payload(predictions, expected_segments=expected_segments)
    sample_count = int(np.asarray(predictions["ids"]).size)
    for name in ("queries", "split_types"):
        if np.asarray(predictions[name]).reshape(-1).size != sample_count:
            raise ValueError(f"{name} must contain one value per sample")
    queries = np.asarray(predictions["queries"]).astype(str)
    if any(not query.strip() for query in queries):
        raise ValueError("queries must be non-empty")
    logits = np.asarray(predictions["logits"], dtype=np.float64).reshape(-1)
    probabilities = np.asarray(predictions["probabilities"], dtype=np.float64).reshape(-1)
    expected_probabilities = 1.0 / (1.0 + np.exp(-logits))
    if not np.allclose(probabilities, expected_probabilities, rtol=1e-6, atol=1e-8):
        raise ValueError("probabilities do not match sigmoid(logits)")


def apply_empirical_priors(
    predictions: Mapping[str, np.ndarray],
    priors: Mapping[str, Any],
    *,
    expected_segments: int,
) -> dict[str, Any]:
    task_segments = int(expected_segments)
    _validate_predictions(predictions, task_segments)
    if int(priors.get("expected_segments", -1)) != task_segments:
        raise ValueError("Prior and prediction task-segment counts differ")
    queries = np.asarray(predictions["queries"]).astype(str)
    offsets = np.asarray(predictions["sample_offsets"], dtype=np.int64)
    by_query = dict(priors["by_query"])
    by_query_position = dict(priors["by_query_position"])
    global_prior = float(priors["global"])
    position_prior = np.asarray(priors["by_position"], dtype=np.float64)
    if position_prior.shape != (task_segments,):
        raise ValueError("Global position prior has an invalid shape")

    query_only = np.empty(int(offsets[-1]), dtype=np.float64)
    query_position = np.empty(int(offsets[-1]), dtype=np.float64)
    known = 0
    fallback = 0
    for sample_index, query in enumerate(queries):
        start, end = int(offsets[sample_index]), int(offsets[sample_index + 1])
        if end - start != task_segments:
            raise ValueError("Prediction sample length changed after validation")
        if query in by_query:
            known += 1
            query_only[start:end] = float(by_query[query])
            values = np.asarray(by_query_position[query], dtype=np.float64)
            if values.shape != (task_segments,):
                raise ValueError(f"Query-position prior for {query!r} has an invalid shape")
            query_position[start:end] = values
        else:
            fallback += 1
            query_only[start:end] = global_prior
            query_position[start:end] = position_prior

    return {
        "query_only_probabilities": query_only,
        "query_position_probabilities": query_position,
        "known_query_samples": known,
        "fallback_query_samples": fallback,
        "query_only_fallback": "global_training_positive_rate",
        "query_position_fallback": "global_training_position_rate",
    }


def _validate_offsets(offsets: np.ndarray, value_count: int) -> np.ndarray:
    values = np.asarray(offsets, dtype=np.int64).reshape(-1)
    if (
        values.size < 2
        or values[0] != 0
        or values[-1] != value_count
        or np.any(np.diff(values) <= 0)
    ):
        raise ValueError("sample_offsets are malformed")
    return values


def mean_center_logits(logits: np.ndarray, sample_offsets: np.ndarray) -> np.ndarray:
    values = np.asarray(logits, dtype=np.float64).reshape(-1)
    if not np.isfinite(values).all():
        raise ValueError("logits contain NaN/Inf")
    offsets = _validate_offsets(sample_offsets, values.size)
    centered = values.copy()
    for start, end in zip(offsets[:-1], offsets[1:]):
        segment = centered[int(start) : int(end)]
        segment -= segment.mean()
    return centered


def shuffle_logits_within_samples(
    logits: np.ndarray, sample_offsets: np.ndarray, rng: np.random.Generator
) -> np.ndarray:
    values = np.asarray(logits, dtype=np.float64).reshape(-1)
    if not np.isfinite(values).all():
        raise ValueError("logits contain NaN/Inf")
    offsets = _validate_offsets(sample_offsets, values.size)
    shuffled = values.copy()
    for start, end in zip(offsets[:-1], offsets[1:]):
        begin, finish = int(start), int(end)
        shuffled[begin:finish] = values[begin:finish][rng.permutation(finish - begin)]
    return shuffled


def _safe_ap(labels: np.ndarray, probabilities: np.ndarray) -> float:
    y = np.asarray(labels, dtype=np.int64).reshape(-1)
    p = np.asarray(probabilities, dtype=np.float64).reshape(-1)
    return float(average_precision_score(y, p)) if np.any(y == 1) else 0.0


def _distribution(values: np.ndarray) -> dict[str, Any]:
    array = np.asarray(values, dtype=np.float64).reshape(-1)
    return {
        "count": int(array.size),
        "mean": float(array.mean()),
        "std": float(array.std()),
        "quantiles": {
            str(q): float(np.quantile(array, q))
            for q in (0.0, 0.05, 0.25, 0.5, 0.75, 0.95, 1.0)
        },
    }


def temporal_shuffle_diagnostic(
    predictions: Mapping[str, np.ndarray], *, repeats: int, seed: int
) -> dict[str, Any]:
    if int(repeats) <= 0:
        raise ValueError("repeats must be positive")
    labels = np.asarray(predictions["labels"], dtype=np.int64)
    logits = np.asarray(predictions["logits"], dtype=np.float64)
    offsets = np.asarray(predictions["sample_offsets"], dtype=np.int64)
    _validate_offsets(offsets, logits.size)
    if labels.size != logits.size or not np.isin(labels, (0, 1)).all():
        raise ValueError("Shuffle labels must be aligned and binary")
    original_probabilities = 1.0 / (1.0 + np.exp(-logits))
    original_ap = _safe_ap(labels, original_probabilities)
    rng = np.random.default_rng(int(seed))
    values = np.asarray(
        [
            _safe_ap(
                labels,
                1.0
                / (
                    1.0
                    + np.exp(
                        -shuffle_logits_within_samples(logits, offsets, rng)
                    )
                ),
            )
            for _ in range(int(repeats))
        ],
        dtype=np.float64,
    )
    return {
        "semantics": "labels_fixed_logits_permuted_independently_within_each_sample",
        "repeats": int(repeats),
        "seed": int(seed),
        "student_original_ap": original_ap,
        "ap_distribution": _distribution(values),
        "mean_delta_from_original": float(values.mean() - original_ap),
    }


def _split_report(
    predictions: Mapping[str, np.ndarray],
    priors: Mapping[str, Any],
    *,
    expected_segments: int,
    shuffle_repeats: int,
    seed: int,
) -> dict[str, Any]:
    _validate_predictions(predictions, expected_segments)
    labels = np.asarray(predictions["labels"], dtype=np.int64)
    probabilities = np.asarray(predictions["probabilities"], dtype=np.float64)
    logits = np.asarray(predictions["logits"], dtype=np.float64)
    offsets = np.asarray(predictions["sample_offsets"], dtype=np.int64)
    prior_scores = apply_empirical_priors(
        predictions, priors, expected_segments=expected_segments
    )
    centered_logits = mean_center_logits(logits, offsets)
    centered_probabilities = 1.0 / (1.0 + np.exp(-centered_logits))
    centered_means = [
        float(centered_logits[int(start) : int(end)].mean())
        for start, end in zip(offsets[:-1], offsets[1:])
    ]
    fallback_receipt = {
        name: prior_scores[name]
        for name in (
            "known_query_samples",
            "fallback_query_samples",
            "query_only_fallback",
            "query_position_fallback",
        )
    }
    return {
        "sample_count": int(np.asarray(predictions["ids"]).size),
        "segment_count": int(labels.size),
        "student_original_ap": _safe_ap(labels, probabilities),
        "query_only_prior": {
            "ap": _safe_ap(labels, prior_scores["query_only_probabilities"]),
            **fallback_receipt,
        },
        "query_position_prior": {
            "ap": _safe_ap(labels, prior_scores["query_position_probabilities"]),
            **fallback_receipt,
        },
        "mean_centered_student": {
            "ap": _safe_ap(labels, centered_probabilities),
            "delta_from_original": _safe_ap(labels, centered_probabilities)
            - _safe_ap(labels, probabilities),
            "within_sample_logit_mean_max_abs": float(
                np.max(np.abs(centered_means)) if centered_means else 0.0
            ),
        },
        "temporal_shuffle": temporal_shuffle_diagnostic(
            predictions, repeats=shuffle_repeats, seed=seed
        ),
    }


def build_shortcut_report(
    *,
    train_manifest: str | Path,
    validation_predictions: str | Path,
    test_predictions: str | Path,
    expected_segments: int = 10,
    shuffle_repeats: int = 100,
    seed: int = 42,
) -> dict[str, Any]:
    train_path = Path(train_manifest)
    validation_path = Path(validation_predictions)
    test_path = Path(test_predictions)
    priors = build_empirical_priors(
        load_manifest(train_path), expected_segments=expected_segments
    )
    validation = load_prediction_npz(validation_path)
    test = load_prediction_npz(test_path)
    return {
        "schema_version": 1,
        "status": "PASS",
        "metric_claim": "diagnostic_global_segment_micro_ap",
        "protocol": {
            "task_segments": int(expected_segments),
            "temporal_conversion": "forbidden",
            "prior_estimator": "empirical_training_segment_frequency",
            "prior_smoothing": "none",
            "shuffle_repeats": int(shuffle_repeats),
            "shuffle_seed": int(seed),
        },
        "sources": {
            "train_manifest": _source_receipt(train_path),
            "validation": _source_receipt(validation_path),
            "test": _source_receipt(test_path),
        },
        "training_priors": priors,
        "validation": _split_report(
            validation,
            priors,
            expected_segments=expected_segments,
            shuffle_repeats=shuffle_repeats,
            seed=seed,
        ),
        "test": _split_report(
            test,
            priors,
            expected_segments=expected_segments,
            shuffle_repeats=shuffle_repeats,
            seed=seed,
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only query/position/temporal shortcut diagnostics"
    )
    parser.add_argument("--train-manifest", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--test", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-segments", type=int, default=10)
    parser.add_argument("--shuffle-repeats", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_shortcut_report(
        train_manifest=args.train_manifest,
        validation_predictions=args.validation,
        test_predictions=args.test,
        expected_segments=args.expected_segments,
        shuffle_repeats=args.shuffle_repeats,
        seed=args.seed,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
