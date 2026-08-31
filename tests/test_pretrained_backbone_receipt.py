from __future__ import annotations

from pathlib import Path

import pytest
import torch
from torch import nn
import yaml

from scripts.audit_pretrained_backbones import (
    audit_backbone_initialization,
    build_pretrained_backbone_report,
    state_dict_sha256,
)


class _FakeEncoder(nn.Module):
    def __init__(self, model_name: str, *, pretrained: bool, value: float) -> None:
        super().__init__()
        self.backbone = nn.Linear(2, 2, bias=False)
        with torch.no_grad():
            self.backbone.weight.fill_(value)
        self.backbone.pretrained_cfg = {
            "architecture": model_name,
            "tag": "fake.weights" if pretrained else None,
            "hf_hub_id": f"fake/{model_name}" if pretrained else None,
        }
        self.feature_dim = 2


def test_state_dict_hash_is_order_stable_and_value_sensitive() -> None:
    first = {"b": torch.tensor([2.0]), "a": torch.tensor([1.0])}
    reordered = {"a": torch.tensor([1.0]), "b": torch.tensor([2.0])}
    changed = {"a": torch.tensor([1.0]), "b": torch.tensor([3.0])}

    assert state_dict_sha256(first) == state_dict_sha256(reordered)
    assert state_dict_sha256(first) != state_dict_sha256(changed)


def test_state_dict_hash_supports_scalar_integer_buffers() -> None:
    first = {"num_batches_tracked": torch.tensor(7, dtype=torch.long)}
    same = {"num_batches_tracked": torch.tensor(7, dtype=torch.long)}
    changed = {"num_batches_tracked": torch.tensor(8, dtype=torch.long)}

    assert state_dict_sha256(first) == state_dict_sha256(same)
    assert state_dict_sha256(first) != state_dict_sha256(changed)


def test_backbone_audit_calls_true_then_false_and_receipts_different_states() -> None:
    calls: list[tuple[str, bool]] = []

    def factory(model_name: str, pretrained: bool = False) -> _FakeEncoder:
        calls.append((model_name, pretrained))
        return _FakeEncoder(
            model_name,
            pretrained=pretrained,
            value=2.0 if pretrained else 1.0,
        )

    receipt = audit_backbone_initialization(
        "tiny.backbone", seed=42, encoder_factory=factory
    )

    assert calls == [("tiny.backbone", True), ("tiny.backbone", False)]
    assert receipt["status"] == "PASS"
    assert receipt["pretrained_requested"] is True
    assert receipt["random_reference_requested"] is False
    assert receipt["pretrained_state_sha256"] != receipt["random_state_sha256"]
    assert receipt["resolved_pretrained_cfg"]["hf_hub_id"] == "fake/tiny.backbone"
    assert receipt["feature_dim"] == 2


def test_backbone_audit_never_swallows_pretrained_construction_failure() -> None:
    def factory(model_name: str, pretrained: bool = False) -> _FakeEncoder:
        if pretrained:
            raise RuntimeError(f"download failed for {model_name}")
        return _FakeEncoder(model_name, pretrained=False, value=1.0)

    with pytest.raises(RuntimeError, match="download failed"):
        audit_backbone_initialization("tiny.backbone", seed=42, encoder_factory=factory)


def test_backbone_audit_rejects_equal_pretrained_and_random_state_hashes() -> None:
    def factory(model_name: str, pretrained: bool = False) -> _FakeEncoder:
        return _FakeEncoder(model_name, pretrained=pretrained, value=1.0)

    with pytest.raises(RuntimeError, match="identical"):
        audit_backbone_initialization("tiny.backbone", seed=42, encoder_factory=factory)


def test_report_requires_pretrained_config_and_receipts_both_backbones(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "s3.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "seed": 42,
                "student": {
                    "pretrained": True,
                    "visual_backbone": "visual.fake",
                    "audio_backbone": "audio.fake",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    calls: list[tuple[str, bool]] = []

    def factory(model_name: str, pretrained: bool = False) -> _FakeEncoder:
        calls.append((model_name, pretrained))
        return _FakeEncoder(
            model_name,
            pretrained=pretrained,
            value=2.0 if pretrained else 1.0,
        )

    report = build_pretrained_backbone_report(config_path, encoder_factory=factory)

    assert report["status"] == "PASS"
    assert report["claim_level"] == "runtime_construction_receipt_not_archival_fact"
    assert report["config"]["sha256"] and len(report["config"]["sha256"]) == 64
    assert set(report["backbones"]) == {"visual", "audio"}
    assert calls == [
        ("visual.fake", True),
        ("visual.fake", False),
        ("audio.fake", True),
        ("audio.fake", False),
    ]

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["student"]["pretrained"] = False
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError, match="pretrained=true"):
        build_pretrained_backbone_report(config_path, encoder_factory=factory)
