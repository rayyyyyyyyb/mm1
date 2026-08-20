#!/usr/bin/env python3

from __future__ import annotations

import argparse
import ast
import csv
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.split_types import normalize_split_type
from scripts.discover_ovave_raw_video_layout import VIDEO_EXTENSIONS, index_raw_videos


CANONICAL_MODE = "canonical_official_png_wav"
LEGACY_MODE = "noncanonical_legacy_generated_jpeg_mel"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build source manifests by referencing an already-discovered official OV-AVEBench layout."
    )
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--raw-video-root", required=True)
    parser.add_argument("--annotation-json", required=True)
    parser.add_argument("--meta-csv", required=True)
    parser.add_argument("--output-dir", default="data/ov_ave/source")
    parser.add_argument("--path-root", default=".")
    parser.add_argument(
        "--path-mode",
        choices=("relative_to_path_root", "absolute"),
        default="relative_to_path_root",
    )
    parser.add_argument("--mode", choices=(CANONICAL_MODE, LEGACY_MODE), default=CANONICAL_MODE)
    parser.add_argument("--spectrogram-dir", default="data/noncanonical_legacy_generated_jpeg_mel")
    parser.add_argument("--image-size", type=int, default=224)
    parser.add_argument("--sample-rate", type=int, default=None)
    parser.add_argument("--n-mels", type=int, default=128)
    parser.add_argument("--overwrite-specs", action="store_true")
    parser.add_argument("--limit-per-split", type=int, default=None)
    return parser.parse_args()


def _load_annotations(path: Path) -> dict[str, dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Annotation JSON must be a dict keyed by video id.")
    return data


def _load_meta_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("Meta CSV is empty.")
    required = {"split", "cls_name", "cls_type", "vid_name"}
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"Meta CSV missing required columns: {sorted(missing)}")
    return rows


def _parse_label_list(value: Any) -> list[int]:
    labels = value if isinstance(value, list) else ast.literal_eval(str(value))
    if not isinstance(labels, list) or not labels:
        raise ValueError(f"Invalid segment label list: {value!r}")
    normalized = [int(item) for item in labels]
    if any(item not in {0, 1} for item in normalized):
        raise ValueError(f"Segment labels must be binary: {value!r}")
    return normalized


def natural_path_key(path: Path) -> tuple[object, ...]:
    return tuple(
        int(token) if token.isdigit() else token.lower()
        for token in re.split(r"(\d+)", path.name)
    )


def _serialize_path(path: Path, path_root: Path, path_mode: str) -> str:
    resolved = path.expanduser().resolve()
    if path_mode == "absolute":
        return str(resolved)
    if path_mode != "relative_to_path_root":
        raise ValueError(f"Unsupported path mode: {path_mode}")
    try:
        return resolved.relative_to(path_root.expanduser().resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"Path {resolved} is outside declared path_root {path_root}") from exc


def _official_clip_paths(dataset_root: Path, row: dict[str, str]) -> tuple[Path, Path]:
    split = row["split"].strip()
    category = row["cls_name"].strip()
    clip_id = row["vid_name"].strip()
    return (
        dataset_root / split / "audio" / category / f"{clip_id}.wav",
        dataset_root / split / "video" / category / clip_id,
    )


def build_official_record(
    *,
    dataset_root: Path,
    row: dict[str, str],
    annotations: dict[str, dict[str, Any]],
    raw_video_path: Path,
    path_root: Path,
    path_mode: str,
) -> dict[str, Any]:
    split = row["split"].strip()
    category = row["cls_name"].strip()
    cls_type = row["cls_type"].strip()
    clip_id = row["vid_name"].strip()
    annotation = annotations.get(clip_id)
    if annotation is None:
        raise KeyError(f"Missing annotation entry for clip {clip_id}")
    labels = _parse_label_list(annotation.get("label"))
    audio_path, video_dir = _official_clip_paths(dataset_root, row)
    if not audio_path.is_file() or audio_path.suffix.lower() != ".wav":
        raise FileNotFoundError(f"Missing official WAV: {audio_path}")
    if not video_dir.is_dir():
        raise FileNotFoundError(f"Missing official PNG directory: {video_dir}")
    raw_video_path = raw_video_path.expanduser().resolve()
    if not raw_video_path.is_file() or raw_video_path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise FileNotFoundError(f"Missing official raw video: {raw_video_path}")
    png_paths = sorted(
        (path for path in video_dir.iterdir() if path.is_file() and path.suffix.lower() == ".png"),
        key=natural_path_key,
    )
    if len(png_paths) != len(labels):
        raise ValueError(
            f"Canonical clip {clip_id} requires exactly {len(labels)} PNG files; found {len(png_paths)}. "
            "Silent frame repetition or temporal resampling is forbidden."
        )
    split_type = normalize_split_type(cls_type)
    return {
        "id": clip_id,
        "query": category,
        "frame_paths": [[_serialize_path(path, path_root, path_mode)] for path in png_paths],
        "spectrogram_paths": [],
        "audio_path": _serialize_path(audio_path, path_root, path_mode),
        "raw_video_path": _serialize_path(raw_video_path, path_root, path_mode),
        "segment_labels": labels,
        "split_type": split_type,
        "domain": "ov_avebench",
        "meta": {
            "split": split,
            "category": category,
            "cls_type": cls_type,
            "split_type": split_type,
            "source": "released_ovavel_dataset_anno.json",
            "raw_video_source": "official_sharepoint_raw_video",
            "preprocessing_mode": CANONICAL_MODE,
            "student_audio_preprocessing": "unresolved_not_generated",
            "preprocessing_evidence": {
                "temporal_resampling_performed": False,
                "audio_resampling_performed": False,
            },
        },
    }


def _build_record(**kwargs: Any) -> dict[str, Any]:
    """Canonical task-book entry point; kept named for archival traceability."""

    return build_official_record(**kwargs)


def _legacy_partition_frames(frame_paths: Sequence[Path], segment_count: int) -> list[list[Path]]:
    ordered = sorted(frame_paths, key=natural_path_key)
    if not ordered:
        raise ValueError("Frame directory is empty.")
    if len(ordered) >= segment_count:
        return [
            [Path(item) for item in group]
            for group in np.array_split(np.asarray(ordered, dtype=object), segment_count)
        ]
    groups: list[list[Path]] = []
    for segment_index in range(segment_count):
        source_index = int(round(segment_index * (len(ordered) - 1) / max(segment_count - 1, 1)))
        groups.append([ordered[source_index]])
    return groups


def build_noncanonical_legacy_generated_jpeg_mel(
    *,
    dataset_root: Path,
    spectrogram_root: Path,
    row: dict[str, str],
    annotations: dict[str, dict[str, Any]],
    path_root: Path,
    path_mode: str,
    image_size: int,
    requested_sample_rate: int | None,
    n_mels: int,
    overwrite_specs: bool,
) -> dict[str, Any]:
    """Preserve the R1 invented JPEG-mel pipeline under an explicit noncanonical name."""

    try:
        import librosa
        import soundfile as sf
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(f"{LEGACY_MODE} requires librosa, soundfile, and Pillow") from exc

    split = row["split"].strip()
    category = row["cls_name"].strip()
    cls_type = row["cls_type"].strip()
    clip_id = row["vid_name"].strip()
    annotation = annotations.get(clip_id)
    if annotation is None:
        raise KeyError(f"Missing annotation entry for clip {clip_id}")
    labels = _parse_label_list(annotation.get("label"))
    audio_path, video_dir = _official_clip_paths(dataset_root, row)
    frame_files = [
        path
        for path in video_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png"}
    ]
    frame_groups = _legacy_partition_frames(frame_files, len(labels))
    waveform, sample_rate = sf.read(audio_path)
    original_sample_rate = int(sample_rate)
    if waveform.ndim > 1:
        waveform = waveform.mean(axis=1)
    waveform = waveform.astype(np.float32)
    if requested_sample_rate and requested_sample_rate != sample_rate:
        waveform = librosa.resample(
            waveform, orig_sr=sample_rate, target_sr=int(requested_sample_rate)
        )
        sample_rate = int(requested_sample_rate)
    boundaries = np.linspace(0.0, waveform.shape[0] / sample_rate, len(labels) + 1)
    output_dir = spectrogram_root / split / category / clip_id
    output_dir.mkdir(parents=True, exist_ok=True)
    spectrogram_paths: list[str] = []
    for index, (start_time, end_time) in enumerate(zip(boundaries[:-1], boundaries[1:])):
        output_path = output_dir / f"seg_{index:03d}.jpg"
        if overwrite_specs or not output_path.exists():
            start = int(round(start_time * sample_rate))
            end = int(round(end_time * sample_rate))
            segment = waveform[start:end]
            spec = librosa.feature.melspectrogram(
                y=segment,
                sr=sample_rate,
                n_mels=n_mels,
                n_fft=1024,
                hop_length=256,
            )
            db = np.clip(librosa.power_to_db(spec, ref=np.max), -80.0, 0.0)
            pixels = ((db + 80.0) / 80.0 * 255.0).astype(np.uint8)
            Image.fromarray(pixels, mode="L").convert("RGB").resize(
                (image_size, image_size), Image.BILINEAR
            ).save(output_path, quality=95)
        spectrogram_paths.append(_serialize_path(output_path, path_root, path_mode))
    split_type = normalize_split_type(cls_type)
    return {
        "id": clip_id,
        "query": category,
        "frame_paths": [
            [_serialize_path(path, path_root, path_mode) for path in group] for group in frame_groups
        ],
        "spectrogram_paths": spectrogram_paths,
        "audio_path": _serialize_path(audio_path, path_root, path_mode),
        "segment_timestamps": [
            [float(start), float(end)] for start, end in zip(boundaries[:-1], boundaries[1:])
        ],
        "segment_labels": labels,
        "split_type": split_type,
        "domain": "ov_avebench",
        "meta": {
            "split": split,
            "category": category,
            "cls_type": cls_type,
            "split_type": split_type,
            "source": "released_ovavel_dataset_anno.json",
            "preprocessing_mode": LEGACY_MODE,
            "preprocessing_evidence": {
                "temporal_resampling_performed": len(frame_files) != len(labels),
                "audio_resampling_performed": int(sample_rate) != original_sample_rate,
            },
        },
    }


def atomic_write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    try:
        with partial.open("w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(partial, path)
    finally:
        if partial.exists():
            partial.unlink()


def source_manifest_outputs(output_dir: Path) -> dict[str, Path]:
    return {split: output_dir / f"{split}.jsonl" for split in ("train", "val", "test")}


def main() -> None:
    args = parse_args()

    def resolved(value: str) -> Path:
        path = Path(value).expanduser()
        return (PROJECT_ROOT / path).resolve() if not path.is_absolute() else path.resolve()

    dataset_root = resolved(args.dataset_root)
    raw_video_root = resolved(args.raw_video_root)
    annotation_json = resolved(args.annotation_json)
    meta_csv = resolved(args.meta_csv)
    output_dir = resolved(args.output_dir)
    path_root = resolved(args.path_root)
    spectrogram_root = resolved(args.spectrogram_dir)
    for required in (dataset_root, raw_video_root, annotation_json, meta_csv):
        if not required.exists():
            raise FileNotFoundError(f"Required official input not found: {required}")
    annotations = _load_annotations(annotation_json)
    rows = _load_meta_rows(meta_csv)
    raw_video_index = index_raw_videos(raw_video_root)
    records_by_split: dict[str, list[dict[str, Any]]] = {"train": [], "val": [], "test": []}
    limit = None if args.limit_per_split is None else max(1, int(args.limit_per_split))
    for row in rows:
        split = row["split"].strip()
        if split not in records_by_split:
            continue
        if limit is not None and len(records_by_split[split]) >= limit:
            continue
        if args.mode == CANONICAL_MODE:
            record = _build_record(
                dataset_root=dataset_root,
                row=row,
                annotations=annotations,
                raw_video_path=raw_video_index.get(row["vid_name"].strip(), raw_video_root / "__missing__"),
                path_root=path_root,
                path_mode=args.path_mode,
            )
        else:
            record = build_noncanonical_legacy_generated_jpeg_mel(
                dataset_root=dataset_root,
                spectrogram_root=spectrogram_root,
                row=row,
                annotations=annotations,
                path_root=path_root,
                path_mode=args.path_mode,
                image_size=int(args.image_size),
                requested_sample_rate=args.sample_rate,
                n_mels=int(args.n_mels),
                overwrite_specs=bool(args.overwrite_specs),
            )
        records_by_split[split].append(record)
    if limit is None:
        metadata_ids = {
            row["vid_name"].strip()
            for row in rows
            if row["split"].strip() in records_by_split
        }
        extra_raw_ids = sorted(set(raw_video_index) - metadata_ids)
        if extra_raw_ids:
            raise ValueError(f"Raw videos absent from official metadata: {extra_raw_ids[:20]}")
    outputs = source_manifest_outputs(output_dir)
    for split, output in outputs.items():
        atomic_write_jsonl(output, records_by_split[split])
    print(
        json.dumps(
            {
                "mode": args.mode,
                "path_mode": args.path_mode,
                "path_root": str(path_root),
                "outputs": {split: str(path) for split, path in outputs.items()},
                "records_per_split": {
                    split: len(records) for split, records in records_by_split.items()
                },
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
