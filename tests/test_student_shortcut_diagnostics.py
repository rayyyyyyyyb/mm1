from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
from sklearn.metrics import average_precision_score

from scripts.diagnose_student_shortcuts import (
    apply_empirical_priors,
    build_empirical_priors,
    build_shortcut_report,
    mean_center_logits,
    shuffle_logits_within_samples,
    temporal_shuffle_diagnostic,
)


def _records() -> list[dict[str, object]]:
    return [
        {"id": "train-1", "query": "known", "segment_labels": [1, 0]},
        {"id": "train-2", "query": "known", "segment_labels": [1, 1]},
        {"id": "train-3", "query": "other", "segment_labels": [0, 0]},
    ]


def _predictions() -> dict[str, np.ndarray]:
    logits = np.asarray([1.0, 3.0, 4.0, 4.0], dtype=np.float64)
    return {
        "ids": np.asarray(["eval-known", "eval-unseen"], dtype=str),
        "queries": np.asarray(["known", "unseen"], dtype=str),
        "split_types": np.asarray(["seen", "unseen"], dtype=str),
        "sample_offsets": np.asarray([0, 2, 4], dtype=np.int64),
        "segment_indices": np.asarray([0, 1, 0, 1], dtype=np.int64),
        "labels": np.asarray([1, 0, 0, 1], dtype=np.float64),
        "logits": logits,
        "probabilities": 1.0 / (1.0 + np.exp(-logits)),
    }


def test_empirical_priors_use_literal_rates_and_receipt_unseen_fallbacks() -> None:
    priors = build_empirical_priors(_records(), expected_segments=2)

    assert priors["global"] == pytest.approx(0.5)
    assert priors["by_query"] == {"known": pytest.approx(0.75), "other": 0.0}
    assert priors["by_position"] == pytest.approx([2.0 / 3.0, 1.0 / 3.0])
    assert priors["by_query_position"]["known"] == pytest.approx([1.0, 0.5])

    scored = apply_empirical_priors(_predictions(), priors, expected_segments=2)

    assert scored["query_only_probabilities"] == pytest.approx([0.75, 0.75, 0.5, 0.5])
    assert scored["query_position_probabilities"] == pytest.approx(
        [1.0, 0.5, 2.0 / 3.0, 1.0 / 3.0]
    )
    assert scored["known_query_samples"] == 1
    assert scored["fallback_query_samples"] == 1
    assert scored["query_only_fallback"] == "global_training_positive_rate"
    assert scored["query_position_fallback"] == "global_training_position_rate"


@pytest.mark.parametrize(
    "record,match",
    [
        ({"id": "missing-query", "segment_labels": [1, 0]}, "query"),
        ({"id": "short", "query": "x", "segment_labels": [1]}, "exactly 2"),
        ({"id": "nonbinary", "query": "x", "segment_labels": [1, 2]}, "binary"),
        ({"id": "empty", "query": "", "segment_labels": [1, 0]}, "query"),
    ],
)
def test_empirical_prior_manifest_validation_fails_closed(
    record: dict[str, object], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        build_empirical_priors([record], expected_segments=2)


def test_mean_centering_is_strictly_per_sample() -> None:
    centered = mean_center_logits(
        np.asarray([1.0, 3.0, 4.0, 4.0]),
        np.asarray([0, 2, 4]),
    )

    assert centered == pytest.approx([-1.0, 1.0, 0.0, 0.0])
    assert centered[:2].mean() == pytest.approx(0.0)
    assert centered[2:].mean() == pytest.approx(0.0)


def test_temporal_shuffle_never_crosses_sample_boundaries_and_is_reproducible() -> None:
    logits = np.asarray([1.0, 2.0, 100.0, 200.0], dtype=np.float64)
    offsets = np.asarray([0, 2, 4], dtype=np.int64)
    first = shuffle_logits_within_samples(logits, offsets, np.random.default_rng(7))
    second = shuffle_logits_within_samples(logits, offsets, np.random.default_rng(7))

    assert np.array_equal(first, second)
    assert sorted(first[:2]) == [1.0, 2.0]
    assert sorted(first[2:]) == [100.0, 200.0]

    diagnostic_a = temporal_shuffle_diagnostic(_predictions(), repeats=25, seed=42)
    diagnostic_b = temporal_shuffle_diagnostic(_predictions(), repeats=25, seed=42)
    assert diagnostic_a == diagnostic_b
    assert diagnostic_a["repeats"] == 25
    assert diagnostic_a["seed"] == 42
    assert diagnostic_a["ap_distribution"]["count"] == 25


def _write_manifest(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )


def _write_predictions(path: Path, predictions: dict[str, np.ndarray]) -> None:
    np.savez_compressed(path, **predictions)


def test_shortcut_report_receipts_sources_and_labels_metrics_as_diagnostic(
    tmp_path: Path,
) -> None:
    train = tmp_path / "train.jsonl"
    validation = tmp_path / "validation_predictions.npz"
    test = tmp_path / "test_predictions.npz"
    _write_manifest(train, _records())
    _write_predictions(validation, _predictions())
    _write_predictions(test, _predictions())

    report = build_shortcut_report(
        train_manifest=train,
        validation_predictions=validation,
        test_predictions=test,
        expected_segments=2,
        shuffle_repeats=10,
        seed=42,
    )

    assert report["status"] == "PASS"
    assert report["metric_claim"] == "diagnostic_global_segment_micro_ap"
    assert report["protocol"]["task_segments"] == 2
    assert report["protocol"]["temporal_conversion"] == "forbidden"
    assert report["protocol"]["prior_smoothing"] == "none"
    assert set(report["sources"]) == {"train_manifest", "validation", "test"}
    assert all(len(receipt["sha256"]) == 64 for receipt in report["sources"].values())

    split = report["test"]
    expected_original = average_precision_score(
        _predictions()["labels"], _predictions()["probabilities"]
    )
    assert split["student_original_ap"] == pytest.approx(expected_original)
    assert split["query_only_prior"]["ap"] == pytest.approx(0.5)
    assert split["query_position_prior"]["fallback_query_samples"] == 1
    assert split["mean_centered_student"]["within_sample_logit_mean_max_abs"] < 1e-12
    assert split["temporal_shuffle"]["repeats"] == 10


def test_cli_help_runs_when_current_directory_is_not_the_repository(
    tmp_path: Path,
) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "diagnose_student_shortcuts.py"

    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--train-manifest" in completed.stdout
