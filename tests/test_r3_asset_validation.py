from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.assets.asset_validation import (
    probe_response,
    validate_checkpoint_structure,
    validate_download,
)
from scripts.assets.mm26_asset_catalog import AssetSpec


def _spec(payload: bytes, *, min_bytes: int = 1) -> AssetSpec:
    return AssetSpec(
        name="fixture",
        kind="weight",
        target=Path("weights/fixture.pth"),
        sources=("https://example.invalid/fixture.pth",),
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        checkpoint_format=None,
        min_bytes=min_bytes,
    )


@pytest.mark.parametrize(
    "payload,content_type,expected_code",
    [
        (b"<html><title>Sign in</title></html>", "text/html", "html_payload"),
        (b"<?xml version='1.0'?><Error/>", "application/xml", "xml_payload"),
        (
            b"version https://git-lfs.github.com/spec/v1\noid sha256:abcd\nsize 1\n",
            "application/octet-stream",
            "git_lfs_pointer",
        ),
    ],
)
def test_probe_rejects_non_asset_payloads(
    payload: bytes, content_type: str, expected_code: str
) -> None:
    assert expected_code in probe_response(payload, content_type, len(payload))


def test_validate_download_accepts_exact_binary_and_reports_bytes(tmp_path: Path) -> None:
    payload = bytes(range(256)) * 4
    path = tmp_path / "asset.pth"
    path.write_bytes(payload)

    receipt = validate_download(path, _spec(payload), content_type="application/octet-stream")

    assert receipt.status == "passed"
    assert receipt.bytes == len(payload)
    assert receipt.sha256 == hashlib.sha256(payload).hexdigest()
    assert receipt.errors == ()


def test_validate_download_rejects_wrong_hash_without_modifying_file(tmp_path: Path) -> None:
    payload = b"real binary payload"
    path = tmp_path / "asset.pth"
    path.write_bytes(payload)
    spec = _spec(b"different expected payload")

    receipt = validate_download(path, spec)

    assert receipt.status == "failed"
    assert "sha256_mismatch" in receipt.errors
    assert path.read_bytes() == payload


def test_validate_download_rejects_zero_and_too_small_files(tmp_path: Path) -> None:
    empty = tmp_path / "empty.pth"
    empty.write_bytes(b"")
    small = tmp_path / "small.pth"
    small.write_bytes(b"1234")

    empty_receipt = validate_download(empty, _spec(b""))
    small_receipt = validate_download(small, _spec(b"1234", min_bytes=5))

    assert "empty_file" in empty_receipt.errors
    assert "below_minimum_size" in small_receipt.errors


def test_validate_download_rejects_html_even_when_hash_matches(tmp_path: Path) -> None:
    payload = b"<!doctype html><html>Microsoft login</html>"
    path = tmp_path / "model.pth"
    path.write_bytes(payload)

    receipt = validate_download(path, _spec(payload), content_type="application/octet-stream")

    assert receipt.status == "failed"
    assert "html_payload" in receipt.errors


def _internvideo_stage2_checkpoint() -> dict[str, object]:
    required = {
        "cls_token": object(),
        "pos_embed": object(),
        "patch_embed.proj.weight": object(),
        "blocks.0.attn.qkv.weight": object(),
        "final_clip_decoder.norm.bias": object(),
    }
    required.update({f"fixture.{index}": object() for index in range(217 - len(required))})
    return required


def test_checkpoint_structure_uses_safe_loader_and_accepts_fixed_b14_stage2(
    tmp_path: Path,
) -> None:
    path = tmp_path / "B14_dist_1B_stage2.pth"
    path.write_bytes(b"checkpoint")
    calls = []

    def loader(candidate, **kwargs):
        calls.append((candidate, kwargs))
        return _internvideo_stage2_checkpoint()

    receipt = validate_checkpoint_structure(path, "internvideo2_b14", load_fn=loader)

    assert receipt.status == "passed"
    assert receipt.key_count == 217
    assert calls == [(path, {"map_location": "cpu", "weights_only": True})]


def test_checkpoint_structure_accepts_fixed_extra_clip_and_beats_layout(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.pt"
    path.write_bytes(b"checkpoint")
    extra_keys = {
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
    extra = validate_checkpoint_structure(
        path,
        "internvideo2_clip_b14",
        load_fn=lambda *_args, **_kwargs: {key: object() for key in extra_keys},
    )
    beats_model = {
        "post_extract_proj.weight": object(),
        "patch_embedding.weight": object(),
        "encoder.layers.0.self_attn.q_proj.weight": object(),
        "encoder.layers.11.self_attn.grep_linear.bias": object(),
    }
    beats_model.update(
        {f"fixture.{index}": object() for index in range(250 - len(beats_model))}
    )
    beats = validate_checkpoint_structure(
        path,
        "beats_iter3_plus_as2m",
        load_fn=lambda *_args, **_kwargs: {
            "cfg": {
                "encoder_layers": 12,
                "encoder_embed_dim": 768,
                "encoder_attention_heads": 12,
                "embed_dim": 512,
            },
            "model": beats_model,
        },
    )

    assert extra.status == "passed"
    assert extra.key_count == 19
    assert beats.status == "passed"
    assert beats.key_count == 2


def test_checkpoint_structure_fails_closed_on_missing_official_keys(tmp_path: Path) -> None:
    path = tmp_path / "B14_dist_1B_stage2.pth"
    path.write_bytes(b"checkpoint")
    checkpoint = _internvideo_stage2_checkpoint()
    checkpoint.pop("cls_token")

    receipt = validate_checkpoint_structure(
        path, "internvideo2_b14", load_fn=lambda *_args, **_kwargs: checkpoint
    )

    assert receipt.status == "failed"
    assert "internvideo2_b14: exact key count must be 217" in receipt.errors
    assert "internvideo2_b14: missing key cls_token" in receipt.errors
