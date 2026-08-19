#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.teachers import TeacherExportBundle, export_manifest_file
from src.teachers.common import write_records
from src.teachers.mock import MockStrongVisualTeacher, MockTextTeacher, MockWeakAudioTeacher


QUERIES = ("dog barking", "glass breaking", "engine idling", "playing violin")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create bounded, deterministic mock-only MM26 smoke data")
    parser.add_argument("--root", default=".", help="Repository root receiving ignored data/ fixture files")
    parser.add_argument("--records-per-split", type=int, default=4)
    parser.add_argument("--segments", type=int, default=2)
    parser.add_argument("--image-size", type=int, default=64)
    return parser.parse_args()


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _write_rgb(path: Path, rng: np.random.Generator, image_size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    array = rng.integers(0, 256, size=(image_size, image_size, 3), dtype=np.uint8)
    Image.fromarray(array).save(path)


def _source_records(
    root: Path,
    split: str,
    *,
    records_per_split: int,
    segments: int,
    image_size: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    split_seed = {"train": 1101, "val": 2202, "test": 3303}[split]
    rng = np.random.default_rng(split_seed)
    asset_root = root / "data" / "ov_ave_smoke" / "assets" / split

    for record_index in range(records_per_split):
        frame_paths: list[str] = []
        spectrogram_paths: list[str] = []
        audio_paths: list[str] = []
        for segment_index in range(segments):
            stem = f"record_{record_index:02d}_segment_{segment_index:02d}"
            frame_path = asset_root / "frames" / f"{stem}.png"
            spectrogram_path = asset_root / "spectrograms" / f"{stem}.png"
            audio_path = asset_root / "audio" / f"{stem}.npy"
            _write_rgb(frame_path, rng, image_size)
            _write_rgb(spectrogram_path, rng, image_size)
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            np.save(audio_path, np.zeros(1600, dtype=np.float32))
            frame_paths.append(_relative(frame_path, root))
            spectrogram_paths.append(_relative(spectrogram_path, root))
            audio_paths.append(_relative(audio_path, root))

        records.append(
            {
                "id": f"mock_{split}_{record_index:04d}",
                "query": QUERIES[record_index % len(QUERIES)],
                "category": QUERIES[record_index % len(QUERIES)],
                "split_type": "seen" if record_index % 2 == 0 else "unseen",
                "frame_paths": frame_paths,
                "spectrogram_paths": spectrogram_paths,
                "audio_paths": audio_paths,
                "segment_labels": [int((record_index + index) % 2 == 0) for index in range(segments)],
                "domain": "mock_only_r0",
                "meta": {"mock_only": True, "source_split": split},
            }
        )
    return records


def create_mm26_smoke_fixture(
    root: str | Path,
    *,
    records_per_split: int = 4,
    segments: int = 2,
    image_size: int = 64,
) -> dict[str, Any]:
    if not 1 <= records_per_split <= 32:
        raise ValueError("records_per_split must be in [1, 32] for a bounded smoke fixture")
    if not 1 <= segments <= 16:
        raise ValueError("segments must be in [1, 16]")
    if not 16 <= image_size <= 224:
        raise ValueError("image_size must be in [16, 224]")

    root_path = Path(root).resolve()
    manifest_root = root_path / "data" / "ov_ave_smoke"
    artifact_root = root_path / "data" / "teacher_cache" / "mm26_smoke"
    split_summaries: dict[str, Any] = {}
    for split in ("train", "val", "test"):
        source_manifest = manifest_root / "source" / f"{split}_source.jsonl"
        output_manifest = manifest_root / f"{split}.jsonl"
        records = _source_records(
            root_path,
            split,
            records_per_split=records_per_split,
            segments=segments,
            image_size=image_size,
        )
        write_records(source_manifest, records)
        split_summaries[split] = export_manifest_file(
            source_manifest=source_manifest,
            artifact_dir=artifact_root / split,
            output_manifest=output_manifest,
            teachers=TeacherExportBundle(
                strong_visual=MockStrongVisualTeacher(feature_dim=512),
                weak_audio=MockWeakAudioTeacher(feature_dim=768),
                text_teacher=MockTextTeacher(feature_dim=1024),
            ),
            overwrite=True,
        )

    return {
        "mock_only": True,
        "root": str(root_path),
        "records_per_split": records_per_split,
        "segments": segments,
        "splits": split_summaries,
    }


def main() -> None:
    args = parse_args()
    summary = create_mm26_smoke_fixture(
        args.root,
        records_per_split=args.records_per_split,
        segments=args.segments,
        image_size=args.image_size,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
