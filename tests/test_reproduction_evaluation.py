from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import torch

import scripts.evaluate_pr_f1 as evaluation_module
from scripts.evaluate_pr_f1 import (
    best_threshold_from_pr,
    evaluate_prediction_sets,
    validate_formal_checkpoint,
)
from scripts.train_ov_orthkd import (
    collect_predictions,
    compute_grouped_metrics,
    save_evaluation_artifacts,
    save_predictions_npz,
)


def test_formal_checkpoint_requires_matching_invariant_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = {"reproduction": {"claim_level": "archival_exact"}}
    monkeypatch.setattr(evaluation_module, "validate_canonical_readiness", lambda value: None)
    monkeypatch.setattr(
        evaluation_module,
        "build_runtime_reproduction_fingerprint",
        lambda value: {"sha256": "a" * 64},
    )

    with pytest.raises(RuntimeError, match="fingerprint mismatch"):
        validate_formal_checkpoint(
            {"config": config, "reproduction_fingerprint": {"sha256": "b" * 64}},
            "model.pt",
        )

    returned = validate_formal_checkpoint(
        {"config": config, "reproduction_fingerprint": {"sha256": "a" * 64}},
        "model.pt",
    )
    assert returned is config


def test_formal_checkpoint_rejects_partial_batch_evaluation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = {"reproduction": {"claim_level": "archival_exact"}}
    monkeypatch.setattr(evaluation_module, "validate_canonical_readiness", lambda value: None)
    monkeypatch.setattr(
        evaluation_module,
        "build_runtime_reproduction_fingerprint",
        lambda value: {"sha256": "a" * 64},
    )

    with pytest.raises(RuntimeError, match="partial formal evaluation"):
        validate_formal_checkpoint(
            {"config": config, "reproduction_fingerprint": {"sha256": "a" * 64}},
            "model.pt",
            max_batches=1,
        )


class EchoLogitStudent(torch.nn.Module):
    def forward(
        self,
        frame: torch.Tensor,
        spectrogram: torch.Tensor,
        text_embedding: torch.Tensor,
        sequence_mask: torch.Tensor,
        frame_valid: torch.Tensor,
        audio_valid: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        del spectrogram, text_embedding, sequence_mask, frame_valid, audio_valid
        return {"segment_logits": frame[:, :, 0, 0, 0]}


def prediction_batch() -> dict[str, Any]:
    logits = torch.tensor([[1.5, -0.5, 9.0], [0.2, 0.7, -1.0]])
    frame = torch.zeros(2, 3, 3, 1, 1)
    frame[:, :, 0, 0, 0] = logits
    return {
        "id": ["sample_seen", "sample_unseen"],
        "query": ["dog barking", "glass breaking"],
        "domain": ["unit", "unit"],
        "meta": [{"split_type": "seen"}, {"split_type": "unseen"}],
        "frame": frame,
        "spectrogram": torch.zeros_like(frame),
        "text_embedding": torch.zeros(2, 5),
        "sequence_mask": torch.tensor([[1.0, 1.0, 0.0], [1.0, 1.0, 1.0]]),
        "frame_valid": torch.ones(2, 3),
        "audio_valid": torch.ones(2, 3),
        "segment_label": torch.tensor([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]),
    }


def test_prediction_collection_preserves_sample_and_segment_identity(tmp_path: Path) -> None:
    predictions = collect_predictions(
        EchoLogitStudent(),
        [prediction_batch()],
        device=torch.device("cpu"),
    )

    assert predictions["ids"].tolist() == ["sample_seen", "sample_unseen"]
    assert predictions["queries"].tolist() == ["dog barking", "glass breaking"]
    assert predictions["split_types"].tolist() == ["seen", "unseen"]
    assert predictions["sample_offsets"].tolist() == [0, 2, 5]
    assert predictions["segment_indices"].tolist() == [0, 1, 0, 1, 2]
    assert predictions["labels"].tolist() == [1.0, 0.0, 0.0, 1.0, 0.0]
    assert predictions["ids"].dtype.kind == "U"
    assert predictions["queries"].dtype.kind == "U"
    assert predictions["split_types"].dtype.kind == "U"

    output_path = tmp_path / "predictions.npz"
    save_predictions_npz(output_path, predictions)
    with np.load(output_path, allow_pickle=False) as saved:
        assert set(saved.files) == {
            "ids",
            "queries",
            "split_types",
            "sample_offsets",
            "segment_indices",
            "labels",
            "logits",
            "probabilities",
        }
        assert saved["sample_offsets"].tolist() == [0, 2, 5]


def make_predictions(
    probabilities: list[float],
    labels: list[float],
) -> dict[str, np.ndarray]:
    probs = np.asarray(probabilities, dtype=np.float64)
    logits = np.log(probs / (1.0 - probs))
    return {
        "ids": np.asarray(["sample_seen", "sample_unseen"], dtype=str),
        "queries": np.asarray(["dog barking", "glass breaking"], dtype=str),
        "split_types": np.asarray(["seen", "unseen"], dtype=str),
        "sample_offsets": np.asarray([0, 2, 4], dtype=np.int64),
        "segment_indices": np.asarray([0, 1, 0, 1], dtype=np.int64),
        "labels": np.asarray(labels, dtype=np.float64),
        "logits": logits,
        "probabilities": probs,
    }


def test_grouped_metrics_report_total_seen_unseen_and_one_class_auroc() -> None:
    predictions = make_predictions(
        probabilities=[0.9, 0.8, 0.7, 0.1],
        labels=[1.0, 1.0, 0.0, 0.0],
    )

    metrics = compute_grouped_metrics(predictions, threshold=0.5)

    assert set(metrics) == {"total", "seen", "unseen"}
    assert metrics["total"]["sample_count"] == 2
    assert metrics["total"]["segment_count"] == 4
    assert metrics["seen"]["sample_count"] == 1
    assert metrics["seen"]["segment_count"] == 2
    assert metrics["seen"]["auroc"] is None
    assert metrics["seen"]["auroc_available"] is False
    assert metrics["unseen"]["auroc"] is None
    assert metrics["unseen"]["auroc_available"] is False
    assert metrics["total"]["binary_micro_f1_at_0_5"] == pytest.approx(0.8)
    assert metrics["total"]["query_fg_f1_macro_at_0_5"] == pytest.approx(0.5)
    assert "ovavel_segment_f1_at_0_5" in metrics["total"]
    assert "ovavel_event_f1_at_0_5" in metrics["total"]
    assert "binary_micro_f1_at_threshold" in metrics["total"]
    assert "f1" not in metrics["total"]


def test_test_metrics_use_validation_threshold_without_recalibration() -> None:
    validation = make_predictions(
        probabilities=[0.9, 0.6, 0.55, 0.1],
        labels=[1.0, 1.0, 0.0, 0.0],
    )
    test = make_predictions(
        probabilities=[0.8, 0.3, 0.25, 0.1],
        labels=[1.0, 0.0, 1.0, 0.0],
    )
    independent_test_best = best_threshold_from_pr(
        test["labels"],
        test["probabilities"],
    )["best_threshold"]

    report = evaluate_prediction_sets(validation, test)

    validation_threshold = report["validation_calibration"]["best_threshold"]
    assert independent_test_best != pytest.approx(validation_threshold)
    assert report["validation"]["threshold"] == pytest.approx(validation_threshold)
    assert report["test"]["threshold"] == pytest.approx(validation_threshold)
    assert "test_calibration" not in report
    assert report["validation_calibration"]["precision"].ndim == 1
    assert report["validation_calibration"]["recall"].ndim == 1
    assert report["validation_calibration"]["thresholds"].ndim == 1
    assert "best_binary_f1" in report["validation_calibration"]
    assert "best_f1" not in report["validation_calibration"]
    assert "binary_micro_f1_at_threshold" in report["test"]["metrics"]["total"]


def test_eval_only_artifact_helper_saves_structured_predictions_and_frozen_metrics(tmp_path: Path) -> None:
    validation = make_predictions(
        probabilities=[0.9, 0.6, 0.55, 0.1],
        labels=[1.0, 1.0, 0.0, 0.0],
    )
    test = make_predictions(
        probabilities=[0.8, 0.3, 0.25, 0.1],
        labels=[1.0, 0.0, 1.0, 0.0],
    )

    report = save_evaluation_artifacts(tmp_path, validation, test)

    assert (tmp_path / "validation_predictions.npz").is_file()
    assert (tmp_path / "test_predictions.npz").is_file()
    assert (tmp_path / "validation_pr_curve.npz").is_file()
    assert report["test"]["threshold"] == pytest.approx(
        report["validation_calibration"]["best_threshold"]
    )
