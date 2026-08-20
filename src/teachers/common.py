from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Sequence

import numpy as np

from src.utils.atomic_artifacts import atomic_save_array, atomic_write_jsonl


@dataclass(frozen=True)
class AudioSegmentSpec:
    path: str
    start_time: float | None = None
    end_time: float | None = None
    sample_rate: int | None = None


class AttrDict(dict):
    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


def to_attr_dict(value: Any) -> Any:
    if isinstance(value, dict):
        return AttrDict({key: to_attr_dict(item) for key, item in value.items()})
    if isinstance(value, list):
        return [to_attr_dict(item) for item in value]
    return value


def load_records(path_str: str | Path) -> List[Dict[str, Any]]:
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"Expected a JSON list in {path}")
        return data

    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_no}") from exc
    return records


def write_records(path_str: str | Path, records: Sequence[Dict[str, Any]]) -> None:
    atomic_write_jsonl(path_str, records)


def save_array(path_str: str | Path, array: np.ndarray) -> None:
    normalized = np.asarray(array, dtype=np.float32)
    atomic_save_array(path_str, normalized, expected_shape=normalized.shape)


def ensure_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def iter_batches(items: Sequence[Any], batch_size: int) -> Iterator[Sequence[Any]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


def record_id(record: Dict[str, Any], fallback_index: int) -> str:
    value = record.get("id")
    if value is None:
        return f"sample_{fallback_index:06d}"
    return str(value)


def safe_record_id(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return sanitized or "sample"


def resolve_query(record: Dict[str, Any]) -> str:
    query = record.get("query") or record.get("text_query")
    if not query:
        raise ValueError("Each record must contain `query` or `text_query` for teacher export.")
    return str(query)


def segment_count(record: Dict[str, Any]) -> int:
    labels = record.get("segment_labels")
    if labels is None:
        raise ValueError("Each record must contain `segment_labels`.")
    count = int(np.asarray(labels).reshape(-1).shape[0])
    if count <= 0:
        raise ValueError("`segment_labels` cannot be empty.")
    return count


def _normalize_group_item(item: Any) -> List[str]:
    if isinstance(item, (list, tuple)):
        values = [str(value) for value in item if value]
    elif item:
        values = [str(item)]
    else:
        values = []
    if not values:
        raise ValueError("Segment group cannot be empty.")
    return values


def _resolve_grouped_paths(record: Dict[str, Any], field_names: Sequence[str], expected_len: int) -> List[List[str]]:
    for field_name in field_names:
        value = record.get(field_name)
        if value is None:
            continue
        groups = [_normalize_group_item(item) for item in ensure_list(value)]
        if len(groups) != expected_len:
            raise ValueError(f"`{field_name}` length {len(groups)} != expected segment count {expected_len}.")
        return groups
    raise ValueError(f"Missing any of the required grouped fields: {', '.join(field_names)}")


def resolve_frame_groups(record: Dict[str, Any], expected_len: int) -> List[List[str]]:
    return _resolve_grouped_paths(
        record=record,
        field_names=("segment_frame_paths", "frame_groups", "frame_paths", "frames"),
        expected_len=expected_len,
    )


def resolve_raw_video(record: Dict[str, Any]) -> Path:
    for field_name in ("raw_video_path", "official_video_path", "video_path"):
        value = record.get(field_name)
        if value:
            return Path(str(value)).expanduser().resolve()
    raise ValueError(
        "Each record must contain a raw video path in `raw_video_path`, "
        "`official_video_path`, or `video_path`; PNG fallback is forbidden."
    )


def resolve_audio_segments(record: Dict[str, Any], expected_len: int) -> List[AudioSegmentSpec]:
    direct_fields = (
        "audio_segment_paths",
        "audio_paths",
        "audio_waveform_paths",
        "waveform_paths",
    )
    sample_rate_list = ensure_list(record.get("audio_segment_sample_rates") or record.get("audio_sample_rates"))
    default_sample_rate = record.get("audio_sample_rate")

    for field_name in direct_fields:
        value = record.get(field_name)
        if value is None:
            continue
        items = ensure_list(value)
        if len(items) != expected_len:
            raise ValueError(f"`{field_name}` length {len(items)} != expected segment count {expected_len}.")
        specs: List[AudioSegmentSpec] = []
        for idx, item in enumerate(items):
            if isinstance(item, dict):
                path = item.get("path")
                start_time = item.get("start_time")
                end_time = item.get("end_time")
                sample_rate = item.get("sample_rate")
            else:
                path = item
                start_time = None
                end_time = None
                sample_rate = None
            if not path:
                raise ValueError(f"Audio segment path at index {idx} is empty.")
            if len(sample_rate_list) == expected_len:
                sample_rate = sample_rate_list[idx]
            elif sample_rate is None:
                sample_rate = default_sample_rate
            specs.append(
                AudioSegmentSpec(
                    path=str(path),
                    start_time=float(start_time) if start_time is not None else None,
                    end_time=float(end_time) if end_time is not None else None,
                    sample_rate=int(sample_rate) if sample_rate is not None else None,
                )
            )
        return specs

    clip_audio_path = record.get("audio_path") or record.get("waveform_path")
    timestamps = record.get("segment_timestamps") or record.get("timestamps")
    if clip_audio_path and timestamps is not None:
        items = ensure_list(timestamps)
        if len(items) != expected_len:
            raise ValueError(f"`segment_timestamps` length {len(items)} != expected segment count {expected_len}.")
        specs = []
        for idx, item in enumerate(items):
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise ValueError(f"Timestamp at index {idx} must be a [start, end] pair.")
            start_time, end_time = float(item[0]), float(item[1])
            if end_time <= start_time:
                raise ValueError(f"Invalid timestamp pair at index {idx}: {item}")
            sample_rate = sample_rate_list[idx] if len(sample_rate_list) == expected_len else default_sample_rate
            specs.append(
                AudioSegmentSpec(
                    path=str(clip_audio_path),
                    start_time=start_time,
                    end_time=end_time,
                    sample_rate=int(sample_rate) if sample_rate is not None else None,
                )
            )
        return specs

    raise ValueError(
        "Missing audio source fields. Expected one of "
        "`audio_segment_paths`, `audio_paths`, `audio_waveform_paths`, `waveform_paths`, "
        "or `audio_path` + `segment_timestamps`."
    )


def canonical_split_name(split: str) -> str:
    canonical = str(split).strip().lower()
    if canonical not in {"train", "val", "test"}:
        raise ValueError(f"Unsupported split: {split!r}")
    return canonical


def record_artifact_dir(artifact_root: str | Path, split: str, record_name: str) -> Path:
    return Path(artifact_root) / canonical_split_name(split) / safe_record_id(record_name)


def strong_teacher_artifact_paths(
    artifact_dir: str | Path,
    record_name: str,
    *,
    split: str,
) -> tuple[Path, Path]:
    base = record_artifact_dir(artifact_dir, split, record_name)
    return base / "strong_teacher_features.npy", base / "strong_teacher_logits.npy"


def weak_teacher_artifact_path(artifact_dir: str | Path, record_name: str, *, split: str) -> Path:
    return record_artifact_dir(artifact_dir, split, record_name) / "weak_teacher_features.npy"


def query_sha256(query: str) -> str:
    return hashlib.sha256(str(query).encode("utf-8")).hexdigest()


def text_artifact_path(artifact_dir: str | Path, query: str) -> Path:
    return Path(artifact_dir) / "text_by_query" / f"{query_sha256(query)}.npy"


def verify_checkpoint_sha256(
    checkpoint_path: str | Path,
    expected_sha256: str,
    *,
    label: str,
) -> dict[str, Any]:
    path = Path(checkpoint_path).expanduser().resolve()
    expected = str(expected_sha256).strip()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError(f"{label} checkpoint SHA256 must be 64 lowercase hex characters")
    if not path.is_file():
        raise FileNotFoundError(f"{label} checkpoint not found: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected:
        raise RuntimeError(
            f"{label} checkpoint SHA256 mismatch: expected {expected}, actual {actual}"
        )
    return {"bytes": path.stat().st_size, "sha256": actual}
