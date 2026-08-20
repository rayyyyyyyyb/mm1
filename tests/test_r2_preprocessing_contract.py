from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import wave
import zipfile

from PIL import Image
import pytest

try:
    from scripts.build_ov_avebench_source_manifests import (
        atomic_write_jsonl,
        build_official_record,
        natural_path_key,
        source_manifest_outputs,
    )
except ModuleNotFoundError:
    atomic_write_jsonl = None
    build_official_record = None
    natural_path_key = None
    source_manifest_outputs = None

try:
    from scripts.discover_ovave_layout import discover_layout
except ModuleNotFoundError:
    discover_layout = None

try:
    from scripts.safe_extract_official_archive import safe_extract_archive
except ModuleNotFoundError:
    safe_extract_archive = None

try:
    from scripts.safe_extract_archive import _reject_login_document
except ModuleNotFoundError:
    _reject_login_document = None


def _write_wav(path: Path, *, sample_rate: int = 16000, frames: int = 1600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * frames)


def _official_clip(
    root: Path, *, png_names: tuple[str, ...] = ("frame10.png", "frame2.png")
) -> Path:
    video = root / "val" / "video" / "cat" / "clip"
    video.mkdir(parents=True)
    for name in png_names:
        Image.new("RGB", (12, 8), color=(1, 2, 3)).save(video / name)
    _write_wav(root / "val" / "audio" / "cat" / "clip.wav")
    raw_video = root.parent / "raw-videos" / "clip.mp4"
    raw_video.parent.mkdir(parents=True, exist_ok=True)
    raw_video.write_bytes(b"official raw video fixture")
    return raw_video


def test_official_builder_naturally_sorts_png_and_never_repeats_frames(tmp_path: Path) -> None:
    assert build_official_record is not None, "canonical official-layout builder is missing"
    assert natural_path_key is not None, "natural path ordering is missing"
    dataset_root = tmp_path / "dataset"
    raw_video = _official_clip(dataset_root)

    record = build_official_record(
        dataset_root=dataset_root,
        row={"split": "val", "cls_name": "cat", "cls_type": "open", "vid_name": "clip"},
        annotations={"clip": {"label": [0, 1]}},
        raw_video_path=raw_video,
        path_root=tmp_path,
        path_mode="relative_to_path_root",
    )

    assert [Path(group[0]).name for group in record["frame_paths"]] == ["frame2.png", "frame10.png"]
    assert len({group[0] for group in record["frame_paths"]}) == 2
    assert record["audio_path"].endswith("clip.wav")
    assert record["raw_video_path"].endswith("clip.mp4")
    assert record["spectrogram_paths"] == []
    assert record["split_type"] == "unseen"
    assert record["meta"]["split_type"] == "unseen"
    assert record["meta"]["preprocessing_mode"] == "canonical_official_png_wav"


def test_official_builder_rejects_fewer_png_than_segments_instead_of_repeating(tmp_path: Path) -> None:
    assert build_official_record is not None, "canonical official-layout builder is missing"
    dataset_root = tmp_path / "dataset"
    raw_video = _official_clip(dataset_root, png_names=("only.png",))

    with pytest.raises(ValueError, match="exactly 2 PNG"):
        build_official_record(
            dataset_root=dataset_root,
            row={"split": "val", "cls_name": "cat", "cls_type": "open", "vid_name": "clip"},
            annotations={"clip": {"label": [0, 1]}},
            raw_video_path=raw_video,
            path_root=tmp_path,
            path_mode="relative_to_path_root",
        )


def test_absolute_path_mode_and_atomic_jsonl_publication(tmp_path: Path) -> None:
    assert build_official_record is not None, "canonical official-layout builder is missing"
    assert atomic_write_jsonl is not None, "atomic manifest writer is missing"
    dataset_root = tmp_path / "dataset"
    raw_video = _official_clip(dataset_root)
    record = build_official_record(
        dataset_root=dataset_root,
        row={"split": "val", "cls_name": "cat", "cls_type": "close", "vid_name": "clip"},
        annotations={"clip": {"label": [1, 0]}},
        raw_video_path=raw_video,
        path_root=tmp_path / "unrelated",
        path_mode="absolute",
    )
    output = tmp_path / "manifests" / "val_source.jsonl"

    atomic_write_jsonl(output, [record])

    assert Path(record["audio_path"]).is_absolute()
    assert json.loads(output.read_text(encoding="utf-8"))["id"] == "clip"
    assert not output.with_suffix(output.suffix + ".partial").exists()


def test_canonical_builder_blocks_missing_raw_video_and_uses_taskbook_output_names(
    tmp_path: Path,
) -> None:
    assert source_manifest_outputs is not None
    dataset_root = tmp_path / "dataset"
    raw_video = _official_clip(dataset_root)
    raw_video.unlink()

    with pytest.raises(FileNotFoundError, match="Missing official raw video"):
        build_official_record(
            dataset_root=dataset_root,
            row={"split": "val", "cls_name": "cat", "cls_type": "open", "vid_name": "clip"},
            annotations={"clip": {"label": [0, 1]}},
            raw_video_path=raw_video,
            path_root=tmp_path,
            path_mode="relative_to_path_root",
        )

    assert source_manifest_outputs(tmp_path / "source") == {
        "train": tmp_path / "source/train.jsonl",
        "val": tmp_path / "source/val.jsonl",
        "test": tmp_path / "source/test.jsonl",
    }


def test_safe_extract_accepts_zip_and_rejects_path_traversal(tmp_path: Path) -> None:
    assert safe_extract_archive is not None, "safe official archive extractor is missing"
    safe_zip = tmp_path / "safe.zip"
    with zipfile.ZipFile(safe_zip, "w") as archive:
        archive.writestr("dataset/train/example.txt", "ok")

    receipt = safe_extract_archive(safe_zip, tmp_path / "safe-output")

    assert receipt["status"] == "passed"
    assert receipt["extraction_status"] == "passed"
    assert receipt["files"] == 1
    assert (tmp_path / "safe-output" / "dataset" / "train" / "example.txt").read_text() == "ok"

    unsafe_zip = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(unsafe_zip, "w") as archive:
        archive.writestr("../escape.txt", "bad")
    with pytest.raises(ValueError, match="unsafe archive member"):
        safe_extract_archive(unsafe_zip, tmp_path / "unsafe-output")
    assert not (tmp_path / "escape.txt").exists()
    assert not (tmp_path / "unsafe-output").exists()


def test_official_archive_preflight_rejects_login_html(tmp_path: Path) -> None:
    assert _reject_login_document is not None
    downloaded = tmp_path / "download.bin"
    downloaded.write_bytes(b"  <!DOCTYPE html><title>Sign in</title>")

    with pytest.raises(ValueError, match="login document"):
        _reject_login_document(downloaded)


def test_layout_discovery_reports_png_and_wav_evidence(tmp_path: Path) -> None:
    assert discover_layout is not None, "official layout discovery is missing"
    dataset_root = tmp_path / "dataset"
    for split in ("train", "val", "test"):
        video = dataset_root / split / "video" / "cat" / f"{split}_clip"
        video.mkdir(parents=True)
        Image.new("RGB", (12, 8)).save(video / f"{split}_segment1.png")
        _write_wav(dataset_root / split / "audio" / "cat" / f"{split}_clip.wav")

    report = discover_layout(dataset_root)

    assert report["status"] == "passed"
    assert report["split_presence"] == {"test": True, "train": True, "val": True}
    assert report["extension_counts"][".png"] == 3
    assert report["extension_counts"][".wav"] == 3


def test_layout_discovery_verifies_metadata_file_bijection(tmp_path: Path) -> None:
    assert discover_layout is not None
    dataset_root = tmp_path / "dataset"
    rows = ["split,cls_name,cls_type,vid_name"]
    for split in ("train", "val", "test"):
        clip_id = f"{split}_clip"
        video = dataset_root / split / "video" / "cat" / clip_id
        video.mkdir(parents=True)
        Image.new("RGB", (12, 8)).save(video / f"{split}_segment1.png")
        _write_wav(dataset_root / split / "audio" / "cat" / f"{clip_id}.wav")
        rows.append(f"{split},cat,close,{clip_id}")
    metadata = tmp_path / "meta.csv"
    metadata.write_text("\n".join(rows) + "\n", encoding="utf-8")

    report = discover_layout(
        dataset_root,
        meta_csv=metadata,
        enforce_official_counts=False,
    )

    assert report["status"] == "passed"
    assert report["metadata_bijection_verified"] is True
    assert report["split_counts"] == {"test": 1, "train": 1, "val": 1}
    assert report["missing_clip_ids"] == {"test": [], "train": [], "val": []}
    assert report["extra_clip_ids"] == {"test": [], "train": [], "val": []}
    assert report["png_dimensions"] == {"12x8x3": 3}
    assert report["wav_sample_rates"] == {"16000": 3}


def test_layout_discovery_reports_global_basenames_without_rejecting_distinct_clips(
    tmp_path: Path,
) -> None:
    assert discover_layout is not None
    dataset_root = tmp_path / "dataset"
    rows = ["split,cls_name,cls_type,vid_name"]
    clips = [
        ("train", "cat_a", "train_a", "frame1.png"),
        ("train", "cat_b", "train_b", "frame1.png"),
        ("val", "cat", "val_clip", "val_frame.png"),
        ("test", "cat", "test_clip", "test_frame.png"),
    ]
    for split, category, clip_id, frame_name in clips:
        video = dataset_root / split / "video" / category / clip_id
        video.mkdir(parents=True)
        Image.new("RGB", (12, 8)).save(video / frame_name)
        _write_wav(dataset_root / split / "audio" / category / f"{clip_id}.wav")
        rows.append(f"{split},{category},close,{clip_id}")
    metadata = tmp_path / "meta.csv"
    metadata.write_text("\n".join(rows) + "\n", encoding="utf-8")

    report = discover_layout(
        dataset_root,
        meta_csv=metadata,
        enforce_official_counts=False,
    )

    assert report["status"] == "passed"
    assert report["duplicate_basenames"] == [
        {
            "basename": "frame1.png",
            "count": 2,
            "paths": [
                "train/video/cat_a/train_a/frame1.png",
                "train/video/cat_b/train_b/frame1.png",
            ],
        }
    ]
    assert report["duplicate_logical_basenames"] == []
    assert report["warnings"] == []


def test_layout_discovery_rejects_duplicate_basename_within_one_logical_clip(
    tmp_path: Path,
) -> None:
    assert discover_layout is not None
    dataset_root = tmp_path / "dataset"
    for category in ("cat_a", "cat_b"):
        video = dataset_root / "train" / "video" / category / "same_clip"
        video.mkdir(parents=True)
        Image.new("RGB", (12, 8)).save(video / "frame1.png")
    _write_wav(dataset_root / "train" / "audio" / "cat_a" / "same_clip.wav")
    for split in ("val", "test"):
        video = dataset_root / split / "video" / "cat" / f"{split}_clip"
        video.mkdir(parents=True)
        Image.new("RGB", (12, 8)).save(video / f"{split}_frame.png")
        _write_wav(dataset_root / split / "audio" / "cat" / f"{split}_clip.wav")
    metadata = tmp_path / "meta.csv"
    metadata.write_text(
        "split,cls_name,cls_type,vid_name\n"
        "train,cat_a,close,same_clip\n"
        "val,cat,close,val_clip\n"
        "test,cat,close,test_clip\n",
        encoding="utf-8",
    )

    report = discover_layout(
        dataset_root,
        meta_csv=metadata,
        enforce_official_counts=False,
    )

    assert report["status"] == "failed"
    assert report["duplicate_logical_basenames"][0]["logical_clip"] == "train/same_clip"
    assert any("duplicate basename within logical clip" in item["error"] for item in report["errors"])


def test_preprocessing_entrypoints_run_directly_from_repository_root() -> None:
    project_root = Path(__file__).resolve().parents[1]
    for script_name in (
        "build_ov_avebench_source_manifests.py",
        "safe_extract_official_archive.py",
        "safe_extract_archive.py",
        "discover_ovave_layout.py",
        "discover_ovave_raw_video_layout.py",
    ):
        completed = subprocess.run(
            [sys.executable, str(project_root / "scripts" / script_name), "--help"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
