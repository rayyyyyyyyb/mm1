"""Streaming, fail-closed validation for downloaded MM26 assets."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from scripts.assets.mm26_asset_catalog import AssetSpec


_READ_CHUNK_BYTES = 8 * 1024 * 1024
_SNIFF_BYTES = 4096


@dataclass(frozen=True)
class ValidationReceipt:
    asset: str
    path: str
    status: str
    bytes: int | None
    sha256: str | None
    content_type: str | None
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CheckpointStructureReceipt:
    asset: str
    path: str
    status: str
    top_level_type: str | None
    key_count: int | None
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


_INTERNVIDEO_EXTRA_CLIP_KEYS = {
    "temp",
    "vision_encoder.clip_projector.norm1_q.weight",
    "vision_encoder.clip_projector.norm1_q.bias",
    "vision_encoder.clip_projector.norm1_k.weight",
    "vision_encoder.clip_projector.norm1_k.bias",
    "vision_encoder.clip_projector.norm1_v.weight",
    "vision_encoder.clip_projector.norm1_v.bias",
    "vision_encoder.clip_projector.cross_attn.q_bias",
    "vision_encoder.clip_projector.cross_attn.k_bias",
    "vision_encoder.clip_projector.cross_attn.v_bias",
    "vision_encoder.clip_projector.cross_attn.q.weight",
    "vision_encoder.clip_projector.cross_attn.k.weight",
    "vision_encoder.clip_projector.cross_attn.v.weight",
    "vision_encoder.clip_projector.cross_attn.proj.weight",
    "vision_encoder.clip_projector.cross_attn.proj.bias",
    "vision_align.0.weight",
    "vision_align.0.bias",
    "vision_align.1.weight",
    "vision_align.1.bias",
}


def _default_torch_load(path: Path, **kwargs: object) -> object:
    import torch

    return torch.load(path, **kwargs)


def _missing_keys(errors: list[str], asset: str, checkpoint: Mapping, keys: set[str]) -> None:
    for key in sorted(keys - set(checkpoint)):
        errors.append(f"{asset}: missing key {key}")


def validate_checkpoint_structure(
    path: str | Path,
    asset: str,
    *,
    load_fn: Callable[..., Any] | None = None,
) -> CheckpointStructureReceipt:
    """Safely load and validate the exact fixed-commit checkpoint container."""

    candidate = Path(path)
    if not candidate.is_file():
        return CheckpointStructureReceipt(
            asset, str(candidate), "failed", None, None, ("missing_file",)
        )
    loader = load_fn or _default_torch_load
    try:
        checkpoint = loader(candidate, map_location="cpu", weights_only=True)
    except Exception as error:
        return CheckpointStructureReceipt(
            asset,
            str(candidate),
            "failed",
            None,
            None,
            (f"safe_checkpoint_load_failed: {type(error).__name__}: {error}",),
        )

    top_level_type = type(checkpoint).__name__
    if not isinstance(checkpoint, Mapping):
        return CheckpointStructureReceipt(
            asset,
            str(candidate),
            "failed",
            top_level_type,
            None,
            (f"{asset}: top level must be a mapping",),
        )

    errors: list[str] = []
    key_count = len(checkpoint)
    if asset == "internvideo2_b14":
        if key_count != 217:
            errors.append("internvideo2_b14: exact key count must be 217")
        _missing_keys(
            errors,
            asset,
            checkpoint,
            {
                "cls_token",
                "pos_embed",
                "patch_embed.proj.weight",
                "blocks.0.attn.qkv.weight",
                "final_clip_decoder.norm.bias",
            },
        )
    elif asset == "internvideo2_clip_b14":
        actual = set(checkpoint)
        if actual != _INTERNVIDEO_EXTRA_CLIP_KEYS:
            errors.append("internvideo2_clip_b14: exact 19-key overlay set mismatch")
        _missing_keys(errors, asset, checkpoint, _INTERNVIDEO_EXTRA_CLIP_KEYS)
    elif asset == "beats_iter3_plus_as2m":
        if set(checkpoint) != {"cfg", "model"}:
            errors.append("beats_iter3_plus_as2m: top-level keys must be cfg and model")
        cfg = checkpoint.get("cfg")
        model = checkpoint.get("model")
        if not isinstance(cfg, Mapping):
            errors.append("beats_iter3_plus_as2m: cfg must be a mapping")
        else:
            expected_cfg = {
                "encoder_layers": 12,
                "encoder_embed_dim": 768,
                "encoder_attention_heads": 12,
                "embed_dim": 512,
            }
            for key, expected in expected_cfg.items():
                if cfg.get(key) != expected:
                    errors.append(f"beats_iter3_plus_as2m: cfg {key} mismatch")
        if not isinstance(model, Mapping):
            errors.append("beats_iter3_plus_as2m: model must be a mapping")
        else:
            if len(model) != 250:
                errors.append("beats_iter3_plus_as2m: exact model key count must be 250")
            _missing_keys(
                errors,
                asset,
                model,
                {
                    "post_extract_proj.weight",
                    "patch_embedding.weight",
                    "encoder.layers.0.self_attn.q_proj.weight",
                    "encoder.layers.11.self_attn.grep_linear.bias",
                },
            )
    else:
        errors.append(f"{asset}: no fixed checkpoint structure validator")

    return CheckpointStructureReceipt(
        asset=asset,
        path=str(candidate),
        status="failed" if errors else "passed",
        top_level_type=top_level_type,
        key_count=key_count,
        errors=tuple(errors),
    )


def probe_response(
    head: bytes,
    content_type: str | None,
    content_length: int | None,
) -> list[str]:
    """Return public-payload rejection codes for a small response prefix."""

    errors: list[str] = []
    normalized_type = (content_type or "").split(";", 1)[0].strip().casefold()
    normalized_head = head.lstrip().lower()
    if content_length == 0:
        errors.append("empty_response")
    if normalized_type in {"text/html", "application/xhtml+xml"} or normalized_head.startswith(
        (b"<!doctype html", b"<html")
    ):
        errors.append("html_payload")
    if normalized_type in {"application/xml", "text/xml"} or normalized_head.startswith(
        b"<?xml"
    ):
        errors.append("xml_payload")
    if normalized_head.startswith(b"version https://git-lfs.github.com/spec/v1"):
        errors.append("git_lfs_pointer")
    return errors


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_READ_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_download(
    path: str | Path,
    spec: AssetSpec,
    *,
    content_type: str | None = None,
) -> ValidationReceipt:
    """Validate immutable bytes without modifying or deleting the candidate file."""

    candidate = Path(path)
    if not candidate.is_file():
        return ValidationReceipt(
            asset=spec.name,
            path=str(candidate),
            status="failed",
            bytes=None,
            sha256=None,
            content_type=content_type,
            errors=("missing_file",),
        )

    size = candidate.stat().st_size
    errors: list[str] = []
    if size == 0:
        errors.append("empty_file")
    if size < spec.min_bytes:
        errors.append("below_minimum_size")

    with candidate.open("rb") as handle:
        head = handle.read(_SNIFF_BYTES)
    errors.extend(probe_response(head, content_type, size))

    sha256 = _sha256_file(candidate)
    if spec.expected_sha256 is not None and sha256 != spec.expected_sha256:
        errors.append("sha256_mismatch")

    unique_errors = tuple(dict.fromkeys(errors))
    return ValidationReceipt(
        asset=spec.name,
        path=str(candidate),
        status="failed" if unique_errors else "passed",
        bytes=size,
        sha256=sha256,
        content_type=content_type,
        errors=unique_errors,
    )
