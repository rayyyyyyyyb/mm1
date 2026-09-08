from __future__ import annotations

import pytest
import torch
from torch import nn
import yaml

from src.utils.pretrained_config import resolve_modality_pretrained
from scripts.audit_pretrained_backbones import build_pretrained_backbone_report


class _FakeEncoder(nn.Module):
    def __init__(self, model_name: str, *, pretrained: bool) -> None:
        super().__init__()
        self.backbone = nn.Linear(2, 2, bias=False)
        with torch.no_grad():
            self.backbone.weight.fill_(2.0 if pretrained else 1.0)
        self.backbone.pretrained_cfg = {"architecture": model_name, "requested": pretrained}
        self.feature_dim = 2


def test_legacy_pretrained_is_used_only_when_both_new_fields_are_absent() -> None:
    assert resolve_modality_pretrained({"pretrained": True}) == (True, True)
    assert resolve_modality_pretrained({"pretrained": False}) == (False, False)
    assert resolve_modality_pretrained({}) == (False, False)


def test_visual_and_audio_pretrained_fields_allow_independent_overrides() -> None:
    assert resolve_modality_pretrained({"visual_pretrained": True, "audio_pretrained": False}) == (True, False)
    assert resolve_modality_pretrained({"visual_pretrained": False, "audio_pretrained": True}) == (False, True)


@pytest.mark.parametrize(
    "config",
    [
        {"visual_pretrained": True},
        {"audio_pretrained": False},
        {"pretrained": True, "visual_pretrained": True, "audio_pretrained": True},
        {"visual_pretrained": 1, "audio_pretrained": False},
        {"visual_pretrained": False, "audio_pretrained": "yes"},
    ],
)
def test_malformed_or_ambiguous_pretrained_fields_fail_closed(config: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        resolve_modality_pretrained(config)


def test_backbone_report_records_independent_requested_states(tmp_path) -> None:
    config_path = tmp_path / "independent.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "seed": 42,
                "student": {
                    "visual_pretrained": True,
                    "audio_pretrained": False,
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
        return _FakeEncoder(model_name, pretrained=pretrained)

    report = build_pretrained_backbone_report(config_path, encoder_factory=factory)
    assert report["resolved_modality_pretrained"] == {"visual": True, "audio": False}
    assert report["backbones"]["visual"]["requested_pretrained"] is True
    assert report["backbones"]["audio"]["requested_pretrained"] is False
    assert calls == [("visual.fake", True), ("visual.fake", False), ("audio.fake", False)]


def test_student_constructs_visual_and_audio_encoders_independently(monkeypatch) -> None:
    pytest.importorskip("timm")
    import src.models.ov_orthkd as module

    calls: list[tuple[str, bool]] = []

    class FakeSequenceEncoder(nn.Module):
        def __init__(self, model_name: str, pretrained: bool = False) -> None:
            super().__init__()
            calls.append((model_name, pretrained))
            self.feature_dim = 4
            self.backbone = nn.Identity()

        def forward(self, x):
            return torch.zeros(*x.shape[:2], 4, device=x.device)

    monkeypatch.setattr(module, "SequenceImageEncoder", FakeSequenceEncoder)
    model = module.OVOrthKDStudent(
        visual_backbone="visual.fake",
        audio_backbone="audio.fake",
        text_dim=4,
        fusion_dim=8,
        projection_dim=4,
        temporal_layers=1,
        temporal_heads=1,
        temporal_dropout=0.0,
        visual_pretrained=True,
        audio_pretrained=False,
    )
    assert calls == [("visual.fake", True), ("audio.fake", False)]
    assert model.visual_pretrained is True
    assert model.audio_pretrained is False
