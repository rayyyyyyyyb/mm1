from __future__ import annotations

import sys
import re
from argparse import Namespace
from collections.abc import Mapping
from pathlib import Path
from typing import Sequence

import numpy as np
import torch

from .common import verify_checkpoint_sha256


_GPT2_NONPERSISTENT_BUFFER = re.compile(
    r"^caption_encoder\.base\.h\.(\d+)\.attn\.(bias|masked_bias)$"
)


def _strip_verified_gpt2_compatibility_buffers(
    model: torch.nn.Module,
    state: Mapping[str, object],
) -> dict[str, object]:
    """Remove only byte/value-verified legacy GPT-2 causal-mask buffers."""

    working = dict(state)
    persistent_keys = set(model.state_dict())
    extras = set(working) - persistent_keys
    if not extras:
        return working
    try:
        layers = model.caption_encoder.base.h
    except AttributeError as exc:
        raise RuntimeError(f"CLAP checkpoint has unexpected keys: {sorted(extras)}") from exc
    expected = {
        f"caption_encoder.base.h.{index}.attn.{name}"
        for index in range(len(layers))
        for name in ("bias", "masked_bias")
    }
    if extras != expected:
        raise RuntimeError(
            "CLAP checkpoint unexpected keys are not the exact legacy GPT-2 mask set: "
            f"expected={sorted(expected)}, actual={sorted(extras)}"
        )
    for name in sorted(extras):
        match = _GPT2_NONPERSISTENT_BUFFER.fullmatch(name)
        if match is None:  # defensive: the exact set above already excludes this
            raise RuntimeError(f"CLAP checkpoint unexpected compatibility key: {name}")
        layer_index, buffer_name = int(match.group(1)), match.group(2)
        checkpoint_value = working[name]
        if not isinstance(checkpoint_value, torch.Tensor):
            raise RuntimeError(f"CLAP GPT-2 compatibility buffer is not a tensor: {name}")
        attention = layers[layer_index].attn
        model_value = getattr(attention, buffer_name, None)
        if isinstance(model_value, torch.Tensor):
            checkpoint_cpu = checkpoint_value.cpu()
            model_cpu = model_value.detach().cpu()
            exact_match = (
                checkpoint_cpu.shape == model_cpu.shape
                and checkpoint_cpu.dtype == model_cpu.dtype
                and torch.equal(checkpoint_cpu, model_cpu)
            )
            legacy_float_mask_match = (
                buffer_name == "bias"
                and checkpoint_cpu.shape == model_cpu.shape
                and checkpoint_cpu.dtype == torch.float32
                and model_cpu.dtype == torch.bool
                and torch.equal(checkpoint_cpu, checkpoint_cpu.bool().float())
                and torch.equal(checkpoint_cpu.bool(), model_cpu)
            )
            if not (exact_match or legacy_float_mask_match):
                raise RuntimeError(f"CLAP GPT-2 compatibility buffer value mismatch: {name}")
        elif not (
            buffer_name == "masked_bias"
            and checkpoint_value.numel() == 1
            and float(checkpoint_value.item()) == -10000.0
        ):
            raise RuntimeError(f"CLAP GPT-2 compatibility buffer value mismatch: {name}")
        del working[name]
    return working


def _strict_load_clap_checkpoint(model: torch.nn.Module, checkpoint: Path) -> None:
    payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
    if not isinstance(payload, Mapping) or not isinstance(payload.get("model"), Mapping):
        raise ValueError("CLAP 2023 checkpoint must contain a model state mapping")
    state = _strip_verified_gpt2_compatibility_buffers(model, payload["model"])
    model.load_state_dict(state, strict=True)


class ClapTextTeacher:
    def __init__(
        self,
        repo_root: str | Path,
        checkpoint_path: str | Path,
        checkpoint_sha256: str,
        text_model_root: str | Path,
        version: str = "2023",
        device: str = "cpu",
        normalize: bool = False,
    ) -> None:
        repo_dir = Path(repo_root).resolve()
        checkpoint = Path(checkpoint_path).resolve()
        text_model_dir = Path(text_model_root).resolve()
        if not repo_dir.exists():
            raise FileNotFoundError(f"CLAP repo not found: {repo_dir}")
        if not checkpoint.exists():
            raise FileNotFoundError(f"CLAP checkpoint not found: {checkpoint}")
        if not text_model_dir.is_dir():
            raise FileNotFoundError(f"Pinned GPT-2 snapshot not found: {text_model_dir}")
        for filename in (
            "config.json",
            "generation_config.json",
            "merges.txt",
            "model.safetensors",
            "tokenizer.json",
            "tokenizer_config.json",
            "vocab.json",
        ):
            if not (text_model_dir / filename).is_file():
                raise FileNotFoundError(f"Pinned GPT-2 file not found: {text_model_dir / filename}")
        verify_checkpoint_sha256(checkpoint, checkpoint_sha256, label="CLAP")

        if str(repo_dir) not in sys.path:
            sys.path.insert(0, str(repo_dir))

        try:
            import yaml
            from msclap.models.clap import CLAP as CLAPModel
            from transformers import AutoTokenizer
        except ImportError as exc:
            raise ImportError(
                "Failed to import CLAP. Install `transformers`, `torchaudio`, and the repo requirements first."
            ) from exc

        self.device = torch.device(device)
        self.normalize = bool(normalize)
        if version != "2023":
            raise ValueError("Conference CLAP teacher requires version 2023")
        config_path = repo_dir / "msclap" / "configs" / "config_2023.yml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if not isinstance(config, Mapping) or config.get("text_model") != "gpt2":
            raise RuntimeError("Fixed CLAP 2023 config must declare text_model: gpt2")
        args = Namespace(**config)
        self.clap = CLAPModel(
            audioenc_name=args.audioenc_name,
            sample_rate=args.sampling_rate,
            window_size=args.window_size,
            hop_size=args.hop_size,
            mel_bins=args.mel_bins,
            fmin=args.fmin,
            fmax=args.fmax,
            classes_num=args.num_classes,
            out_emb=args.out_emb,
            text_model=str(text_model_dir),
            transformer_embed_dim=args.transformer_embed_dim,
            d_proj=args.d_proj,
        )
        _strict_load_clap_checkpoint(self.clap, checkpoint)
        self.tokenizer = AutoTokenizer.from_pretrained(
            text_model_dir,
            local_files_only=True,
        )
        self.args = args
        self.clap.eval()
        self.clap.to(self.device)
        self.model = self.clap
        self.feature_dim = int(args.d_proj)

    def encode_queries(self, queries: Sequence[str]) -> np.ndarray:
        tokenized = []
        for query in queries:
            item = self.tokenizer.encode_plus(
                text=f"{query} <|endoftext|>",
                add_special_tokens=True,
                max_length=int(self.args.text_len),
                padding="max_length",
                return_tensors="pt",
            )
            tokenized.append(
                {
                    key: item[key].reshape(-1)
                    for key in ("input_ids", "attention_mask")
                }
            )
        batch = {
            key: torch.stack([item[key] for item in tokenized]).to(self.device)
            for key in ("input_ids", "attention_mask")
        }
        with torch.no_grad():
            embeddings = self.clap.caption_encoder(batch)
        array = embeddings.detach().cpu().float().numpy()
        if self.normalize:
            norms = np.linalg.norm(array, axis=-1, keepdims=True).clip(min=1e-6)
            array = array / norms
        return array.astype(np.float32)
