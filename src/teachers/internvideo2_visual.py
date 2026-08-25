from __future__ import annotations

import os
import sys
import types
from contextlib import contextmanager
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.machinery import ModuleSpec
from pathlib import Path
from typing import Callable, Sequence

import numpy as np
from PIL import Image
import torch
import torch.nn.functional as F
from .common import to_attr_dict, verify_checkpoint_sha256


@dataclass(frozen=True)
class DecodedVideo:
    frames: np.ndarray
    duration_seconds: float
    source_fps: float


def deterministic_video_timestamps(
    *,
    duration_seconds: int,
    intervals: int,
    sampling_fps: int,
    frames_per_interval: int,
) -> np.ndarray:
    """Build timestamps for the legacy noncanonical raw-video diagnostic only."""
    if duration_seconds <= 0 or intervals <= 0 or sampling_fps <= 0 or frames_per_interval <= 0:
        raise ValueError("video timestamp geometry must be positive")
    if duration_seconds != intervals:
        raise ValueError("raw-video diagnostic requires one-second intervals")
    candidates_per_interval = sampling_fps
    if frames_per_interval > candidates_per_interval:
        raise ValueError("cannot select more frames than the 16-fps sampling grid provides")

    # Historical diagnostic only; the canonical keyframe path never calls this.
    # This applies the upstream `sample='middle'` rule to an explicit grid.
    boundaries = np.linspace(
        start=0,
        stop=candidates_per_interval,
        num=frames_per_interval + 1,
    ).astype(int)
    indices = np.asarray(
        [
            (int(start) + int(boundaries[index + 1]) - 1) // 2
            for index, start in enumerate(boundaries[:-1])
        ],
        dtype=np.float64,
    )
    within_interval = indices / float(sampling_fps)
    return np.stack(
        [within_interval + float(interval) for interval in range(intervals)], axis=0
    )


def decode_video_with_decord(path: Path, timestamps: np.ndarray) -> DecodedVideo:
    try:
        import decord
    except ImportError as exc:
        raise RuntimeError(
            "Raw InternVideo2 decoding requires the pinned `decord` runtime."
        ) from exc

    reader = decord.VideoReader(str(path), ctx=decord.cpu(0), num_threads=1)
    frame_count = len(reader)
    source_fps = float(reader.get_avg_fps())
    if frame_count <= 0 or not np.isfinite(source_fps) or source_fps <= 0:
        raise ValueError(f"Cannot determine raw video geometry: {path}")
    duration_seconds = frame_count / source_fps
    flat_timestamps = np.asarray(timestamps, dtype=np.float64).reshape(-1)
    frame_indices = np.rint(flat_timestamps * source_fps).astype(np.int64)
    if np.any(frame_indices < 0) or np.any(frame_indices >= frame_count):
        raise ValueError(f"Raw video does not cover all deterministic timestamps: {path}")
    frames = np.asarray(reader.get_batch(frame_indices).asnumpy())
    return DecodedVideo(
        frames=frames,
        duration_seconds=float(duration_seconds),
        source_fps=source_fps,
    )


@contextmanager
def _pushd(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _install_flash_attn_stub() -> None:
    try:
        import flash_attn  # noqa: F401
        return
    except ImportError:
        pass

    class _MissingModule(torch.nn.Module):
        def __init__(self, *args, **kwargs):
            raise ImportError(
                "flash_attn is not installed. OV-OrthKD export keeps `use_flash_attn=False`, "
                "so this stub should never be instantiated unless the upstream config is changed."
            )

    def _missing_function(*args, **kwargs):
        raise ImportError(
            "flash_attn is not installed. OV-OrthKD export keeps `use_flash_attn=False`, "
            "so this function should never be called unless the upstream config is changed."
        )

    flash_attn_pkg = types.ModuleType("flash_attn")
    flash_attn_interface = types.ModuleType("flash_attn.flash_attn_interface")
    flash_attn_interface.flash_attn_varlen_qkvpacked_func = _missing_function

    bert_padding = types.ModuleType("flash_attn.bert_padding")
    bert_padding.unpad_input = _missing_function
    bert_padding.pad_input = _missing_function

    flash_attn_modules = types.ModuleType("flash_attn.modules")
    flash_attn_modules_mlp = types.ModuleType("flash_attn.modules.mlp")
    flash_attn_modules_mlp.FusedMLP = _MissingModule

    flash_attn_ops = types.ModuleType("flash_attn.ops")
    flash_attn_ops_rms_norm = types.ModuleType("flash_attn.ops.rms_norm")
    flash_attn_ops_rms_norm.DropoutAddRMSNorm = _MissingModule

    flash_attn_pkg.flash_attn_interface = flash_attn_interface
    flash_attn_pkg.bert_padding = bert_padding
    flash_attn_pkg.modules = flash_attn_modules
    flash_attn_pkg.ops = flash_attn_ops

    # Newer transformers checks importlib metadata when probing flash-attn availability.
    flash_attn_pkg.__spec__ = ModuleSpec("flash_attn", loader=None)
    flash_attn_interface.__spec__ = ModuleSpec("flash_attn.flash_attn_interface", loader=None)
    bert_padding.__spec__ = ModuleSpec("flash_attn.bert_padding", loader=None)
    flash_attn_modules.__spec__ = ModuleSpec("flash_attn.modules", loader=None)
    flash_attn_modules_mlp.__spec__ = ModuleSpec("flash_attn.modules.mlp", loader=None)
    flash_attn_ops.__spec__ = ModuleSpec("flash_attn.ops", loader=None)
    flash_attn_ops_rms_norm.__spec__ = ModuleSpec("flash_attn.ops.rms_norm", loader=None)

    sys.modules.setdefault("flash_attn", flash_attn_pkg)
    sys.modules["flash_attn.flash_attn_interface"] = flash_attn_interface
    sys.modules["flash_attn.bert_padding"] = bert_padding
    sys.modules["flash_attn.modules"] = flash_attn_modules
    sys.modules["flash_attn.modules.mlp"] = flash_attn_modules_mlp
    sys.modules["flash_attn.ops"] = flash_attn_ops
    sys.modules["flash_attn.ops.rms_norm"] = flash_attn_ops_rms_norm


def _weights_only_mapping(path: Path, *, label: str) -> Mapping[str, torch.Tensor]:
    payload = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} checkpoint must contain a mapping")
    return payload


def _unwrap_checkpoint_mapping(
    payload: Mapping[str, object], *, allow_model: bool
) -> Mapping[str, torch.Tensor]:
    if isinstance(payload.get("module"), Mapping):
        return payload["module"]  # type: ignore[return-value]
    if allow_model and isinstance(payload.get("model"), Mapping):
        return payload["model"]  # type: ignore[return-value]
    return payload  # type: ignore[return-value]


def _compose_internvideo_checkpoint(
    vision_payload: Mapping[str, object],
    text_payload: Mapping[str, object],
    extra_payload: Mapping[str, object],
) -> dict[str, torch.Tensor]:
    """Reproduce the fixed upstream three-role composition without deserializing unsafely."""

    combined: dict[str, torch.Tensor] = {}
    vision = _unwrap_checkpoint_mapping(vision_payload, allow_model=True)
    for key, value in vision.items():
        if key.startswith(("clip_decoder.", "mae_decoder.", "final_clip_decoder.")):
            continue
        if key in {"clip_pos_embed", "mae_pos_embed"}:
            continue
        combined[f"vision_encoder.{key}"] = value

    text = _unwrap_checkpoint_mapping(text_payload, allow_model=False)
    for key, value in text.items():
        if key.startswith("text_encoder."):
            combined[key] = value

    extra = _unwrap_checkpoint_mapping(extra_payload, allow_model=False)
    for key, value in extra.items():
        combined[key] = value
    return combined


@contextmanager
def _defer_upstream_checkpoint_load(model_class):
    original = model_class.load_checkpoint
    model_class.load_checkpoint = lambda self, *args, **kwargs: None
    try:
        yield
    finally:
        model_class.load_checkpoint = original


class InternVideo2ClipB14Teacher:
    def __init__(
        self,
        repo_root: str | Path,
        vision_ckpt_path: str | Path,
        text_ckpt_path: str | Path,
        extra_ckpt_path: str | Path,
        vision_ckpt_sha256: str,
        text_ckpt_sha256: str,
        extra_ckpt_sha256: str,
        device: str = "cpu",
        num_frames: int = 8,
        align_dim: int = 512,
        input_mode: str = "official_segment_keyframes",
        task_segments: int = 10,
        frame_expansion: str = "repeat_last_to_num_frames",
        raw_video_diagnostic: Mapping[str, object] | None = None,
        intervals: int | None = None,
        video_duration_seconds: int | None = None,
        sampling_fps: int | None = None,
        decoder: Callable[[Path, np.ndarray], DecodedVideo] | None = None,
    ) -> None:
        repo_dir = Path(repo_root).resolve()
        repo_parent = repo_dir.parent
        vision_ckpt = Path(vision_ckpt_path).resolve()
        text_ckpt = Path(text_ckpt_path).resolve()
        extra_ckpt = Path(extra_ckpt_path).resolve()

        for path, label in (
            (repo_dir, "InternVideo2 multi-modality repo"),
            (vision_ckpt, "InternVideo2 vision checkpoint"),
            (text_ckpt, "InternVideo2 text checkpoint"),
            (extra_ckpt, "InternVideo2 extra CLIP checkpoint"),
        ):
            if not path.exists():
                raise FileNotFoundError(f"{label} not found: {path}")
        verify_checkpoint_sha256(vision_ckpt, vision_ckpt_sha256, label="InternVideo2 vision")
        verify_checkpoint_sha256(text_ckpt, text_ckpt_sha256, label="InternVideo2 text")
        verify_checkpoint_sha256(extra_ckpt, extra_ckpt_sha256, label="InternVideo2 extra CLIP")

        # Import InternVideo2 through the `multi_modality` package root so its
        # internal relative imports like `..utils.*` resolve correctly.
        if str(repo_parent) not in sys.path:
            sys.path.insert(0, str(repo_parent))

        _install_flash_attn_stub()
        try:
            from multi_modality.models.internvideo2_clip_small import InternVideo2_CLIP_small
        except ImportError as exc:
            raise ImportError(
                "Failed to import InternVideo2_CLIP_small. Install `open-clip-torch` and the repo requirements first."
            ) from exc

        self.device = torch.device(device)
        self.input_mode = str(input_mode)
        self.num_frames = int(num_frames)
        self.task_segments = int(task_segments)
        self.frame_expansion = str(frame_expansion)
        diagnostic = dict(raw_video_diagnostic or {})
        self.raw_video_diagnostic_enabled = bool(diagnostic.get("enabled", False))
        self.intervals = int(
            intervals if intervals is not None else diagnostic.get("intervals", 10)
        )
        self.video_duration_seconds = int(
            video_duration_seconds
            if video_duration_seconds is not None
            else diagnostic.get("video_duration_seconds", 10)
        )
        self.sampling_fps = int(
            sampling_fps
            if sampling_fps is not None
            else diagnostic.get("sampling_fps", 16)
        )
        if self.input_mode not in {
            "official_segment_keyframes",
            "raw_multiframe_diagnostic",
        }:
            raise ValueError(f"Unsupported InternVideo2 input_mode: {self.input_mode}")
        if (
            self.num_frames != 8
            or self.task_segments != 10
            or self.frame_expansion != "repeat_last_to_num_frames"
        ):
            raise ValueError(
                "canonical InternVideo2 export requires ten task segments, one official "
                "keyframe per segment repeated to eight model frames"
            )
        if self.input_mode == "raw_multiframe_diagnostic" and (
            not self.raw_video_diagnostic_enabled
            or self.intervals != 10
            or self.video_duration_seconds != 10
            or self.sampling_fps != 16
        ):
            raise ValueError(
                "legacy noncanonical raw multiframe diagnostic mode must be explicitly "
                "enabled with 10 seconds, ten intervals and its explicit timestamp grid"
            )
        self._decode_video = decoder or decode_video_with_decord
        self.feature_dim = int(align_dim)
        config = self._build_config(
            vision_ckpt_path=str(vision_ckpt),
            text_ckpt_path=str(text_ckpt),
            extra_ckpt_path=str(extra_ckpt),
            num_frames=self.num_frames,
            align_dim=self.feature_dim,
        )

        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        with _pushd(repo_dir):
            with _defer_upstream_checkpoint_load(InternVideo2_CLIP_small):
                self.model = InternVideo2_CLIP_small(config=config)
        combined = _compose_internvideo_checkpoint(
            _weights_only_mapping(vision_ckpt, label="InternVideo2 vision"),
            _weights_only_mapping(text_ckpt, label="InternVideo2 text"),
            _weights_only_mapping(extra_ckpt, label="InternVideo2 extra CLIP"),
        )
        self.model.load_state_dict(combined, strict=True)
        self.model.eval()
        self.model.to(self.device)

    def _build_config(
        self,
        vision_ckpt_path: str,
        text_ckpt_path: str,
        extra_ckpt_path: str,
        num_frames: int,
        align_dim: int,
    ):
        return to_attr_dict(
            {
                "model": {
                    "model_cls": "InternVideo2_CLIP_small",
                    "vision_encoder": {
                        "name": "internvideo2",
                        "in_chans": 3,
                        "patch_size": 14,
                        "img_size": 224,
                        "qkv_bias": False,
                        "drop_path_rate": 0.0,
                        "head_drop_path_rate": 0.0,
                        "embed_dim": 768,
                        "num_heads": 12,
                        "mlp_ratio": 4,
                        "init_values": 0.1,
                        "qk_normalization": True,
                        "depth": 12,
                        "use_flash_attn": False,
                        "use_fused_rmsnorm": False,
                        "use_fused_mlp": False,
                        "fused_mlp_heuristic": 1,
                        "attn_pool_num_heads": 16,
                        "clip_embed_dim": 768,
                        "layerscale_no_force_fp32": True,
                        "num_frames": int(num_frames),
                        "tubelet_size": 1,
                        "sep_pos_embed": False,
                        "use_checkpoint": False,
                        "checkpoint_num": 0,
                        "align_dim": int(align_dim),
                    },
                    "text_encoder": {"name": "mobileclip_b"},
                    "temp": 1 / 100.0,
                    "temp_min": 1 / 100.0,
                    "freeze_vision": True,
                    "open_vision_clip_projector": True,
                    "freeze_text": True,
                    "open_text_projection": False,
                    "vision_ckpt_path": vision_ckpt_path,
                    "load_vision_ckpt_from_internvideo2_stage2": False,
                    "text_ckpt_path": text_ckpt_path,
                    "extra_ckpt_path": extra_ckpt_path,
                }
            }
        )

    def _load_video_tensor(self, video_path: str | Path) -> torch.Tensor:
        path = Path(video_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Missing official raw video for InternVideo2 export: {path}")
        timestamps = deterministic_video_timestamps(
            duration_seconds=self.video_duration_seconds,
            intervals=self.intervals,
            sampling_fps=self.sampling_fps,
            frames_per_interval=self.num_frames,
        )
        decoded = self._decode_video(path, timestamps)
        if not np.isfinite(decoded.duration_seconds) or decoded.duration_seconds < float(
            self.video_duration_seconds
        ):
            raise ValueError(
                f"InternVideo2 requires a complete 10-second raw video; "
                f"decoded duration={decoded.duration_seconds}: {path}"
            )
        frames = np.asarray(decoded.frames)
        expected = self.intervals * self.num_frames
        if frames.ndim != 4 or frames.shape[0] != expected or frames.shape[-1] != 3:
            raise ValueError(
                f"Raw video decoder must return [{expected},H,W,3], got {list(frames.shape)}"
            )
        transformed = []
        for frame in frames:
            tensor = torch.from_numpy(np.asarray(frame, dtype=np.uint8).copy()).permute(2, 0, 1)
            transformed.append(self.model.transform(tensor))
        return torch.stack(transformed, dim=0).reshape(
            self.intervals, self.num_frames, *transformed[0].shape
        )

    def _select_frame_paths(self, frame_group: Sequence[str]) -> list[str]:
        items = [str(path) for path in frame_group if path]
        if self.input_mode == "official_segment_keyframes":
            if len(items) != 1:
                raise ValueError(
                    "Canonical InternVideo2 export requires exactly one official keyframe "
                    "for each one-second task segment"
                )
            if Path(items[0]).suffix.lower() != ".jpg":
                raise ValueError(
                    "Canonical InternVideo2 keyframes must use the official .jpg extension"
                )
            if self.frame_expansion != "repeat_last_to_num_frames":
                raise ValueError(f"Unsupported keyframe expansion: {self.frame_expansion}")
            return items * self.num_frames
        if not items:
            raise ValueError("Frame group cannot be empty")
        if len(items) == self.num_frames:
            return items
        if len(items) > self.num_frames:
            indices = np.linspace(0, len(items) - 1, num=self.num_frames, dtype=int)
            return [items[index] for index in indices.tolist()]
        return [items[min(index, len(items) - 1)] for index in range(self.num_frames)]

    def _load_segment_tensor(self, frame_group: Sequence[str]) -> torch.Tensor:
        selected_paths = self._select_frame_paths(frame_group)

        def load_and_transform(path_string: str) -> torch.Tensor:
            path = Path(path_string).expanduser().resolve()
            if not path.is_file():
                raise FileNotFoundError(
                    f"Missing official keyframe for InternVideo2 export: {path}"
                )
            with Image.open(path) as image:
                array = np.asarray(image.convert("RGB"), dtype=np.uint8).copy()
            tensor = torch.from_numpy(array).permute(2, 0, 1)
            return self.model.transform(tensor)

        if self.input_mode == "official_segment_keyframes":
            # The approved K_teacher=8 path repeats one deterministic official
            # keyframe tensor; decoding or transforming it eight times is both
            # redundant and less explicit about the identity of the inputs.
            keyframe = load_and_transform(selected_paths[0])
            return keyframe.unsqueeze(0).repeat(self.num_frames, 1, 1, 1)

        return torch.stack(
            [load_and_transform(path_string) for path_string in selected_paths],
            dim=0,
        )

    def export_video(self, video_path: str | Path, query: str) -> tuple[np.ndarray, np.ndarray]:
        if self.input_mode != "raw_multiframe_diagnostic":
            raise RuntimeError(
                "Raw-video export is diagnostic-only and must be selected explicitly"
            )
        batch = self._load_video_tensor(video_path).to(self.device)
        text_tokens = self.model.tokenizer([query] * self.intervals).to(self.device)

        with torch.no_grad():
            visual_features = self.model.encode_vision(batch, test=True)
            text_features = self.model.encode_text(text_tokens)
            logits = (
                F.normalize(visual_features, dim=-1) * F.normalize(text_features, dim=-1)
            ).sum(dim=-1) / float(self.model.temp.detach().cpu())

        return (
            visual_features.detach().cpu().float().numpy().astype(np.float32),
            logits.detach().cpu().float().numpy().astype(np.float32),
        )

    def export_segments(
        self, frame_groups: Sequence[Sequence[str]], query: str
    ) -> tuple[np.ndarray, np.ndarray]:
        if self.input_mode != "official_segment_keyframes":
            raise RuntimeError("Keyframe export requires official_segment_keyframes mode")
        if len(frame_groups) != self.task_segments:
            raise ValueError(
                f"InternVideo2 requires exactly {self.task_segments} official task segments, "
                f"got {len(frame_groups)}"
            )
        batch = torch.stack(
            [self._load_segment_tensor(group) for group in frame_groups], dim=0
        ).to(self.device)
        text_tokens = self.model.tokenizer([query] * self.task_segments).to(self.device)

        with torch.no_grad():
            visual_features = self.model.encode_vision(batch, test=True)
            text_features = self.model.encode_text(text_tokens)
            logits = (
                F.normalize(visual_features, dim=-1)
                * F.normalize(text_features, dim=-1)
            ).sum(dim=-1) / float(self.model.temp.detach().cpu())

        return (
            visual_features.detach().cpu().float().numpy().astype(np.float32),
            logits.detach().cpu().float().numpy().astype(np.float32),
        )
