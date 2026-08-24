from __future__ import annotations

from pathlib import Path
import importlib
import io
import tarfile
import wave

from PIL import Image
import pytest

from scripts.build_ov_avebench_source_manifests import (
    CANONICAL_MODE,
    build_official_record,
)
from scripts.discover_ovave_layout import discover_layout


OFFICIAL_JPG_NAMES = tuple(f"{index:08d}.jpg" for index in range(1, 11))


def _audit_archive():
    try:
        module = importlib.import_module(
            "scripts.audit_ovave_preprocessed_archive_layout"
        )
    except ModuleNotFoundError:
        pytest.fail("preprocessed archive layout auditor is missing")
    return module.audit_preprocessed_archive


def _write_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 1600)


def _write_clip(root: Path, names: tuple[str, ...]) -> Path:
    video_dir = root / "val" / "video" / "cat" / "abcdefghijk"
    video_dir.mkdir(parents=True)
    for name in names:
        Image.new("RGB", (12, 8), color=(1, 2, 3)).save(video_dir / name)
    _write_wav(root / "val" / "audio" / "cat" / "abcdefghijk.wav")
    raw_video = root.parent / "raw" / "abcdefghijk.mp4"
    raw_video.parent.mkdir()
    raw_video.write_bytes(b"official raw fixture")
    return raw_video


def _build(root: Path, raw_video: Path) -> dict:
    return build_official_record(
        dataset_root=root,
        row={
            "split": "val",
            "cls_name": "cat",
            "cls_type": "open",
            "vid_name": "abcdefghijk",
        },
        annotations={"abcdefghijk": {"label": [0] * 10}},
        raw_video_path=raw_video,
        path_root=root.parent,
        path_mode="relative_to_path_root",
    )


def test_official_jpg_sequence_is_the_only_canonical_visual_layout(
    tmp_path: Path,
) -> None:
    dataset_root = tmp_path / "dataset"
    raw_video = _write_clip(dataset_root, OFFICIAL_JPG_NAMES)

    record = _build(dataset_root, raw_video)

    assert CANONICAL_MODE == "canonical_official_jpg_wav"
    assert [Path(group[0]).name for group in record["frame_paths"]] == list(
        OFFICIAL_JPG_NAMES
    )
    assert record["meta"]["canonical_visual_extension"] == ".jpg"


def test_canonical_builder_records_zero_byte_raw_video_as_optional_diagnostic(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    raw_video = _write_clip(dataset_root, OFFICIAL_JPG_NAMES)
    raw_video.write_bytes(b"")

    record = _build(dataset_root, raw_video)

    assert "raw_video_path" not in record
    assert record["meta"]["raw_video_diagnostic"] == {
        "available": False,
        "status": "zero_byte_optional_input",
    }


@pytest.mark.parametrize(
    "names",
    [
        OFFICIAL_JPG_NAMES[:-1],
        OFFICIAL_JPG_NAMES + ("00000011.jpg",),
        OFFICIAL_JPG_NAMES[:-1] + ("00000010.png",),
        OFFICIAL_JPG_NAMES[:-1] + ("frame10.jpg",),
    ],
)
def test_canonical_builder_rejects_missing_extra_mixed_or_misnamed_frames(
    tmp_path: Path, names: tuple[str, ...]
) -> None:
    dataset_root = tmp_path / "dataset"
    raw_video = _write_clip(dataset_root, names)

    with pytest.raises(ValueError, match="00000001.jpg through 00000010.jpg"):
        _build(dataset_root, raw_video)


def test_layout_discovery_records_jpg_as_canonical_extension(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    for split in ("train", "val", "test"):
        video_dir = dataset_root / split / "video" / "cat" / f"{split}_clip"
        video_dir.mkdir(parents=True)
        for name in OFFICIAL_JPG_NAMES:
            Image.new("RGB", (12, 8)).save(video_dir / name)
        _write_wav(dataset_root / split / "audio" / "cat" / f"{split}_clip.wav")

    report = discover_layout(dataset_root)

    assert report["status"] == "passed"
    assert report["canonical_visual_extension"] == ".jpg"
    assert report["visual_dimensions"] == {"12x8x3": 30}
    assert report["visual_segment_count_histogram"] == {"10": 3}
    assert report["warnings"] == []


def _add_tar_bytes(handle: tarfile.TarFile, name: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    handle.addfile(info, io.BytesIO(payload))


def _write_archive_fixture(
    tmp_path: Path, *, corrupt_frame_name: str | None = None
) -> tuple[Path, Path]:
    archive = tmp_path / "official.tar.gz"
    metadata = tmp_path / "meta.csv"
    metadata.write_text(
        "split,cls_name,cls_type,vid_name\n"
        "train,cat,close,train_clip\n"
        "val,cat,open,val_clip\n"
        "test,cat,open,test_clip\n",
        encoding="utf-8",
    )
    with tarfile.open(archive, "w:gz") as handle:
        for split in ("train", "val", "test"):
            clip_id = f"{split}_clip"
            audio = f"ovave_dataset_preprocessed/{split}/audio/cat/{clip_id}.wav"
            _add_tar_bytes(handle, audio, b"wav")
            for index, frame_name in enumerate(OFFICIAL_JPG_NAMES):
                if corrupt_frame_name is not None and split == "val" and index == 9:
                    frame_name = corrupt_frame_name
                frame = (
                    f"ovave_dataset_preprocessed/{split}/video/cat/"
                    f"{clip_id}/{frame_name}"
                )
                _add_tar_bytes(handle, frame, b"jpg")
    return archive, metadata


def test_archive_auditor_verifies_full_metadata_layout_bijection(
    tmp_path: Path,
) -> None:
    archive, metadata = _write_archive_fixture(tmp_path)

    report = _audit_archive()(
        archive, metadata, enforce_official_counts=False
    )

    assert report["status"] == "passed"
    assert report["sample_count"] == 3
    assert report["split_counts"] == {"test": 1, "train": 1, "val": 1}
    assert report["extension_counts"] == {".jpg": 30, ".wav": 3}
    assert report["metadata_bijection_verified"] is True
    assert len(report["logical_layout_sha256"]) == 64


@pytest.mark.parametrize(
    "corrupt_frame_name",
    ["00000010.png", "00000011.jpg", "frame10.jpg"],
)
def test_archive_auditor_rejects_mixed_extra_or_misnamed_frame(
    tmp_path: Path, corrupt_frame_name: str
) -> None:
    archive, metadata = _write_archive_fixture(
        tmp_path, corrupt_frame_name=corrupt_frame_name
    )

    report = _audit_archive()(
        archive, metadata, enforce_official_counts=False
    )

    assert report["status"] == "failed"
    assert any("00000001.jpg through 00000010.jpg" in error for error in report["errors"])
