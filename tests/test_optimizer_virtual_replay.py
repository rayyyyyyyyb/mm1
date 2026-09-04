from __future__ import annotations

import copy

import pytest
import torch

from scripts.audit_optimizer_virtual_replay import replay_virtual_update, summarize_virtual_deltas


def test_virtual_adamw_matches_real_one_step_and_preserves_inputs() -> None:
    parameter = torch.tensor([1.0, -2.0], dtype=torch.float64)
    gradient = torch.tensor([3.0, 4.0], dtype=torch.float64)
    state = {
        "groups": {"weight": {"lr": 0.1, "weight_decay": 0.01}},
        "hyperparameters": {"betas": (0.9, 0.999), "eps": 1e-8, "max_norm": 1.0},
        "state": {"weight": {"step": 0, "exp_avg": torch.zeros(2, dtype=torch.float64), "exp_avg_sq": torch.zeros(2, dtype=torch.float64)}},
    }
    before_parameter = parameter.clone()
    before_state = copy.deepcopy(state)
    replay = replay_virtual_update({"weight": parameter}, state, {"weight": gradient}, clip_scope="current_global_all_grad_clip")

    real = torch.nn.Parameter(parameter.clone())
    optimizer = torch.optim.AdamW([{"params": [real], "lr": 0.1, "weight_decay": 0.01}], betas=(0.9, 0.999), eps=1e-8)
    real.grad = gradient.clone()
    torch.nn.utils.clip_grad_norm_([real], 1.0)
    optimizer.step()

    assert replay["parameters"]["weight"] == pytest.approx(real.detach())
    assert torch.equal(parameter, before_parameter)
    assert state["state"]["weight"]["step"] == before_state["state"]["weight"]["step"]
    assert torch.equal(state["state"]["weight"]["exp_avg"], before_state["state"]["weight"]["exp_avg"])


def test_positive_lr_scope_excludes_zero_lr_group_and_summarizes_deltas() -> None:
    parameters = {"student": torch.tensor([1.0]), "projector": torch.tensor([1.0])}
    gradients = {"student": torch.tensor([2.0]), "projector": torch.tensor([100.0])}
    state = {
        "groups": {
            "student": {"lr": 0.1, "weight_decay": 0.0},
            "projector": {"lr": 0.0, "weight_decay": 0.0},
        },
        "hyperparameters": {"max_norm": 1.0},
    }
    replay = replay_virtual_update(parameters, state, gradients, clip_scope="updating_parameters_only_clip")
    assert replay["clip_scope"] == "updating_parameters_only_clip"
    assert replay["included_parameters"] == ["student"]
    assert replay["parameters"]["projector"] == pytest.approx(1.0)
    summary = summarize_virtual_deltas({"all": replay, "positive": replay})
    assert summary["scopes"] == ["all", "positive"]
