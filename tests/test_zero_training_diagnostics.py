from __future__ import annotations

from copy import deepcopy

import numpy as np
import pytest
import torch

from src.utils.zero_training_diagnostics import (
    build_audio_donor_maps,
    mixed_pairwise_concordance,
    summarize_label_strata,
    temporally_shuffle_audio,
    validate_t10_predictions,
)


def _predictions(
    *,
    mixed_scores: list[float] | None = None,
    task_segments: int = 10,
) -> dict[str, np.ndarray]:
    if mixed_scores is None:
        mixed_scores = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.0]
    labels = np.asarray(
        [0] * task_segments
        + [1, 1, 1, 1] + [0] * (task_segments - 4)
        + [1] * task_segments,
        dtype=np.int64,
    )
    scores = np.asarray(
        [0.05] * task_segments
        + mixed_scores[:task_segments]
        + [0.95] * task_segments,
        dtype=np.float64,
    )
    logits = np.log(scores / (1.0 - scores + 1e-12) + 1e-12)
    return {
        "ids": np.asarray(["all-negative", "mixed", "all-positive"]),
        "queries": np.asarray(["q0", "q1", "q2"]),
        "split_types": np.asarray(["seen", "unseen", "seen"]),
        "sample_offsets": np.asarray(
            [0, task_segments, task_segments * 2, task_segments * 3],
            dtype=np.int64,
        ),
        "segment_indices": np.tile(
            np.arange(task_segments, dtype=np.int64), 3
        ),
        "labels": labels,
        "logits": logits,
        "probabilities": scores,
    }


def _modes() -> dict[str, dict[str, np.ndarray]]:
    original = _predictions()
    visual_zero = deepcopy(original)
    visual_zero["probabilities"] = original["probabilities"].copy()
    visual_zero["logits"] = original["logits"].copy()
    audio_zero = deepcopy(original)
    audio_zero["probabilities"] = original["probabilities"].copy()
    audio_zero["logits"] = original["logits"].copy()
    both_zero = deepcopy(original)
    both_zero["probabilities"] = original["probabilities"].copy()
    both_zero["logits"] = original["logits"].copy()
    return {
        "original": original,
        "visual_zero": visual_zero,
        "audio_zero": audio_zero,
        "both_zero": both_zero,
    }


def test_label_strata_keep_single_class_metrics_explicitly_undefined() -> None:
    """Catch fabricated AUROC values for all-negative/all-positive strata."""
    report = summarize_label_strata(
        _modes(), shuffle_repeats=25, seed=42, threshold=0.5
    )

    assert report["task_segments"] == 10
    assert report["sample_count"] == 3
    assert report["positive_count_histogram"] == {
        str(index): (1 if index in {0, 4, 10} else 0)
        for index in range(11)
    }
    assert report["strata"]["k0"]["sample_count"] == 1
    assert report["strata"]["mixed"]["sample_count"] == 1
    assert report["strata"]["k10"]["sample_count"] == 1

    k0 = report["strata"]["k0"]["modes"]["original"]
    k10 = report["strata"]["k10"]["modes"]["original"]
    mixed = report["strata"]["mixed"]["modes"]["original"]
    assert k0["ap"] == 0.0
    assert k10["ap"] == 1.0
    assert k0["auroc"] is None
    assert k10["auroc"] is None
    assert k0["auroc_reason"] == "undefined_single_class_labels"
    assert k10["auroc_reason"] == "undefined_single_class_labels"
    assert mixed["ap"] == pytest.approx(1.0)
    assert mixed["auroc"] == pytest.approx(1.0)
    assert mixed["predicted_positive_rate"] == pytest.approx(0.5)


def test_mixed_shuffle_and_pairwise_use_only_boundary_bearing_samples() -> None:
    """Catch dilution by constant-label videos and the old pair-count denominator bug."""
    report = summarize_label_strata(
        _modes(), shuffle_repeats=25, seed=7, threshold=0.5
    )

    shuffle = report["mixed_only_shuffle"]["original"]
    assert shuffle["sample_count"] == 1
    assert shuffle["segment_count"] == 10
    assert shuffle["repeats"] == 25
    assert shuffle["ap"]["baseline"] == pytest.approx(1.0)
    assert shuffle["auroc"]["baseline"] == pytest.approx(1.0)
    assert shuffle["ap"]["mean_drop"] > 0.0
    assert shuffle["auroc"]["mean_drop"] > 0.0

    concordance = report["mixed_pairwise_concordance"]["original"]
    assert concordance == {
        "videos": 1,
        "pairs": 24,
        "pair_weighted": pytest.approx(1.0),
        "video_macro_mean": pytest.approx(1.0),
    }

    direct = mixed_pairwise_concordance(
        _predictions()["labels"],
        _predictions()["probabilities"],
        _predictions()["sample_offsets"],
    )
    assert direct["pairs"] == 24
    assert direct["pair_weighted"] == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda payload: _predictions(task_segments=16),
            "exactly 10",
        ),
        (
            lambda payload: {**payload, "sample_offsets": np.asarray([0, 10, 19, 30])},
            "exactly 10",
        ),
        (
            lambda payload: {
                **payload,
                "labels": np.asarray(payload["labels"]).copy(),
            },
            "binary",
        ),
    ],
)
def test_t10_prediction_validation_fails_closed(mutator, message: str) -> None:
    """Catch temporal conversion, malformed offsets, and non-binary labels."""
    base = _predictions()
    candidate = mutator(base)
    if message == "binary":
        candidate["labels"][3] = 2

    with pytest.raises(ValueError, match=message):
        validate_t10_predictions(candidate)


def test_strata_reject_cross_mode_metadata_changes() -> None:
    """Catch intervention outputs that no longer align to the same samples/labels."""
    modes = _modes()
    modes["audio_zero"]["ids"] = np.asarray(
        ["all-negative", "wrong-id", "all-positive"]
    )

    with pytest.raises(ValueError, match="audio_zero.*ids"):
        summarize_label_strata(modes, shuffle_repeats=5, seed=1, threshold=0.5)


def test_t10_predictions_reject_probabilities_that_do_not_match_logits() -> None:
    """Catch an NPZ whose reported probabilities are detached from its logits."""
    payload = _predictions()
    payload["probabilities"] = payload["probabilities"].copy()
    payload["probabilities"][0] = 0.75

    with pytest.raises(ValueError, match="sigmoid.*logits"):
        validate_t10_predictions(payload)


def test_audio_donor_maps_are_bijective_and_obey_query_contracts() -> None:
    """Catch self donors, same-query violations, and non-bijective donor reuse."""
    ids = ["a1", "a2", "b1", "b2"]
    queries = ["a", "a", "b", "b"]

    maps = build_audio_donor_maps(ids, queries)

    for mode, donors in maps.items():
        assert sorted(donors.tolist()) == [0, 1, 2, 3], mode
        assert all(int(donor) != index for index, donor in enumerate(donors)), mode
    for index, donor in enumerate(maps["same_query"]):
        assert queries[index] == queries[int(donor)]
        assert ids[index] != ids[int(donor)]
    for index, donor in enumerate(maps["different_query"]):
        assert queries[index] != queries[int(donor)]


def test_audio_donor_map_rejects_unpairable_singleton_query() -> None:
    """Catch partial same-query coverage being silently reported as complete."""
    with pytest.raises(ValueError, match="same-query donor.*singleton"):
        build_audio_donor_maps(["a1", "a2", "b1"], ["a", "a", "b"])


def test_temporal_audio_shuffle_is_reproducible_and_keeps_masks_paired() -> None:
    """Catch cross-sample shuffles or a spectrogram/audio-valid permutation mismatch."""
    spectrogram = torch.tensor(
        [
            [[[[0.0]]], [[[1.0]]], [[[2.0]]], [[[3.0]]]],
            [[[[10.0]]], [[[11.0]]], [[[12.0]]], [[[13.0]]]],
        ]
    )
    audio_valid = spectrogram[:, :, 0, 0, 0] + 100.0
    batch = {
        "spectrogram": spectrogram,
        "audio_valid": audio_valid,
        "frame": torch.arange(8).reshape(2, 4),
        "segment_label": torch.tensor([[0, 1, 0, 1], [1, 1, 0, 0]]),
        "id": ["first", "second"],
    }

    first = temporally_shuffle_audio(batch, seed=9, sample_offset=100)
    second = temporally_shuffle_audio(batch, seed=9, sample_offset=100)

    assert torch.equal(first["spectrogram"], second["spectrogram"])
    assert torch.equal(first["audio_valid"], second["audio_valid"])
    assert first["_audio_temporal_permutations"] == second[
        "_audio_temporal_permutations"
    ]
    assert torch.equal(first["frame"], batch["frame"])
    assert torch.equal(first["segment_label"], batch["segment_label"])
    assert first["id"] == batch["id"]
    shuffled_values = first["spectrogram"][:, :, 0, 0, 0]
    assert torch.equal(first["audio_valid"], shuffled_values + 100.0)
    assert sorted(shuffled_values[0].tolist()) == [0.0, 1.0, 2.0, 3.0]
    assert sorted(shuffled_values[1].tolist()) == [10.0, 11.0, 12.0, 13.0]
    assert not torch.equal(first["spectrogram"], batch["spectrogram"])
