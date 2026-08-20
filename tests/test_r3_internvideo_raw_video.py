from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import torch
import yaml

from scripts.export_teacher_artifacts import build_teachers
from src.teachers import TeacherExportBundle
from src.teachers.internvideo2_visual import (
    DecodedVideo,
    InternVideo2ClipB14Teacher,
    deterministic_video_timestamps,
)
from src.teachers.pipeline import export_manifest_records


def test_deterministic_timestamp_plan_uses_official_middle_sampling_on_16fps_grid() -> None:
    timestamps = deterministic_video_timestamps(
        duration_seconds=10,
        intervals=10,
        sampling_fps=16,
        frames_per_interval=8,
    )

    assert timestamps.shape == (10, 8)
    assert timestamps[0].tolist() == pytest.approx(
        [0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875]
    )
    for interval_index, row in enumerate(timestamps):
        assert np.all(row >= interval_index)
        assert np.all(row < interval_index + 1)
        assert np.allclose(row * 16, np.rint(row * 16))


def test_raw_video_decoder_must_supply_all_80_timestamped_frames(tmp_path) -> None:
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"video fixture")
    observed: list[np.ndarray] = []

    def fake_decoder(path, timestamps):
        assert path == video.resolve()
        observed.append(np.asarray(timestamps))
        frames = np.arange(80 * 2 * 2 * 3, dtype=np.uint8).reshape(80, 2, 2, 3)
        return DecodedVideo(frames=frames, duration_seconds=10.0, source_fps=30.0)

    teacher = InternVideo2ClipB14Teacher.__new__(InternVideo2ClipB14Teacher)
    teacher.num_frames = 8
    teacher.intervals = 10
    teacher.video_duration_seconds = 10
    teacher.sampling_fps = 16
    teacher._decode_video = fake_decoder
    teacher.model = SimpleNamespace(transform=lambda value: value.float())

    tensor = teacher._load_video_tensor(video)

    assert tensor.shape == (10, 8, 3, 2, 2)
    assert observed[0].shape == (10, 8)


def test_missing_or_short_raw_video_blocks_without_png_fallback(tmp_path) -> None:
    teacher = InternVideo2ClipB14Teacher.__new__(InternVideo2ClipB14Teacher)
    teacher.num_frames = 8
    teacher.intervals = 10
    teacher.video_duration_seconds = 10
    teacher.sampling_fps = 16
    teacher.model = SimpleNamespace(transform=lambda value: value.float())
    teacher._decode_video = lambda path, timestamps: DecodedVideo(
        frames=np.zeros((80, 2, 2, 3), dtype=np.uint8),
        duration_seconds=9.5,
        source_fps=30.0,
    )

    with pytest.raises(FileNotFoundError, match="raw video"):
        teacher._load_video_tensor(tmp_path / "missing.mp4")

    short = tmp_path / "short.mp4"
    short.write_bytes(b"short video")
    with pytest.raises(ValueError, match="10-second raw video"):
        teacher._load_video_tensor(short)


class _RawVideoTeacher:
    def __init__(self) -> None:
        self.paths: list[str] = []

    def export_video(self, video_path, query):
        self.paths.append(str(video_path))
        return np.ones((10, 512), dtype=np.float32), np.ones(10, dtype=np.float32)


def test_teacher_pipeline_routes_real_visual_teacher_to_raw_video_only(tmp_path) -> None:
    raw_video = tmp_path / "clip.mp4"
    raw_video.write_bytes(b"fixture")
    teacher = _RawVideoTeacher()
    records = [
        {
            "id": "clip-1",
            "query": "event",
            "segment_labels": [0, 1] * 5,
            "raw_video_path": str(raw_video),
        }
    ]

    summary = export_manifest_records(
        records=records,
        artifact_dir=tmp_path / "cache",
        output_manifest=tmp_path / "exported.jsonl",
        teachers=TeacherExportBundle(strong_visual=teacher),
        source_manifest_sha256="1" * 64,
        teacher_lock_sha256="2" * 64,
        split="train",
    )

    assert summary["records_exported"] == 1
    assert teacher.paths == [str(raw_video.resolve())]


def test_teacher_pipeline_blocks_when_raw_video_field_is_missing(tmp_path) -> None:
    records = [{"id": "clip-1", "query": "event", "segment_labels": [0, 1] * 5}]

    with pytest.raises(ValueError, match="raw video"):
        export_manifest_records(
            records=records,
            artifact_dir=tmp_path / "cache",
            output_manifest=tmp_path / "exported.jsonl",
            teachers=TeacherExportBundle(strong_visual=_RawVideoTeacher()),
            source_manifest_sha256="1" * 64,
            teacher_lock_sha256="2" * 64,
            split="train",
        )


def test_export_builder_passes_all_raw_video_geometry_to_internvideo_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    config = yaml.safe_load(
        (project_root / "configs/ov_orthkd_mm26_repro.yaml").read_text(encoding="utf-8")
    )
    config["teacher_export"]["weak_audio_backend"] = "mock"
    config["teacher_export"]["text_backend"] = "mock"
    observed: dict[str, object] = {}

    class FakeInternVideo:
        def __init__(self, **kwargs):
            observed.update(kwargs)

    monkeypatch.setattr(
        "src.teachers.internvideo2_visual.InternVideo2ClipB14Teacher", FakeInternVideo
    )
    args = SimpleNamespace(
        device=None,
        strong_visual_backend=None,
        weak_audio_backend=None,
        text_backend=None,
        internvideo2_repo_root=None,
        internvideo2_vision_ckpt=None,
        internvideo2_text_ckpt=None,
        internvideo2_extra_ckpt=None,
        internvideo2_num_frames=None,
        beats_repo_root=None,
        beats_ckpt=None,
        clap_repo_root=None,
        clap_ckpt=None,
        clap_version=None,
        clap_normalize=False,
        artifact_dir=None,
    )

    build_teachers(args, config)

    assert observed["video_duration_seconds"] == 10
    assert observed["intervals"] == 10
    assert observed["sampling_fps"] == 16
    assert observed["num_frames"] == 8
