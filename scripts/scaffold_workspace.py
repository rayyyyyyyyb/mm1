#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List


TEMPLATE_RECORDS: Dict[str, List[dict]] = {
    "train_source.template.jsonl": [
        {
            "id": "train_clip_0001",
            "query": "dog barking",
            "frame_paths": [
                [
                    "data/raw/ov_avebench_preprocessed/train_clip_0001/frames/seg_000/frame_000.jpg",
                    "data/raw/ov_avebench_preprocessed/train_clip_0001/frames/seg_000/frame_001.jpg",
                ],
                [
                    "data/raw/ov_avebench_preprocessed/train_clip_0001/frames/seg_001/frame_000.jpg",
                    "data/raw/ov_avebench_preprocessed/train_clip_0001/frames/seg_001/frame_001.jpg",
                ],
            ],
            "spectrogram_paths": [
                "data/raw/ov_avebench_preprocessed/train_clip_0001/specs/seg_000.jpg",
                "data/raw/ov_avebench_preprocessed/train_clip_0001/specs/seg_001.jpg",
            ],
            "audio_paths": [
                "data/raw/ov_avebench_preprocessed/train_clip_0001/audio/seg_000.wav",
                "data/raw/ov_avebench_preprocessed/train_clip_0001/audio/seg_001.wav",
            ],
            "segment_labels": [1, 0],
            "domain": "ov_avebench",
        }
    ],
    "val_source.template.jsonl": [
        {
            "id": "val_clip_0001",
            "query": "glass breaking",
            "frame_paths": [
                [
                    "data/raw/ov_avebench_preprocessed/val_clip_0001/frames/seg_000/frame_000.jpg",
                    "data/raw/ov_avebench_preprocessed/val_clip_0001/frames/seg_000/frame_001.jpg",
                ]
            ],
            "spectrogram_paths": [
                "data/raw/ov_avebench_preprocessed/val_clip_0001/specs/seg_000.jpg"
            ],
            "audio_paths": [
                "data/raw/ov_avebench_preprocessed/val_clip_0001/audio/seg_000.wav"
            ],
            "segment_labels": [1],
            "domain": "ov_avebench",
        }
    ],
    "test_source.template.jsonl": [
        {
            "id": "test_clip_0001",
            "query": "engine idling",
            "frame_paths": [
                [
                    "data/raw/ov_avebench_preprocessed/test_clip_0001/frames/seg_000/frame_000.jpg",
                    "data/raw/ov_avebench_preprocessed/test_clip_0001/frames/seg_000/frame_001.jpg",
                ]
            ],
            "spectrogram_paths": [
                "data/raw/ov_avebench_preprocessed/test_clip_0001/specs/seg_000.jpg"
            ],
            "audio_paths": [
                "data/raw/ov_avebench_preprocessed/test_clip_0001/audio/seg_000.wav"
            ],
            "segment_labels": [0],
            "domain": "ov_avebench",
        }
    ],
}


README_TEXT = """OV-OrthKD workspace scaffold
=================================

This folder was created by `python scripts/scaffold_workspace.py`.

What each folder is for:
- data/raw/: benchmark archives, extracted raw files, or manually downloaded upstream releases
- data/ov_ave/: source and exported manifests that the training code reads
- data/teacher_cache/ov_ave/: offline teacher artifacts written by export_teacher_artifacts.py
- weights/: teacher checkpoints
- outputs/: logs, configs, checkpoints, and preflight outputs

Template manifests:
- `*_source.template.jsonl` are examples, not ready-to-train files
- copy a template to `train_source.jsonl`, `val_source.jsonl`, or `test_source.jsonl`
- replace every path with your real local file paths
- keep `frame_paths`, `spectrogram_paths`, `audio_paths`, and `segment_labels` aligned by segment index

Two valid audio styles:
1. Per-segment audio files:
   - `audio_paths`: ["seg_000.wav", "seg_001.wav"]
2. One clip waveform plus timestamps:
   - `audio_path`: "clip.wav"
   - `segment_timestamps`: [[0.0, 1.0], [1.0, 2.0]]
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a beginner-friendly OV-OrthKD workspace scaffold.")
    parser.add_argument("--root", type=str, default=".", help="Repo root. Default: current directory")
    return parser.parse_args()


def write_jsonl(path: Path, records: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> None:
    args = parse_args()
    root = Path(args.root).resolve()

    for relpath in (
        "data/downloads",
        "data/raw/ave",
        "data/raw/unav100_meta",
        "data/raw/unav100_media",
        "data/raw/ov_avebench_raw",
        "data/raw/ov_avebench_preprocessed",
        "data/ov_ave",
        "data/teacher_cache/ov_ave",
        "outputs/ov_orthkd",
        "weights/internvideo2",
        "weights/beats",
        "weights/clap",
    ):
        (root / relpath).mkdir(parents=True, exist_ok=True)

    for filename, records in TEMPLATE_RECORDS.items():
        write_jsonl(root / "data/ov_ave" / filename, records)

    (root / "data/ov_ave" / "README.txt").write_text(README_TEXT, encoding="utf-8")

    summary = {
        "root": str(root),
        "created_dirs": [
            "data/downloads",
            "data/raw/ave",
            "data/raw/unav100_meta",
            "data/raw/unav100_media",
            "data/raw/ov_avebench_raw",
            "data/raw/ov_avebench_preprocessed",
            "data/ov_ave",
            "data/teacher_cache/ov_ave",
            "outputs/ov_orthkd",
            "weights/internvideo2",
            "weights/beats",
            "weights/clap",
        ],
        "template_manifests": [f"data/ov_ave/{name}" for name in TEMPLATE_RECORDS],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
