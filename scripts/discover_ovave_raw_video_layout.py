#!/usr/bin/env python3

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable
import csv
import json
import math
import os
from pathlib import Path
import subprocess
from typing import Any


VIDEO_EXTENSIONS = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}
OFFICIAL_SPLIT_COUNTS = {"train": 13182, "val": 5798, "test": 5820}


def _video_paths_by_id(root: Path) -> dict[str, list[Path]]:
    paths: dict[str, list[Path]] = {}
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
            paths.setdefault(path.stem, []).append(path.resolve())
    return {key: sorted(value) for key, value in sorted(paths.items())}


def index_raw_videos(raw_video_root: str | Path) -> dict[str, Path]:
    root = Path(raw_video_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Official raw-video root not found: {root}")
    paths = _video_paths_by_id(root)
    duplicates = sorted(clip_id for clip_id, values in paths.items() if len(values) != 1)
    if duplicates:
        raise ValueError(f"Duplicate official raw-video IDs: {duplicates[:20]}")
    return {clip_id: values[0] for clip_id, values in paths.items()}


def _metadata_ids(path: Path) -> tuple[dict[str, set[str]], list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    ids_by_split = {split: set() for split in ("train", "val", "test")}
    id_counts: Counter[str] = Counter()
    errors: list[dict[str, str]] = []
    for row in rows:
        split = str(row.get("split", "")).strip().lower()
        clip_id = str(row.get("vid_name", "")).strip()
        if split not in ids_by_split or not clip_id:
            errors.append({"path": str(path), "error": f"invalid metadata row: {row}"})
            continue
        ids_by_split[split].add(clip_id)
        id_counts[clip_id] += 1
    duplicates = sorted(clip_id for clip_id, count in id_counts.items() if count > 1)
    if duplicates:
        errors.append({"path": str(path), "error": "duplicate metadata vid_name values"})
    return ids_by_split, duplicates, errors


def _ratio(value: str | None) -> float:
    if not value:
        return 0.0
    numerator, separator, denominator = value.partition("/")
    if not separator:
        return float(numerator)
    bottom = float(denominator)
    return float(numerator) / bottom if bottom else 0.0


def probe_video(path: Path, *, ffprobe_path: str | Path) -> dict[str, object]:
    completed = subprocess.run(
        [
            str(ffprobe_path),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,avg_frame_rate,r_frame_rate,duration:format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError(f"ffprobe exit {completed.returncode}: {completed.stderr.strip()}")
    payload = json.loads(completed.stdout)
    streams = payload.get("streams")
    if not isinstance(streams, list) or not streams:
        raise ValueError("ffprobe found no video stream")
    stream = streams[0]
    fps = _ratio(stream.get("avg_frame_rate")) or _ratio(stream.get("r_frame_rate"))
    duration_value = stream.get("duration") or payload.get("format", {}).get("duration")
    duration = float(duration_value or 0.0)
    return {
        "codec": str(stream.get("codec_name") or ""),
        "fps": fps,
        "duration_seconds": duration,
    }


def discover_raw_video_layout(
    raw_video_root: str | Path,
    *,
    meta_csv: str | Path,
    enforce_official_counts: bool = True,
    ffprobe_path: str | Path | None = None,
    probe_fn: Callable[[Path], dict[str, object]] | None = None,
) -> dict[str, Any]:
    root = Path(raw_video_root).expanduser().resolve()
    metadata_path = Path(meta_csv).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Official raw-video root not found: {root}")
    if not metadata_path.is_file():
        raise FileNotFoundError(f"Official metadata CSV not found: {metadata_path}")

    paths_by_id = _video_paths_by_id(root)
    duplicate_video_ids = sorted(
        clip_id for clip_id, paths in paths_by_id.items() if len(paths) > 1
    )
    unique_paths = {
        clip_id: paths[0] for clip_id, paths in paths_by_id.items() if len(paths) == 1
    }
    ids_by_split, duplicate_metadata_ids, errors = _metadata_ids(metadata_path)
    metadata_ids = set().union(*ids_by_split.values())
    discovered_ids = set(paths_by_id)
    missing_clip_ids = sorted(metadata_ids - discovered_ids)
    extra_clip_ids = sorted(discovered_ids - metadata_ids)
    split_counts = {split: len(values) for split, values in sorted(ids_by_split.items())}

    if duplicate_video_ids:
        errors.append({"path": str(root), "error": "duplicate official raw-video IDs"})
    if missing_clip_ids:
        errors.append({"path": str(root), "error": "metadata clips missing raw video"})
    if extra_clip_ids:
        errors.append({"path": str(root), "error": "raw videos absent from official metadata"})
    if enforce_official_counts and split_counts != OFFICIAL_SPLIT_COUNTS:
        errors.append(
            {"path": str(metadata_path), "error": f"official split counts mismatch: {split_counts}"}
        )

    extension_counts: Counter[str] = Counter()
    codec_counts: Counter[str] = Counter()
    fps_histogram: Counter[str] = Counter()
    duration_histogram: Counter[str] = Counter()
    zero_byte_files: list[str] = []
    records: list[dict[str, object]] = []
    if probe_fn is None:
        if ffprobe_path is None:
            raise ValueError("ffprobe_path or probe_fn is required for full raw-video audit")
        probe_fn = lambda path: probe_video(path, ffprobe_path=ffprobe_path)

    for clip_id, paths in paths_by_id.items():
        for path in paths:
            relative = path.relative_to(root).as_posix()
            size = path.stat().st_size
            extension_counts[path.suffix.lower()] += 1
            if size == 0:
                zero_byte_files.append(relative)
                errors.append({"path": relative, "error": "zero-byte raw video"})
                continue
            try:
                probed = probe_fn(path)
                codec = str(probed.get("codec") or "")
                fps = float(probed.get("fps") or 0.0)
                duration = float(probed.get("duration_seconds") or 0.0)
                if not codec:
                    raise ValueError("missing video codec")
                if not math.isfinite(fps) or fps <= 0:
                    raise ValueError("invalid video fps")
                if not math.isfinite(duration) or duration <= 0:
                    raise ValueError("invalid video duration")
                if duration < 10.0:
                    errors.append({"path": relative, "error": "raw video is shorter than 10 seconds"})
                codec_counts[codec] += 1
                fps_histogram[f"{fps:.6f}"] += 1
                duration_histogram[f"{duration:.6f}"] += 1
                records.append(
                    {
                        "id": clip_id,
                        "path": relative,
                        "bytes": size,
                        "codec": codec,
                        "fps": fps,
                        "duration_seconds": duration,
                    }
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
                errors.append({"path": relative, "error": f"video probe failed: {error}"})

    metadata_bijection_verified = not any(
        (duplicate_metadata_ids, duplicate_video_ids, missing_clip_ids, extra_clip_ids)
    )
    matched = len(metadata_ids & discovered_ids)
    return {
        "schema_version": 1,
        "status": "passed" if not errors else "failed",
        "raw_video_root": str(root),
        "video_count": sum(len(paths) for paths in paths_by_id.values()),
        "split_counts": split_counts,
        "metadata_bijection_verified": metadata_bijection_verified,
        "id_match_rate": matched / len(metadata_ids) if metadata_ids else 0.0,
        "missing_clip_ids": missing_clip_ids,
        "extra_clip_ids": extra_clip_ids,
        "duplicate_video_ids": duplicate_video_ids,
        "duplicate_metadata_ids": duplicate_metadata_ids,
        "zero_byte_files": sorted(zero_byte_files),
        "extension_counts": dict(sorted(extension_counts.items())),
        "codec_counts": dict(sorted(codec_counts.items())),
        "fps_histogram": dict(sorted(fps_histogram.items())),
        "duration_seconds_histogram": dict(sorted(duration_histogram.items())),
        "video_records": sorted(records, key=lambda item: str(item["path"])),
        "errors": errors,
        "warnings": [],
    }


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fully audit official OV-AVEBench raw videos")
    parser.add_argument("--raw-video-root", required=True)
    parser.add_argument("--meta-csv", required=True)
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--output-json", required=True)
    args = parser.parse_args()
    report = discover_raw_video_layout(
        args.raw_video_root,
        meta_csv=args.meta_csv,
        ffprobe_path=args.ffprobe,
    )
    _atomic_write(Path(args.output_json), report)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    raise SystemExit(0 if report["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
