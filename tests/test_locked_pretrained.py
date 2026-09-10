from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import torch
import yaml

from src.utils.locked_pretrained import (
    _state_key_sha256,
    _state_tensor_sha256,
    compare_nonvisual_initialization,
    load_locked_timm_state_into_encoder,
    resolve_locked_asset,
)


def _write_locked_asset(tmp_path: Path) -> Path:
    root = tmp_path / "asset"
    root.mkdir()
    config = b'{"architectures":["convnextv2_tiny"]}\n'
    weights = b"locked weights"
    (root / "config.json").write_bytes(config)
    (root / "model.safetensors").write_bytes(weights)
    lock = tmp_path / "lock.yaml"
    lock.write_text(
        yaml.safe_dump(
            {
                "model": {
                    "id": "timm/fake",
                    "revision": "abc123",
                    "files": {
                        "config.json": {
                            "size_bytes": len(config),
                            "sha256": hashlib.sha256(config).hexdigest(),
                        },
                        "model.safetensors": {
                            "size_bytes": len(weights),
                            "sha256": hashlib.sha256(b"locked weights").hexdigest(),
                        },
                    },
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return lock


def test_resolve_locked_asset_verifies_size_and_sha256(tmp_path: Path) -> None:
    lock = _write_locked_asset(tmp_path)
    _, files = resolve_locked_asset(lock, tmp_path / "asset")
    assert files["config.json"].read_bytes().startswith(b"{")
    (tmp_path / "asset" / "model.safetensors").write_bytes(b"changed weights")
    with pytest.raises(ValueError, match="size|sha256"):
        resolve_locked_asset(lock, tmp_path / "asset")


def test_state_fingerprints_are_key_order_invariant() -> None:
    first = {
        "b": torch.tensor([2.0]),
        "a": torch.tensor([1.0]),
        "scalar_long_buffer": torch.tensor(0, dtype=torch.long),
    }
    second = {
        "scalar_long_buffer": first["scalar_long_buffer"].clone(),
        "a": first["a"].clone(),
        "b": first["b"].clone(),
    }
    assert _state_key_sha256(first) == _state_key_sha256(second)
    assert _state_tensor_sha256(first) == _state_tensor_sha256(second)


def test_nonvisual_initialization_parity_is_bitwise_and_excludes_visual() -> None:
    reference = {
        "visual_encoder.weight": torch.tensor([1.0]),
        "audio_encoder.weight": torch.tensor([2.0]),
        "temporal.bias": torch.tensor([3.0]),
    }
    candidate = {
        "visual_encoder.weight": torch.tensor([9.0]),
        "audio_encoder.weight": torch.tensor([2.0]),
        "temporal.bias": torch.tensor([3.0]),
    }
    receipt = compare_nonvisual_initialization(reference, candidate)
    assert receipt["pass"] is True
    assert receipt["compared_key_count"] == 2

    candidate["temporal.bias"] = torch.tensor([4.0])
    with pytest.raises(ValueError, match="non-visual initialization differs"):
        compare_nonvisual_initialization(reference, candidate)


def test_locked_state_can_be_injected_into_existing_encoder(monkeypatch: pytest.MonkeyPatch) -> None:
    class Encoder:
        backbone = torch.nn.Linear(2, 2)

    called = {}

    def fake_loader(backbone, model_name, lock_path, *, asset_root=None):
        called.update(
            backbone=backbone,
            model_name=model_name,
            lock_path=lock_path,
            asset_root=asset_root,
        )
        return {"weights_sha256": "a" * 64}

    monkeypatch.setattr(
        "src.utils.locked_pretrained._load_locked_state_into_backbone", fake_loader
    )
    encoder = Encoder()
    receipt = load_locked_timm_state_into_encoder(
        encoder, "fake", "lock.yaml", asset_root="asset"
    )
    assert called["backbone"] is encoder.backbone
    assert receipt["loaded_into_existing_encoder"] is True
