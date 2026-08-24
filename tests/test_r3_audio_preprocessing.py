from __future__ import annotations

import json
import numpy as np
import pytest
import torch

from src.data.audio_preprocessing import (
    AudioPreprocessingSpec,
    adapt_fbank_for_student,
    segment_and_repeat_waveform,
    waveform_to_fbank_segments,
)
from src.data.ov_avel_dataset import QueryConditionedOVAvelDataset


def _spec() -> AudioPreprocessingSpec:
    return AudioPreprocessingSpec(
        sample_rate=16_000,
        duration_seconds=10,
        segments=10,
        segment_seconds=1,
        repeat_waveform_to_seconds=2,
        num_mel_bins=128,
        frame_length_ms=25,
        frame_shift_ms=10,
        target_length=204,
        mean=-4.268,
        std=9.138,
        student_channels=3,
        student_size=(224, 224),
    )


def test_waveform_is_padded_or_truncated_then_split_and_repeated_exactly() -> None:
    spec = _spec()
    short = torch.arange(9 * 16_000, dtype=torch.float32)
    long = torch.arange(11 * 16_000, dtype=torch.float32)

    short_segments = segment_and_repeat_waveform(short, spec)
    long_segments = segment_and_repeat_waveform(long, spec)

    assert short_segments.shape == (10, 32_000)
    assert torch.equal(short_segments[0, :16_000], short[:16_000])
    assert torch.equal(short_segments[0, 16_000:], short[:16_000])
    assert torch.count_nonzero(short_segments[9]) == 0
    assert torch.equal(long_segments[9, :16_000], long[9 * 16_000 : 10 * 16_000])
    assert torch.equal(long_segments[9, 16_000:], long[9 * 16_000 : 10 * 16_000])


def test_kaldi_fbank_contract_is_10_by_1_by_128_by_204() -> None:
    spec = _spec()
    calls: list[dict[str, object]] = []

    def fake_fbank(waveform: torch.Tensor, **kwargs) -> torch.Tensor:
        calls.append({"shape": tuple(waveform.shape), **kwargs})
        return torch.full((200, 128), 2.0, dtype=torch.float32)

    output = waveform_to_fbank_segments(
        torch.zeros(160_000), spec, fbank_function=fake_fbank
    )

    assert output.shape == (10, 1, 128, 204)
    assert len(calls) == 10
    assert all(call["shape"] == (1, 32_000) for call in calls)
    assert all(call["sample_frequency"] == 16_000 for call in calls)
    assert all(call["num_mel_bins"] == 128 for call in calls)
    assert all(call["frame_length"] == 25 for call in calls)
    assert all(call["frame_shift"] == 10 for call in calls)
    assert torch.isfinite(output).all()
    expected = (2.0 - spec.mean) / spec.std
    assert output[0, 0, 0, 0].item() == pytest.approx(expected)


def test_each_repeated_segment_is_mean_centered_before_official_fbank() -> None:
    spec = _spec()
    observed_means: list[float] = []

    def fake_fbank(waveform: torch.Tensor, **kwargs) -> torch.Tensor:
        observed_means.append(float(waveform.mean()))
        return torch.zeros((204, 128), dtype=torch.float32)

    waveform = torch.arange(160_000, dtype=torch.float32)
    waveform_to_fbank_segments(waveform, spec, fbank_function=fake_fbank)

    # Official code mean-centres in float32, whose reduction leaves a tiny
    # residual for these deliberately large fixture values.
    assert max(abs(value) for value in observed_means) < 1e-2


def test_student_adapter_repeats_channels_resizes_and_stays_finite() -> None:
    fbank = torch.linspace(-1, 1, 10 * 128 * 204).reshape(10, 1, 128, 204)

    student = adapt_fbank_for_student(fbank, size=(224, 224), channels=3)

    assert student.shape == (10, 3, 224, 224)
    assert torch.equal(student[:, 0], student[:, 1])
    assert torch.equal(student[:, 1], student[:, 2])
    assert torch.isfinite(student).all()


def test_nonfinite_waveform_is_rejected() -> None:
    waveform = torch.zeros(160_000)
    waveform[1] = float("nan")

    with pytest.raises(ValueError, match="finite"):
        segment_and_repeat_waveform(waveform, _spec())


def test_canonical_dataset_uses_official_wav_not_legacy_spectrogram_images(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = tmp_path / "train.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "id": "clip-1",
                "query": "event",
                "split_type": "seen",
                "segment_labels": [0, 1] * 5,
                "wav_path": "audio/clip-1.wav",
                "segment_frame_paths": [[] for _ in range(10)],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    expected = torch.arange(10, dtype=torch.float32).reshape(10, 1, 1, 1).expand(10, 3, 224, 224)
    observed: list[str] = []
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio/clip-1.wav").write_bytes(b"fixture")

    def fake_load(path, spec):
        observed.append(str(path))
        assert spec == _spec()
        return expected

    monkeypatch.setattr("src.data.ov_avel_dataset.load_official_wav_for_student", fake_load)
    audio_config = {
        "sample_rate": 16_000,
        "duration_seconds": 10,
        "segments": 10,
        "segment_seconds": 1,
        "repeat_waveform_to_seconds": 2,
        "num_mel_bins": 128,
        "frame_length_ms": 25,
        "frame_shift_ms": 10,
        "target_length": 204,
        "mean": -4.268,
        "std": 9.138,
        "student_channels": 3,
        "student_resize": [224, 224],
    }
    dataset = QueryConditionedOVAvelDataset(
        str(manifest),
        path_root=str(tmp_path),
        preprocessing_mode="canonical_official_jpg_wav",
        audio_preprocessing=audio_config,
        allow_missing_modalities=True,
    )

    item = dataset[0]

    assert observed == [str((tmp_path / "audio/clip-1.wav").resolve())]
    assert torch.equal(item["spectrogram"], expected)
    assert item["audio_valid"].tolist() == [1.0] * 10
