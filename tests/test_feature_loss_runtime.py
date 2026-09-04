from __future__ import annotations

import copy

import pytest
import torch
from torch import nn

from scripts.audit_feature_loss_runtime import (
    decompose_runtime_batch,
    module_gradient_receipts,
)


class TinyStudent(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.visual_encoder = nn.Linear(2, 2, bias=False)

    def forward(self, **kwargs: torch.Tensor) -> dict[str, torch.Tensor]:
        del kwargs
        values = torch.tensor(
            [[[1.0, 0.0], [2.0, 0.0], [3.0, 0.0]]],
            dtype=torch.float32,
        )
        return {"decision_features": self.visual_encoder(values)}


class TinyLoss(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.strong_teacher_proj = nn.Identity()
        self.visual_l2_reduction = "mean_feature_then_masked_mean_segments"


def _batch() -> dict[str, torch.Tensor]:
    return {
        "frame": torch.zeros(1, 3, 1),
        "spectrogram": torch.zeros(1, 3, 1),
        "text_embedding": torch.zeros(1, 1),
        "sequence_mask": torch.ones(1, 3),
        "frame_valid": torch.ones(1, 3),
        "audio_valid": torch.ones(1, 3),
        "strong_teacher_features": torch.zeros(1, 3, 2),
        "strong_teacher_feature_mask": torch.ones(1, 3),
        "segment_label": torch.tensor([[1.0, 0.0, 1.0]]),
    }


def test_runtime_decomposition_has_exact_components_and_groups_without_mutation() -> None:
    student = TinyStudent()
    loss_module = TinyLoss()
    student_before = copy.deepcopy(student.state_dict())
    loss_before = copy.deepcopy(loss_module.state_dict())

    result = decompose_runtime_batch(student, loss_module, _batch(), torch.device("cpu"))

    assert result["valid_segments"] == 3
    assert result["groups"]["k=2"]["samples"] == 1
    assert result["groups"]["overall"]["samples"] == 1
    assert result["identity_abs_error"] <= 1e-5
    assert result["mean_term"] + result["centered_term"] == pytest.approx(result["total"])
    assert result["normalized_total"] == pytest.approx(result["total"] / 2.0 / 3.0)
    assert all(torch.equal(student.state_dict()[key], value) for key, value in student_before.items())
    assert all(torch.equal(loss_module.state_dict()[key], value) for key, value in loss_before.items())


def test_module_gradient_receipts_are_finite_and_report_zero_for_unused_modules() -> None:
    module = nn.Module()
    module.visual_encoder = nn.Linear(2, 2, bias=False)
    module.fusion = nn.Linear(2, 2, bias=False)
    value = module.visual_encoder(torch.ones(1, 2)).square().sum()

    receipts = module_gradient_receipts(
        module,
        {"mean": value, "centered": value * 0.5},
    )

    assert receipts["mean"]["visual_encoder"]["norm"] > 0.0
    assert receipts["mean"]["fusion"]["norm"] == pytest.approx(0.0)
    assert receipts["centered"]["visual_encoder"]["norm"] > 0.0
