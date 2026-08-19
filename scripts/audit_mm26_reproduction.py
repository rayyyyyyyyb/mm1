#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import numpy as np


CANONICAL_COUNTS = {"train": 13182, "val": 5798, "test": 5820}
EXPECTED_ARTIFACT_SHAPES = {
    "strong_teacher_features": "[T, 512]",
    "strong_teacher_logits": "[T] or [T, 1]",
    "weak_teacher_features": "[T, 768]",
    "text_embedding": "[1024]",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit ACM MM 2026 OV-OrthKD reproduction inputs")
    parser.add_argument("--train-manifest", required=True)
    parser.add_argument("--val-manifest", required=True)
    parser.add_argument("--test-manifest", required=True)
    parser.add_argument("--path-root", default=".")
    parser.add_argument("--stage", choices=("source", "exported"), required=True)
    parser.add_argument("--artifact-scan", choices=("none", "sample", "full"), default="sample")
    parser.add_argument("--sample-count", type=int, default=100)
    parser.add_argument("--output-json", default=None)
    parser.add_argument("--expected-segments", choices=("auto", "10", "16"), default="auto")
    parser.add_argument("--fail-on-warning", action="store_true")
    return parser.parse_args()


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")
    if path.suffix.lower() == ".json":
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            raise ValueError(f"Expected a JSON list: {path}")
        return value
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}") from exc
    return records


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(path_root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = path_root / path
    return path.resolve()


def _iter_paths(value: Any) -> Iterable[str]:
    if isinstance(value, (str, Path)):
        yield str(value)
    elif isinstance(value, dict):
        if value.get("path"):
            yield str(value["path"])
    elif isinstance(value, list):
        for item in value:
            yield from _iter_paths(item)


def _record_path_value(record: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        value = record.get(name)
        if value is not None:
            return value
    return None


def _issue(code: str, split: str, record_id: str | None, message: str) -> dict[str, Any]:
    return {
        "code": code,
        "split": split,
        "record_id": record_id,
        "message": message,
    }


def _load_artifact(path_root: Path, value: Any) -> tuple[np.ndarray | None, Path | None]:
    if value is None:
        return None, None
    if isinstance(value, str):
        path = _resolve(path_root, value)
        if not path.exists():
            return None, path
        if path.suffix.lower() == ".npy":
            return np.load(path), path
        if path.suffix.lower() == ".npz":
            with np.load(path) as bundle:
                key = "arr_0" if "arr_0" in bundle else next(iter(bundle.keys()))
                return bundle[key], path
        raise ValueError(f"Unsupported artifact extension: {path}")
    return np.asarray(value), None


def _artifact_shape_valid(field: str, shape: tuple[int, ...], segments: int) -> bool:
    if field == "strong_teacher_features":
        return shape == (segments, 512)
    if field == "strong_teacher_logits":
        return shape in {(segments,), (segments, 1)}
    if field == "weak_teacher_features":
        return shape == (segments, 768)
    if field == "text_embedding":
        return shape == (1024,)
    raise KeyError(field)


def audit_reproduction(
    *,
    train_manifest: str | Path,
    val_manifest: str | Path,
    test_manifest: str | Path,
    path_root: str | Path,
    stage: str,
    artifact_scan: str,
    sample_count: int,
    expected_segments: str,
) -> dict[str, Any]:
    if stage not in {"source", "exported"}:
        raise ValueError(f"Unsupported stage: {stage}")
    if artifact_scan not in {"none", "sample", "full"}:
        raise ValueError(f"Unsupported artifact_scan: {artifact_scan}")
    if expected_segments not in {"auto", "10", "16"}:
        raise ValueError(f"Unsupported expected_segments: {expected_segments}")

    root = Path(path_root).expanduser().resolve()
    manifest_paths = {
        "train": _resolve(root, train_manifest),
        "val": _resolve(root, val_manifest),
        "test": _resolve(root, test_manifest),
    }
    split_records = {split: _load_manifest(path) for split, path in manifest_paths.items()}
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    segment_histogram: Counter[int] = Counter()
    label_histogram: Counter[int] = Counter()
    frame_count_histogram: Counter[int] = Counter()
    category_counts: Counter[str] = Counter()
    split_type_counts: Counter[str] = Counter()
    ids_by_split: dict[str, set[str]] = {}
    duplicate_ids: dict[str, list[str]] = {}
    scanned_artifacts = 0

    for split, records in split_records.items():
        seen_ids: set[str] = set()
        duplicates: set[str] = set()
        ids_by_split[split] = set()
        for record_index, record in enumerate(records):
            raw_id = record.get("id")
            record_id = str(raw_id).strip() if raw_id is not None else ""
            if not record_id:
                errors.append(_issue("empty_id", split, None, f"Record {record_index} has no id"))
                record_id = f"<missing:{record_index}>"
            if record_id in seen_ids:
                duplicates.add(record_id)
            seen_ids.add(record_id)
            ids_by_split[split].add(record_id)

            labels_value = record.get("segment_labels")
            labels = np.asarray(labels_value if labels_value is not None else []).reshape(-1)
            if labels.size == 0:
                errors.append(_issue("empty_labels", split, record_id, "segment_labels is empty"))
                continue
            if not np.isin(labels, [0, 1]).all():
                errors.append(
                    _issue("non_binary_label", split, record_id, f"Labels are not binary: {labels.tolist()}")
                )
            segments = int(labels.size)
            segment_histogram[segments] += 1
            for label in labels.tolist():
                if label in (0, 1):
                    label_histogram[int(label)] += 1

            query = str(record.get("query", record.get("category", ""))).strip()
            if not query:
                errors.append(_issue("missing_query", split, record_id, "query/category metadata is missing"))
            else:
                category_counts[query] += 1
            split_type = str(
                record.get("split_type", record.get("seen_unseen", record.get("meta", {}).get("split_type", "")))
            ).lower()
            if split_type not in {"seen", "unseen"}:
                errors.append(
                    _issue("missing_split_type", split, record_id, "seen/unseen metadata is missing or invalid")
                )
            else:
                split_type_counts[split_type] += 1

            frame_value = _record_path_value(
                record,
                ("segment_frame_paths", "frame_groups", "frame_paths", "frames"),
            )
            spec_value = _record_path_value(
                record,
                ("spectrogram_paths", "spectrograms", "audio_image_paths"),
            )
            for field, value in (("frame_paths", frame_value), ("spectrogram_paths", spec_value)):
                outer_length = len(value) if isinstance(value, list) else (1 if value else 0)
                if outer_length not in {0, segments}:
                    errors.append(
                        _issue(
                            "path_alignment",
                            split,
                            record_id,
                            f"{field} length {outer_length} != label length {segments}",
                        )
                    )
                if field == "frame_paths":
                    frame_count_histogram[sum(1 for _ in _iter_paths(value))] += 1
                for raw_path in _iter_paths(value):
                    resolved = _resolve(root, raw_path)
                    if not resolved.exists():
                        errors.append(
                            _issue("missing_path", split, record_id, f"Missing {field}: {resolved}")
                        )

            if stage != "exported":
                continue
            should_scan = artifact_scan == "full" or (
                artifact_scan == "sample" and scanned_artifacts < max(0, int(sample_count))
            )
            artifact_values = {
                field: _record_path_value(record, (field, f"{field}_path"))
                for field in EXPECTED_ARTIFACT_SHAPES
            }
            for field, value in artifact_values.items():
                if value is None:
                    errors.append(_issue("missing_artifact", split, record_id, f"Missing {field}"))
                    continue
                if isinstance(value, str) and not _resolve(root, value).exists():
                    errors.append(
                        _issue("missing_path", split, record_id, f"Missing {field}: {_resolve(root, value)}")
                    )
                    continue
                if not should_scan:
                    continue
                try:
                    array, _ = _load_artifact(root, value)
                except (OSError, ValueError) as exc:
                    errors.append(_issue("artifact_load", split, record_id, f"{field}: {exc}"))
                    continue
                if array is None:
                    errors.append(_issue("missing_artifact", split, record_id, f"Missing {field}"))
                    continue
                if not _artifact_shape_valid(field, tuple(array.shape), segments):
                    errors.append(
                        _issue(
                            "artifact_dimension",
                            split,
                            record_id,
                            f"{field} shape {tuple(array.shape)} != {EXPECTED_ARTIFACT_SHAPES[field]}",
                        )
                    )
                if not np.isfinite(array).all():
                    errors.append(
                        _issue("non_finite_artifact", split, record_id, f"{field} contains NaN/Inf")
                    )
            if should_scan:
                scanned_artifacts += 1
        duplicate_ids[split] = sorted(duplicates)
        for duplicate in duplicates:
            errors.append(_issue("duplicate_id", split, duplicate, "Duplicate id within split"))

    split_overlap: list[dict[str, Any]] = []
    split_names = ("train", "val", "test")
    for left_index, left in enumerate(split_names):
        for right in split_names[left_index + 1 :]:
            overlap = sorted(ids_by_split[left] & ids_by_split[right])
            if overlap:
                split_overlap.append({"splits": [left, right], "ids": overlap})
                for record_id in overlap:
                    errors.append(
                        _issue("split_overlap", f"{left}/{right}", record_id, "Id appears in multiple splits")
                    )

    if expected_segments != "auto":
        expected = int(expected_segments)
        for observed, count in sorted(segment_histogram.items()):
            if observed != expected:
                warnings.append(
                    _issue(
                        "unexpected_segment_count",
                        "all",
                        None,
                        f"{count} records have T={observed}; expected T={expected}",
                    )
                )

    split_counts = {split: len(records) for split, records in split_records.items()}
    return {
        "stage": stage,
        "artifact_scan": artifact_scan,
        "path_root": str(root),
        "split_counts": split_counts,
        "canonical_expected_split_counts": CANONICAL_COUNTS,
        "canonical_split_count_matches": {
            split: split_counts[split] == expected for split, expected in CANONICAL_COUNTS.items()
        },
        "record_count": sum(split_counts.values()),
        "category_count": len(category_counts),
        "category_counts": dict(sorted(category_counts.items())),
        "seen_classes": sum(1 for name in category_counts if any(
            str(record.get("query", record.get("category", ""))).strip() == name
            and str(record.get("split_type", record.get("seen_unseen", record.get("meta", {}).get("split_type", "")))).lower() == "seen"
            for records in split_records.values() for record in records
        )),
        "unseen_classes": sum(1 for name in category_counts if any(
            str(record.get("query", record.get("category", ""))).strip() == name
            and str(record.get("split_type", record.get("seen_unseen", record.get("meta", {}).get("split_type", "")))).lower() == "unseen"
            for records in split_records.values() for record in records
        )),
        "split_type_counts": dict(sorted(split_type_counts.items())),
        "duplicate_ids": duplicate_ids,
        "split_overlap": split_overlap,
        "label_histogram": {str(key): value for key, value in sorted(label_histogram.items())},
        "segment_length_histogram": {
            str(key): value for key, value in sorted(segment_histogram.items())
        },
        "frame_count_histogram": {
            str(key): value for key, value in sorted(frame_count_histogram.items())
        },
        "manifest_sha256": {split: _sha256(path) for split, path in manifest_paths.items()},
        "configured_max_segments": 16,
        "resampling_performed_by_dataset": False,
        "artifacts_scanned": scanned_artifacts,
        "path_errors": [item for item in errors if item["code"] in {"missing_path", "path_alignment"}],
        "artifact_errors": [
            item
            for item in errors
            if item["code"] in {"missing_artifact", "artifact_load", "artifact_dimension", "non_finite_artifact"}
        ],
        "errors": errors,
        "warnings": warnings,
    }


def audit_exit_code(report: dict[str, Any], fail_on_warning: bool) -> int:
    if report.get("errors"):
        return 1
    if fail_on_warning and report.get("warnings"):
        return 1
    return 0


def main() -> None:
    args = parse_args()
    report = audit_reproduction(
        train_manifest=args.train_manifest,
        val_manifest=args.val_manifest,
        test_manifest=args.test_manifest,
        path_root=args.path_root,
        stage=args.stage,
        artifact_scan=args.artifact_scan,
        sample_count=args.sample_count,
        expected_segments=args.expected_segments,
    )
    payload = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload, encoding="utf-8")
    print(payload, end="")
    raise SystemExit(audit_exit_code(report, args.fail_on_warning))


if __name__ == "__main__":
    main()
