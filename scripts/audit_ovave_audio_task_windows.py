#!/usr/bin/env python3
"""Audit every official WAV against the fixed ten-second/T=10 task window."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Callable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.teachers.common import load_records


EXPECTED_COUNTS = {"train": 13_182, "val": 5_798, "test": 5_820}
TASK_SEGMENTS = 10
TASK_DURATION_SECONDS = 10
SAMPLE_RATE = 16_000


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _soundfile_info(path: Path) -> tuple[int, int]:
    try:
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError("Audio task-window audit requires soundfile") from exc
    info = sf.info(str(path))
    return int(info.frames), int(info.samplerate)


def _canonical_timestamps() -> list[list[float]]:
    return [[float(index), float(index + 1)] for index in range(TASK_SEGMENTS)]


def audit_audio_task_windows(
    *,
    manifests: Mapping[str, str | Path],
    path_root: str | Path,
    expected_counts: Mapping[str, int] = EXPECTED_COUNTS,
    info_reader: Callable[[Path], tuple[int, int]] = _soundfile_info,
) -> dict[str, Any]:
    root = Path(path_root).expanduser().resolve()
    errors: list[dict[str, Any]] = []
    manifest_evidence: dict[str, dict[str, Any]] = {}
    split_counts: dict[str, int] = {}
    fit_counts = {
        "zero_pad_to_task_duration": 0,
        "unchanged": 0,
        "truncate_to_task_duration": 0,
    }
    zero_padding_samples = 0
    truncated_samples = 0
    frame_histogram: dict[str, int] = {}
    sample_rate_histogram: dict[str, int] = {}
    shortest: dict[str, Any] | None = None
    longest: dict[str, Any] | None = None
    seen_audio_paths: set[Path] = set()

    for split, raw_manifest in manifests.items():
        manifest = Path(raw_manifest).expanduser().resolve()
        records = load_records(manifest)
        split_counts[str(split)] = len(records)
        manifest_evidence[str(split)] = {
            "path": str(manifest),
            "bytes": manifest.stat().st_size,
            "sha256": _sha256(manifest),
        }
        expected = expected_counts.get(str(split))
        if expected is not None and len(records) != int(expected):
            errors.append(
                {
                    "code": "split_count",
                    "split": str(split),
                    "record_id": None,
                    "detail": f"expected {int(expected)} records, found {len(records)}",
                }
            )
        for record in records:
            record_id = str(record.get("id", ""))
            labels = record.get("segment_labels")
            timestamps = record.get("segment_timestamps")
            if labels is None or len(labels) != TASK_SEGMENTS or timestamps != _canonical_timestamps():
                errors.append(
                    {
                        "code": "temporal_protocol",
                        "split": str(split),
                        "record_id": record_id,
                        "detail": "record must contain ten labels and exact [0,1] through [9,10] timestamps",
                    }
                )
                continue
            raw_audio_path = record.get("audio_path")
            if not isinstance(raw_audio_path, str) or not raw_audio_path:
                errors.append(
                    {
                        "code": "audio_path",
                        "split": str(split),
                        "record_id": record_id,
                        "detail": "audio_path is missing",
                    }
                )
                continue
            audio_path = Path(raw_audio_path).expanduser()
            if not audio_path.is_absolute():
                audio_path = root / audio_path
            audio_path = audio_path.resolve()
            if audio_path in seen_audio_paths:
                errors.append(
                    {
                        "code": "duplicate_audio_path",
                        "split": str(split),
                        "record_id": record_id,
                        "detail": str(audio_path),
                    }
                )
                continue
            seen_audio_paths.add(audio_path)
            if not audio_path.is_file() or audio_path.stat().st_size <= 0:
                errors.append(
                    {
                        "code": "audio_file",
                        "split": str(split),
                        "record_id": record_id,
                        "detail": f"missing or zero-byte WAV: {audio_path}",
                    }
                )
                continue
            try:
                frames, sample_rate = info_reader(audio_path)
            except Exception as exc:
                errors.append(
                    {
                        "code": "audio_probe",
                        "split": str(split),
                        "record_id": record_id,
                        "detail": f"{type(exc).__name__}: {exc}",
                    }
                )
                continue
            frame_histogram[str(frames)] = frame_histogram.get(str(frames), 0) + 1
            sample_rate_histogram[str(sample_rate)] = (
                sample_rate_histogram.get(str(sample_rate), 0) + 1
            )
            descriptor = {
                "split": str(split),
                "record_id": record_id,
                "frames": int(frames),
                "sample_rate": int(sample_rate),
                "duration_seconds": float(frames / sample_rate) if sample_rate > 0 else None,
            }
            if shortest is None or int(frames) * int(shortest["sample_rate"]) < int(
                shortest["frames"]
            ) * int(sample_rate):
                shortest = descriptor
            if longest is None or int(frames) * int(longest["sample_rate"]) > int(
                longest["frames"]
            ) * int(sample_rate):
                longest = descriptor
            if sample_rate != SAMPLE_RATE or frames <= 0:
                errors.append(
                    {
                        "code": "audio_format",
                        "split": str(split),
                        "record_id": record_id,
                        "detail": f"expected positive 16 kHz WAV, found frames={frames}, sample_rate={sample_rate}",
                    }
                )
                continue
            target_frames = SAMPLE_RATE * TASK_DURATION_SECONDS
            if frames < target_frames:
                fit_counts["zero_pad_to_task_duration"] += 1
                zero_padding_samples += target_frames - frames
            elif frames > target_frames:
                fit_counts["truncate_to_task_duration"] += 1
                truncated_samples += frames - target_frames
            else:
                fit_counts["unchanged"] += 1

    record_count = sum(split_counts.values())
    return {
        "schema_version": 1,
        "status": "passed" if not errors else "failed",
        "source": "official_preprocessed_wav",
        "task_segments": TASK_SEGMENTS,
        "task_duration_seconds": TASK_DURATION_SECONDS,
        "required_sample_rate": SAMPLE_RATE,
        "short_waveform_policy": "zero_pad_to_task_duration",
        "long_waveform_policy": "truncate_to_task_duration",
        "temporal_resampling_performed": False,
        "record_count": record_count,
        "split_counts": split_counts,
        "manifest_evidence": manifest_evidence,
        "waveform_fit_counts": fit_counts,
        "zero_padding_samples": zero_padding_samples,
        "truncated_samples": truncated_samples,
        "sample_rate_histogram": dict(sorted(sample_rate_histogram.items())),
        "frame_count_histogram": dict(
            sorted(frame_histogram.items(), key=lambda item: int(item[0]))
        ),
        "shortest_waveform": shortest,
        "longest_waveform": longest,
        "errors": errors,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path-root", default=".")
    parser.add_argument("--train-manifest", default="data/ov_ave/source/train.jsonl")
    parser.add_argument("--val-manifest", default="data/ov_ave/source/val.jsonl")
    parser.add_argument("--test-manifest", default="data/ov_ave/source/test.jsonl")
    parser.add_argument(
        "--output", default="reports/data/official_audio_task_window_audit.json"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = audit_audio_task_windows(
        manifests={
            "train": args.train_manifest,
            "val": args.val_manifest,
            "test": args.test_manifest,
        },
        path_root=args.path_root,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
