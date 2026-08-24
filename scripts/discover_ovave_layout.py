#!/usr/bin/env python3

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import csv
import json
import os
from pathlib import Path
import re
import wave
from typing import Any

from PIL import Image


TRACKED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".wav", ".npy", ".npz"}
OFFICIAL_SPLIT_COUNTS = {"train": 13182, "val": 5798, "test": 5820}
VISUAL_EXTENSIONS = {".png", ".jpg", ".jpeg"}
OFFICIAL_FRAME_NAMES = tuple(f"{index:08d}.jpg" for index in range(1, 11))


def _name_pattern(name: str) -> str:
    return re.sub(r"\d+", "<N>", name.lower())


def _natural_key(path: Path) -> tuple[object, ...]:
    return tuple(
        int(token) if token.isdigit() else token.lower()
        for token in re.split(r"(\d+)", path.name)
    )


def _inspect_media(
    job: tuple[Path, str, str],
) -> tuple[str, str, dict[str, object] | None, str | None]:
    path, extension, relative = job
    try:
        if extension in VISUAL_EXTENSIONS:
            with Image.open(path) as image:
                payload: dict[str, object] = {
                    "dimensions": f"{image.width}x{image.height}x{len(image.getbands())}",
                    "name_pattern": _name_pattern(path.name),
                }
            return extension, relative, payload, None
        if extension == ".wav":
            with wave.open(str(path), "rb") as handle:
                rate = int(handle.getframerate())
                channels = int(handle.getnchannels())
                duration = handle.getnframes() / rate if rate else 0.0
            return extension, relative, {
                "sample_rate": rate,
                "channels": channels,
                "duration_bucket": f"{round(duration, 3):.3f}",
            }, None
    except (OSError, ValueError, wave.Error, EOFError) as error:
        return extension, relative, None, str(error)
    return extension, relative, {}, None


def discover_layout(
    dataset_root: str | Path,
    *,
    meta_csv: str | Path | None = None,
    enforce_official_counts: bool = True,
    max_workers: int = 1,
) -> dict[str, Any]:
    root = Path(dataset_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Official preprocessed root not found: {root}")
    split_presence = {split: (root / split).is_dir() for split in ("train", "val", "test")}
    extension_counts: Counter[str] = Counter()
    visual_dimensions: Counter[str] = Counter()
    visual_name_patterns: Counter[str] = Counter()
    wav_sample_rates: Counter[str] = Counter()
    wav_channels: Counter[str] = Counter()
    wav_duration_buckets: Counter[str] = Counter()
    directory_counts: dict[str, Counter[str]] = {}
    errors: list[dict[str, str]] = []
    zero_byte_files: list[str] = []
    files_by_directory: dict[Path, list[Path]] = {}
    paths_by_basename: dict[str, list[str]] = {}
    paths_by_logical_basename: dict[tuple[str, str, str], list[str]] = {}
    discovered_ids_by_split = {split: set() for split in ("train", "val", "test")}
    inspection_jobs: list[tuple[Path, str, str]] = []

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        extension = path.suffix.lower()
        if extension not in TRACKED_EXTENSIONS:
            continue
        relative = path.relative_to(root)
        paths_by_basename.setdefault(path.name.lower(), []).append(relative.as_posix())
        if path.stat().st_size == 0:
            zero_byte_files.append(relative.as_posix())
        files_by_directory.setdefault(path.parent, []).append(path)
        split = relative.parts[0].lower() if relative.parts else ""
        if split in discovered_ids_by_split:
            clip_id = path.stem if extension == ".wav" else path.parent.name
            discovered_ids_by_split[split].add(clip_id)
            paths_by_logical_basename.setdefault(
                (split, clip_id, path.name.lower()), []
            ).append(relative.as_posix())
        extension_counts[extension] += 1
        relative_parent = path.parent.relative_to(root).as_posix()
        directory_counts.setdefault(relative_parent, Counter())[extension] += 1
        if extension in VISUAL_EXTENSIONS or extension == ".wav":
            inspection_jobs.append((path, extension, relative.as_posix()))

    if max_workers < 1:
        raise ValueError("max_workers must be at least one")
    if max_workers == 1:
        inspection_results = map(_inspect_media, inspection_jobs)
        executor = None
    else:
        executor = ThreadPoolExecutor(max_workers=max_workers)

        def bounded_results():
            for offset in range(0, len(inspection_jobs), 4096):
                yield from executor.map(
                    _inspect_media, inspection_jobs[offset : offset + 4096]
                )

        inspection_results = bounded_results()
    try:
        for extension, relative, payload, error in inspection_results:
            if error is not None or payload is None:
                errors.append({"path": relative, "error": str(error)})
            elif extension in VISUAL_EXTENSIONS:
                visual_dimensions[str(payload["dimensions"])] += 1
                visual_name_patterns[str(payload["name_pattern"])] += 1
            elif extension == ".wav":
                wav_sample_rates[str(payload["sample_rate"])] += 1
                wav_channels[str(payload["channels"])] += 1
                wav_duration_buckets[str(payload["duration_bucket"])] += 1
    finally:
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)

    visual_segment_histogram: Counter[str] = Counter()
    for directory, paths in files_by_directory.items():
        visual_files = sorted(
            (path for path in paths if path.suffix.lower() in VISUAL_EXTENSIONS),
            key=_natural_key,
        )
        if not visual_files:
            continue
        visual_segment_histogram[str(len(visual_files))] += 1
        actual_names = tuple(path.name for path in visual_files)
        if actual_names != OFFICIAL_FRAME_NAMES:
            errors.append(
                {
                    "path": directory.relative_to(root).as_posix(),
                    "error": (
                        "canonical visual layout must be exactly 00000001.jpg "
                        "through 00000010.jpg"
                    ),
                }
            )
    warnings: list[str] = []
    missing_splits = [split for split, present in split_presence.items() if not present]
    if missing_splits:
        warnings.append(f"missing split directories: {missing_splits}")
    visual_extension_counts = {
        extension: int(extension_counts.get(extension, 0))
        for extension in sorted(VISUAL_EXTENSIONS)
        if extension_counts.get(extension, 0)
    }
    canonical_visual_extension = (
        ".jpg" if set(visual_extension_counts) == {".jpg"} else None
    )
    if canonical_visual_extension is None:
        warnings.append(
            "canonical visual extension is not exclusively .jpg"
        )
    if extension_counts.get(".wav", 0) == 0:
        warnings.append("no WAV files found")
    if zero_byte_files:
        errors.extend({"path": value, "error": "zero-byte tracked file"} for value in zero_byte_files)
    duplicate_basenames = [
        {
            "basename": basename,
            "count": len(paths),
            "paths": sorted(paths),
        }
        for basename, paths in sorted(paths_by_basename.items())
        if len(paths) > 1
    ]
    duplicate_logical_basenames = [
        {
            "logical_clip": f"{split}/{clip_id}",
            "basename": basename,
            "count": len(paths),
            "paths": sorted(paths),
        }
        for (split, clip_id, basename), paths in sorted(paths_by_logical_basename.items())
        if len(paths) > 1
    ]
    if duplicate_logical_basenames:
        errors.append(
            {
                "path": str(root),
                "error": (
                    "duplicate basename within logical clip: "
                    f"{len(duplicate_logical_basenames)} conflict(s)"
                ),
            }
        )

    natural_sort_changed_directories = [
        directory.relative_to(root).as_posix()
        for directory, paths in sorted(files_by_directory.items(), key=lambda item: item[0].as_posix())
        if sorted(paths, key=lambda path: path.name.lower()) != sorted(paths, key=_natural_key)
    ]
    metadata_split_counts: dict[str, int] | None = None
    missing_clip_ids: dict[str, list[str]] | None = None
    extra_clip_ids: dict[str, list[str]] | None = None
    duplicate_clip_ids: list[str] = []
    metadata_bijection_verified = False
    if meta_csv is not None:
        metadata_path = Path(meta_csv).expanduser().resolve()
        with metadata_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        metadata_ids_by_split = {split: set() for split in ("train", "val", "test")}
        id_counts: Counter[str] = Counter()
        for row in rows:
            split = str(row.get("split", "")).strip().lower()
            clip_id = str(row.get("vid_name", "")).strip()
            if split not in metadata_ids_by_split or not clip_id:
                errors.append({"path": str(metadata_path), "error": f"invalid metadata row: {row}"})
                continue
            metadata_ids_by_split[split].add(clip_id)
            id_counts[clip_id] += 1
        duplicate_clip_ids = sorted(value for value, count in id_counts.items() if count > 1)
        metadata_split_counts = {
            split: len(metadata_ids_by_split[split]) for split in ("train", "val", "test")
        }
        missing_clip_ids = {
            split: sorted(metadata_ids_by_split[split] - discovered_ids_by_split[split])
            for split in ("train", "val", "test")
        }
        extra_clip_ids = {
            split: sorted(discovered_ids_by_split[split] - metadata_ids_by_split[split])
            for split in ("train", "val", "test")
        }
        if duplicate_clip_ids:
            errors.append({"path": str(metadata_path), "error": "duplicate vid_name values"})
        if any(missing_clip_ids.values()):
            errors.append({"path": str(root), "error": "metadata clips missing from extracted layout"})
        if any(extra_clip_ids.values()):
            errors.append({"path": str(root), "error": "extracted clips absent from official metadata"})
        if enforce_official_counts and metadata_split_counts != OFFICIAL_SPLIT_COUNTS:
            errors.append(
                {
                    "path": str(metadata_path),
                    "error": f"official split counts mismatch: {metadata_split_counts}",
                }
            )
        metadata_bijection_verified = not any(
            (duplicate_clip_ids, *missing_clip_ids.values(), *extra_clip_ids.values())
        )
    split_counts = (
        metadata_split_counts
        if metadata_split_counts is not None
        else {split: len(values) for split, values in discovered_ids_by_split.items()}
    )
    return {
        "schema_version": 1,
        "status": "passed" if not errors and not warnings else "failed",
        "dataset_root": str(root),
        "top_level_entries": sorted(path.name for path in root.iterdir()),
        "split_presence": dict(sorted(split_presence.items())),
        "split_counts": dict(sorted(split_counts.items())),
        "metadata_bijection_verified": metadata_bijection_verified,
        "missing_clip_ids": missing_clip_ids,
        "extra_clip_ids": extra_clip_ids,
        "duplicate_clip_ids": duplicate_clip_ids,
        "duplicate_basenames": duplicate_basenames,
        "duplicate_logical_basenames": duplicate_logical_basenames,
        "zero_byte_files": sorted(zero_byte_files),
        "natural_sort_changed_directories": natural_sort_changed_directories,
        "extension_counts": dict(sorted(extension_counts.items())),
        "canonical_visual_extension": canonical_visual_extension,
        "visual_dimensions": dict(sorted(visual_dimensions.items())),
        "visual_name_patterns": dict(sorted(visual_name_patterns.items())),
        "png_dimensions": (
            dict(sorted(visual_dimensions.items()))
            if extension_counts.get(".png", 0)
            else {}
        ),
        "png_name_patterns": (
            dict(sorted(visual_name_patterns.items()))
            if extension_counts.get(".png", 0)
            else {}
        ),
        "visual_segment_count_histogram": dict(sorted(visual_segment_histogram.items())),
        "wav_sample_rates": dict(sorted(wav_sample_rates.items())),
        "wav_channels": dict(sorted(wav_channels.items())),
        "wav_duration_seconds_histogram": dict(sorted(wav_duration_buckets.items())),
        "directories_with_tracked_files": [
            {"path": path, "counts": dict(sorted(counts.items()))}
            for path, counts in sorted(directory_counts.items())
        ],
        "errors": errors,
        "warnings": warnings,
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Official OV-AVEBench Preprocessed Layout Discovery",
        "",
        f"Status: `{report['status']}`",
        "",
        f"Root: `{report['dataset_root']}`",
        "",
        "## Split presence",
        "",
    ]
    lines.extend(f"- {split}: {present}" for split, present in report["split_presence"].items())
    lines.extend(["", "## Extension counts", ""])
    lines.extend(f"- {extension}: {count}" for extension, count in report["extension_counts"].items())
    lines.extend(["", "## Visual dimensions", ""])
    lines.extend(f"- {key}: {value}" for key, value in report["visual_dimensions"].items())
    lines.extend(["", "## WAV sample rates", ""])
    lines.extend(f"- {key}: {value}" for key, value in report["wav_sample_rates"].items())
    if report["errors"] or report["warnings"]:
        lines.extend(["", "## Issues", "", "```json", json.dumps({"errors": report["errors"], "warnings": report["warnings"]}, indent=2), "```"])
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    try:
        with partial.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(partial, path)
    finally:
        if partial.exists():
            partial.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="Inventory a safely extracted official OV-AVEBench tree")
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--meta-csv", default=None)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    report = discover_layout(
        args.dataset_root, meta_csv=args.meta_csv, max_workers=args.workers
    )
    _atomic_write(Path(args.output_json), json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    _atomic_write(Path(args.output_md), _markdown(report))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    raise SystemExit(0 if report["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
