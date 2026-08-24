#!/usr/bin/env python3
"""Audit the complete official OV-AVEBench preprocessed tar without extraction."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tarfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any


ARCHIVE_ROOT = "ovave_dataset_preprocessed"
OFFICIAL_SPLIT_COUNTS = {"train": 13182, "val": 5798, "test": 5820}
OFFICIAL_FRAME_NAMES = tuple(f"{index:08d}.jpg" for index in range(1, 11))


def _metadata(path: Path) -> dict[tuple[str, str, str], dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected: dict[tuple[str, str, str], dict[str, str]] = {}
    seen_ids: set[str] = set()
    for line_number, row in enumerate(rows, start=2):
        split = str(row.get("split", "")).strip()
        category = str(row.get("cls_name", "")).strip()
        class_type = str(row.get("cls_type", "")).strip()
        sample_id = str(row.get("vid_name", "")).strip()
        if split not in OFFICIAL_SPLIT_COUNTS or not all(
            (category, class_type, sample_id)
        ):
            raise ValueError(f"invalid OV-AVEL metadata row {line_number}: {row}")
        if sample_id in seen_ids:
            raise ValueError(f"duplicate OV-AVEL sample ID: {sample_id}")
        seen_ids.add(sample_id)
        expected[(split, category, sample_id)] = {
            "class_type": class_type,
        }
    if not expected:
        raise ValueError("OV-AVEL metadata is empty")
    return expected


def audit_preprocessed_archive(
    archive_path: str | Path,
    meta_csv: str | Path,
    *,
    enforce_official_counts: bool = True,
) -> dict[str, Any]:
    archive = Path(archive_path).expanduser().resolve()
    metadata_path = Path(meta_csv).expanduser().resolve()
    if not archive.is_file():
        raise FileNotFoundError(f"preprocessed archive not found: {archive}")
    expected = _metadata(metadata_path)

    frames: dict[tuple[str, str, str], list[tuple[str, int]]] = defaultdict(list)
    audio: dict[tuple[str, str, str], list[tuple[str, int]]] = defaultdict(list)
    extension_counts: Counter[str] = Counter()
    member_count = 0
    file_count = 0
    zero_byte_count = 0
    unsafe_member_count = 0
    unsupported_member_count = 0
    duplicate_destination_count = 0
    seen_destinations: set[str] = set()
    errors: list[str] = []

    def add_error(message: str) -> None:
        if len(errors) < 100:
            errors.append(message)

    with tarfile.open(archive, "r:*") as handle:
        for member in handle:
            member_count += 1
            name = member.name.replace("\\", "/")
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts or not pure.parts:
                unsafe_member_count += 1
                add_error(f"unsafe archive member: {name}")
                continue
            if member.isdir():
                continue
            if not member.isfile():
                unsupported_member_count += 1
                add_error(f"unsupported archive member type: {name}")
                continue
            file_count += 1
            destination_key = pure.as_posix().casefold()
            if destination_key in seen_destinations:
                duplicate_destination_count += 1
                add_error(f"duplicate archive destination: {name}")
                continue
            seen_destinations.add(destination_key)
            if member.size <= 0:
                zero_byte_count += 1
                add_error(f"zero-byte file: {name}")
            extension_counts[pure.suffix.lower()] += 1
            parts = pure.parts
            if len(parts) == 6 and parts[0] == ARCHIVE_ROOT and parts[2] == "video":
                _, split, _, category, sample_id, filename = parts
                frames[(split, category, sample_id)].append((filename, member.size))
            elif len(parts) == 5 and parts[0] == ARCHIVE_ROOT and parts[2] == "audio":
                _, split, _, category, filename = parts
                sample_id = PurePosixPath(filename).stem
                if PurePosixPath(filename).suffix.lower() != ".wav":
                    add_error(f"non-WAV audio member: {name}")
                audio[(split, category, sample_id)].append((filename, member.size))
            else:
                add_error(f"unexpected regular-file layout: {name}")

    observed = set(frames) | set(audio)
    missing = sorted(expected.keys() - observed)
    extra = sorted(observed - expected.keys())
    if missing:
        add_error(f"metadata samples missing from archive: {len(missing)}")
    if extra:
        add_error(f"archive samples absent from metadata: {len(extra)}")

    logical_rows: list[str] = []
    for key in sorted(expected):
        frame_entries = sorted(frames.get(key, []))
        frame_names = tuple(name for name, _ in frame_entries)
        audio_entries = audio.get(key, [])
        if frame_names != OFFICIAL_FRAME_NAMES:
            add_error(
                f"{'/'.join(key)}: visual layout must be exactly "
                "00000001.jpg through 00000010.jpg"
            )
        if len(audio_entries) != 1 or audio_entries[0][0] != f"{key[2]}.wav":
            add_error(f"{'/'.join(key)}: requires exactly one ID-matched WAV")
        audio_size = audio_entries[0][1] if len(audio_entries) == 1 else -1
        frame_sizes = ",".join(str(size) for _, size in frame_entries)
        logical_rows.append(
            "\0".join((*key, str(audio_size), frame_sizes))
        )

    split_counts = dict(
        sorted(Counter(split for split, _, _ in expected).items())
    )
    if enforce_official_counts and split_counts != OFFICIAL_SPLIT_COUNTS:
        add_error(f"official split counts mismatch: {split_counts}")
    metadata_bijection_verified = not missing and not extra
    logical_layout_sha256 = hashlib.sha256(
        ("\n".join(logical_rows) + "\n").encode("utf-8")
    ).hexdigest()
    passed = not errors and not any(
        (
            zero_byte_count,
            unsafe_member_count,
            unsupported_member_count,
            duplicate_destination_count,
        )
    )
    return {
        "schema_version": 1,
        "status": "passed" if passed else "failed",
        "archive": archive.as_posix(),
        "archive_bytes": archive.stat().st_size,
        "metadata": metadata_path.as_posix(),
        "sample_count": len(expected),
        "split_counts": split_counts,
        "metadata_bijection_verified": metadata_bijection_verified,
        "missing_sample_count": len(missing),
        "extra_sample_count": len(extra),
        "missing_clip_ids": {
            split: sorted(key[2] for key in missing if key[0] == split)
            for split in OFFICIAL_SPLIT_COUNTS
        },
        "extra_clip_ids": {
            split: sorted(key[2] for key in extra if key[0] == split)
            for split in OFFICIAL_SPLIT_COUNTS
        },
        "duplicate_clip_ids": [],
        "duplicate_logical_basenames": [],
        "member_count": member_count,
        "file_count": file_count,
        "zero_byte_count": zero_byte_count,
        "unsafe_member_count": unsafe_member_count,
        "unsupported_member_count": unsupported_member_count,
        "duplicate_destination_count": duplicate_destination_count,
        "extension_counts": dict(sorted(extension_counts.items())),
        "canonical_visual_extension": ".jpg",
        "canonical_frame_names": list(OFFICIAL_FRAME_NAMES),
        "logical_layout_sha256": logical_layout_sha256,
        "zero_byte_files": [],
        "errors": errors,
        "warnings": [],
        "error_output_truncated": len(errors) >= 100,
    }


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    try:
        with partial.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(partial, path)
    finally:
        if partial.exists():
            partial.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--meta-csv", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--no-enforce-official-counts", action="store_true")
    args = parser.parse_args()
    report = audit_preprocessed_archive(
        args.archive,
        args.meta_csv,
        enforce_official_counts=not args.no_enforce_official_counts,
    )
    _atomic_write(args.output, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
