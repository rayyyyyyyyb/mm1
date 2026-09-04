import torch
from torch import nn

from src.utils.projector_update_modes import (
    apply_projector_update_modes,
    build_named_optimizer_groups,
    resolve_projector_update_modes,
    tensor_state_sha256,
)


class _Loss(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.strong_teacher_proj = nn.Linear(3, 2)
        self.weak_teacher_proj = nn.Linear(3, 2)
        self.text_teacher_proj = nn.Linear(3, 2)


def test_legacy_boolean_fallback_is_explicit() -> None:
    assert resolve_projector_update_modes({"teacher_target_projector_trainable": True}) == {
        "strong_teacher": "trainable",
        "weak_teacher": "trainable",
        "text_teacher": "trainable",
    }
    assert resolve_projector_update_modes({"teacher_target_projector_trainable": False})["strong_teacher"] == "frozen_no_grad"


def test_partial_or_conflicting_new_fields_fail_closed() -> None:
    try:
        resolve_projector_update_modes({"strong_teacher_projector_update_mode": "trainable"})
    except ValueError as exc:
        assert "all three" in str(exc)
    else:
        raise AssertionError("partial new mode configuration must fail")
    try:
        resolve_projector_update_modes(
            {
                "teacher_target_projector_trainable": True,
                "strong_teacher_projector_update_mode": "static_zero_lr_keep_grad",
                "weak_teacher_projector_update_mode": "trainable",
                "text_teacher_projector_update_mode": "trainable",
            }
        )
    except ValueError as exc:
        assert "conflict" in str(exc).lower()
    else:
        raise AssertionError("old/new fields must fail closed")


def test_static_mode_keeps_grad_but_zero_group_hyperparameters() -> None:
    loss = _Loss()
    modes = {
        "strong_teacher": "static_zero_lr_keep_grad",
        "weak_teacher": "frozen_no_grad",
        "text_teacher": "trainable",
    }
    apply_projector_update_modes(loss, modes)
    assert all(p.requires_grad for p in loss.strong_teacher_proj.parameters())
    assert not any(p.requires_grad for p in loss.weak_teacher_proj.parameters())
    before = tensor_state_sha256(loss.strong_teacher_proj)
    groups = build_named_optimizer_groups(
        nn.Linear(3, 2), loss, learning_rate=0.01, weight_decay=0.1, modes=modes
    )
    static = next(group for group in groups if group["group_name"] == "loss.strong_teacher_proj")
    assert static["lr"] == 0.0 and static["weight_decay"] == 0.0
    assert static["update_mode"] == "static_zero_lr_keep_grad"
    optimizer = torch.optim.AdamW(groups)
    loss.strong_teacher_proj.weight.sum().backward()
    optimizer.step()
    assert static["params"][0].grad is not None
    assert tensor_state_sha256(loss.strong_teacher_proj) == before
    assert optimizer.state[static["params"][0]], "moments may update even when lr is zero"


def test_named_groups_have_unique_parameter_names() -> None:
    loss = _Loss()
    modes = resolve_projector_update_modes({})
    apply_projector_update_modes(loss, modes)
    groups = build_named_optimizer_groups(nn.Linear(3, 2), loss, learning_rate=0.01, weight_decay=0.1, modes=modes)
    names = [name for group in groups for name in group["param_names"]]
    assert len(names) == len(set(names))
    assert all(group["parameter_count"] > 0 for group in groups)
