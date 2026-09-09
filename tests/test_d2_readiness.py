from __future__ import annotations

from pathlib import Path

import pytest
import torch
from torch import nn

import scripts.audit_d2_readiness as audit


class _VisualEncoder(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.backbone = nn.Linear(2, 2, bias=False)


class _Student(nn.Module):
    def __init__(self, *, alter_nonvisual: bool = False) -> None:
        super().__init__()
        self.visual_encoder = _VisualEncoder()
        self.audio_encoder = nn.Linear(2, 2, bias=False)
        self.head = nn.Linear(2, 1, bias=False)
        if alter_nonvisual:
            with torch.no_grad():
                self.audio_encoder.weight.add_(1.0)
        self.visual_pretrained = False


def _locked_receipt(backbone: nn.Module) -> dict[str, object]:
    tensor_hash = audit._state_tensor_sha256(backbone.state_dict())
    return {
        "model_id": "timm/fake.visual",
        "revision": "abc123",
        "source_state_key_sha256": "key-hash",
        "source_state_tensor_sha256": tensor_hash,
        "loaded_backbone_key_sha256": "key-hash-no-head",
        "loaded_backbone_tensor_sha256": tensor_hash,
        "parameter_count": 4,
        "feature_dim": 2,
    }


def _patch_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    lock_path: Path,
    *,
    gpu_name: str = "NVIDIA GeForce RTX 5090",
    alter_nonvisual: bool = False,
) -> None:
    d2 = {
        "tag": "d2",
        "diagnostic": {"pretrained_asset_lock": str(lock_path)},
        "student": {
            "visual_backbone": "fake.visual",
            "visual_pretrained": True,
            "audio_pretrained": False,
        },
    }
    c2 = {
        "tag": "c2",
        "student": {
            "visual_backbone": "fake.visual",
            "visual_pretrained": False,
            "audio_pretrained": False,
        },
    }
    monkeypatch.setattr(audit, "_load_probe_config", lambda _: d2)
    monkeypatch.setattr(audit, "_resolve_config_file", lambda _: c2)
    monkeypatch.setattr(
        audit,
        "_runtime_versions",
        lambda: {"gpu_name": gpu_name, "cuda_available": True},
    )

    def fake_locked_loader(*args, **kwargs):
        del args, kwargs
        backbone = nn.Linear(2, 2, bias=False)
        with torch.no_grad():
            backbone.weight.fill_(9.0)
        return backbone, _locked_receipt(backbone)

    def fake_builder(config, device):
        del device
        student = _Student(
            alter_nonvisual=alter_nonvisual and config.get("tag") == "d2"
        )
        return student, nn.Linear(2, 2, bias=False)

    monkeypatch.setattr(audit, "load_locked_timm_encoder", fake_locked_loader)
    monkeypatch.setattr(audit, "_build_model_and_loss", fake_builder)
    monkeypatch.setattr(audit, "_set_seed", torch.manual_seed)


def test_d2_readiness_is_zero_training_and_checks_nonvisual_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = tmp_path / "lock.yaml"
    lock.write_text("placeholder", encoding="utf-8")
    _patch_dependencies(monkeypatch, lock)
    output = tmp_path / "readiness.json"

    result = audit.audit_d2_readiness(
        c2_config_path=tmp_path / "c2.yaml",
        d2_config_path=tmp_path / "d2.yaml",
        asset_lock_path=lock,
        asset_root=tmp_path / "asset",
        output=output,
    )

    assert result["status"] == "D2_PROBE_READY_FOR_ZERO_TRAINING_GATE"
    assert result["locked_load"]["repeat_load_equal"] is True
    assert result["initialization_parity"]["pass"] is True
    assert result["initialization_parity"]["visual_state_changed"] is True
    assert all(value is False for key, value in result["protocol"].items() if key != "seed" and key != "zero_training_only")
    assert result["protocol"]["zero_training_only"] is True
    assert output.is_file()


def test_d2_readiness_rejects_wrong_gpu_before_asset_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = tmp_path / "lock.yaml"
    lock.write_text("placeholder", encoding="utf-8")
    _patch_dependencies(monkeypatch, lock, gpu_name="NVIDIA GeForce RTX 4070")
    result = audit.audit_d2_readiness(
        c2_config_path=tmp_path / "c2.yaml",
        d2_config_path=tmp_path / "d2.yaml",
        asset_lock_path=lock,
        asset_root=tmp_path / "asset",
        output=tmp_path / "readiness.json",
    )
    assert result["status"] == "BLOCKED_BY_TARGET_5090_ENVIRONMENT"


def test_d2_readiness_rejects_nonvisual_initialization_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = tmp_path / "lock.yaml"
    lock.write_text("placeholder", encoding="utf-8")
    _patch_dependencies(monkeypatch, lock, alter_nonvisual=True)
    result = audit.audit_d2_readiness(
        c2_config_path=tmp_path / "c2.yaml",
        d2_config_path=tmp_path / "d2.yaml",
        asset_lock_path=lock,
        asset_root=tmp_path / "asset",
        output=tmp_path / "readiness.json",
    )
    assert result["status"] == "BLOCKED_BY_INITIALIZATION_PARITY"
