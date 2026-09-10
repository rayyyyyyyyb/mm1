from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pytest
import torch
import yaml

from src.utils.d2a_early_dynamics import (
    D2A_CHECKPOINTS,
    batch_input_receipt,
    build_fixed_batch_plan,
    materialize_d2a_configs,
    recompute_d2a_gate,
    summarize_d2a_evaluation,
    validate_d2a_wrapper,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WRAPPER = (
    PROJECT_ROOT
    / "configs"
    / "diagnostics"
    / "recovery"
    / "ov_orthkd_d2a_paired_pretrained_early_dynamics_400.yaml"
)


def _predictions(logits: np.ndarray) -> dict[str, np.ndarray]:
    labels = np.asarray(
        [0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 1, 1, 0, 0, 0, 1, 1, 0, 0, 0],
        dtype=np.float64,
    )
    return {
        "ids": np.asarray(["a", "b"]),
        "queries": np.asarray(["q1", "q2"]),
        "split_types": np.asarray(["seen", "unseen"]),
        "sample_offsets": np.asarray([0, 10, 20], dtype=np.int64),
        "segment_indices": np.tile(np.arange(10, dtype=np.int64), 2),
        "labels": labels,
        "logits": logits.astype(np.float64),
        "probabilities": 1.0 / (1.0 + np.exp(-logits.astype(np.float64))),
    }


def _snapshot(concordance: float, *, visual_zero_drop: float, ap: float) -> dict:
    return {
        "modes": {
            "original": {
                "mixed_pair_weighted_concordance": concordance,
                "validation_ap": ap,
                "predicted_positive_rate": 0.5,
            }
        },
        "paths": {"decision_features": {"within_sample_temporal_std_mean": 0.004}},
        "mixed_temporal_shuffle": {"ap_drop": 0.011, "auroc_drop": 0.0},
        "causal_deltas": {
            "visual_zero_mixed_concordance_drop": visual_zero_drop,
        },
    }


def test_preregistered_wrapper_is_fail_closed_and_materializes_one_difference(
    tmp_path: Path,
) -> None:
    wrapper = yaml.safe_load(WRAPPER.read_text(encoding="utf-8"))
    validate_d2a_wrapper(wrapper)
    materialized = materialize_d2a_configs(
        WRAPPER, PROJECT_ROOT, tmp_path, tmp_path / "offline-asset"
    )
    assert materialized["scientific_changed_paths"] == ["student.visual_pretrained"]
    assert set(materialized["configs"]) == {"random", "pretrained"}
    assert "test_manifest" not in materialized["configs"]["random"]["data"]
    assert materialized["configs"]["random"]["evaluation"]["run_test"] is False

    tampered = copy.deepcopy(wrapper)
    tampered["control"]["attempted_batches"] = 401
    with pytest.raises(ValueError, match="attempted_batches"):
        validate_d2a_wrapper(tampered)


def test_fixed_batch_plan_is_deterministic_unique_and_exact_budget() -> None:
    first = build_fixed_batch_plan(2000, 4, 42)
    second = build_fixed_batch_plan(2000, 4, 42)
    assert first == second
    assert len(first) == 400
    flattened = [index for batch in first for index in batch]
    assert len(flattened) == len(set(flattened)) == 1600


def test_raw_evaluation_summary_and_gate_are_fixed() -> None:
    labels = _predictions(np.zeros(20))["labels"]
    aligned_logits = labels * 4.0 - 2.0
    predictions = {
        "original": _predictions(aligned_logits),
        "visual_zero": _predictions(np.zeros(20)),
        "audio_zero": _predictions(aligned_logits * 0.5),
    }
    summary = summarize_d2a_evaluation(
        predictions,
        {"decision_features": {"within_sample_temporal_std_mean": 0.004}},
        shuffle_repeats=5,
        shuffle_seed=42,
    )
    assert summary["protocol"]["task_segments"] == 10
    assert summary["modes"]["original"]["mixed_pair_weighted_concordance"] == 1.0
    assert summary["causal_deltas"]["visual_zero_mixed_concordance_drop"] == 0.5

    gate = yaml.safe_load(WRAPPER.read_text(encoding="utf-8"))["gate"]
    passed = recompute_d2a_gate(
        _snapshot(0.50, visual_zero_drop=0.0, ap=0.70),
        _snapshot(0.53, visual_zero_drop=0.02, ap=0.69),
        gate,
    )
    assert passed["pass"] is True
    assert passed["scientific_status"] == "D2A_PRETRAINED_EARLY_DYNAMICS_PASS"
    assert passed["authorization"]["automatic_extension"] is False
    failed = recompute_d2a_gate(
        _snapshot(0.50, visual_zero_drop=0.0, ap=0.70),
        _snapshot(0.51, visual_zero_drop=0.0, ap=0.60),
        gate,
    )
    assert failed["pass"] is False


def test_input_receipt_hashes_content_and_metadata() -> None:
    batch = {
        "id": ["a"],
        "query": ["q"],
        "frame": torch.zeros(1, 10, 3, 2, 2),
        "spectrogram": torch.ones(1, 10, 3, 2, 2),
        "segment_label": torch.zeros(1, 10),
        "sequence_mask": torch.ones(1, 10),
        "frame_valid": torch.ones(1, 10),
        "audio_valid": torch.ones(1, 10),
        "selected_segment_indices": [[*range(10)]],
    }
    receipt = batch_input_receipt(batch)
    assert len(receipt["composite_sha256"]) == 64
    changed = copy.deepcopy(batch)
    changed["frame"][0, 0, 0, 0, 0] = 1
    assert batch_input_receipt(changed)["composite_sha256"] != receipt["composite_sha256"]
    assert D2A_CHECKPOINTS == (0, 25, 50, 100, 200, 400)
