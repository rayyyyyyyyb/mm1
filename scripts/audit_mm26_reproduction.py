#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.split_types import split_type_from_record
from src.teachers.common import safe_record_id
from src.teachers.pipeline import _validate_receipt
from src.utils.atomic_artifacts import canonical_tree_hash
from src.utils.reproduction_locks import teacher_identity_sha256


CANONICAL_COUNTS = {"train": 13182, "val": 5798, "test": 5820}
CANONICAL_SPLIT_SEEN_UNSEEN_COUNTS = {
    "train": {"seen": 13182, "unseen": 0},
    "val": {"seen": 1651, "unseen": 4147},
    "test": {"seen": 1664, "unseen": 4156},
}
EXPECTED_ARTIFACT_SHAPES = {
    "strong_teacher_features": "[T, 512]",
    "strong_teacher_logits": "[T] or [T, 1]",
    "weak_teacher_features": "[T, 768]",
    "text_embedding": "[1024]",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit ACM MM 2026 OV-OrthKD reproduction inputs")
    parser.add_argument("--config", default="configs/ov_orthkd_mm26_repro.yaml")
    parser.add_argument("--preprocessing-lock", default=None)
    parser.add_argument("--teacher-lock", default=None)
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


def _load_mapping(value: str | Path | Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    path = Path(value).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Configuration/lock not found: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise ValueError(f"Expected a mapping in configuration/lock: {path}")
    return dict(loaded)


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
            return np.load(path, allow_pickle=False), path
        if path.suffix.lower() == ".npz":
            with np.load(path, allow_pickle=False) as bundle:
                keys = list(bundle.keys())
                if keys != ["arr_0"]:
                    raise ValueError(f"Expected exactly one npz key named 'arr_0', got {keys}")
                return bundle["arr_0"], path
        raise ValueError(f"Unsupported artifact extension: {path}")
    return np.asarray(value), None


def _artifact_shape_valid(
    field: str,
    shape: tuple[int, ...],
    segments: int,
    dimensions: Mapping[str, int],
) -> bool:
    if field == "strong_teacher_features":
        return shape == (segments, dimensions[field])
    if field == "strong_teacher_logits":
        return shape in {(segments,), (segments, 1)}
    if field == "weak_teacher_features":
        return shape == (segments, dimensions[field])
    if field == "text_embedding":
        return shape == (dimensions[field],)
    raise KeyError(field)


def _artifact_shape_description(field: str, dimensions: Mapping[str, int]) -> str:
    if field == "strong_teacher_logits":
        return "[T] or [T, 1]"
    if field == "text_embedding":
        return f"[{dimensions[field]}]"
    return f"[T, {dimensions[field]}]"


def _teacher_dimension(
    teacher_lock: Mapping[str, Any], teacher_name: str, default: int
) -> int:
    teacher = teacher_lock.get("teachers", {}).get(teacher_name, {})
    value = teacher.get("output_dim") if isinstance(teacher, Mapping) else None
    return int(value) if value is not None else int(default)


def _record_resampling_evidence(record: Mapping[str, Any]) -> bool | None:
    meta = record.get("meta", {})
    evidence = meta.get("preprocessing_evidence", {}) if isinstance(meta, Mapping) else {}
    if not isinstance(evidence, Mapping):
        return None
    values = [
        evidence.get("temporal_resampling_performed"),
        evidence.get("audio_resampling_performed"),
    ]
    present = [value for value in values if isinstance(value, bool)]
    if present:
        return any(present)
    fallback = record.get("noncanonical_temporal_sampling")
    return fallback if isinstance(fallback, bool) else None


def _validate_export_receipt_binding(
    receipt_path: Path,
    *,
    record_id: str,
    split: str,
    teacher_identity_sha256: str,
    source_manifest_sha256: str,
) -> str | None:
    if not receipt_path.is_file():
        return "missing per-record receipt"
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"invalid per-record receipt: {exc}"
    if not isinstance(receipt, Mapping):
        return "per-record receipt must be a mapping"
    if receipt.get("schema_version") != 3:
        return "receipt schema mismatch"
    if receipt.get("record_id") != record_id:
        return "record id mismatch"
    if receipt.get("split") != split:
        return "split mismatch"
    if receipt.get("teacher_identity_sha256") != teacher_identity_sha256:
        return "teacher identity hash mismatch"
    if receipt.get("source_manifest_sha256") != source_manifest_sha256:
        return "source manifest hash mismatch"
    if not isinstance(receipt.get("artifacts"), Mapping):
        return "missing artifact metadata"
    return None


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
    config: str | Path | Mapping[str, Any] | None = None,
    preprocessing_lock: str | Path | Mapping[str, Any] | None = None,
    teacher_lock: str | Path | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if stage not in {"source", "exported"}:
        raise ValueError(f"Unsupported stage: {stage}")
    if artifact_scan not in {"none", "sample", "full"}:
        raise ValueError(f"Unsupported artifact_scan: {artifact_scan}")
    if expected_segments not in {"auto", "10", "16"}:
        raise ValueError(f"Unsupported expected_segments: {expected_segments}")

    config_document = _load_mapping(config)
    data_cfg = config_document.get("data", {})
    if not isinstance(data_cfg, Mapping):
        raise ValueError("config.data must be a mapping")
    readiness_cfg = config_document.get("reproduction", {}).get("readiness", {})
    if not isinstance(readiness_cfg, Mapping):
        readiness_cfg = {}
    preprocessing_lock_value = preprocessing_lock or readiness_cfg.get("preprocessing_lock")
    teacher_lock_value = teacher_lock or readiness_cfg.get("teacher_lock")
    preprocessing_lock_document = _load_mapping(preprocessing_lock_value)
    teacher_lock_document = _load_mapping(teacher_lock_value)
    from src.utils.temporal_protocol import task_segments_from_config

    configured_task_segments = task_segments_from_config(config_document)
    artifact_dimensions = {
        "strong_teacher_features": int(
            data_cfg.get(
                "strong_teacher_dim",
                _teacher_dimension(teacher_lock_document, "internvideo2", 512),
            )
        ),
        "weak_teacher_features": int(
            data_cfg.get(
                "weak_teacher_dim",
                _teacher_dimension(teacher_lock_document, "beats", 768),
            )
        ),
        "text_embedding": int(
            data_cfg.get(
                "text_dim",
                _teacher_dimension(teacher_lock_document, "clap", 1024),
            )
        ),
    }
    root = Path(path_root).expanduser().resolve()
    manifest_paths = {
        "train": _resolve(root, train_manifest),
        "val": _resolve(root, val_manifest),
        "test": _resolve(root, test_manifest),
    }
    split_records = {split: _load_manifest(path) for split, path in manifest_paths.items()}
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    teacher_identity_digest: str | None = None
    artifact_root: Path | None = None
    source_manifest_hashes: dict[str, str] = {}
    if stage == "exported" and artifact_scan == "full" and teacher_lock_document:
        try:
            teacher_identity_digest = teacher_identity_sha256(teacher_lock_document)
        except ValueError as exc:
            errors.append(_issue("teacher_identity_binding", "all", None, str(exc)))
        artifact_dir = config_document.get("teacher_export", {}).get("artifact_dir")
        if artifact_dir:
            artifact_root = _resolve(root, artifact_dir)
        for split, key in (
            ("train", "train_manifest"),
            ("val", "val_manifest"),
            ("test", "test_manifest"),
        ):
            source_value = data_cfg.get(key)
            if source_value:
                source_path = _resolve(root, source_value)
                if source_path.is_file():
                    source_manifest_hashes[split] = _sha256(source_path)
                else:
                    errors.append(
                        _issue(
                            "source_manifest_binding",
                            split,
                            None,
                            f"Configured source manifest is missing: {source_path}",
                        )
                    )
    segment_histogram: Counter[int] = Counter()
    label_histogram: Counter[int] = Counter()
    frame_count_histogram: Counter[int] = Counter()
    category_counts: Counter[str] = Counter()
    split_type_counts: Counter[str] = Counter()
    split_seen_unseen_counts = {
        split: {"seen": 0, "unseen": 0} for split in ("train", "val", "test")
    }
    resampling_counts = {
        "records_with_resampling": 0,
        "records_without_resampling": 0,
        "records_missing_evidence": 0,
    }
    seen_class_names: set[str] = set()
    unseen_class_names: set[str] = set()
    ids_by_split: dict[str, set[str]] = {}
    duplicate_ids: dict[str, list[str]] = {}
    scanned_artifacts = 0
    receipt_bindings_checked = 0

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
            try:
                split_type = split_type_from_record(record)
            except ValueError as exc:
                split_type = "unknown"
                errors.append(_issue("invalid_split_type", split, record_id, str(exc)))
            if split_type not in {"seen", "unseen"}:
                errors.append(
                    _issue("missing_split_type", split, record_id, "seen/unseen metadata is missing or invalid")
                )
            else:
                split_type_counts[split_type] += 1
                split_seen_unseen_counts[split][split_type] += 1
                if query:
                    (seen_class_names if split_type == "seen" else unseen_class_names).add(query)

            resampling = _record_resampling_evidence(record)
            if resampling is True:
                resampling_counts["records_with_resampling"] += 1
            elif resampling is False:
                resampling_counts["records_without_resampling"] += 1
            else:
                resampling_counts["records_missing_evidence"] += 1

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

            if stage == "source":
                source_assets = {
                    "audio_path": _record_path_value(
                        record,
                        (
                            "wav_path",
                            "audio_path",
                            "official_wav_path",
                            "audio_segment_paths",
                            "audio_paths",
                            "audio_waveform_paths",
                            "waveform_paths",
                        ),
                    ),
                }
                for field, value in source_assets.items():
                    paths = list(_iter_paths(value))
                    if not paths:
                        errors.append(
                            _issue(
                                "missing_source_asset",
                                split,
                                record_id,
                                f"Missing required {field}",
                            )
                        )
                        continue
                    for raw_path in paths:
                        resolved = _resolve(root, raw_path)
                        if not resolved.is_file():
                            errors.append(
                                _issue(
                                    "missing_path",
                                    split,
                                    record_id,
                                    f"Missing {field}: {resolved}",
                                )
                            )
                optional_raw_video = _record_path_value(
                    record,
                    ("raw_video_path", "official_video_path", "video_path"),
                )
                for raw_path in _iter_paths(optional_raw_video):
                    resolved = _resolve(root, raw_path)
                    if not resolved.is_file():
                        warnings.append(
                            _issue(
                                "missing_optional_raw_video_diagnostic",
                                split,
                                record_id,
                                f"Optional raw-video diagnostic input is missing: {resolved}",
                            )
                        )

            if stage != "exported":
                continue
            if (
                artifact_scan == "full"
                and artifact_root is not None
                and teacher_identity_digest is not None
                and split in source_manifest_hashes
            ):
                receipt_path = (
                    artifact_root
                    / "receipts"
                    / split
                    / f"{safe_record_id(record_id)}.json"
                )
                binding_error = _validate_export_receipt_binding(
                    receipt_path,
                    record_id=record_id,
                    split=split,
                    teacher_identity_sha256=teacher_identity_digest,
                    source_manifest_sha256=source_manifest_hashes[split],
                )
                if binding_error is not None:
                    errors.append(
                        _issue(
                            "teacher_identity_binding",
                            split,
                            record_id,
                            binding_error,
                        )
                    )
                else:
                    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                    valid, reason = _validate_receipt(
                        receipt,
                        artifact_root=artifact_root,
                        source_manifest_sha256=source_manifest_hashes[split],
                        teacher_identity_sha256=teacher_identity_digest,
                        split=split,
                    )
                    if not valid:
                        errors.append(
                            _issue(
                                "teacher_identity_binding",
                                split,
                                record_id,
                                reason,
                            )
                        )
                    else:
                        receipt_bindings_checked += 1
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
                if not _artifact_shape_valid(field, tuple(array.shape), segments, artifact_dimensions):
                    errors.append(
                        _issue(
                            "artifact_dimension",
                            split,
                            record_id,
                            f"{field} shape {tuple(array.shape)} != "
                            f"{_artifact_shape_description(field, artifact_dimensions)}",
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
    manifest_hashes = {split: _sha256(path) for split, path in manifest_paths.items()}
    manifest_bytes = {split: path.stat().st_size for split, path in manifest_paths.items()}
    reproduction = config_document.get("reproduction", {})
    claim_level = str(reproduction.get("claim_level", "")) if isinstance(reproduction, Mapping) else ""
    if claim_level in {"archival_exact", "paper_specified_reconstruction"}:
        if split_counts != CANONICAL_COUNTS:
            errors.append(
                _issue(
                    "official_split_count_mismatch",
                    "all",
                    None,
                    f"Expected {CANONICAL_COUNTS}, got {split_counts}",
                )
            )
        if split_seen_unseen_counts != CANONICAL_SPLIT_SEEN_UNSEEN_COUNTS:
            errors.append(
                _issue(
                    "official_seen_unseen_count_mismatch",
                    "all",
                    None,
                    f"Expected {CANONICAL_SPLIT_SEEN_UNSEEN_COUNTS}, got {split_seen_unseen_counts}",
                )
            )
    if config is not None and artifact_scan == "full" and resampling_counts["records_missing_evidence"]:
        warnings.append(
            _issue(
                "missing_resampling_evidence",
                "all",
                None,
                f"{resampling_counts['records_missing_evidence']} records lack explicit resampling evidence",
            )
        )
    teacher_checkpoint_sha256 = sorted(
        str(checkpoint.get("sha256"))
        for teacher in teacher_lock_document.get("teachers", {}).values()
        if isinstance(teacher, Mapping)
        for checkpoint in teacher.get("checkpoint_files", [])
        if isinstance(checkpoint, Mapping) and checkpoint.get("sha256")
    )
    cache_root_sha256 = None
    cache_tree = None
    artifact_dir = config_document.get("teacher_export", {}).get("artifact_dir")
    if stage == "exported" and artifact_scan == "full" and artifact_dir:
        cache_root = _resolve(root, artifact_dir)
        if cache_root.is_dir():
            cache_tree = canonical_tree_hash(cache_root)
            cache_root_sha256 = cache_tree["sha256"]
        else:
            errors.append(
                _issue("missing_cache_root", "all", None, f"Teacher cache root is missing: {cache_root}")
            )
    status = "passed" if not errors and not warnings else "failed"
    return {
        "schema_version": 1,
        "status": status,
        "stage": stage,
        "artifact_scan": artifact_scan,
        "path_root": str(root),
        "split_counts": split_counts,
        "canonical_expected_split_counts": CANONICAL_COUNTS,
        "canonical_split_count_matches": {
            split: split_counts[split] == expected for split, expected in CANONICAL_COUNTS.items()
        },
        "canonical_expected_split_seen_unseen_counts": CANONICAL_SPLIT_SEEN_UNSEEN_COUNTS,
        "record_count": sum(split_counts.values()),
        "category_count": len(category_counts),
        "category_counts": dict(sorted(category_counts.items())),
        "seen_classes": len(seen_class_names),
        "unseen_classes": len(unseen_class_names),
        "split_type_counts": dict(sorted(split_type_counts.items())),
        "split_seen_unseen_counts": split_seen_unseen_counts,
        "duplicate_ids": duplicate_ids,
        "split_overlap": split_overlap,
        "label_histogram": {str(key): value for key, value in sorted(label_histogram.items())},
        "segment_length_histogram": {
            str(key): value for key, value in sorted(segment_histogram.items())
        },
        "frame_count_histogram": {
            str(key): value for key, value in sorted(frame_count_histogram.items())
        },
        "manifest_sha256": manifest_hashes,
        "manifest_bytes": manifest_bytes,
        "source_manifest_sha256": manifest_hashes if stage == "source" else None,
        "exported_manifest_sha256": manifest_hashes if stage == "exported" else None,
        "configured_task_segments": configured_task_segments,
        "configured_artifact_dimensions": artifact_dimensions,
        "resampling_performed_by_dataset": resampling_counts["records_with_resampling"] > 0,
        "resampling_evidence": resampling_counts,
        "preprocessing_lock_status": preprocessing_lock_document.get("status"),
        "teacher_lock_status": teacher_lock_document.get("status"),
        "teacher_identity_sha256": teacher_identity_digest,
        "receipt_bindings_checked": receipt_bindings_checked,
        "teacher_checkpoint_sha256": teacher_checkpoint_sha256,
        "cache_root_sha256": cache_root_sha256,
        "cache_tree": cache_tree,
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
        config=args.config,
        preprocessing_lock=args.preprocessing_lock,
        teacher_lock=args.teacher_lock,
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
