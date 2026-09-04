import numpy as np

from scripts.audit_static_target_root_cause import (
    feature_geometry,
    gradient_cosine_matrix,
)


def test_feature_geometry_reports_temporal_variation_and_ratio() -> None:
    values = np.asarray([[[1.0], [2.0], [3.0]], [[5.0], [5.0], [5.0]]])
    result = feature_geometry(values, np.ones((2, 3), dtype=np.float32))
    assert result["shape"] == [2, 3, 1]
    assert result["within_sample_temporal_std_mean"] > 0.0
    assert result["centered_row_l2_to_total_row_l2"] > 0.0


def test_gradient_cosines_handle_zero_vectors() -> None:
    result = gradient_cosine_matrix({"bce": np.array([1.0, 0.0]), "visual": np.array([0.0, 1.0]), "zero": np.zeros(2)})
    assert result["bce"]["visual"] == 0.0
    assert result["zero"]["bce"] is None
