"""Paper-specified OV-AVEBench WAV-to-student-fbank preprocessing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np
import torch
import torch.nn.functional as F


@dataclass(frozen=True)
class AudioPreprocessingSpec:
    sample_rate: int
    duration_seconds: int
    segments: int
    segment_seconds: int
    repeat_waveform_to_seconds: int
    num_mel_bins: int
    frame_length_ms: int
    frame_shift_ms: int
    target_length: int
    mean: float
    std: float
    student_channels: int
    student_size: tuple[int, int]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AudioPreprocessingSpec":
        size = value.get("student_resize", (224, 224))
        if not isinstance(size, (list, tuple)) or len(size) != 2:
            raise ValueError("student_resize must contain height and width")
        spec = cls(
            sample_rate=int(value["sample_rate"]),
            duration_seconds=int(value["duration_seconds"]),
            segments=int(value["segments"]),
            segment_seconds=int(value["segment_seconds"]),
            repeat_waveform_to_seconds=int(value["repeat_waveform_to_seconds"]),
            num_mel_bins=int(value["num_mel_bins"]),
            frame_length_ms=int(value["frame_length_ms"]),
            frame_shift_ms=int(value["frame_shift_ms"]),
            target_length=int(value["target_length"]),
            mean=float(value["mean"]),
            std=float(value["std"]),
            student_channels=int(value["student_channels"]),
            student_size=(int(size[0]), int(size[1])),
        )
        if spec.sample_rate != 16_000 or spec.duration_seconds != 10 or spec.segments != 10:
            raise ValueError("conference audio preprocessing requires 16 kHz, 10 seconds and 10 segments")
        if spec.segment_seconds != 1 or spec.repeat_waveform_to_seconds != 2:
            raise ValueError("each one-second segment must be repeated to two seconds")
        if spec.num_mel_bins != 128 or spec.target_length != 204:
            raise ValueError("conference fbank requires 128 Mel bins and target length 204")
        if spec.frame_length_ms != 25 or spec.frame_shift_ms != 10:
            raise ValueError("conference fbank requires 25 ms frames and 10 ms shift")
        if spec.std <= 0 or spec.student_channels != 3:
            raise ValueError("audio standard deviation must be positive and student channels must be 3")
        return spec


def segment_and_repeat_waveform(
    waveform: torch.Tensor, spec: AudioPreprocessingSpec
) -> torch.Tensor:
    normalized = torch.as_tensor(waveform, dtype=torch.float32).reshape(-1)
    if normalized.numel() == 0 or not bool(torch.isfinite(normalized).all()):
        raise ValueError("official waveform must be non-empty and finite")
    total_samples = spec.sample_rate * spec.duration_seconds
    if normalized.numel() < total_samples:
        normalized = F.pad(normalized, (0, total_samples - normalized.numel()))
    else:
        normalized = normalized[:total_samples]
    segment_samples = spec.sample_rate * spec.segment_seconds
    if spec.segments * segment_samples != total_samples:
        raise ValueError("audio segment geometry does not cover the exact ten-second waveform")
    segments = normalized.reshape(spec.segments, segment_samples)
    repeats = spec.repeat_waveform_to_seconds // spec.segment_seconds
    if repeats * spec.segment_seconds != spec.repeat_waveform_to_seconds:
        raise ValueError("waveform repeat duration must be an integer number of segments")
    return segments.repeat(1, repeats)


def waveform_to_fbank_segments(
    waveform: torch.Tensor,
    spec: AudioPreprocessingSpec,
    *,
    fbank_function: Callable[..., torch.Tensor] | None = None,
) -> torch.Tensor:
    if fbank_function is None:
        try:
            from torchaudio.compliance.kaldi import fbank as fbank_function
        except (ImportError, OSError) as exc:
            raise RuntimeError("Kaldi fbank preprocessing requires a working torchaudio install") from exc

    rows: list[torch.Tensor] = []
    for segment in segment_and_repeat_waveform(waveform, spec):
        # Mirror the fixed OV-AVEL ImageBind `waveform2melspec` semantics.
        segment = segment - segment.mean()
        fbank = fbank_function(
            segment.unsqueeze(0),
            htk_compat=True,
            sample_frequency=spec.sample_rate,
            use_energy=False,
            window_type="hanning",
            num_mel_bins=spec.num_mel_bins,
            dither=0.0,
            frame_length=spec.frame_length_ms,
            frame_shift=spec.frame_shift_ms,
        )
        fbank = torch.as_tensor(fbank, dtype=torch.float32)
        if fbank.ndim != 2 or fbank.shape[1] != spec.num_mel_bins:
            raise ValueError(f"Kaldi fbank returned invalid shape: {list(fbank.shape)}")
        if fbank.shape[0] < spec.target_length:
            fbank = F.pad(fbank, (0, 0, 0, spec.target_length - fbank.shape[0]))
        else:
            fbank = fbank[: spec.target_length]
        fbank = (fbank - spec.mean) / spec.std
        if not bool(torch.isfinite(fbank).all()):
            raise ValueError("student fbank contains NaN or Inf")
        rows.append(fbank.transpose(0, 1).unsqueeze(0))
    return torch.stack(rows, dim=0)


def adapt_fbank_for_student(
    fbank: torch.Tensor, *, size: tuple[int, int], channels: int
) -> torch.Tensor:
    value = torch.as_tensor(fbank, dtype=torch.float32)
    if value.ndim != 4 or value.shape[1] != 1:
        raise ValueError(f"expected fbank [T,1,Mel,frames], got {list(value.shape)}")
    if channels != 3:
        raise ValueError("conference student audio input requires exactly three repeated channels")
    value = value.repeat(1, channels, 1, 1)
    value = F.interpolate(value, size=size, mode="bilinear", align_corners=False)
    if not bool(torch.isfinite(value).all()):
        raise ValueError("student audio tensor contains NaN or Inf")
    return value


def load_official_wav_for_student(
    path: str | Path, spec: AudioPreprocessingSpec
) -> torch.Tensor:
    try:
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError("official WAV preprocessing requires soundfile") from exc
    array, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
    waveform = torch.from_numpy(np.asarray(array, dtype=np.float32)).mean(dim=1)
    if int(sample_rate) != spec.sample_rate:
        try:
            from torchaudio.functional import resample
        except (ImportError, OSError) as exc:
            raise RuntimeError("official WAV resampling requires a working torchaudio install") from exc
        waveform = resample(waveform, int(sample_rate), spec.sample_rate)
    fbank = waveform_to_fbank_segments(waveform, spec)
    return adapt_fbank_for_student(
        fbank, size=spec.student_size, channels=spec.student_channels
    )
