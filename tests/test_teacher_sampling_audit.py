from __future__ import annotations

from pathlib import Path
import json

import numpy as np
import pytest

from scripts.audit_teacher_sampling import (
    RawVideoUnavailable,
    audit_sampling_availability,
    compare_sampling_receipts,
    segment_time_bounds,
    select_stratified_mixed_records,
    sample_segment_timestamps,
    validate_raw_video,
)


def _records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for index in range(18):
        labels = [0] * 10
        if index % 3 == 0:
            labels[2:4] = [1, 1]
        elif index % 3 == 1:
            labels[5] = 1
        records.append(
            {
                "id": f"v{index:02d}",
                "query": f"q{index % 3}",
                "segment_labels": labels,
                "frame_paths": [],
                "meta": {"raw_video_diagnostic": {"available": False}},
            }
        )
    return records


def test_stratified_selection_is_deterministic_and_mixed_only() -> None:
    first = select_stratified_mixed_records(_records(), count=9, seed=42)
    second = select_stratified_mixed_records(_records(), count=9, seed=42)
    assert [row["id"] for row in first] == [row["id"] for row in second]
    assert len(first) == 9
    assert all(0 < sum(row["segment_labels"]) < 10 for row in first)


def test_segment_sampling_uses_exact_one_second_task_boundaries() -> None:
    assert segment_time_bounds(0) == (0.0, 1.0)
    assert segment_time_bounds(9) == (9.0, 10.0)
    timestamps = sample_segment_timestamps(3, frame_count=8)
    np.testing.assert_allclose(timestamps, np.linspace(3.0 + 1.0 / 16.0, 4.0 - 1.0 / 16.0, 8))
    assert np.all(timestamps > 3.0)
    assert np.all(timestamps < 4.0)


def test_missing_or_non_video_inputs_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(RawVideoUnavailable):
        validate_raw_video(tmp_path / "missing.mp4")
    non_video = tmp_path / "not_a_video.txt"
    non_video.write_text("not a video", encoding="utf-8")
    with pytest.raises(RawVideoUnavailable):
        validate_raw_video(non_video)


def test_sampling_comparison_reports_geometry_and_tie_aware_logits() -> None:
    repeat = np.zeros((2, 10, 3), dtype=np.float32)
    multiframe = repeat.copy()
    labels = np.zeros((2, 10), dtype=np.int64)
    labels[:, 0] = 1
    repeat_logits = np.zeros((2, 10), dtype=np.float32)
    multiframe_logits = repeat_logits.copy()
    result = compare_sampling_receipts(
        repeat,
        multiframe,
        labels,
        np.zeros((2, 4), dtype=np.float32),
        np.asarray([0, 10, 20]),
        repeat_logits=repeat_logits,
        multiframe_logits=multiframe_logits,
        source_hashes={"raw_videos": ["a"]},
    )
    assert result["protocol"]["task_segments"] == 10
    assert result["geometry"]["mean_cosine"] == 0.0
    assert result["direct_logits"]["repeat_keyframe"]["mixed"]["pair_weighted_concordance"] == pytest.approx(0.5)
    assert result["direct_logits"]["repeat_keyframe"]["shuffle"]["repeats"] == 100
    assert "onset_auroc" in result["direct_logits"]["repeat_keyframe"]["transitions"]


def test_positive_sampling_branch_encodes_and_compares_without_cache_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = []
    for index in range(4):
        raw_video = tmp_path / f"v{index}.mp4"
        raw_video.write_bytes(f"video-{index}".encode("ascii"))
        repeat_features = np.zeros((10, 512), dtype=np.float32)
        repeat_features[:, 0] = np.linspace(0.0, 1.0, 10)
        repeat_logits = np.linspace(-1.0, 1.0, 10, dtype=np.float32)
        query = np.asarray([float(index), 1.0], dtype=np.float32)
        feature_path = tmp_path / f"repeat-feature-{index}.npy"
        logit_path = tmp_path / f"repeat-logit-{index}.npy"
        query_path = tmp_path / f"query-{index}.npy"
        np.save(feature_path, repeat_features)
        np.save(logit_path, repeat_logits)
        np.save(query_path, query)
        labels = [0] * 10
        labels[2 + index : 4 + index] = [1, 1]
        records.append(
            {
                "id": f"v{index}",
                "query": f"q{index % 2}",
                "segment_labels": labels,
                "raw_video_path": str(raw_video),
                "strong_teacher_features_path": str(feature_path),
                "strong_teacher_logits_path": str(logit_path),
                "text_embedding_path": str(query_path),
                "meta": {"raw_video_diagnostic": {"available": True}},
            }
        )
    manifest = tmp_path / "validation.jsonl"
    manifest.write_text(
        "".join(f"{json.dumps(record)}\n" for record in records), encoding="utf-8"
    )

    def fake_sample(_path: Path, segment_index: int, frame_count: int):
        frames = np.full((frame_count, 2, 2, 3), segment_index, dtype=np.uint8)
        return frames, sample_segment_timestamps(segment_index, frame_count)

    monkeypatch.setattr("scripts.audit_teacher_sampling.sample_segment_frames", fake_sample)

    class FakeTeacher:
        def export_frame_array(self, frames: np.ndarray, query: str):
            assert frames.shape == (10, 8, 2, 2, 3)
            features = np.zeros((10, 512), dtype=np.float32)
            features[:, 0] = np.linspace(0.0, 1.0, 10)
            features[:, 1] = np.arange(10)
            features[:, 2] = 1.0
            logits = np.linspace(-2.0, 2.0, 10, dtype=np.float32)
            return features, logits

    train_features = np.stack(
        [
            np.stack(
                [np.arange(10), np.ones(10) * index, np.linspace(0, 1, 10)], axis=-1
            )
            for index in range(6)
        ]
    ).astype(np.float32)
    train_features = np.pad(train_features, ((0, 0), (0, 0), (0, 509)))
    train_labels = np.zeros((6, 10), dtype=np.int64)
    train_labels[:, 3:6] = 1
    probe_train = {
        "ids": np.asarray([f"train-{index}" for index in range(6)]),
        "queries": np.stack(
            [np.asarray([float(index), 1.0]) for index in range(6)]
        ).astype(np.float32),
        "features": train_features,
        "labels": train_labels,
    }

    result = audit_sampling_availability(
        manifest,
        output=tmp_path / "sampling.json",
        count=4,
        seed=42,
        raw_teacher=FakeTeacher(),
        probe_train=probe_train,
    )

    assert result["status"] == "PASS"
    assert result["comparison"]["query_conditioned_feature_probe"] is not None
    assert result["comparison"]["direct_logits"]["uniform_8"]["shuffle"]["repeats"] == 100
    assert "all_transition_auroc" in result["comparison"]["direct_logits"]["uniform_8"]["transitions"]
    assert result["comparison"]["feature_temporal_statistics"]["uniform_8"]["centered_temporal_rms"] > 0
    assert not list(tmp_path.rglob("*.pt"))
