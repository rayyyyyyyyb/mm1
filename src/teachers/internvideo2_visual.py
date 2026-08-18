from __future__ import annotations

import os
import sys
import types
from contextlib import contextmanager
from importlib.machinery import ModuleSpec
from pathlib import Path
from typing import List, Sequence

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

from .common import to_attr_dict


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


class InternVideo2ClipB14Teacher:
    def __init__(
        self,
        repo_root: str | Path,
        vision_ckpt_path: str | Path,
        text_ckpt_path: str | Path,
        extra_ckpt_path: str | Path,
        device: str = "cpu",
        num_frames: int = 8,
        align_dim: int = 512,
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
        self.num_frames = int(num_frames)
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
            self.model = InternVideo2_CLIP_small(config=config)
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

    def _select_frame_paths(self, frame_group: Sequence[str]) -> List[str]:
        items = [str(path) for path in frame_group if path]
        if not items:
            raise ValueError("Frame group cannot be empty.")
        if len(items) == self.num_frames:
            return items
        if len(items) > self.num_frames:
            indices = np.linspace(0, len(items) - 1, num=self.num_frames, dtype=int)
            return [items[index] for index in indices.tolist()]
        repeated: List[str] = []
        for idx in range(self.num_frames):
            repeated.append(items[min(idx, len(items) - 1)])
        return repeated

    def _load_segment_tensor(self, frame_group: Sequence[str]) -> torch.Tensor:
        frames = []
        for path_str in self._select_frame_paths(frame_group):
            path = Path(path_str)
            if not path.exists():
                raise FileNotFoundError(f"Missing frame for InternVideo2 export: {path}")
            image = Image.open(path).convert("RGB")
            array = np.asarray(image, dtype=np.uint8)
            tensor = torch.from_numpy(array).permute(2, 0, 1)
            tensor = self.model.transform(tensor)
            frames.append(tensor)
        return torch.stack(frames, dim=0)

    def export_segments(self, frame_groups: Sequence[Sequence[str]], query: str) -> tuple[np.ndarray, np.ndarray]:
        if not frame_groups:
            raise ValueError("frame_groups cannot be empty.")

        batch = torch.stack([self._load_segment_tensor(group) for group in frame_groups], dim=0).to(self.device)
        text_tokens = self.model.tokenizer([query] * len(frame_groups)).to(self.device)

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
