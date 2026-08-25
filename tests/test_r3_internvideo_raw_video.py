from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image
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


def test_official_keyframe_is_decoded_and_transformed_once_before_eight_repeats(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "00000001.jpg"
    Image.fromarray(np.full((4, 5, 3), 127, dtype=np.uint8)).save(image_path)

    class DeterministicModel:
        def __init__(self) -> None:
            self.transform_calls = 0

        def transform(self, tensor: torch.Tensor) -> torch.Tensor:
            self.transform_calls += 1
            return tensor.float() / 255.0

    teacher = InternVideo2ClipB14Teacher.__new__(InternVideo2ClipB14Teacher)
    teacher.input_mode = "official_segment_keyframes"
    teacher.frame_expansion = "repeat_last_to_num_frames"
    teacher.num_frames = 8
    teacher.model = DeterministicModel()

    frames = teacher._load_segment_tensor([str(image_path)])

    assert teacher.model.transform_calls == 1
    assert list(frames.shape) == [8, 3, 4, 5]
    assert all(torch.equal(frames[0], frames[index]) for index in range(1, 8))


def test_raw_diagnostic_timestamp_plan_uses_middle_sampling_on_16fps_grid() -> None:
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


def test_canonical_teacher_repeats_each_official_keyframe_to_eight_model_frames(
    tmp_path: Path,
) -> None:
    keyframe = tmp_path / "00000001.jpg"
    Image.new("RGB", (3, 2), color=(7, 11, 13)).save(keyframe)
    teacher = InternVideo2ClipB14Teacher.__new__(InternVideo2ClipB14Teacher)
    teacher.input_mode = "official_segment_keyframes"
    teacher.num_frames = 8
    teacher.frame_expansion = "repeat_last_to_num_frames"
    teacher.model = SimpleNamespace(transform=lambda value: value.float())

    selected = teacher._select_frame_paths([str(keyframe)])
    tensor = teacher._load_segment_tensor([str(keyframe)])

    assert selected == [str(keyframe)] * 8
    assert tensor.shape == (8, 3, 2, 3)

    with pytest.raises(ValueError, match="exactly one official keyframe"):
        teacher._select_frame_paths([str(keyframe), str(keyframe)])


class _RawVideoTeacher:
    def __init__(self) -> None:
        self.input_mode = "raw_multiframe_diagnostic"
        self.paths: list[str] = []

    def export_video(self, video_path, query):
        self.paths.append(str(video_path))
        return np.ones((10, 512), dtype=np.float32), np.ones(10, dtype=np.float32)


def test_teacher_pipeline_routes_explicit_raw_diagnostic_mode_to_raw_video(tmp_path) -> None:
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
        teacher_identity_sha256="2" * 64,
        split="train",
    )

    assert summary["records_exported"] == 1
    assert teacher.paths == [str(raw_video.resolve())]


class _KeyframeTeacherWithBothInterfaces:
    def __init__(self) -> None:
        self.input_mode = "official_segment_keyframes"
        self.frame_groups: list[list[list[str]]] = []

    def export_video(self, video_path, query):
        raise AssertionError("canonical keyframe mode must not touch raw video")

    def export_segments(self, frame_groups, query):
        self.frame_groups.append(frame_groups)
        return np.ones((10, 512), dtype=np.float32), np.ones(10, dtype=np.float32)


def test_teacher_pipeline_routes_canonical_mode_to_ten_official_keyframes(tmp_path) -> None:
    teacher = _KeyframeTeacherWithBothInterfaces()
    frame_paths: list[list[str]] = []
    for index in range(1, 11):
        path = tmp_path / f"{index:08d}.jpg"
        path.write_bytes(b"fixture")
        frame_paths.append([str(path)])
    records = [
        {
            "id": "clip-1",
            "query": "event",
            "segment_labels": [0, 1] * 5,
            "frame_paths": frame_paths,
        }
    ]

    summary = export_manifest_records(
        records=records,
        artifact_dir=tmp_path / "cache",
        output_manifest=tmp_path / "exported.jsonl",
        teachers=TeacherExportBundle(strong_visual=teacher),
        source_manifest_sha256="1" * 64,
        teacher_identity_sha256="2" * 64,
        split="train",
    )

    assert summary["records_exported"] == 1
    assert len(teacher.frame_groups) == 1
    assert [Path(group[0]).name for group in teacher.frame_groups[0]] == [
        f"{index:08d}.jpg" for index in range(1, 11)
    ]


def test_teacher_pipeline_blocks_when_raw_video_field_is_missing(tmp_path) -> None:
    records = [{"id": "clip-1", "query": "event", "segment_labels": [0, 1] * 5}]

    with pytest.raises(ValueError, match="raw video"):
        export_manifest_records(
            records=records,
            artifact_dir=tmp_path / "cache",
            output_manifest=tmp_path / "exported.jsonl",
            teachers=TeacherExportBundle(strong_visual=_RawVideoTeacher()),
            source_manifest_sha256="1" * 64,
            teacher_identity_sha256="2" * 64,
            split="train",
        )


def test_export_builder_passes_canonical_keyframe_mode_and_optional_raw_geometry(
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

    assert observed["input_mode"] == "official_segment_keyframes"
    assert observed["task_segments"] == 10
    assert observed["num_frames"] == 8
    assert observed["frame_expansion"] == "repeat_last_to_num_frames"
    assert observed["raw_video_diagnostic"]["sampling_fps"] == 16
