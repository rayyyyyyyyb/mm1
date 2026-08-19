from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import numpy as np

from src.utils.atomic_artifacts import (
    artifact_metadata,
    atomic_save_array,
    atomic_write_jsonl,
    canonical_tree_hash,
    sha256_file,
)

from .common import (
    load_records,
    record_id,
    resolve_audio_segments,
    resolve_frame_groups,
    resolve_query,
    safe_record_id,
    segment_count,
    strong_teacher_artifact_paths,
    text_artifact_path,
    weak_teacher_artifact_path,
)


@dataclass
class TeacherExportBundle:
    strong_visual: Any | None = None
    weak_audio: Any | None = None
    text_teacher: Any | None = None


def _as_feature_matrix(array: np.ndarray, expected_rows: int, name: str) -> np.ndarray:
    output = np.asarray(array, dtype=np.float32)
    if output.ndim != 2:
        raise ValueError(f"{name} must be a 2D array, got shape {output.shape}")
    if output.shape[0] != expected_rows:
        raise ValueError(f"{name} row count {output.shape[0]} != expected segment count {expected_rows}")
    return output


def _as_logit_vector(array: np.ndarray, expected_rows: int) -> np.ndarray:
    output = np.asarray(array, dtype=np.float32).reshape(-1)
    if output.shape[0] != expected_rows:
        raise ValueError(f"strong teacher logits length {output.shape[0]} != expected segment count {expected_rows}")
    return output


def _artifact_field_path(artifact_root: Path, metadata: Dict[str, Any]) -> Path:
    relative = Path(str(metadata["path"]))
    if relative.is_absolute():
        raise ValueError(f"Receipt artifact path must be relative: {relative}")
    resolved = (artifact_root / relative).resolve()
    try:
        resolved.relative_to(artifact_root.resolve())
    except ValueError as exc:
        raise ValueError(f"Receipt artifact path escapes cache root: {relative}") from exc
    return resolved


def _validate_receipt(
    receipt: Dict[str, Any],
    *,
    artifact_root: Path,
    source_manifest_sha256: str,
    teacher_lock_sha256: str,
) -> tuple[bool, str]:
    if receipt.get("teacher_lock_sha256") != teacher_lock_sha256:
        return False, "teacher lock hash mismatch"
    if receipt.get("source_manifest_sha256") != source_manifest_sha256:
        return False, "source manifest hash mismatch"
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, dict):
        return False, "missing artifact metadata"
    try:
        for metadata in artifacts.values():
            if not isinstance(metadata, dict):
                return False, "invalid artifact metadata"
            path = _artifact_field_path(artifact_root, metadata)
            if not path.is_file():
                return False, f"missing artifact {path}"
            actual = artifact_metadata(path, relative_to=artifact_root)
            for key in ("path", "bytes", "shape", "sha256"):
                if actual[key] != metadata.get(key):
                    return False, f"artifact {key} mismatch for {path}"
    except (OSError, ValueError) as exc:
        return False, str(exc)
    return True, "ok"


def _apply_receipt_paths(record: Dict[str, Any], receipt: Dict[str, Any], artifact_root: Path) -> None:
    for field_name, metadata in receipt.get("artifacts", {}).items():
        record[f"{field_name}_path"] = str(_artifact_field_path(artifact_root, metadata))


def _receipt_map(path: Path | None) -> Dict[str, Dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    return {str(record["record_id"]): record for record in load_records(path)}


def _preflight_record_paths(records: Sequence[Dict[str, Any]], count: int) -> None:
    owners: Dict[str, str] = {}
    for index in range(count):
        original = record_id(records[index], index)
        sanitized = safe_record_id(original)
        previous = owners.get(sanitized)
        if previous is not None and previous != original:
            raise ValueError(
                f"artifact path collision after record ID sanitization: {previous!r} and {original!r}"
            )
        owners[sanitized] = original


def export_manifest_records(
    records: Sequence[Dict[str, Any]],
    artifact_dir: str | Path,
    output_manifest: str | Path,
    teachers: TeacherExportBundle,
    overwrite: bool = False,
    limit: Optional[int] = None,
    copy_unprocessed_records: bool = False,
    receipt_jsonl: str | Path | None = None,
    error_jsonl: str | Path | None = None,
    source_manifest_sha256: str = "UNSPECIFIED",
    teacher_lock_sha256: str = "UNSPECIFIED",
    split: str = "unknown",
    resume: bool = False,
) -> Dict[str, Any]:
    updated_records: list[Dict[str, Any]] = []
    artifact_root = Path(artifact_dir).resolve()
    output_path = Path(output_manifest)
    partial_path = output_path.with_name(output_path.name + ".partial")
    receipt_path = Path(receipt_jsonl) if receipt_jsonl is not None else None
    error_path = Path(error_jsonl) if error_jsonl is not None else artifact_root / "export_errors.jsonl"

    max_records = len(records) if limit is None else min(len(records), int(limit))
    _preflight_record_paths(records, max_records)
    artifact_root.mkdir(parents=True, exist_ok=True)

    text_cache: Dict[str, np.ndarray] = {}
    records_written = 0
    records_skipped = 0
    records_resumed = 0
    receipts_by_id = _receipt_map(receipt_path)
    published_receipts: list[Dict[str, Any]] = []
    errors: list[Dict[str, Any]] = []

    for index in range(max_records):
        record = deepcopy(records[index])
        record_name = record_id(record, index)
        try:
            existing_receipt = receipts_by_id.get(record_name)
            if resume and existing_receipt is not None:
                valid, reason = _validate_receipt(
                    existing_receipt,
                    artifact_root=artifact_root,
                    source_manifest_sha256=source_manifest_sha256,
                    teacher_lock_sha256=teacher_lock_sha256,
                )
                if not valid:
                    raise RuntimeError(f"stale artifact receipt for {record_name}: {reason}")
                _apply_receipt_paths(record, existing_receipt, artifact_root)
                updated_records.append(record)
                published_receipts.append(existing_receipt)
                records_resumed += 1
                continue

            expected_len = segment_count(record)
            query = resolve_query(record) if (teachers.text_teacher is not None or teachers.strong_visual is not None) else None
            artifacts: Dict[str, Dict[str, Any]] = {}

            if teachers.text_teacher is not None:
                artifact_path = text_artifact_path(artifact_root, record_name).resolve()
                record["text_embedding_path"] = str(artifact_path)
                if artifact_path.exists() and not overwrite:
                    raise RuntimeError(f"artifact exists without a validated receipt: {artifact_path}")
                cached = text_cache.get(query)
                if cached is None:
                    cached = np.asarray(teachers.text_teacher.encode_queries([query])[0], dtype=np.float32)
                    text_cache[query] = cached
                metadata = atomic_save_array(
                    artifact_path,
                    cached,
                    expected_shape=(int(cached.reshape(-1).shape[0]),),
                )
                metadata["path"] = artifact_path.relative_to(artifact_root).as_posix()
                artifacts["text_embedding"] = metadata

            if teachers.strong_visual is not None:
                feature_path, logit_path = strong_teacher_artifact_paths(artifact_root, record_name)
                feature_path = feature_path.resolve()
                logit_path = logit_path.resolve()
                record["strong_teacher_features_path"] = str(feature_path)
                record["strong_teacher_logits_path"] = str(logit_path)
                if not overwrite and (feature_path.exists() or logit_path.exists()):
                    raise RuntimeError("strong artifacts exist without a validated receipt")
                frame_groups = resolve_frame_groups(record, expected_len)
                features, logits = teachers.strong_visual.export_segments(frame_groups=frame_groups, query=query)
                feature_array = _as_feature_matrix(features, expected_len, "strong teacher features")
                logit_array = _as_logit_vector(logits, expected_len)
                feature_metadata = atomic_save_array(feature_path, feature_array, expected_shape=feature_array.shape)
                logit_metadata = atomic_save_array(logit_path, logit_array, expected_shape=(expected_len,))
                feature_metadata["path"] = feature_path.relative_to(artifact_root).as_posix()
                logit_metadata["path"] = logit_path.relative_to(artifact_root).as_posix()
                artifacts["strong_teacher_features"] = feature_metadata
                artifacts["strong_teacher_logits"] = logit_metadata

            if teachers.weak_audio is not None:
                artifact_path = weak_teacher_artifact_path(artifact_root, record_name).resolve()
                record["weak_teacher_features_path"] = str(artifact_path)
                if artifact_path.exists() and not overwrite:
                    raise RuntimeError(f"artifact exists without a validated receipt: {artifact_path}")
                audio_segments = resolve_audio_segments(record, expected_len)
                features = _as_feature_matrix(
                    teachers.weak_audio.export_segments(audio_segments),
                    expected_len,
                    "weak teacher features",
                )
                metadata = atomic_save_array(artifact_path, features, expected_shape=features.shape)
                metadata["path"] = artifact_path.relative_to(artifact_root).as_posix()
                artifacts["weak_teacher_features"] = metadata

            receipt = {
                "record_id": record_name,
                "split": str(split),
                "source_manifest_sha256": source_manifest_sha256,
                "teacher_lock_sha256": teacher_lock_sha256,
                "artifacts": artifacts,
            }
            updated_records.append(record)
            published_receipts.append(receipt)
            records_written += 1
            if receipt_path is not None:
                atomic_write_jsonl(receipt_path, published_receipts)
        except Exception as exc:
            errors.append(
                {
                    "record_id": record_name,
                    "split": str(split),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            atomic_write_jsonl(error_path, errors)
            if partial_path.exists():
                partial_path.unlink()
            raise

    if copy_unprocessed_records:
        for index in range(max_records, len(records)):
            updated_records.append(deepcopy(records[index]))
            records_skipped += 1

    atomic_write_jsonl(partial_path, updated_records)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(partial_path, output_path)
    if receipt_path is not None:
        atomic_write_jsonl(receipt_path, published_receipts)
    tree_hash = canonical_tree_hash(artifact_root)
    return {
        "records_total": len(records),
        "records_exported": records_written,
        "records_copied_without_rewrite": records_skipped,
        "records_resumed": records_resumed,
        "output_manifest": str(output_path.resolve()),
        "artifact_dir": str(artifact_root.resolve()),
        "source_manifest_sha256": source_manifest_sha256,
        "teacher_lock_sha256": teacher_lock_sha256,
        "receipt_jsonl": str(receipt_path.resolve()) if receipt_path is not None else None,
        "cache_root_sha256": tree_hash["sha256"],
        "cache_files": tree_hash["files"],
        "cache_bytes": tree_hash["bytes"],
        "strong_visual_enabled": teachers.strong_visual is not None,
        "weak_audio_enabled": teachers.weak_audio is not None,
        "text_teacher_enabled": teachers.text_teacher is not None,
        "unique_queries_encoded": len(text_cache),
    }


def export_manifest_file(
    source_manifest: str | Path,
    artifact_dir: str | Path,
    output_manifest: str | Path,
    teachers: TeacherExportBundle,
    overwrite: bool = False,
    limit: Optional[int] = None,
    copy_unprocessed_records: bool = False,
    receipt_jsonl: str | Path | None = None,
    error_jsonl: str | Path | None = None,
    teacher_lock_sha256: str = "UNSPECIFIED",
    split: str = "unknown",
    resume: bool = False,
) -> Dict[str, Any]:
    source_path = Path(source_manifest)
    records = load_records(source_path)
    return export_manifest_records(
        records=records,
        artifact_dir=artifact_dir,
        output_manifest=output_manifest,
        teachers=teachers,
        overwrite=overwrite,
        limit=limit,
        copy_unprocessed_records=copy_unprocessed_records,
        receipt_jsonl=receipt_jsonl,
        error_jsonl=error_jsonl,
        source_manifest_sha256=sha256_file(source_path),
        teacher_lock_sha256=teacher_lock_sha256,
        split=split,
        resume=resume,
    )
