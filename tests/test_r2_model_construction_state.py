from __future__ import annotations

import torch
from torch import nn

import src.models.ov_orthkd as model_module
from src.models.ov_orthkd import SequenceImageEncoder


class _BatchNormBackbone(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.bn = nn.BatchNorm2d(3)
        self.pool = nn.AdaptiveAvgPool2d(1)

    def forward(self, value: torch.Tensor) -> torch.Tensor:
        return self.pool(self.bn(value)).flatten(1)


class _DeclaredBackbone(nn.Module):
    num_features = 7

    def forward(self, value: torch.Tensor) -> torch.Tensor:
        raise AssertionError("declared num_features should avoid a probe forward")


class _HeadDeclaredBackbone(nn.Module):
    num_features = 3
    head_hidden_size = 5

    def forward(self, value: torch.Tensor) -> torch.Tensor:
        return torch.zeros(value.shape[0], self.head_hidden_size)


def test_feature_dim_probe_preserves_batchnorm_buffers_and_training_mode(monkeypatch) -> None:
    backbone = _BatchNormBackbone()
    before_mean = backbone.bn.running_mean.clone()
    before_variance = backbone.bn.running_var.clone()
    monkeypatch.setattr(model_module.timm, "create_model", lambda *args, **kwargs: backbone)

    encoder = SequenceImageEncoder("test-backbone", pretrained=False)

    assert encoder.feature_dim == 3
    assert backbone.training is True
    assert torch.equal(backbone.bn.running_mean, before_mean)
    assert torch.equal(backbone.bn.running_var, before_variance)


def test_declared_backbone_feature_dim_avoids_probe_forward(monkeypatch) -> None:
    backbone = _DeclaredBackbone()
    monkeypatch.setattr(model_module.timm, "create_model", lambda *args, **kwargs: backbone)

    encoder = SequenceImageEncoder("declared-backbone", pretrained=False)

    assert encoder.feature_dim == 7


def test_head_hidden_size_wins_when_timm_forward_includes_head_projection(monkeypatch) -> None:
    backbone = _HeadDeclaredBackbone()
    monkeypatch.setattr(model_module.timm, "create_model", lambda *args, **kwargs: backbone)

    encoder = SequenceImageEncoder("head-projected-backbone", pretrained=False)

    assert encoder.feature_dim == 5
