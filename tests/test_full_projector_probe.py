from __future__ import annotations

import copy

import pytest
import torch

from scripts.diagnose_full_projector_probe import probe_strong_projector


def _fixture() -> tuple[torch.nn.Module, torch.Tensor, torch.Tensor, torch.Tensor]:
    projector = torch.nn.Linear(2, 2, bias=False)
    with torch.no_grad():
        projector.weight.copy_(torch.tensor([[1.0, 0.5], [-0.25, 0.75]]))
    decision = torch.tensor(
        [[[0.2, -0.1], [1.4, 0.3], [0.0, 9.0]]], dtype=torch.float64
    )
    teacher = torch.tensor(
        [[[1.0, 0.0], [0.0, 2.0], [7.0, 7.0]]], dtype=torch.float64
    )
    mask = torch.tensor([[1.0, 1.0, 0.0]], dtype=torch.float64)
    return projector.double(), decision, teacher, mask


def test_probe_compares_literal_mean_and_sum_gradients_on_disposable_clones() -> None:
    projector, decision, teacher, mask = _fixture()
    source_state = copy.deepcopy(projector.state_dict())

    report = probe_strong_projector(
        projector=projector,
        decision_features=decision,
        teacher_features=teacher,
        mask=mask,
        learning_rate=1e-2,
    )

    mean = report["reductions"]["mean_feature_then_masked_mean_segments"]
    summed = report["reductions"]["sum_feature_then_masked_mean_segments"]
    assert report["feature_dimension"] == 2
    assert summed["loss"] == pytest.approx(2.0 * mean["loss"])
    assert summed["gradient_l2"]["projector"] == pytest.approx(
        2.0 * mean["gradient_l2"]["projector"]
    )
    assert summed["gradient_l2"]["student_decision"] == pytest.approx(
        2.0 * mean["gradient_l2"]["student_decision"]
    )
    assert mean["gradient_l2"]["projector"] > 0.0
    assert mean["gradient_l2"]["student_decision"] > 0.0
    assert report["source_projector"]["state_sha256_before"] == report[
        "source_projector"
    ]["state_sha256_after"]
    assert report["source_projector"]["gradients_remained_none"] is True
    assert report["disposable_adamw_step"]["clone_state_changed"] is True
    assert report["disposable_adamw_step"]["persisted"] is False
    assert report["disposable_adamw_step"]["source_state_unchanged"] is True
    assert report["disposable_adamw_step"]["target_variance_before"] >= 0.0
    assert report["disposable_adamw_step"]["target_variance_after"] >= 0.0
    assert projector.state_dict().keys() == source_state.keys()
    assert all(
        torch.equal(projector.state_dict()[name], source_state[name])
        for name in source_state
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "bad_decision_shape",
        "bad_mask_shape",
        "empty_mask",
        "nonfinite",
        "bad_lr",
        "zero_gradient",
    ],
)
def test_probe_fails_closed_on_invalid_inputs(mutation: str) -> None:
    projector, decision, teacher, mask = _fixture()
    learning_rate = 1e-2
    if mutation == "bad_decision_shape":
        decision = decision[:, :, :1]
    elif mutation == "bad_mask_shape":
        mask = mask[:, :2]
    elif mutation == "empty_mask":
        mask = torch.zeros_like(mask)
    elif mutation == "nonfinite":
        teacher[0, 0, 0] = float("nan")
    elif mutation == "zero_gradient":
        with torch.no_grad():
            projector.weight.copy_(torch.eye(2, dtype=torch.float64))
        decision = teacher.clone()
    else:
        learning_rate = 0.0

    with pytest.raises(ValueError):
        probe_strong_projector(
            projector=projector,
            decision_features=decision,
            teacher_features=teacher,
            mask=mask,
            learning_rate=learning_rate,
        )
