from __future__ import annotations

import copy

import pytest
import torch
from torch import nn

from scripts.audit_per_loss_gradient_conflict import (
    collect_loss_gradients,
    summarize_pairwise_cosines,
)


class TinyStudent(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.visual_encoder = nn.Linear(2, 1, bias=False)

    def forward(self, **kwargs: torch.Tensor) -> dict[str, torch.Tensor]:
        del kwargs
        values = torch.tensor([[[1.0, 0.0], [0.0, 1.0]]])
        decision = self.visual_encoder(values)
        return {
            "segment_logits": decision.squeeze(-1),
            "decision_features": decision,
            "query_features": decision,
        }


class TinyLoss(nn.Module):
    alpha_strong_feat = 1.0
    alpha_text_align = 1.0
    text_alignment_mode = "legacy_logit_temperature"
    query_anchor_mode = "independent_loss_projection"
    visual_l2_reduction = "mean_feature_then_masked_mean_segments"

    def __init__(self) -> None:
        super().__init__()
        self.strong_teacher_proj = nn.Identity()
        self.text_teacher_proj = nn.Linear(2, 1, bias=False)


def _batch() -> dict[str, torch.Tensor]:
    return {
        "frame": torch.zeros(1, 2, 1),
        "spectrogram": torch.zeros(1, 2, 1),
        "text_embedding": torch.ones(1, 2),
        "sequence_mask": torch.ones(1, 2),
        "frame_valid": torch.ones(1, 2),
        "audio_valid": torch.ones(1, 2),
        "strong_teacher_features": torch.zeros(1, 2, 1),
        "strong_teacher_feature_mask": torch.ones(1, 2),
        "segment_label": torch.tensor([[1.0, 0.0]]),
        "text_valid": torch.ones(1),
    }


def test_collect_loss_gradients_is_finite_and_does_not_mutate_parameters() -> None:
    student = TinyStudent()
    loss = TinyLoss()
    before_student = copy.deepcopy(student.state_dict())
    before_loss = copy.deepcopy(loss.state_dict())

    receipts = collect_loss_gradients(student, loss, _batch(), torch.device("cpu"))

    assert set(receipts) == {"bce", "visual", "text"}
    assert receipts["bce"]["modules"]["visual_encoder"]["norm"] > 0.0
    assert all(torch.equal(student.state_dict()[key], value) for key, value in before_student.items())
    assert all(torch.equal(loss.state_dict()[key], value) for key, value in before_loss.items())


def test_pairwise_cosines_report_medians_and_zero_gradient_as_none() -> None:
    receipts = {
        "bce": {"gradients": {"visual_encoder": torch.tensor([1.0, 0.0])}},
        "visual": {"gradients": {"visual_encoder": torch.tensor([-1.0, 0.0])}},
        "text": {"gradients": {"visual_encoder": torch.tensor([0.0, 0.0])}},
    }
    summary = summarize_pairwise_cosines(receipts)

    assert summary["pairs"]["bce_vs_visual"]["median"] == pytest.approx(-1.0)
    assert summary["pairs"]["bce_vs_visual"]["negative_fraction"] == pytest.approx(1.0)
    assert summary["pairs"]["text_vs_visual"]["finite_count"] == 0
    assert summary["classification"] == "INTRINSIC_GRADIENT_CONFLICT"
