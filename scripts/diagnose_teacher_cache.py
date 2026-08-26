#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.preprocessing import StandardScaler


def _load_direct_record(
    record: dict[str, Any],
    *,
    expected_segments: int,
    project_root: Path | None,
) -> tuple[np.ndarray, np.ndarray, str]:
    sample_id = str(record.get("id", "<unknown>"))
    labels = np.asarray(record["segment_labels"], dtype=np.int64).reshape(-1)
    if labels.shape != (expected_segments,) or not np.isin(labels, (0, 1)).all():
        raise ValueError(f"{sample_id}: invalid labels shape/content {labels.shape}")
    source = Path(record["strong_teacher_logits_path"])
    if not source.is_absolute() and project_root is not None:
        source = project_root / source
    if not source.is_file():
        raise FileNotFoundError(f"{sample_id}: missing strong teacher logits: {source}")
    raw = np.load(source, allow_pickle=False)
    if raw.shape not in {(expected_segments,), (expected_segments, 1)}:
        raise ValueError(f"{sample_id}: invalid strong teacher logit shape {raw.shape}")
    logits = np.asarray(raw, dtype=np.float64).reshape(-1)
    if not np.isfinite(logits).all():
        raise ValueError(f"{sample_id}: strong teacher logits contain NaN/Inf")
    return labels, logits, json.dumps(list(raw.shape), separators=(",", ":"))


def audit_direct_logits(
    manifest: str | Path,
    *,
    expected_segments: int = 10,
    workers: int = 16,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    manifest_path = Path(manifest)
    records = [json.loads(line) for line in manifest_path.open(encoding="utf-8") if line.strip()]
    if not records:
        raise ValueError(f"manifest is empty: {manifest_path}")
    root = Path(project_root) if project_root is not None else None

    def load(record: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, str]:
        return _load_direct_record(
            record,
            expected_segments=int(expected_segments),
            project_root=root,
        )

    if int(workers) <= 1:
        rows = [load(record) for record in records]
    else:
        with ThreadPoolExecutor(max_workers=int(workers)) as executor:
            rows = list(executor.map(load, records, chunksize=32))
    labels = np.concatenate([row[0] for row in rows])
    logits = np.concatenate([row[1] for row in rows])
    per_sample = [
        float(average_precision_score(row[0], row[1])) if np.any(row[0] == 1) else 0.0
        for row in rows
    ]
    shapes = Counter(row[2] for row in rows)
    return {
        "manifest": str(manifest_path),
        "samples": len(rows),
        "segments": int(labels.size),
        "expected_segments_per_sample": int(expected_segments),
        "array_shapes": dict(sorted(shapes.items())),
        "label_positive_rate": float(labels.mean()),
        "logit_mean": float(logits.mean()),
        "logit_std": float(logits.std()),
        "logit_min": float(logits.min()),
        "logit_max": float(logits.max()),
        "ap": float(average_precision_score(labels, logits)),
        "auroc": float(roc_auc_score(labels, logits)),
        "per_sample_ap_macro_all_negative_zero": float(np.mean(per_sample)),
    }


def _load_feature_record(
    record: dict[str, Any],
    *,
    field: str,
    expected_segments: int,
    expected_dim: int,
    project_root: Path | None,
) -> tuple[np.ndarray, np.ndarray, str]:
    sample_id = str(record.get("id", "<unknown>"))
    labels = np.asarray(record["segment_labels"], dtype=np.int64).reshape(-1)
    if labels.shape != (expected_segments,) or not np.isin(labels, (0, 1)).all():
        raise ValueError(f"{sample_id}: invalid labels shape/content {labels.shape}")
    source = Path(record[field])
    if not source.is_absolute() and project_root is not None:
        source = project_root / source
    if not source.is_file():
        raise FileNotFoundError(f"{sample_id}: missing {field}: {source}")
    raw = np.load(source, allow_pickle=False)
    if raw.shape != (expected_segments, expected_dim):
        raise ValueError(f"{sample_id}: invalid {field} shape {raw.shape}")
    features = np.asarray(raw, dtype=np.float32)
    if not np.isfinite(features).all():
        raise ValueError(f"{sample_id}: {field} contains NaN/Inf")
    return features, labels, json.dumps(list(raw.shape), separators=(",", ":"))


def load_feature_split(
    manifest: str | Path,
    *,
    field: str,
    expected_segments: int,
    expected_dim: int,
    workers: int,
    project_root: str | Path | None,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    manifest_path = Path(manifest)
    records = [json.loads(line) for line in manifest_path.open(encoding="utf-8") if line.strip()]
    if not records:
        raise ValueError(f"manifest is empty: {manifest_path}")
    root = Path(project_root) if project_root is not None else None

    def load(record: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, str]:
        return _load_feature_record(
            record,
            field=field,
            expected_segments=int(expected_segments),
            expected_dim=int(expected_dim),
            project_root=root,
        )

    if int(workers) <= 1:
        rows = [load(record) for record in records]
    else:
        with ThreadPoolExecutor(max_workers=int(workers)) as executor:
            rows = list(executor.map(load, records, chunksize=32))
    features = np.concatenate([row[0] for row in rows], axis=0)
    labels = np.concatenate([row[1] for row in rows], axis=0)
    shapes = Counter(row[2] for row in rows)
    receipt = {
        "manifest": str(manifest_path),
        "field": field,
        "samples": len(rows),
        "segments": int(labels.size),
        "feature_dim": int(features.shape[1]),
        "array_shapes": dict(sorted(shapes.items())),
        "feature_dtype": str(features.dtype),
        "feature_mean": float(features.mean()),
        "feature_std": float(features.std()),
        "label_positive_rate": float(labels.mean()),
    }
    return features, labels, receipt


def fit_linear_probe(
    train_features: np.ndarray,
    train_labels: np.ndarray,
    evaluation_splits: dict[str, tuple[np.ndarray, np.ndarray]],
    *,
    random_state: int = 42,
) -> dict[str, Any]:
    x_train = np.asarray(train_features, dtype=np.float32)
    y_train = np.asarray(train_labels, dtype=np.int64).reshape(-1)
    if x_train.ndim != 2 or x_train.shape[0] != y_train.size:
        raise ValueError("train features/labels shape mismatch")
    if not np.isfinite(x_train).all() or not np.isin(y_train, (0, 1)).all():
        raise ValueError("train features/labels contain invalid values")
    if np.unique(y_train).size != 2:
        raise ValueError("linear probe training requires both binary classes")

    scaler = StandardScaler(copy=True)
    standardized_train = scaler.fit_transform(x_train)
    classifier = SGDClassifier(
        loss="log_loss",
        penalty="l2",
        alpha=1e-4,
        fit_intercept=True,
        max_iter=2000,
        tol=1e-5,
        shuffle=True,
        random_state=int(random_state),
        learning_rate="optimal",
        early_stopping=False,
        class_weight=None,
        average=True,
        n_jobs=1,
    )
    classifier.fit(standardized_train, y_train)
    evaluation: dict[str, Any] = {}
    for name, (features, labels) in evaluation_splits.items():
        x_eval = np.asarray(features, dtype=np.float32)
        y_eval = np.asarray(labels, dtype=np.int64).reshape(-1)
        if x_eval.ndim != 2 or x_eval.shape[1] != x_train.shape[1] or x_eval.shape[0] != y_eval.size:
            raise ValueError(f"{name}: evaluation features/labels shape mismatch")
        if not np.isfinite(x_eval).all() or not np.isin(y_eval, (0, 1)).all():
            raise ValueError(f"{name}: evaluation data contain invalid values")
        scores = classifier.decision_function(scaler.transform(x_eval))
        evaluation[name] = {
            "segments": int(y_eval.size),
            "positive_rate": float(y_eval.mean()),
            "ap": float(average_precision_score(y_eval, scores)),
            "auroc": float(roc_auc_score(y_eval, scores)),
            "score_mean": float(scores.mean()),
            "score_std": float(scores.std()),
        }
    return {
        "claim": "transparent_reconstruction_probe_not_archival_exact",
        "protocol": {
            "model": "sklearn.linear_model.SGDClassifier",
            "loss": "log_loss",
            "penalty": "l2",
            "alpha": 1e-4,
            "feature_standardization": "train_split_standard_scaler",
            "max_iter": 2000,
            "tol": 1e-5,
            "shuffle": True,
            "random_state": int(random_state),
            "learning_rate": "optimal",
            "early_stopping": False,
            "average_parameters": True,
            "class_weight": None,
            "aggregation": "global_micro_over_official_task_segments",
        },
        "fit": {
            "train_segments": int(y_train.size),
            "feature_dim": int(x_train.shape[1]),
            "iterations": int(classifier.n_iter_),
            "coefficient_l2_norm": float(np.linalg.norm(classifier.coef_)),
            "intercept": [float(value) for value in classifier.intercept_.tolist()],
        },
        "evaluation": evaluation,
    }


def _named_path(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("expected NAME=PATH")
    name, path = value.split("=", 1)
    if not name.strip() or not path.strip():
        raise argparse.ArgumentTypeError("expected nonempty NAME=PATH")
    return name.strip(), Path(path.strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit locked teacher-cache signals")
    parser.add_argument("--manifest", action="append", type=_named_path, required=True)
    parser.add_argument("--project-root", type=Path, default=None)
    parser.add_argument("--expected-segments", type=int, default=10)
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--probe-train", type=Path, default=None)
    parser.add_argument("--probe-eval", action="append", type=_named_path, default=[])
    parser.add_argument(
        "--probe",
        action="append",
        choices=("strong", "weak"),
        default=[],
        help="Run the transparent reconstruction linear probe for this feature source.",
    )
    parser.add_argument("--strong-dim", type=int, default=512)
    parser.add_argument("--weak-dim", type=int, default=768)
    parser.add_argument("--probe-seed", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = {
        "schema_version": 1,
        "status": "PASS",
        "metric_semantics": "global_micro_over_official_task_segments",
        "direct_logits": {
            name: audit_direct_logits(
                path,
                expected_segments=args.expected_segments,
                workers=args.workers,
                project_root=args.project_root,
            )
            for name, path in args.manifest
        },
    }
    if args.probe:
        if args.probe_train is None or not args.probe_eval:
            raise ValueError("--probe requires --probe-train and at least one --probe-eval")
        report["feature_probes"] = {}
        for probe_name in args.probe:
            field = (
                "strong_teacher_features_path"
                if probe_name == "strong"
                else "weak_teacher_features_path"
            )
            dimension = args.strong_dim if probe_name == "strong" else args.weak_dim
            train_features, train_labels, train_receipt = load_feature_split(
                args.probe_train,
                field=field,
                expected_segments=args.expected_segments,
                expected_dim=dimension,
                workers=args.workers,
                project_root=args.project_root,
            )
            evaluation_data: dict[str, tuple[np.ndarray, np.ndarray]] = {}
            evaluation_receipts: dict[str, Any] = {}
            for split_name, split_path in args.probe_eval:
                features, labels, receipt = load_feature_split(
                    split_path,
                    field=field,
                    expected_segments=args.expected_segments,
                    expected_dim=dimension,
                    workers=args.workers,
                    project_root=args.project_root,
                )
                evaluation_data[split_name] = (features, labels)
                evaluation_receipts[split_name] = receipt
            report["feature_probes"][probe_name] = {
                "data": {"train": train_receipt, "evaluation": evaluation_receipts},
                "probe": fit_linear_probe(
                    train_features,
                    train_labels,
                    evaluation_data,
                    random_state=args.probe_seed,
                ),
            }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
