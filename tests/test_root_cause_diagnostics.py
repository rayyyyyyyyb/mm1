from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import torch
from torch import nn
from sklearn.metrics import average_precision_score

from scripts.diagnose_formal_predictions import audit_prediction_payload
from scripts.diagnose_teacher_cache import audit_direct_logits, fit_linear_probe
from src.evaluation.ovavel_metrics import compute_thresholded_ovavel_metrics
from src.utils.training_diagnostics import (
    collect_training_diagnostic,
    diagnostic_parameter_snapshots,
    module_gradient_norm,
    parameter_drift,
    snapshot_parameters,
    summarize_gate_weights,
    summarize_temporal_logits,
    summarize_tensor_geometry,
)


def _prediction_payload() -> dict[str, np.ndarray]:
    probabilities = np.asarray([0.90, 0.80, 0.70, 0.60, 0.55, 0.10], dtype=np.float64)
    return {
        "ids": np.asarray(["a1", "a2", "b1"], dtype=str),
        "queries": np.asarray(["query-a", "query-a", "query-b"], dtype=str),
        "split_types": np.asarray(["seen", "seen", "unseen"], dtype=str),
        "sample_offsets": np.asarray([0, 2, 4, 6], dtype=np.int64),
        "segment_indices": np.asarray([0, 1, 0, 1, 0, 1], dtype=np.int64),
        "labels": np.asarray([1, 0, 0, 1, 1, 0], dtype=np.float64),
        "logits": np.log(probabilities / (1.0 - probabilities)),
        "probabilities": probabilities,
    }


def test_thresholded_ovavel_metrics_keep_segment_macro_distinct_from_binary_micro() -> None:
    metrics = compute_thresholded_ovavel_metrics(
        labels=[1, 0, 0, 1],
        probabilities=[0.8, 0.7, 0.6, 0.5],
        sample_offsets=[0, 2, 4],
        threshold=0.65,
    )

    assert metrics["threshold"] == pytest.approx(0.65)
    assert metrics["binary_micro_f1_at_threshold"] == pytest.approx(0.5)
    assert metrics["ovavel_segment_f1_at_threshold"] == pytest.approx(1.0 / 3.0)
    assert metrics["query_fg_f1_macro_at_threshold"] == pytest.approx(1.0 / 3.0)


def test_prediction_audit_labels_micro_sample_macro_and_query_macro_semantics() -> None:
    predictions = _prediction_payload()

    audit = audit_prediction_payload(predictions, threshold=0.65)

    expected_micro = average_precision_score(
        predictions["labels"], predictions["probabilities"]
    )
    assert audit["aggregation"]["global_segment_micro"]["ap"] == pytest.approx(
        expected_micro
    )
    assert audit["aggregation"]["per_sample_macro"]["sample_count"] == 3
    assert audit["aggregation"]["per_query_macro"]["query_count"] == 2
    assert set(audit["groups"]) == {"total", "seen", "unseen"}
    assert audit["thresholded_metrics"]["ovavel_segment_f1_at_threshold"] == pytest.approx(
        2.0 / 9.0
    )
    assert audit["logit_distribution"]["positive_label"]["count"] == 3
    assert audit["logit_distribution"]["negative_label"]["count"] == 3


def _write_manifest(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )


def test_teacher_direct_logit_audit_is_shape_strict_and_reproduces_metrics(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.npy"
    second = tmp_path / "second.npy"
    np.save(first, np.asarray([0.9, 0.1], dtype=np.float32))
    np.save(second, np.asarray([0.8, 0.2], dtype=np.float32))
    manifest = tmp_path / "split.jsonl"
    _write_manifest(
        manifest,
        [
            {
                "id": "first",
                "segment_labels": [1, 0],
                "strong_teacher_logits_path": str(first),
            },
            {
                "id": "second",
                "segment_labels": [0, 1],
                "strong_teacher_logits_path": str(second),
            },
        ],
    )

    audit = audit_direct_logits(manifest, expected_segments=2, workers=1)

    assert audit["samples"] == 2
    assert audit["segments"] == 4
    assert audit["array_shapes"] == {"[2]": 2}
    assert audit["ap"] == pytest.approx(
        average_precision_score([1, 0, 0, 1], [0.9, 0.1, 0.8, 0.2])
    )
    assert audit["auroc"] == pytest.approx(0.75)


@pytest.mark.parametrize("defect", ["missing", "shape", "nonfinite"])
def test_teacher_direct_logit_audit_fails_closed_on_invalid_cache(
    tmp_path: Path,
    defect: str,
) -> None:
    array_path = tmp_path / "teacher.npy"
    if defect == "shape":
        np.save(array_path, np.asarray([0.1], dtype=np.float32))
    elif defect == "nonfinite":
        np.save(array_path, np.asarray([0.1, np.nan], dtype=np.float32))
    manifest = tmp_path / "split.jsonl"
    _write_manifest(
        manifest,
        [
            {
                "id": "bad",
                "segment_labels": [1, 0],
                "strong_teacher_logits_path": str(array_path),
            }
        ],
    )

    error = FileNotFoundError if defect == "missing" else ValueError
    with pytest.raises(error):
        audit_direct_logits(manifest, expected_segments=2, workers=1)


def test_reconstruction_linear_probe_is_deterministic_and_receipted() -> None:
    negative = np.linspace(-3.0, -0.5, 40, dtype=np.float32)
    positive = np.linspace(0.5, 3.0, 40, dtype=np.float32)
    train_features = np.concatenate([negative, positive])[:, None]
    train_features = np.concatenate([train_features, -train_features], axis=1)
    train_labels = np.concatenate(
        [np.zeros(negative.size, dtype=np.int64), np.ones(positive.size, dtype=np.int64)]
    )
    eval_features = np.asarray(
        [[-2.0, 2.0], [-1.0, 1.0], [1.0, -1.0], [2.0, -2.0]],
        dtype=np.float32,
    )
    eval_labels = np.asarray([0, 0, 1, 1], dtype=np.int64)

    first = fit_linear_probe(
        train_features,
        train_labels,
        {"test": (eval_features, eval_labels)},
        random_state=42,
    )
    second = fit_linear_probe(
        train_features,
        train_labels,
        {"test": (eval_features, eval_labels)},
        random_state=42,
    )

    assert first == second
    assert first["claim"] == "transparent_reconstruction_probe_not_archival_exact"
    assert first["protocol"]["feature_standardization"] == "train_split_standard_scaler"
    assert first["protocol"]["class_weight"] is None
    assert first["evaluation"]["test"]["ap"] == pytest.approx(1.0)
    assert first["evaluation"]["test"]["auroc"] == pytest.approx(1.0)


def test_training_diagnostics_preserve_temporal_and_label_conditioned_semantics() -> None:
    logits = torch.tensor([[[-2.0], [0.0], [2.0]], [[1.0], [1.0], [99.0]]]).squeeze(-1)
    labels = torch.tensor([[0, 1, 1], [1, 0, 0]])
    mask = torch.tensor([[1, 1, 1], [1, 1, 0]])

    summary = summarize_temporal_logits(logits, labels, mask)

    assert summary["valid_segments"] == 5
    assert summary["positive"]["mean"] == pytest.approx(1.0)
    assert summary["negative"]["mean"] == pytest.approx(-0.5)
    assert summary["within_sample_logit_std"]["count"] == 2
    assert summary["within_sample_logit_std"]["mean"] == pytest.approx(
        (np.std([-2.0, 0.0, 2.0]) + 0.0) / 2.0
    )
    assert summary["probabilities"]["quantiles"]["0.5"] == pytest.approx(
        torch.sigmoid(torch.tensor(1.0)).item()
    )


def test_training_diagnostics_report_geometry_gates_gradients_and_parameter_drift() -> None:
    features = torch.tensor(
        [[[1.0, 0.0], [0.0, 1.0]], [[1.0, 1.0], [9.0, 9.0]]]
    )
    mask = torch.tensor([[1, 1], [1, 0]])
    geometry = summarize_tensor_geometry(features, mask)
    gates = summarize_gate_weights(
        torch.tensor(
            [[[0.9, 0.1], [0.5, 0.5]], [[0.1, 0.9], [1.0, 0.0]]]
        ),
        mask,
    )

    assert geometry["valid_rows"] == 3
    assert 1.0 <= geometry["effective_rank"] <= 2.0
    assert gates["valid_rows"] == 3
    assert gates["visual"]["mean"] == pytest.approx(0.5)
    assert gates["audio"]["mean"] == pytest.approx(0.5)
    assert gates["saturation_rate_at_0_95"] == pytest.approx(0.0)

    module = nn.Linear(2, 1, bias=True)
    initial = snapshot_parameters(module)
    module(torch.ones(3, 2)).sum().backward()
    assert module_gradient_norm(module) > 0.0
    with torch.no_grad():
        module.weight.add_(1.0)
    drift = parameter_drift(module, initial)
    assert drift["absolute_l2"] == pytest.approx(np.sqrt(2.0))
    assert drift["relative_l2"] > 0.0


def test_complete_training_diagnostic_record_is_json_serializable_and_observation_only() -> None:
    class DummyStudent(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.segment_head = nn.Linear(2, 1)

    class DummyLoss(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.strong_teacher_proj = nn.Linear(3, 2)
            self.weak_teacher_proj = nn.Linear(4, 2)
            self.text_teacher_proj = nn.Linear(5, 2)

    student = DummyStudent()
    loss_module = DummyLoss()
    snapshots = diagnostic_parameter_snapshots(student, loss_module)
    shared = torch.randn(2, 3, 2, requires_grad=True)
    logits = student.segment_head(shared).squeeze(-1)
    logits.sum().backward()
    outputs = {
        "segment_logits": logits,
        "shared_features": shared,
        "decision_features": shared,
        "audio_aux_features": shared,
        "query_features": shared,
        "gate_weights": torch.full((2, 3, 2), 0.5),
    }
    batch = {
        "sequence_mask": torch.tensor([[1, 1, 1], [1, 1, 0]]),
        "segment_label": torch.tensor([[0, 1, 1], [1, 0, 0]]),
        "strong_teacher_features": torch.randn(2, 3, 3),
        "strong_teacher_feature_mask": torch.ones(2, 3),
        "weak_teacher_features": torch.randn(2, 3, 4),
        "weak_teacher_feature_mask": torch.ones(2, 3),
        "audio_valid": torch.ones(2, 3),
        "text_embedding": torch.randn(2, 5),
        "text_valid": torch.ones(2),
    }

    student_before = {name: value.detach().clone() for name, value in student.state_dict().items()}
    loss_before = {name: value.detach().clone() for name, value in loss_module.state_dict().items()}
    record = collect_training_diagnostic(
        student=student,
        loss_module=loss_module,
        outputs=outputs,
        batch=batch,
        initial_parameters=snapshots,
        epoch=0,
        batch_index=0,
        global_step=0,
    )

    json.dumps(record)
    assert record["temporal_logits"]["valid_segments"] == 5
    assert record["teacher_target_geometry"]["strong"]["valid_rows"] == 5
    assert record["gradient_l2_before_clip"]["student_segment_head"] > 0.0
    assert all(
        torch.equal(value, student_before[name]) for name, value in student.state_dict().items()
    )
    assert all(
        torch.equal(value, loss_before[name]) for name, value in loss_module.state_dict().items()
    )
