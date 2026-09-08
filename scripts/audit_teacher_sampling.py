"""Read-only audit of the diagnostic raw-video sampling prerequisites."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.teacher_signal_probe import (
    build_common_space,
    build_interaction_design,
    fit_probe_and_score,
    score_signal_metrics,
)

RAW_VIDEO_SUFFIXES = frozenset({".avi", ".mkv", ".mov", ".mp4", ".webm"})


class RawVideoUnavailable(RuntimeError):
    """Raised when a record cannot provide a usable official raw video."""


def _safe_metric(labels: np.ndarray, scores: np.ndarray, kind: str) -> float | None:
    if labels.size == 0 or np.unique(labels).size < 2:
        return None
    if kind == "ap":
        from sklearn.metrics import average_precision_score

        return float(average_precision_score(labels, scores))
    if kind == "auroc":
        from sklearn.metrics import roc_auc_score

        return float(roc_auc_score(labels, scores))
    raise ValueError(f"unsupported metric kind: {kind}")


def _tie_aware_concordance(scores: np.ndarray, labels: np.ndarray) -> float | None:
    positives = scores[labels > 0]
    negatives = scores[labels <= 0]
    if positives.size == 0 or negatives.size == 0:
        return None
    pair = positives[:, None] - negatives[None, :]
    return float((pair > 0).mean() + 0.5 * (pair == 0).mean())


def compare_sampling_receipts(
    repeat_features: np.ndarray,
    multiframe_features: np.ndarray,
    labels: np.ndarray,
    queries: np.ndarray,
    offsets: np.ndarray,
    *,
    repeat_logits: np.ndarray | None = None,
    multiframe_logits: np.ndarray | None = None,
    sample_ids: np.ndarray | None = None,
    query_ids: np.ndarray | None = None,
    probe_train_features: np.ndarray | None = None,
    probe_train_labels: np.ndarray | None = None,
    probe_train_queries: np.ndarray | None = None,
    probe_train_ids: np.ndarray | None = None,
    source_hashes: Mapping[str, Any] | None = None,
    seed: int = 42,
    shuffle_repeats: int = 100,
) -> dict[str, Any]:
    """Compare encoded repeat-keyframe and true-uniform-8-frame receipts.

    This function never fits on the selected validation rows.  If a separate
    canonical train receipt is supplied, it fits the same label-independent
    interaction probe on that train split and evaluates both sampling paths.
    """

    repeat = np.asarray(repeat_features, dtype=np.float32)
    multi = np.asarray(multiframe_features, dtype=np.float32)
    label_array = np.asarray(labels, dtype=np.int64)
    query_array = np.asarray(queries, dtype=np.float32)
    offset_array = np.asarray(offsets, dtype=np.int64)
    if repeat.ndim != 3 or multi.shape != repeat.shape:
        raise ValueError("repeat and multiframe features must have identical [B,10,D] shapes")
    if repeat.shape[1] != 10 or label_array.shape != repeat.shape[:2]:
        raise ValueError("sampling comparison is locked to labels with shape [B,10]")
    if query_array.shape[0] != repeat.shape[0] or query_array.ndim not in (2, 3):
        raise ValueError("queries/offsets do not match the selected [B,10] records")
    if query_array.ndim == 2:
        query_array = np.broadcast_to(
            query_array[:, None, :], (repeat.shape[0], 10, query_array.shape[1])
        ).copy()
    if offset_array.tolist() != list(range(0, repeat.shape[0] * 10 + 1, 10)):
        raise ValueError("queries/offsets do not match the selected [B,10] records")
    if not (np.isfinite(repeat).all() and np.isfinite(multi).all()):
        raise ValueError("sampling feature receipts contain NaN/Inf")

    repeat_norm = np.linalg.norm(repeat.astype(np.float64), axis=-1)
    multi_norm = np.linalg.norm(multi.astype(np.float64), axis=-1)
    denominator = np.maximum(repeat_norm * multi_norm, 1e-12)
    cosine = np.sum(repeat.astype(np.float64) * multi.astype(np.float64), axis=-1) / denominator
    selected_ids = (
        np.asarray(sample_ids).reshape(-1).astype(str)
        if sample_ids is not None
        else np.asarray([f"sampling-{index}" for index in range(repeat.shape[0])])
    )
    selected_query_ids = (
        np.asarray(query_ids).reshape(-1).astype(str)
        if query_ids is not None
        else selected_ids.copy()
    )
    if selected_ids.size != repeat.shape[0] or selected_query_ids.size != repeat.shape[0]:
        raise ValueError("sample_ids/query_ids must have one value per selected record")
    result: dict[str, Any] = {
        "protocol": {
            "task_segments": 10,
            "frame_count": 8,
            "repeat_policy": "canonical_single_keyframe_repeated_8",
            "multiframe_policy": "uniform_center_within_each_one_second_segment",
            "probe_fit": "separate_train_split_only",
        },
        "shape": {"repeat_features": list(repeat.shape), "multiframe_features": list(multi.shape), "labels": list(label_array.shape)},
        "geometry": {
            "mean_cosine": float(cosine.mean()),
            "mean_absolute_feature_delta": float(np.abs(repeat.astype(np.float64) - multi.astype(np.float64)).mean()),
            "source_hashes": dict(source_hashes or {}),
        },
        "feature_temporal_statistics": {
            "repeat_keyframe": _feature_temporal_statistics(repeat),
            "uniform_8": _feature_temporal_statistics(multi),
        },
    }
    if repeat_logits is not None or multiframe_logits is not None:
        if repeat_logits is None or multiframe_logits is None:
            raise ValueError("repeat_logits and multiframe_logits must be supplied together")
        repeat_score = np.asarray(repeat_logits, dtype=np.float64)
        multi_score = np.asarray(multiframe_logits, dtype=np.float64)
        if repeat_score.shape != label_array.shape or multi_score.shape != label_array.shape:
            raise ValueError("sampling logits must have shape [B,10]")
        result["direct_logits"] = {
            "repeat_keyframe": score_signal_metrics(
                repeat_score,
                label_array,
                np.ones_like(label_array, dtype=bool),
                sample_ids=selected_ids,
                query_ids=selected_query_ids,
                offsets=offset_array,
                shuffle_repeats=shuffle_repeats,
                seed=seed,
            ),
            "uniform_8": score_signal_metrics(
                multi_score,
                label_array,
                np.ones_like(label_array, dtype=bool),
                sample_ids=selected_ids,
                query_ids=selected_query_ids,
                offsets=offset_array,
                shuffle_repeats=shuffle_repeats,
                seed=seed,
            ),
        }
    else:
        result["direct_logits"] = None
    if (
        probe_train_features is None
        or probe_train_labels is None
        or probe_train_queries is None
    ):
        result["query_conditioned_feature_probe"] = None
        result["probe_status"] = "TRAIN_PROBE_RECEIPT_REQUIRED"
    else:
        train_visual = np.asarray(probe_train_features, dtype=np.float32)
        train_labels = np.asarray(probe_train_labels, dtype=np.int64)
        train_query = np.asarray(probe_train_queries, dtype=np.float32)
        if train_visual.ndim != 3 or train_labels.shape != train_visual.shape[:2]:
            raise ValueError("probe_train_features/labels must align as [N,10,D]/[N,10]")
        if train_query.ndim == 2:
            train_query = np.broadcast_to(
                train_query[:, None, :],
                (train_visual.shape[0], 10, train_query.shape[1]),
            ).copy()
        if train_query.ndim != 3 or train_query.shape[:2] != train_visual.shape[:2]:
            raise ValueError("probe_train_queries must align as [N,10,Q] or [N,Q]")
        if probe_train_ids is not None:
            train_ids = np.asarray(probe_train_ids).reshape(-1).astype(str)
            if train_ids.size != train_visual.shape[0]:
                raise ValueError("probe_train_ids must have one value per train record")
            if set(train_ids).intersection(selected_ids.tolist()):
                raise ValueError("probe train and selected validation IDs overlap")
        common_train, query_common_train, common_receipt = build_common_space(
            train_visual, train_query, output_dim=128, seed=seed
        )
        common_repeat, query_common_repeat, _ = build_common_space(
            repeat, query_array, output_dim=128, seed=seed
        )
        common_multi, query_common_multi, _ = build_common_space(
            multi, query_array, output_dim=128, seed=seed
        )
        train_design = build_interaction_design(
            common_train, query_common_train, mode="interaction"
        )
        train_ids = (
            np.asarray(probe_train_ids).reshape(-1).astype(str)
            if probe_train_ids is not None
            else np.asarray([f"probe-train-{index}" for index in range(train_visual.shape[0])])
        )
        probe_repeat = fit_probe_and_score(
            train_design,
            train_labels,
            build_interaction_design(common_repeat, query_common_repeat, mode="interaction"),
            label_array,
            np.ones_like(label_array, dtype=bool),
            sample_ids=selected_ids,
            query_ids=selected_query_ids,
            offsets=offset_array,
            seed=seed,
            shuffle_repeats=shuffle_repeats,
        )
        probe_multi = fit_probe_and_score(
            train_design,
            train_labels,
            build_interaction_design(common_multi, query_common_multi, mode="interaction"),
            label_array,
            np.ones_like(label_array, dtype=bool),
            sample_ids=selected_ids,
            query_ids=selected_query_ids,
            offsets=offset_array,
            seed=seed,
            shuffle_repeats=shuffle_repeats,
        )
        result["query_conditioned_feature_probe"] = {
            "fit_source": "canonical_train_teacher_features",
            "common_space": common_receipt,
            "repeat_keyframe": probe_repeat,
            "uniform_8": probe_multi,
        }
        result["probe_status"] = "PASS"
    return result


def _feature_temporal_statistics(features: np.ndarray) -> dict[str, float]:
    array = np.asarray(features, dtype=np.float64)
    centered = array - array.mean(axis=1, keepdims=True)
    return {
        "raw_temporal_std_mean": float(array.std(axis=1, ddof=0).mean()),
        "centered_temporal_rms": float(np.sqrt(np.mean(np.square(centered)))),
        "centered_row_l2_mean": float(np.linalg.norm(centered, axis=-1).mean()),
    }


def _labels(record: Mapping[str, Any]) -> np.ndarray:
    labels = np.asarray(record.get("segment_labels"), dtype=np.int64)
    if labels.shape != (10,) or not np.isin(labels, (0, 1)).all():
        raise ValueError(f"{record.get('id', '<unknown>')}: expected binary labels [10]")
    return labels


def select_stratified_mixed_records(
    manifest: Sequence[Mapping[str, Any]] | str | Path,
    count: int,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Select deterministic mixed-label records, round-robin over positive counts."""

    if isinstance(manifest, (str, Path)):
        records = [
            json.loads(line)
            for line in Path(manifest).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    else:
        records = [dict(record) for record in manifest]
    if count <= 0:
        raise ValueError("count must be positive")
    groups: dict[int, list[dict[str, Any]]] = {}
    for record in records:
        labels = _labels(record)
        positive_count = int(labels.sum())
        if 0 < positive_count < 10:
            groups.setdefault(positive_count, []).append(dict(record))
    if sum(len(rows) for rows in groups.values()) < count:
        raise ValueError(f"requested {count} mixed records but only {sum(map(len, groups.values()))} exist")
    rng = np.random.default_rng(int(seed))
    for positive_count in sorted(groups):
        rows = groups[positive_count]
        order = rng.permutation(len(rows))
        groups[positive_count] = [rows[int(index)] for index in order]
    selected: list[dict[str, Any]] = []
    cursors = {key: 0 for key in groups}
    keys = sorted(groups)
    while len(selected) < count:
        progressed = False
        for key in keys:
            cursor = cursors[key]
            if cursor >= len(groups[key]):
                continue
            selected.append(groups[key][cursor])
            cursors[key] = cursor + 1
            progressed = True
            if len(selected) == count:
                break
        if not progressed:
            raise RuntimeError("stratified selector exhausted unexpectedly")
    return selected


def segment_time_bounds(
    segment_index: int,
    *,
    task_segments: int = 10,
    duration_seconds: float = 10.0,
) -> tuple[float, float]:
    if task_segments != 10 or duration_seconds != 10.0:
        raise ValueError("OV-AVEBench sampling is locked to ten one-second segments")
    if not 0 <= int(segment_index) < task_segments:
        raise ValueError(f"segment_index must be in [0,{task_segments})")
    start = float(segment_index)
    return start, start + 1.0


def sample_segment_timestamps(segment_index: int, frame_count: int) -> np.ndarray:
    """Return frame-center timestamps strictly inside one official second."""

    if frame_count <= 0:
        raise ValueError("frame_count must be positive")
    start, end = segment_time_bounds(segment_index)
    step = (end - start) / float(frame_count)
    return np.linspace(start + step / 2.0, end - step / 2.0, frame_count, dtype=np.float64)


def validate_raw_video(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_file() or candidate.stat().st_size <= 0:
        raise RawVideoUnavailable(f"missing or empty raw video: {candidate}")
    if candidate.suffix.lower() not in RAW_VIDEO_SUFFIXES:
        raise RawVideoUnavailable(f"raw input is not a supported video file: {candidate}")
    return candidate.resolve()


def sample_segment_frames(
    video_path: str | Path,
    segment_index: int,
    frame_count: int,
    policy: str = "uniform_center",
) -> tuple[np.ndarray, np.ndarray]:
    """Decode true multiframe inputs without falling back to keyframe JPGs."""

    path = validate_raw_video(video_path)
    if policy != "uniform_center":
        raise ValueError(f"unsupported raw-video sampling policy: {policy}")
    timestamps = sample_segment_timestamps(segment_index, frame_count)
    try:
        import decord
    except ImportError as exc:  # pragma: no cover - depends on locked remote env
        raise RawVideoUnavailable("decord is required for raw-video sampling") from exc
    reader = decord.VideoReader(str(path), ctx=decord.cpu(0), num_threads=1)
    source_fps = float(reader.get_avg_fps())
    if not np.isfinite(source_fps) or source_fps <= 0:
        raise RawVideoUnavailable(f"raw video has invalid source fps: {path}")
    frame_indices = np.rint(timestamps * source_fps).astype(np.int64)
    if np.any(frame_indices < 0) or np.any(frame_indices >= len(reader)):
        raise RawVideoUnavailable(f"raw video does not cover timestamps for segment {segment_index}: {path}")
    frames = np.asarray(reader.get_batch(frame_indices).asnumpy())
    if frames.ndim != 4 or frames.shape[0] != frame_count or frames.shape[-1] != 3:
        raise RawVideoUnavailable(f"unexpected decoded frame shape {frames.shape} for {path}")
    return frames, timestamps


def _resolve_record_video(record: Mapping[str, Any], project_root: Path | None) -> Path | None:
    for field in ("raw_video_path", "official_video_path", "video_path"):
        value = record.get(field)
        if value:
            candidate = Path(str(value)).expanduser()
            if not candidate.is_absolute() and project_root is not None:
                candidate = project_root / candidate
            return candidate
    return None


def _resolve_record_artifact(
    record: Mapping[str, Any], field: str, project_root: Path | None
) -> Path:
    value = record.get(field)
    if not value:
        raise RawVideoUnavailable(f"record {record.get('id', '<unknown>')} lacks {field}")
    candidate = Path(str(value)).expanduser()
    if not candidate.is_absolute() and project_root is not None:
        candidate = project_root / candidate
    if not candidate.is_file():
        raise RawVideoUnavailable(f"missing {field}: {candidate}")
    return candidate.resolve()


def _load_repeat_receipts(
    records: Sequence[Mapping[str, Any]], project_root: Path | None
) -> dict[str, Any]:
    features: list[np.ndarray] = []
    logits: list[np.ndarray] = []
    queries: list[np.ndarray] = []
    labels: list[np.ndarray] = []
    ids: list[str] = []
    query_ids: list[str] = []
    for record in records:
        sample_id = str(record.get("id", ""))
        feature_path = _resolve_record_artifact(
            record, "strong_teacher_features_path", project_root
        )
        logit_path = _resolve_record_artifact(
            record, "strong_teacher_logits_path", project_root
        )
        query_path = _resolve_record_artifact(record, "text_embedding_path", project_root)
        feature = np.asarray(np.load(feature_path, allow_pickle=False), dtype=np.float32)
        logit = np.asarray(np.load(logit_path, allow_pickle=False), dtype=np.float32).reshape(-1)
        query = np.asarray(np.load(query_path, allow_pickle=False), dtype=np.float32).reshape(-1)
        label = _labels(record)
        if feature.shape != (10, 512) or logit.shape != (10,) or query.ndim != 1:
            raise ValueError(f"{sample_id}: canonical repeat receipt has unexpected shape")
        if not (np.isfinite(feature).all() and np.isfinite(logit).all() and np.isfinite(query).all()):
            raise ValueError(f"{sample_id}: canonical repeat receipt contains NaN/Inf")
        features.append(feature)
        logits.append(logit)
        queries.append(query)
        labels.append(label)
        ids.append(sample_id)
        query_ids.append(str(record.get("query", "")))
    label_array = np.stack(labels).astype(np.int64)
    return {
        "features": np.stack(features).astype(np.float32),
        "logits": np.stack(logits).astype(np.float32),
        "queries": np.stack(queries).astype(np.float32),
        "labels": label_array,
        "ids": np.asarray(ids),
        "query_ids": np.asarray(query_ids),
        "offsets": np.arange(0, label_array.shape[0] * 10 + 1, 10, dtype=np.int64),
    }


def _load_probe_train_receipts(
    manifest: str | Path, project_root: Path | None
) -> dict[str, Any]:
    records = [
        json.loads(line)
        for line in Path(manifest).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not records:
        raise ValueError(f"probe train manifest is empty: {manifest}")
    return _load_repeat_receipts(records, project_root)


def _build_raw_teacher_from_config(
    config_path: str | Path, project_root: Path | None, device: str
) -> Any:
    import yaml

    path = Path(config_path).expanduser().resolve()
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(config, Mapping):
        raise ValueError(f"teacher config must be a mapping: {path}")
    reproduction = config.get("reproduction", {})
    configured_root = (
        reproduction.get("project_root", ".")
        if isinstance(reproduction, Mapping)
        else "."
    )
    root = project_root or Path(str(configured_root)).expanduser()
    if not root.is_absolute():
        root = (PROJECT_ROOT / root).resolve()
    export = config.get("teacher_export", {})
    iv = export.get("internvideo2", {}) if isinstance(export, Mapping) else {}
    data = config.get("data", {})
    if not isinstance(iv, Mapping) or not isinstance(data, Mapping):
        raise ValueError("teacher config lacks teacher_export.internvideo2/data mappings")

    def resolve(value: Any, label: str) -> Path:
        if value in (None, ""):
            raise ValueError(f"teacher config missing {label}")
        candidate = Path(str(value)).expanduser()
        return candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()

    from src.teachers.internvideo2_visual import InternVideo2ClipB14Teacher

    return InternVideo2ClipB14Teacher(
        repo_root=resolve(iv.get("repo_root"), "internvideo2.repo_root"),
        vision_ckpt_path=resolve(iv.get("vision_ckpt_path"), "internvideo2.vision_ckpt_path"),
        text_ckpt_path=resolve(iv.get("text_ckpt_path"), "internvideo2.text_ckpt_path"),
        extra_ckpt_path=resolve(iv.get("extra_ckpt_path"), "internvideo2.extra_ckpt_path"),
        vision_ckpt_sha256=str(iv.get("vision_ckpt_sha256", "")),
        text_ckpt_sha256=str(iv.get("text_ckpt_sha256", "")),
        extra_ckpt_sha256=str(iv.get("extra_ckpt_sha256", "")),
        device=device,
        num_frames=int(iv.get("num_frames", 8)),
        align_dim=int(iv.get("align_dim", data.get("strong_teacher_dim", 512))),
        input_mode="raw_multiframe_diagnostic",
        task_segments=int(iv.get("task_segments", 10)),
        frame_expansion=str(iv.get("frame_expansion", "repeat_last_to_num_frames")),
        raw_video_diagnostic={
            "enabled": True,
            "video_duration_seconds": 10,
            "intervals": 10,
            "sampling_fps": 16,
        },
    )


def audit_sampling_availability(
    manifest: str | Path,
    *,
    output: str | Path,
    count: int = 512,
    seed: int = 42,
    project_root: str | Path | None = None,
    raw_teacher: Any | None = None,
    teacher_config: str | Path | None = None,
    probe_train: Mapping[str, Any] | None = None,
    probe_train_manifest: str | Path | None = None,
    device: str = "cuda",
) -> dict[str, Any]:
    records = [
        json.loads(line)
        for line in Path(manifest).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    selected = select_stratified_mixed_records(records, count=count, seed=seed)
    root = Path(project_root).expanduser().resolve() if project_root else None
    paths = [_resolve_record_video(record, root) for record in selected]
    present = [path for path in paths if path is not None and path.is_file() and path.stat().st_size > 0]
    suffix_ok = [path for path in present if path.suffix.lower() in RAW_VIDEO_SUFFIXES]
    diagnostic_disabled = sum(
        not bool((record.get("meta") or {}).get("raw_video_diagnostic", {}).get("available", False))
        for record in selected
    )
    unavailable = len(selected) - len(suffix_ok)
    decode_receipts: list[dict[str, Any]] = []
    decoded_frame_arrays: list[np.ndarray] = []
    decode_error: str | None = None
    if unavailable == 0:
        try:
            for path in suffix_ok:
                frame_hash = hashlib.sha256()
                record_frames: list[np.ndarray] = []
                decoded_frames = 0
                first_timestamp = None
                last_timestamp = None
                for segment_index in range(10):
                    frames, timestamps = sample_segment_frames(path, segment_index, 8)
                    record_frames.append(np.asarray(frames, dtype=np.uint8))
                    frame_hash.update(np.asarray(frames, dtype=np.uint8).tobytes())
                    decoded_frames += int(frames.shape[0])
                    first_timestamp = float(timestamps[0]) if first_timestamp is None else first_timestamp
                    last_timestamp = float(timestamps[-1])
                decode_receipts.append(
                    {
                        "path": str(path),
                        "raw_video_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "uniform_frame_sha256": frame_hash.hexdigest(),
                        "decoded_frames": decoded_frames,
                        "first_timestamp_seconds": first_timestamp,
                        "last_timestamp_seconds": last_timestamp,
                    }
                )
                decoded_frame_arrays.append(np.stack(record_frames, axis=0))
        except (RawVideoUnavailable, OSError, ValueError) as exc:
            decode_error = f"{type(exc).__name__}: {exc}"
    comparison: dict[str, Any] | None = None
    comparison_error: str | None = None
    teacher_receipt: dict[str, Any] = {
        "config": str(Path(teacher_config).resolve()) if teacher_config else None,
        "constructed": False,
        "class": None,
    }
    if unavailable == 0 and decode_error is None:
        try:
            if raw_teacher is None and teacher_config is not None:
                raw_teacher = _build_raw_teacher_from_config(teacher_config, root, device)
            if probe_train is None and probe_train_manifest is not None:
                probe_train = _load_probe_train_receipts(probe_train_manifest, root)
            if raw_teacher is None:
                raise RawVideoUnavailable(
                    "a locked InternVideo2 raw teacher is required to encode uniform-8 frames"
                )
            if not callable(getattr(raw_teacher, "export_frame_array", None)):
                raise RawVideoUnavailable(
                    "raw teacher must expose export_frame_array for hashed uniform sampling"
                )
            if probe_train is None:
                raise RawVideoUnavailable(
                    "a separate canonical train receipt is required for the query-conditioned probe"
                )
            repeat = _load_repeat_receipts(selected, root)
            uniform_features: list[np.ndarray] = []
            uniform_logits: list[np.ndarray] = []
            for record, frame_array in zip(selected, decoded_frame_arrays):
                feature, logit = raw_teacher.export_frame_array(
                    frame_array, str(record.get("query", ""))
                )
                feature_array = np.asarray(feature, dtype=np.float32)
                logit_array = np.asarray(logit, dtype=np.float32).reshape(-1)
                if feature_array.shape != (10, 512) or logit_array.shape != (10,):
                    raise ValueError(
                        f"raw teacher returned unexpected shapes {feature_array.shape}, {logit_array.shape}"
                    )
                uniform_features.append(feature_array)
                uniform_logits.append(logit_array)
            comparison = compare_sampling_receipts(
                repeat["features"],
                np.stack(uniform_features).astype(np.float32),
                repeat["labels"],
                repeat["queries"],
                repeat["offsets"],
                repeat_logits=repeat["logits"],
                multiframe_logits=np.stack(uniform_logits).astype(np.float32),
                sample_ids=repeat["ids"],
                query_ids=repeat["query_ids"],
                probe_train_features=np.asarray(probe_train["features"], dtype=np.float32),
                probe_train_labels=np.asarray(probe_train["labels"], dtype=np.int64),
                probe_train_queries=np.asarray(probe_train["queries"], dtype=np.float32),
                probe_train_ids=np.asarray(probe_train.get("ids", []), dtype=str)
                if "ids" in probe_train
                else None,
                source_hashes={
                    "raw_videos": [item["raw_video_sha256"] for item in decode_receipts],
                    "uniform_frame_arrays": [item["uniform_frame_sha256"] for item in decode_receipts],
                    "canonical_repeat_features": [
                        hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in [
                            _resolve_record_artifact(record, "strong_teacher_features_path", root)
                            for record in selected
                        ]
                    ],
                },
                seed=seed,
                shuffle_repeats=100,
            )
            teacher_receipt.update(
                {"constructed": True, "class": type(raw_teacher).__name__}
            )
        except (RawVideoUnavailable, OSError, ValueError, RuntimeError, ImportError) as exc:
            comparison_error = f"{type(exc).__name__}: {exc}"
    if unavailable or decode_error or comparison_error or comparison is None:
        status = "BLOCKED_BY_TEACHER_FRAME_SAMPLING"
    else:
        status = "PASS"
    result: dict[str, Any] = {
        "schema_version": 1,
        "status": status,
        "scientific_status": status,
        "protocol": {
            "task_segments": 10,
            "selected_records": len(selected),
            "seed": int(seed),
            "frame_count": 8,
            "repeat_policy": "canonical_single_keyframe_repeated_8",
            "multiframe_policy": "uniform_center_within_each_one_second_segment",
            "temporary_cache_only": True,
            "canonical_cache_overwrite": False,
        },
        "availability": {
            "raw_video_fields": int(sum(path is not None for path in paths)),
            "existing_nonempty_paths": len(present),
            "supported_video_paths": len(suffix_ok),
            "missing_or_invalid": int(unavailable),
            "records_marked_raw_video_unavailable": int(diagnostic_disabled),
        },
        "decode": {
            "status": "BLOCKED" if decode_error or unavailable else "PASS",
            "error": decode_error,
            "records_decoded": len(decode_receipts),
            "frames_per_record": 80,
            "uniform_center_receipts": decode_receipts,
        },
        "teacher": teacher_receipt,
        "comparison": comparison,
        "comparison_error": comparison_error,
        "selected_ids_sha256": hashlib.sha256(
            "\n".join(str(record.get("id", "")) for record in selected).encode("utf-8")
        ).hexdigest(),
        "source_hashes": {
            "raw_videos": None if unavailable else [item["raw_video_sha256"] for item in decode_receipts],
            "uniform_frame_arrays": None if unavailable else [item["uniform_frame_sha256"] for item in decode_receipts],
            "canonical_keyframe_features": "locked_teacher_cache_not_modified",
        },
        "reason": (
            "Official validation manifests contain no usable raw_video_path/official_video_path/video_path; "
            "preprocessed JPG keyframes cannot stand in for true multiframe decoding."
            if unavailable
            else (
                "Uniform-center raw frames were decoded, but the disposable teacher comparison is incomplete: "
                + str(comparison_error)
                if comparison_error or comparison is None
                else "Uniform-center raw frames were encoded by the disposable locked teacher and compared "
                "against canonical repeat-keyframe receipts."
            )
        ),
    }
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--count", type=int, default=512)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--project-root")
    parser.add_argument("--teacher-config", help="Locked config used to construct the disposable raw teacher")
    parser.add_argument("--probe-train-manifest", help="Canonical train manifest used only to fit the validation probe")
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    result = audit_sampling_availability(
        args.manifest,
        output=args.output,
        count=args.count,
        seed=args.seed,
        project_root=args.project_root,
        teacher_config=args.teacher_config,
        probe_train_manifest=args.probe_train_manifest,
        device=args.device,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
