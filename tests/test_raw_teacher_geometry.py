from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import torch
from torch import nn

from scripts.diagnose_raw_teacher_geometry import (
    _teacher_cache_lock_receipt,
    build_raw_teacher_report,
    fit_linear_probe_metrics,
    pairwise_distance_correlation,
    summarize_feature_geometry,
    summarize_projector_spectrum,
    _state_report,
)


def test_feature_geometry_reports_temporal_and_centered_variance_on_valid_rows() -> None:
    features = torch.tensor(
        [[[1.0, 0.0], [3.0, 0.0], [5.0, 0.0]], [[9.0, 1.0], [9.0, 3.0], [9.0, 5.0]]]
    )
    mask = torch.tensor([[1, 1, 1], [1, 1, 0]], dtype=torch.bool)

    report = summarize_feature_geometry(features, mask)

    assert report["shape"] == [2, 3, 2]
    assert report["valid_rows"] == 5
    assert report["temporal_sample_count"] == 2
    assert report["within_sample_temporal_std_mean"] == pytest.approx(0.6582482905)
    assert report["centered_temporal_variance_mean"] == pytest.approx(1.0)
    assert report["centered_row_l2_mean"] == pytest.approx(1.2)


def test_pairwise_distance_correlation_is_one_for_identical_temporal_geometry() -> None:
    source = torch.tensor(
        [[[0.0, 0.0], [1.0, 0.0], [3.0, 0.0]], [[0.0, 0.0], [0.0, 2.0], [0.0, 5.0]]]
    )
    target = source * 7.0
    mask = torch.ones((2, 3), dtype=torch.bool)

    report = pairwise_distance_correlation(source, target, mask)

    assert report["sample_count"] == 2
    assert report["pair_count"] == 6
    assert report["pair_weighted_mean"] == pytest.approx(1.0)
    assert report["video_macro_mean"] == pytest.approx(1.0)


def test_projector_spectrum_reports_linear_layers_and_output_bias_ratio() -> None:
    projector = nn.Sequential(
        nn.Linear(3, 2, bias=True),
        nn.GELU(),
        nn.LayerNorm(2),
        nn.Linear(2, 2, bias=True),
    )
    with torch.no_grad():
        projector[0].weight.copy_(torch.tensor([[1.0, 0.0, 0.0], [0.0, 2.0, 0.0]]))
        projector[0].bias.copy_(torch.tensor([1.0, -1.0]))
        projector[3].weight.copy_(torch.eye(2))
        projector[3].bias.copy_(torch.tensor([0.5, -0.25]))

    report = summarize_projector_spectrum(projector)

    assert [layer["name"] for layer in report["linear_layers"]] == ["0", "3"]
    assert report["linear_layers"][0]["singular_values"] == pytest.approx([2.0, 1.0])
    assert report["linear_layers"][1]["effective_rank"] == pytest.approx(2.0)
    assert report["output_bias_l2"] == pytest.approx(0.5590169944)
    assert report["output_weight_rms"] == pytest.approx(0.7071067812)


def test_projector_spectrum_rejects_wrong_input_dimension_before_forward() -> None:
    projector = nn.Sequential(nn.Linear(3, 2), nn.Linear(2, 2))

    with pytest.raises(ValueError, match="input dimension"):
        summarize_projector_spectrum(projector, torch.zeros(4, 4))


def test_projector_spectrum_preserves_projector_mode() -> None:
    projector = nn.Sequential(nn.Linear(3, 2), nn.GELU(), nn.Linear(2, 2))
    projector.train()

    summarize_projector_spectrum(projector, torch.zeros(4, 3))

    assert projector.training is True
    projector.eval()
    summarize_projector_spectrum(projector, torch.zeros(4, 3))
    assert projector.training is False


def test_state_report_converts_flattened_numpy_features_for_projector_probe() -> None:
    projector = nn.Linear(3, 2)
    raw = torch.tensor(
        [
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [3.0, 0.0, 0.0]],
            [[0.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 5.0, 0.0]],
        ]
    )
    decision = torch.cat((raw[..., :1], raw[..., :1]), dim=-1)
    mask = torch.ones((2, 3), dtype=torch.bool)

    report = _state_report(
        name="synthetic",
        source={"kind": "test"},
        projector=projector,
        raw=raw,
        decision=decision,
        mask=mask,
        device=torch.device("cpu"),
    )

    assert report["available"] is True
    assert report["projector_spectrum"]["linear_layers"][0]["input_dim"] == 3


def test_pairwise_distance_correlation_excludes_degenerate_sample_from_weights() -> None:
    source = torch.tensor(
        [
            [[0.0, 0.0], [0.0, 0.0], [0.0, 0.0]],
            [[0.0, 0.0], [1.0, 0.0], [3.0, 0.0]],
        ]
    )
    target = torch.tensor(
            [
                [[4.0, 4.0], [4.0, 4.0], [4.0, 4.0]],
                [[0.0, 0.0], [0.0, 2.0], [0.0, 6.0]],
            ]
        )
    mask = torch.ones((2, 3), dtype=torch.bool)

    report = pairwise_distance_correlation(source, target, mask)

    assert report["sample_count"] == 1
    assert report["pair_count"] == 3
    assert report["pair_weighted_mean"] == pytest.approx(1.0)


def test_linear_probe_metrics_are_deterministic_and_receipted() -> None:
    train_features = np.asarray(
        [[-2.0, 0.0], [-1.0, 0.1], [1.0, 0.0], [2.0, -0.1]], dtype=np.float32
    )
    train_labels = np.asarray([0, 0, 1, 1], dtype=np.int64)
    eval_features = np.asarray([[-1.5, 0.0], [1.5, 0.0]], dtype=np.float32)
    eval_labels = np.asarray([0, 1], dtype=np.int64)

    first = fit_linear_probe_metrics(
        train_features, train_labels, eval_features, eval_labels, random_state=42
    )
    second = fit_linear_probe_metrics(
        train_features, train_labels, eval_features, eval_labels, random_state=42
    )

    assert first == second
    assert first["aggregation"] == "global_micro_over_official_task_segments"
    assert first["evaluation"]["ap"] > 0.99
    assert first["evaluation"]["auroc"] > 0.99


def test_teacher_cache_lock_receipt_preserves_lock_and_hash(tmp_path: Path) -> None:
    lock_path = tmp_path / "teacher_cache_hash.json"
    lock_path.write_text('{"sha256":"abc","files":3}\n', encoding="utf-8")

    receipt = _teacher_cache_lock_receipt(lock_path)

    assert receipt["status"] == "PASS"
    assert receipt["lock"] == {"sha256": "abc", "files": 3}
    assert len(receipt["source"]["sha256"]) == 64


def test_build_report_rejects_nonpositive_workers_before_io(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="workers must be at least one"):
        build_raw_teacher_report(
            config_path=tmp_path / "missing.yaml",
            best_checkpoint_path=tmp_path / "missing-best.pt",
            last_checkpoint_path=tmp_path / "missing-last.pt",
            test_predictions_path=tmp_path / "missing.npz",
            output_path=tmp_path / "output.json",
            device=torch.device("cpu"),
            workers=0,
            probe_seed=42,
        )
