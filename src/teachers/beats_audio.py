from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Sequence

import numpy as np
import torch

from .common import AudioSegmentSpec, verify_checkpoint_sha256


def _load_waveform_array(path: Path) -> np.ndarray:
    suffix = path.suffix.lower()
    if suffix == ".npy":
        array = np.load(path, allow_pickle=False)
    elif suffix == ".npz":
        with np.load(path, allow_pickle=False) as bundle:
            keys = list(bundle.keys())
            if keys != ["waveform"]:
                raise ValueError(f"Expected exactly one npz key named 'waveform', got {keys}")
            array = bundle["waveform"]
    else:
        raise ValueError(f"Unsupported NumPy waveform extension: {path}")
    normalized = np.asarray(array, dtype=np.float32).reshape(-1)
    if normalized.size == 0 or not np.isfinite(normalized).all():
        raise ValueError(f"Waveform array must be non-empty and finite: {path}")
    return normalized


class BEATsAudioTeacher:
    def __init__(
        self,
        repo_root: str | Path,
        checkpoint_path: str | Path,
        checkpoint_sha256: str,
        device: str = "cpu",
    ) -> None:
        repo_dir = Path(repo_root).resolve()
        checkpoint = Path(checkpoint_path).resolve()
        if not repo_dir.exists():
            raise FileNotFoundError(f"BEATs repo not found: {repo_dir}")
        if not checkpoint.exists():
            raise FileNotFoundError(f"BEATs checkpoint not found: {checkpoint}")
        verify_checkpoint_sha256(checkpoint, checkpoint_sha256, label="BEATs")

        if str(repo_dir) not in sys.path:
            sys.path.insert(0, str(repo_dir))

        try:
            from BEATs import BEATs, BEATsConfig
        except ImportError as exc:
            raise ImportError(
                "Failed to import BEATs. Ensure the official BEATs repo is available."
            ) from exc

        self.device = torch.device(device)

        payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
        cfg = BEATsConfig(payload["cfg"])
        if bool(getattr(cfg, "finetuned_model", False)):
            raise ValueError("BEATs export expects a pretrained checkpoint, not a finetuned classification checkpoint.")

        self.model = BEATs(cfg)
        self.model.load_state_dict(payload["model"])
        self.model.eval()
        self.model.to(self.device)
        self.feature_dim = int(getattr(cfg, "encoder_embed_dim", 768))

    def _load_segment_waveform(self, spec: AudioSegmentSpec) -> torch.Tensor:
        path = Path(spec.path)
        if not path.exists():
            raise FileNotFoundError(f"Missing audio segment: {path}")

        if path.suffix in {".npy", ".npz"}:
            waveform = torch.as_tensor(_load_waveform_array(path))
            sample_rate = int(spec.sample_rate or 16000)
        else:
            try:
                import soundfile as sf
            except ImportError as exc:
                raise RuntimeError("Reading WAV/FLAC for BEATs requires soundfile") from exc
            waveform_np, sample_rate = sf.read(str(path), dtype="float32", always_2d=False)
            waveform_np = np.asarray(waveform_np, dtype=np.float32)
            if waveform_np.ndim == 2:
                waveform_np = waveform_np.mean(axis=1)
            waveform = torch.as_tensor(waveform_np.reshape(-1), dtype=torch.float32)
            if spec.start_time is not None or spec.end_time is not None:
                start_time = float(spec.start_time or 0.0)
                end_time = float(spec.end_time) if spec.end_time is not None else waveform.numel() / sample_rate
                start = max(int(round(start_time * sample_rate)), 0)
                end = min(int(round(end_time * sample_rate)), waveform.numel())
                if end <= start:
                    raise ValueError(f"Invalid audio crop for {path}: start={start_time}, end={end_time}")
                waveform = waveform[start:end]

        if waveform.numel() == 0 or not bool(torch.isfinite(waveform).all()):
            raise ValueError(f"Audio waveform must be non-empty and finite: {path}")

        if sample_rate != 16000:
            try:
                import librosa
            except ImportError as exc:
                raise RuntimeError("BEATs resampling requires librosa") from exc
            waveform = torch.as_tensor(
                librosa.resample(
                    waveform.detach().cpu().numpy(),
                    orig_sr=sample_rate,
                    target_sr=16000,
                ),
                dtype=torch.float32,
            )
        return waveform.float().clamp(-1.0, 1.0)

    def export_segments(self, audio_segments: Sequence[AudioSegmentSpec]) -> np.ndarray:
        waveforms: List[torch.Tensor] = [self._load_segment_waveform(spec) for spec in audio_segments]
        max_len = max(waveform.numel() for waveform in waveforms)

        batch = torch.zeros(len(waveforms), max_len, dtype=torch.float32)
        padding_mask = torch.ones(len(waveforms), max_len, dtype=torch.bool)
        for idx, waveform in enumerate(waveforms):
            valid_len = waveform.numel()
            batch[idx, :valid_len] = waveform
            padding_mask[idx, :valid_len] = False

        with torch.no_grad():
            token_features, token_mask = self.model.extract_features(
                batch.to(self.device),
                padding_mask=padding_mask.to(self.device),
            )

        if token_mask is not None:
            valid = (~token_mask).float().unsqueeze(-1)
            pooled = (token_features * valid).sum(dim=1) / valid.sum(dim=1).clamp_min(1.0)
        else:
            pooled = token_features.mean(dim=1)
        return pooled.detach().cpu().float().numpy().astype(np.float32)
