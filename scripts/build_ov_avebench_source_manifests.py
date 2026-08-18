#!/usr/bin/env python3

from __future__ import annotations

import argparse
import ast
import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

import librosa
import numpy as np
import soundfile as sf
from PIL import Image


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build OV-OrthKD source manifests from the official OV-AVEBench preprocessed release."
    )
    parser.add_argument(
        "--dataset-root",
        type=str,
        default="data/raw/ov_avebench_preprocessed/ovave_dataset_preprocessed",
        help="Root folder containing train/val/test audio and video directories.",
    )
    parser.add_argument(
        "--annotation-json",
        type=str,
        default="data/raw/ov_avebench_preprocessed/released_ovavel_dataset_anno.json",
        help="Official OV-AVEBench annotation JSON.",
    )
    parser.add_argument(
        "--meta-csv",
        type=str,
        default="data/raw/ov_avebench_preprocessed/ovave_dataset_meta.csv",
        help="Official OV-AVEBench split metadata CSV.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/ov_ave",
        help="Directory where train_source.jsonl / val_source.jsonl / test_source.jsonl will be written.",
    )
    parser.add_argument(
        "--spectrogram-dir",
        type=str,
        default="data/raw/ov_avebench_preprocessed/generated_specs",
        help="Directory for generated per-segment spectrogram images.",
    )
    parser.add_argument("--image-size", type=int, default=224)
    parser.add_argument("--sample-rate", type=int, default=None, help="Optional resample rate for spectrogram generation.")
    parser.add_argument("--n-mels", type=int, default=128)
    parser.add_argument("--overwrite-specs", action="store_true")
    parser.add_argument("--limit-per-split", type=int, default=None)
    return parser.parse_args()


def _load_annotations(path: Path) -> Dict[str, Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Annotation JSON must be a dict keyed by video id.")
    return data


def _load_meta_rows(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    if not rows:
        raise ValueError("Meta CSV is empty.")
    required = {"split", "cls_name", "cls_type", "vid_name"}
    missing = required - set(rows[0].keys())
    if missing:
        raise ValueError(f"Meta CSV missing required columns: {sorted(missing)}")
    return rows


def _parse_label_list(value: Any) -> List[int]:
    if isinstance(value, list):
        labels = value
    else:
        labels = ast.literal_eval(str(value))
    if not isinstance(labels, list) or not labels:
        raise ValueError(f"Invalid segment label list: {value!r}")
    return [int(item) for item in labels]


def _relpath(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _image_from_spectrogram(spec_db: np.ndarray, image_size: int) -> Image.Image:
    spec_db = np.nan_to_num(spec_db, nan=-80.0, neginf=-80.0, posinf=0.0)
    spec_db = np.clip(spec_db, -80.0, 0.0)
    normalized = ((spec_db + 80.0) / 80.0 * 255.0).astype(np.uint8)
    image = Image.fromarray(normalized, mode="L").convert("RGB")
    return image.resize((image_size, image_size), Image.BILINEAR)


def _generate_segment_spectrogram(
    waveform: np.ndarray,
    sample_rate: int,
    start_time: float,
    end_time: float,
    image_size: int,
    n_mels: int,
) -> Image.Image:
    start = max(0, int(round(start_time * sample_rate)))
    end = min(int(round(end_time * sample_rate)), waveform.shape[0])
    segment = waveform[start:end]
    if segment.size == 0:
        segment = np.zeros(max(1, sample_rate // 10), dtype=np.float32)

    spec = librosa.feature.melspectrogram(
        y=segment.astype(np.float32),
        sr=sample_rate,
        n_mels=n_mels,
        n_fft=1024,
        hop_length=256,
    )
    spec_db = librosa.power_to_db(spec, ref=np.max)
    return _image_from_spectrogram(spec_db, image_size=image_size)


def _partition_frames(frame_paths: Sequence[Path], segment_count: int) -> List[List[Path]]:
    if segment_count <= 0:
        raise ValueError("segment_count must be positive.")
    ordered = sorted(frame_paths)
    if not ordered:
        raise ValueError("Frame directory is empty.")

    if len(ordered) >= segment_count:
        groups = [list(chunk) for chunk in np.array_split(np.asarray(ordered, dtype=object), segment_count)]
        return [[Path(item) for item in group] for group in groups]

    # If there are fewer frames than segments, repeat nearest frames so every segment is non-empty.
    groups: List[List[Path]] = []
    for seg_idx in range(segment_count):
        source_idx = int(round(seg_idx * (len(ordered) - 1) / max(segment_count - 1, 1)))
        groups.append([ordered[source_idx]])
    return groups


def _iter_frame_files(video_dir: Path) -> Iterable[Path]:
    return sorted(path for path in video_dir.iterdir() if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png"})


def _build_record(
    repo_root: Path,
    dataset_root: Path,
    spectrogram_root: Path,
    row: Dict[str, str],
    annotations: Dict[str, Dict[str, Any]],
    image_size: int,
    requested_sample_rate: int | None,
    n_mels: int,
    overwrite_specs: bool,
) -> Dict[str, Any]:
    split = row["split"].strip()
    category = row["cls_name"].strip()
    clip_id = row["vid_name"].strip()

    anno = annotations.get(clip_id)
    if anno is None:
        raise KeyError(f"Missing annotation entry for clip {clip_id}")

    labels = _parse_label_list(anno.get("label"))
    num_segments = len(labels)

    audio_path = dataset_root / split / "audio" / category / f"{clip_id}.wav"
    video_dir = dataset_root / split / "video" / category / clip_id
    if not audio_path.exists():
        raise FileNotFoundError(f"Missing audio file: {audio_path}")
    if not video_dir.exists():
        raise FileNotFoundError(f"Missing video directory: {video_dir}")

    frame_groups = _partition_frames(list(_iter_frame_files(video_dir)), num_segments)

    waveform, sample_rate = sf.read(audio_path)
    if waveform.ndim > 1:
        waveform = waveform.mean(axis=1)
    waveform = waveform.astype(np.float32)

    if requested_sample_rate and requested_sample_rate > 0 and requested_sample_rate != sample_rate:
        waveform = librosa.resample(waveform, orig_sr=sample_rate, target_sr=requested_sample_rate)
        sample_rate = int(requested_sample_rate)

    duration = float(waveform.shape[0] / sample_rate)
    boundaries = np.linspace(0.0, duration, num_segments + 1, dtype=np.float64)
    timestamps = [[float(boundaries[idx]), float(boundaries[idx + 1])] for idx in range(num_segments)]

    spectrogram_dir = spectrogram_root / split / category / clip_id
    spectrogram_dir.mkdir(parents=True, exist_ok=True)
    spectrogram_paths: List[str] = []
    for seg_idx, (start_time, end_time) in enumerate(timestamps):
        output_path = spectrogram_dir / f"seg_{seg_idx:03d}.jpg"
        if overwrite_specs or not output_path.exists():
            image = _generate_segment_spectrogram(
                waveform=waveform,
                sample_rate=sample_rate,
                start_time=start_time,
                end_time=end_time,
                image_size=image_size,
                n_mels=n_mels,
            )
            image.save(output_path, quality=95)
        spectrogram_paths.append(_relpath(output_path, repo_root))

    return {
        "id": clip_id,
        "query": category,
        "frame_paths": [[_relpath(path, repo_root) for path in group] for group in frame_groups],
        "spectrogram_paths": spectrogram_paths,
        "audio_path": _relpath(audio_path, repo_root),
        "segment_timestamps": timestamps,
        "segment_labels": labels,
        "domain": "ov_avebench",
        "meta": {
            "split": split,
            "category": category,
            "cls_type": row["cls_type"].strip(),
            "source": "released_ovavel_dataset_anno.json",
        },
    }


def _write_jsonl(path: Path, records: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> None:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    dataset_root = (repo_root / args.dataset_root).resolve()
    annotation_json = (repo_root / args.annotation_json).resolve()
    meta_csv = (repo_root / args.meta_csv).resolve()
    output_dir = (repo_root / args.output_dir).resolve()
    spectrogram_root = (repo_root / args.spectrogram_dir).resolve()

    if not dataset_root.exists():
        raise FileNotFoundError(f"Dataset root not found: {dataset_root}")
    if not annotation_json.exists():
        raise FileNotFoundError(f"Annotation JSON not found: {annotation_json}")
    if not meta_csv.exists():
        raise FileNotFoundError(f"Meta CSV not found: {meta_csv}")

    annotations = _load_annotations(annotation_json)
    meta_rows = _load_meta_rows(meta_csv)

    records_by_split: Dict[str, List[Dict[str, Any]]] = {"train": [], "val": [], "test": []}
    limit = None if args.limit_per_split is None else max(1, int(args.limit_per_split))

    for row in meta_rows:
        split = row["split"].strip()
        if split not in records_by_split:
            continue
        if limit is not None and len(records_by_split[split]) >= limit:
            continue
        records_by_split[split].append(
            _build_record(
                repo_root=repo_root,
                dataset_root=dataset_root,
                spectrogram_root=spectrogram_root,
                row=row,
                annotations=annotations,
                image_size=int(args.image_size),
                requested_sample_rate=args.sample_rate,
                n_mels=int(args.n_mels),
                overwrite_specs=bool(args.overwrite_specs),
            )
        )

    output_paths = {
        "train": output_dir / "train_source.jsonl",
        "val": output_dir / "val_source.jsonl",
        "test": output_dir / "test_source.jsonl",
    }
    for split, records in records_by_split.items():
        _write_jsonl(output_paths[split], records)

    summary = {
        "dataset_root": str(dataset_root),
        "annotation_json": str(annotation_json),
        "meta_csv": str(meta_csv),
        "spectrogram_dir": str(spectrogram_root),
        "outputs": {split: str(path) for split, path in output_paths.items()},
        "records_per_split": {split: len(records) for split, records in records_by_split.items()},
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
