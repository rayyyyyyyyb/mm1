import torch

from src.utils.feature_loss import decompose_temporal_squared_error


def test_temporal_squared_error_decomposition_is_exact() -> None:
    student = torch.tensor(
        [[[1.0, 0.0], [2.0, 1.0], [4.0, 3.0]], [[-1.0, 2.0], [0.0, 1.0], [2.0, 0.0]]]
    )
    target = torch.zeros_like(student)
    mask = torch.ones(2, 3)
    result = decompose_temporal_squared_error(student, target, mask)
    assert torch.allclose(result["total"], result["mean_term"] + result["temporal_term"])
    assert torch.allclose(result["total"], (student - target).pow(2).sum())


def test_decomposition_respects_mask_and_positive_count_groups() -> None:
    student = torch.tensor([[[1.0], [2.0], [3.0]], [[2.0], [2.0], [2.0]]])
    target = torch.zeros_like(student)
    mask = torch.tensor([[1.0, 1.0, 0.0], [1.0, 1.0, 1.0]])
    labels = torch.tensor([[1.0, 0.0, 0.0], [1.0, 1.0, 1.0]])
    result = decompose_temporal_squared_error(student, target, mask, labels)
    assert torch.allclose(result["total"], torch.tensor(17.0))
    assert result["groups"]["k=1"]["samples"] == 1
    assert result["groups"]["k=3"]["samples"] == 1
    assert result["groups"]["overall"]["samples"] == 2


def test_decomposition_rejects_bad_shapes() -> None:
    tensor = torch.zeros(2, 3, 4)
    try:
        decompose_temporal_squared_error(tensor, tensor, torch.ones(2, 4))
    except ValueError as exc:
        assert "mask" in str(exc)
    else:
        raise AssertionError("shape mismatch must fail")
