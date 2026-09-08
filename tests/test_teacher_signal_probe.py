from __future__ import annotations

import numpy as np

from src.utils.teacher_signal_probe import (
    build_common_space,
    build_interaction_design,
    derive_all_transitions,
    direct_logit_shift_sweep,
    fit_probe_and_score,
    score_signal_metrics,
)


def test_interaction_design_keeps_query_ids_separate_and_is_not_a_norm_score() -> None:
    visual = np.asarray([[[1.0], [0.0], [0.0], [0.0]]], dtype=np.float32)
    query = np.asarray([[[2.0], [2.0], [2.0], [2.0]]], dtype=np.float32)
    common_visual, common_query, receipt = build_common_space(
        visual, query, output_dim=1, seed=7
    )
    position = np.asarray([[[0.0], [1.0], [2.0], [3.0]]], dtype=np.float32)
    design = build_interaction_design(
        common_visual, common_query, position, mode="interaction"
    )

    assert receipt["query_id_source"] == "separate_categorical_field"
    assert design.shape == (1, 4, 4)
    # [v, q, v*q, p] has a distinct interaction block; concatenation followed
    # by an L2 norm would not expose this block.
    assert design[0, 0, 2] == 2.0
    assert design[0, 1, 2] == 0.0
    assert not np.allclose(design[..., 2], np.linalg.norm(design, axis=-1))


def test_transition_derivation_retains_all_discontinuous_windows_and_ties() -> None:
    labels = np.asarray([[0, 1, 1, 0, 0, 1, 0]], dtype=np.int64)
    mask = np.ones_like(labels, dtype=bool)
    transitions = derive_all_transitions(labels, mask)

    assert transitions["transition_indices"].tolist() == [[1, 3, 5, 6]]
    assert transitions["onset_indices"].tolist() == [[1, 5]]
    assert transitions["offset_indices"].tolist() == [[3, 6]]
    assert transitions["positive_window_count"].tolist() == [2]
    assert transitions["single_window_continuous"] is False


def test_train_fit_probe_reports_tie_aware_concordance_and_query_macro() -> None:
    train_x = np.asarray([[0.0], [1.0], [0.0], [1.0]], dtype=np.float32)
    train_y = np.asarray([0, 1, 0, 1], dtype=np.int64)
    eval_x = np.zeros((2, 4, 1), dtype=np.float32)
    eval_y = np.asarray([[0, 1, 1, 0], [0, 0, 1, 1]], dtype=np.int64)
    mask = np.ones_like(eval_y, dtype=bool)
    offsets = np.asarray([0, 4, 8], dtype=np.int64)
    result = fit_probe_and_score(
        train_x,
        train_y,
        eval_x,
        eval_y,
        mask,
        sample_ids=np.asarray(["a", "b"]),
        query_ids=np.asarray(["q1", "q2"]),
        offsets=offsets,
        seed=42,
        shuffle_repeats=3,
    )

    assert result["probe"]["fit_segments"] == 4
    assert result["metrics"]["mixed"]["pair_weighted_concordance"] == 0.5
    assert result["metrics"]["per_query_macro_ap"] is not None
    assert result["metrics"]["shuffle"]["repeats"] == 3


def test_direct_logit_shift_sweep_marks_nonzero_best_alignment() -> None:
    labels = np.asarray([[0, 1, 0, 0]], dtype=np.int64)
    logits = np.asarray([[1.0, 0.0, 4.0, 0.0]], dtype=np.float32)
    mask = np.ones_like(labels, dtype=bool)

    result = direct_logit_shift_sweep(logits, labels, mask, shifts=(-1, 0, 1))

    assert result["best_shift"] == 1
    assert result["status"] == "TEMPORAL_INDEX_ALIGNMENT_FAILURE"


def test_direct_score_metrics_include_shuffle_and_all_transition_types() -> None:
    labels = np.asarray([[0, 1, 1, 0, 1, 0, 0, 0, 0, 0]], dtype=np.int64)
    scores = labels.astype(np.float64)
    mask = np.ones_like(labels, dtype=bool)

    result = score_signal_metrics(
        scores,
        labels,
        mask,
        sample_ids=np.asarray(["sample"]),
        query_ids=np.asarray(["query"]),
        offsets=np.asarray([0, 10]),
        shuffle_repeats=5,
        seed=42,
    )

    assert result["mixed"]["pair_weighted_concordance"] == 1.0
    assert result["shuffle"]["repeats"] == 5
    assert result["transitions"]["transition_count"] == 4
    assert result["transitions"]["onset_auroc"] is not None
    assert result["transitions"]["offset_auroc"] is not None
