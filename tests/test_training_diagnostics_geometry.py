import pytest
import torch

from src.utils.training_diagnostics import summarize_tensor_geometry


def test_temporal_geometry_reports_within_sample_std_and_ratio() -> None:
    tensor = torch.tensor([[[1.0], [1.0], [5.0]], [[2.0], [2.0], [100.0]]])
    mask = torch.tensor([[True, True, False], [True, True, False]])
    result = summarize_tensor_geometry(tensor, mask)
    assert result["within_sample_temporal_std_mean"] == pytest.approx(0.0)
    assert result["centered_to_total_l2_ratio"] == pytest.approx(0.0)


def test_temporal_geometry_uses_only_valid_segments() -> None:
    tensor = torch.tensor([[[0.0, 0.0], [2.0, 0.0], [100.0, 100.0]]])
    mask = torch.tensor([[True, True, False]])
    result = summarize_tensor_geometry(tensor, mask)
    assert result["within_sample_temporal_std_mean"] == pytest.approx(2**-0.5)
    assert result["centered_to_total_l2_ratio"] == pytest.approx(0.5)
