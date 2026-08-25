from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import numpy as np

from src.utils.atomic_artifacts import (
    artifact_metadata,
    atomic_save_array,
    atomic_write_jsonl,
    atomic_write_text,
    canonical_tree_hash,
    sha256_file,
)

from .common import (
    canonical_split_name,
    load_records,
    query_sha256,
    record_id,
    resolve_audio_segments,
    resolve_frame_groups,
    resolve_query,
    resolve_raw_video,
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


def export_strong_visual_teacher(
    teacher: Any,
    record: Dict[str, Any],
    *,
    expected_segments: int,
    query: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Dispatch using the teacher's declared input protocol, never method presence."""

    input_mode = getattr(teacher, "input_mode", None)
    if input_mode == "raw_multiframe_diagnostic":
        return teacher.export_video(
            video_path=resolve_raw_video(record),
            query=query,
        )
    if input_mode in {"official_segment_keyframes", "segment_groups"}:
        return teacher.export_segments(
            frame_groups=resolve_frame_groups(record, expected_segments),
            query=query,
        )
    raise ValueError(
        "Strong visual teacher must declare input_mode as "
        "official_segment_keyframes, raw_multiframe_diagnostic, or segment_groups"
    )


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


def _atomic_write_json(path: Path, value: Dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


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
    teacher_identity_sha256: str,
    split: str,
) -> tuple[bool, str]:
    if receipt.get("split") != split:
        return False, "split mismatch"
    if receipt.get("schema_version") != 3:
        return False, "receipt schema mismatch"
    if receipt.get("teacher_identity_sha256") != teacher_identity_sha256:
        return False, "teacher identity hash mismatch"
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


def _record_receipt_path(artifact_root: Path, split: str, record_name: str) -> Path:
    return artifact_root / "receipts" / split / f"{safe_record_id(record_name)}.json"


def _error_receipt_path(artifact_root: Path, split: str, record_name: str) -> Path:
    return artifact_root / "errors" / split / f"{safe_record_id(record_name)}.json"


def _remove_orphan_record_artifacts(
    *,
    artifact_root: Path,
    split: str,
    record_name: str,
    teachers: TeacherExportBundle,
) -> None:
    """Discard unreceipted per-record outputs before a resumable recomputation."""

    paths: list[Path] = []
    if teachers.strong_visual is not None:
        paths.extend(strong_teacher_artifact_paths(artifact_root, record_name, split=split))
    if teachers.weak_audio is not None:
        paths.append(weak_teacher_artifact_path(artifact_root, record_name, split=split))
    for path in paths:
        path.resolve().unlink(missing_ok=True)


def _receipt_map(receipt_dir: Path) -> Dict[str, Dict[str, Any]]:
    if not receipt_dir.exists():
        return {}
    receipts: Dict[str, Dict[str, Any]] = {}
    for path in sorted(receipt_dir.glob("*.json"), key=lambda item: item.name):
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not value.get("record_id"):
            raise ValueError(f"Invalid per-record receipt: {path}")
        record_name = str(value["record_id"])
        if record_name in receipts:
            raise ValueError(f"Duplicate per-record receipt for {record_name}")
        receipts[record_name] = value
    return receipts


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


def _shared_text_artifact(
    *,
    artifact_root: Path,
    query: str,
    teacher: Any,
    teacher_identity_sha256: str,
    overwrite: bool,
) -> tuple[Path, Dict[str, Any], bool]:
    query_hash = query_sha256(query)
    artifact_path = text_artifact_path(artifact_root, query).resolve()
    binding_path = artifact_path.with_suffix(".json")
    if artifact_path.exists() and binding_path.exists() and not overwrite:
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
        if (
            binding.get("query") != query
            or binding.get("query_sha256") != query_hash
            or binding.get("teacher_identity_sha256") != teacher_identity_sha256
        ):
            raise RuntimeError(f"stale shared text artifact binding: {artifact_path}")
        actual = artifact_metadata(artifact_path, relative_to=artifact_root)
        if any(actual[key] != binding.get("artifact", {}).get(key) for key in actual):
            raise RuntimeError(f"shared text artifact metadata mismatch: {artifact_path}")
        return artifact_path, actual, False
    if (artifact_path.exists() or binding_path.exists()) and not overwrite:
        raise RuntimeError(f"incomplete shared text artifact binding: {artifact_path}")

    embedding = np.asarray(teacher.encode_queries([query])[0], dtype=np.float32).reshape(-1)
    metadata = atomic_save_array(artifact_path, embedding, expected_shape=(int(embedding.shape[0]),))
    metadata["path"] = artifact_path.relative_to(artifact_root).as_posix()
    _atomic_write_json(
        binding_path,
        {
            "schema_version": 2,
            "query": query,
            "query_sha256": query_hash,
            "teacher_identity_sha256": teacher_identity_sha256,
            "artifact": metadata,
        },
    )
    return artifact_path, metadata, True


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
    teacher_identity_sha256: str = "UNSPECIFIED",
    split: str = "unknown",
    resume: bool = False,
    progress_path: str | Path | None = None,
) -> Dict[str, Any]:
    canonical_split = canonical_split_name(split)
    updated_records: list[Dict[str, Any]] = []
    artifact_root = Path(artifact_dir).resolve()
    output_path = Path(output_manifest)
    partial_path = output_path.with_name(output_path.name + ".partial")
    aggregate_receipt_path = Path(receipt_jsonl) if receipt_jsonl is not None else None
    aggregate_error_path = Path(error_jsonl) if error_jsonl is not None else None
    receipt_dir = artifact_root / "receipts" / canonical_split
    progress_output = Path(progress_path).resolve() if progress_path is not None else None

    max_records = len(records) if limit is None else min(len(records), int(limit))
    _preflight_record_paths(records, max_records)
    artifact_root.mkdir(parents=True, exist_ok=True)

    text_cache: Dict[str, tuple[Path, Dict[str, Any]]] = {}
    queries_encoded = 0
    records_written = 0
    records_skipped = 0
    records_resumed = 0
    receipts_by_id = _receipt_map(receipt_dir)
    published_receipts: list[Dict[str, Any]] = []
    started_at = datetime.now(timezone.utc).isoformat()

    def write_progress(
        *, status: str, current_record_id: str | None, current_index: int | None
    ) -> None:
        if progress_output is None:
            return
        _atomic_write_json(
            progress_output,
            {
                "schema_version": 1,
                "status": status,
                "split": canonical_split,
                "started_at": started_at,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "current_record_id": current_record_id,
                "current_index": current_index,
                "completed": records_written + records_resumed,
                "total": max_records,
            },
        )

    write_progress(status="running", current_record_id=None, current_index=None)

    for index in range(max_records):
        record = deepcopy(records[index])
        record_name = record_id(record, index)
        write_progress(status="running", current_record_id=record_name, current_index=index)
        try:
            existing_receipt = receipts_by_id.get(record_name)
            if resume and existing_receipt is not None:
                valid, reason = _validate_receipt(
                    existing_receipt,
                    artifact_root=artifact_root,
                    source_manifest_sha256=source_manifest_sha256,
                    teacher_identity_sha256=teacher_identity_sha256,
                    split=canonical_split,
                )
                if not valid:
                    raise RuntimeError(f"stale artifact receipt for {record_name}: {reason}")
                _apply_receipt_paths(record, existing_receipt, artifact_root)
                _error_receipt_path(
                    artifact_root, canonical_split, record_name
                ).unlink(missing_ok=True)
                updated_records.append(record)
                published_receipts.append(existing_receipt)
                records_resumed += 1
                write_progress(status="running", current_record_id=record_name, current_index=index)
                continue
            if existing_receipt is not None and not overwrite:
                raise RuntimeError(f"artifact receipt exists but resume is disabled: {record_name}")
            if resume and existing_receipt is None:
                _remove_orphan_record_artifacts(
                    artifact_root=artifact_root,
                    split=canonical_split,
                    record_name=record_name,
                    teachers=teachers,
                )

            expected_len = segment_count(record)
            query = resolve_query(record) if (teachers.text_teacher is not None or teachers.strong_visual is not None) else None
            artifacts: Dict[str, Dict[str, Any]] = {}

            if teachers.text_teacher is not None:
                assert query is not None
                cached = text_cache.get(query)
                if cached is None:
                    artifact_path, metadata, encoded = _shared_text_artifact(
                        artifact_root=artifact_root,
                        query=query,
                        teacher=teachers.text_teacher,
                        teacher_identity_sha256=teacher_identity_sha256,
                        overwrite=overwrite,
                    )
                    cached = (artifact_path, metadata)
                    text_cache[query] = cached
                    queries_encoded += int(encoded)
                artifact_path, metadata = cached
                record["text_embedding_path"] = str(artifact_path)
                artifacts["text_embedding"] = metadata

            if teachers.strong_visual is not None:
                feature_path, logit_path = strong_teacher_artifact_paths(
                    artifact_root, record_name, split=canonical_split
                )
                feature_path = feature_path.resolve()
                logit_path = logit_path.resolve()
                record["strong_teacher_features_path"] = str(feature_path)
                record["strong_teacher_logits_path"] = str(logit_path)
                if not overwrite and (feature_path.exists() or logit_path.exists()):
                    raise RuntimeError("strong artifacts exist without a validated receipt")
                features, logits = export_strong_visual_teacher(
                    teachers.strong_visual,
                    record,
                    expected_segments=expected_len,
                    query=query,
                )
                feature_array = _as_feature_matrix(features, expected_len, "strong teacher features")
                logit_array = _as_logit_vector(logits, expected_len)
                feature_metadata = atomic_save_array(feature_path, feature_array, expected_shape=feature_array.shape)
                logit_metadata = atomic_save_array(logit_path, logit_array, expected_shape=(expected_len,))
                feature_metadata["path"] = feature_path.relative_to(artifact_root).as_posix()
                logit_metadata["path"] = logit_path.relative_to(artifact_root).as_posix()
                artifacts["strong_teacher_features"] = feature_metadata
                artifacts["strong_teacher_logits"] = logit_metadata

            if teachers.weak_audio is not None:
                artifact_path = weak_teacher_artifact_path(
                    artifact_root, record_name, split=canonical_split
                ).resolve()
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
                "schema_version": 3,
                "record_id": record_name,
                "split": canonical_split,
                "query": query,
                "query_sha256": query_sha256(query) if query is not None else None,
                "source_manifest_sha256": source_manifest_sha256,
                "teacher_identity_sha256": teacher_identity_sha256,
                "artifacts": artifacts,
            }
            _atomic_write_json(_record_receipt_path(artifact_root, canonical_split, record_name), receipt)
            _error_receipt_path(
                artifact_root, canonical_split, record_name
            ).unlink(missing_ok=True)
            updated_records.append(record)
            published_receipts.append(receipt)
            records_written += 1
            write_progress(status="running", current_record_id=record_name, current_index=index)
        except Exception as exc:
            error = {
                "schema_version": 1,
                "record_id": record_name,
                "split": canonical_split,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            _atomic_write_json(_error_receipt_path(artifact_root, canonical_split, record_name), error)
            if aggregate_error_path is not None:
                atomic_write_jsonl(aggregate_error_path, [error])
            if partial_path.exists():
                partial_path.unlink()
            write_progress(status="failed", current_record_id=record_name, current_index=index)
            raise

    if copy_unprocessed_records:
        for index in range(max_records, len(records)):
            updated_records.append(deepcopy(records[index]))
            records_skipped += 1

    atomic_write_jsonl(partial_path, updated_records)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(partial_path, output_path)
    if aggregate_receipt_path is not None:
        atomic_write_jsonl(aggregate_receipt_path, published_receipts)
    if aggregate_error_path is not None:
        atomic_write_jsonl(aggregate_error_path, [])
    write_progress(status="completed", current_record_id=None, current_index=None)
    tree_hash = canonical_tree_hash(artifact_root)
    return {
        "records_total": len(records),
        "records_exported": records_written,
        "records_copied_without_rewrite": records_skipped,
        "records_resumed": records_resumed,
        "output_manifest": str(output_path.resolve()),
        "artifact_dir": str(artifact_root),
        "source_manifest_sha256": source_manifest_sha256,
        "teacher_identity_sha256": teacher_identity_sha256,
        "receipt_dir": str(receipt_dir.resolve()),
        "receipt_jsonl": str(aggregate_receipt_path.resolve()) if aggregate_receipt_path is not None else None,
        "cache_root_sha256": tree_hash["sha256"],
        "cache_files": tree_hash["files"],
        "cache_bytes": tree_hash["bytes"],
        "strong_visual_enabled": teachers.strong_visual is not None,
        "weak_audio_enabled": teachers.weak_audio is not None,
        "text_teacher_enabled": teachers.text_teacher is not None,
        "unique_queries_encoded": queries_encoded,
        "unique_queries_referenced": len(text_cache),
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
    teacher_identity_sha256: str = "UNSPECIFIED",
    split: str = "unknown",
    resume: bool = False,
    progress_path: str | Path | None = None,
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
        teacher_identity_sha256=teacher_identity_sha256,
        split=split,
        resume=resume,
        progress_path=progress_path,
    )
