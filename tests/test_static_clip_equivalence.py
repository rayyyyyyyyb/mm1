from __future__ import annotations

import torch

from scripts.check_static_clip_equivalence import compare_equivalence


def _step(projector_value: float) -> dict[str, object]:
    return {
        "target": torch.tensor([[1.0, 2.0]]),
        "loss": torch.tensor(0.5),
        "pre_clip_student_grad": torch.tensor([1.0, 2.0]),
        "post_clip_student_grad": torch.tensor([0.1, 0.2]),
        "student_parameters": torch.tensor([3.0, 4.0]),
        "projector_receipt": torch.tensor([projector_value]),
    }


def test_equivalence_allows_only_projector_receipt_difference() -> None:
    result = compare_equivalence([_step(1.0) for _ in range(10)], [_step(2.0) for _ in range(10)])
    assert result["pass"] is True
    assert result["steps"] == 10
    assert result["projector_receipt_differences"] == 10


def test_equivalence_fails_on_student_gradient_or_parameter_difference() -> None:
    static = [_step(1.0) for _ in range(10)]
    frozen = [_step(1.0) for _ in range(10)]
    frozen[3]["post_clip_student_grad"] = torch.tensor([0.1, 0.3])
    result = compare_equivalence(static, frozen)
    assert result["pass"] is False
    assert "post_clip_student_grad" in result["mismatches"]
