from __future__ import annotations

import pytest
import torch

from src.utils.optimizer_receipts import (
    clip_gradients_with_receipt,
    resolve_clipping_scope_parameters,
)


def test_positive_lr_clip_scope_excludes_zero_lr_group_but_reports_all_groups() -> None:
    student = torch.nn.Parameter(torch.tensor([3.0]))
    projector = torch.nn.Parameter(torch.tensor([4.0]))
    student.grad = torch.tensor([3.0])
    projector.grad = torch.tensor([4.0])
    groups = [
        {"group_name": "student", "params": [student], "lr": 0.1},
        {"group_name": "projector", "params": [projector], "lr": 0.0},
    ]

    pre_norm, coefficient, group_norms, contributions, clipped = clip_gradients_with_receipt(
        [student, projector], groups, 1.0, clip_parameters=[student]
    )

    assert pre_norm == pytest.approx(3.0)
    assert coefficient == pytest.approx(1.0 / 3.0)
    assert student.grad.item() == pytest.approx(1.0)
    assert projector.grad.item() == pytest.approx(4.0)
    assert group_norms == {"student": pytest.approx(3.0), "projector": pytest.approx(4.0)}
    assert contributions["projector"] > 1.0
    assert clipped


def test_scope_resolver_fails_closed_and_selects_positive_lr_parameters() -> None:
    student = torch.nn.Parameter(torch.tensor([1.0]))
    projector = torch.nn.Parameter(torch.tensor([1.0]))
    groups = [
        {"group_name": "student", "params": [student], "lr": 0.1},
        {"group_name": "projector", "params": [projector], "lr": 0.0},
    ]
    selected = resolve_clipping_scope_parameters(
        [student, projector], groups, {"training": {"gradient_clipping": {"scope": "optimizer_groups_with_positive_lr"}}}
    )
    assert selected == [student]
    with pytest.raises(ValueError, match="unsupported gradient clipping scope"):
        resolve_clipping_scope_parameters(
            [student], groups, {"training": {"gradient_clipping": {"scope": "unknown"}}}
        )
