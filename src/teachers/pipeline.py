from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import numpy as np

from .common import (
    load_records,
    record_id,
    resolve_audio_segments,
    resolve_frame_groups,
    resolve_query,
    save_array,
    segment_count,
    strong_teacher_artifact_paths,
    text_artifact_path,
    weak_teacher_artifact_path,
    write_records,
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


def export_manifest_records(
    records: Sequence[Dict[str, Any]],
    artifact_dir: str | Path,
    output_manifest: str | Path,
    teachers: TeacherExportBundle,
    overwrite: bool = False,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    updated_records = []
    artifact_root = Path(artifact_dir)
    artifact_root.mkdir(parents=True, exist_ok=True)

    text_cache: Dict[str, np.ndarray] = {}
    records_written = 0
    records_skipped = 0

    max_records = len(records) if limit is None else min(len(records), int(limit))
    for index in range(max_records):
        record = deepcopy(records[index])
        record_name = record_id(record, index)
        expected_len = segment_count(record)

        query = resolve_query(record) if (teachers.text_teacher is not None or teachers.strong_visual is not None) else None

        if teachers.text_teacher is not None:
            output_path = text_artifact_path(artifact_root, record_name)
            record["text_embedding_path"] = str(output_path)
            if overwrite or not output_path.exists():
                cached = text_cache.get(query)
                if cached is None:
                    cached = np.asarray(teachers.text_teacher.encode_queries([query])[0], dtype=np.float32)
                    text_cache[query] = cached
                save_array(output_path, cached)

        if teachers.strong_visual is not None:
            feature_path, logit_path = strong_teacher_artifact_paths(artifact_root, record_name)
            record["strong_teacher_features_path"] = str(feature_path)
            record["strong_teacher_logits_path"] = str(logit_path)
            if overwrite or not feature_path.exists() or not logit_path.exists():
                frame_groups = resolve_frame_groups(record, expected_len)
                features, logits = teachers.strong_visual.export_segments(frame_groups=frame_groups, query=query)
                save_array(feature_path, _as_feature_matrix(features, expected_len, "strong teacher features"))
                save_array(logit_path, _as_logit_vector(logits, expected_len))

        if teachers.weak_audio is not None:
            output_path = weak_teacher_artifact_path(artifact_root, record_name)
            record["weak_teacher_features_path"] = str(output_path)
            if overwrite or not output_path.exists():
                audio_segments = resolve_audio_segments(record, expected_len)
                features = teachers.weak_audio.export_segments(audio_segments)
                save_array(output_path, _as_feature_matrix(features, expected_len, "weak teacher features"))

        updated_records.append(record)
        records_written += 1

    for index in range(max_records, len(records)):
        updated_records.append(deepcopy(records[index]))
        records_skipped += 1

    write_records(output_manifest, updated_records)
    return {
        "records_total": len(records),
        "records_exported": records_written,
        "records_copied_without_rewrite": records_skipped,
        "output_manifest": str(Path(output_manifest).resolve()),
        "artifact_dir": str(artifact_root.resolve()),
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
) -> Dict[str, Any]:
    records = load_records(source_manifest)
    return export_manifest_records(
        records=records,
        artifact_dir=artifact_dir,
        output_manifest=output_manifest,
        teachers=teachers,
        overwrite=overwrite,
        limit=limit,
    )
