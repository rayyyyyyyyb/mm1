from __future__ import annotations

import copy

import numpy as np
import pytest
import torch

from scripts.diagnose_visual_sum_posthoc import (
    apply_posthoc_mode,
    select_mixed_sample_indices,
    summarize_intervention_metrics,
    summarize_projector_drift,
)


def _batch() -> dict[str, torch.Tensor | list[str]]:
    return {
        "frame": torch.arange(2 * 10 * 3 * 2 * 2, dtype=torch.float32).reshape(
            2, 10, 3, 2, 2
        ),
        "spectrogram": torch.arange(2 * 10 * 1 * 2 * 2, dtype=torch.float32).reshape(
            2, 10, 1, 2, 2
        ),
        "text_embedding": torch.ones(2, 4),
        "frame_valid": torch.ones(2, 10),
        "audio_valid": torch.ones(2, 10),
        "sequence_mask": torch.ones(2, 10),
    }


def _payload() -> dict[str, np.ndarray]:
    ids = np.asarray(["k0", "mixed_a", "k10", "mixed_b"])
    queries = np.asarray(["q0", "q1", "q2", "q1"])
    split_types = np.asarray(["seen", "seen", "unseen", "unseen"])
    labels = np.concatenate(
        [
            np.zeros(10),
            np.asarray([0, 1] * 5, dtype=np.float64),
            np.ones(10),
            np.asarray([1, 0] * 5, dtype=np.float64),
        ]
    )
    logits = np.linspace(-2.0, 2.0, 40, dtype=np.float64)
    offsets = np.asarray([0, 10, 20, 30, 40], dtype=np.int64)
    return {
        "ids": ids,
        "queries": queries,
        "split_types": split_types,
        "sample_offsets": offsets,
        "segment_indices": np.tile(np.arange(10, dtype=np.int64), 4),
        "labels": labels,
        "logits": logits,
        "probabilities": 1.0 / (1.0 + np.exp(-logits)),
    }


def test_content_modes_zero_only_selected_content_and_preserve_masks() -> None:
    source = _batch()
    original = apply_posthoc_mode(source, "original", seed=42, sample_offset=0)
    visual_zero = apply_posthoc_mode(source, "visual_zero", seed=42, sample_offset=0)
    audio_zero = apply_posthoc_mode(source, "audio_zero", seed=42, sample_offset=0)
    both_zero = apply_posthoc_mode(source, "both_zero", seed=42, sample_offset=0)

    assert torch.equal(original["frame"], source["frame"])
    assert torch.equal(original["spectrogram"], source["spectrogram"])
    assert torch.count_nonzero(visual_zero["frame"]) == 0
    assert torch.equal(visual_zero["spectrogram"], source["spectrogram"])
    assert torch.count_nonzero(audio_zero["spectrogram"]) == 0
    assert torch.equal(audio_zero["frame"], source["frame"])
    assert torch.count_nonzero(both_zero["frame"]) == 0
    assert torch.count_nonzero(both_zero["spectrogram"]) == 0
    for mode in (original, visual_zero, audio_zero, both_zero):
        for field in ("frame_valid", "audio_valid", "sequence_mask"):
            assert torch.equal(mode[field], source[field])


def test_audio_temporal_shuffle_is_deterministic_and_changes_only_audio_order() -> None:
    source = _batch()
    first = apply_posthoc_mode(source, "audio_temporal_shuffle", seed=42, sample_offset=7)
    second = apply_posthoc_mode(source, "audio_temporal_shuffle", seed=42, sample_offset=7)
    assert torch.equal(first["spectrogram"], second["spectrogram"])
    assert first["_audio_temporal_permutations"] == second["_audio_temporal_permutations"]
    assert not torch.equal(first["spectrogram"], source["spectrogram"])
    assert torch.equal(first["frame"], source["frame"])
    assert torch.equal(first["audio_valid"], source["audio_valid"])
    assert torch.equal(first["sequence_mask"], source["sequence_mask"])


def test_mixed_selection_requires_exactly_ten_segments() -> None:
    payload = _payload()
    assert select_mixed_sample_indices(payload) == [1, 3]
    malformed = copy.deepcopy(payload)
    malformed["sample_offsets"] = np.asarray([0, 9, 19, 29, 39], dtype=np.int64)
    with pytest.raises(ValueError, match="10|segment"):
        select_mixed_sample_indices(malformed)


def test_intervention_metrics_include_global_split_and_pairwise_outputs() -> None:
    payload = _payload()
    shifted = dict(payload)
    shifted["logits"] = payload["logits"] + 0.2
    shifted["probabilities"] = 1.0 / (1.0 + np.exp(-shifted["logits"]))
    result = summarize_intervention_metrics(
        {"original": payload, "visual_zero": shifted},
        threshold=0.5,
        shuffle_repeats=3,
        seed=42,
    )
    assert set(result["modes"]) == {"original", "visual_zero"}
    assert set(result["modes"]["original"]["groups"]) == {"total", "seen", "unseen"}
    assert "per_query_macro_ap" in result["modes"]["original"]["groups"]["total"]
    assert result["mixed_pairwise_concordance"]["original"]["pairs"] > 0
    assert result["mixed_only_shuffle"]["original"]["repeats"] == 3


def test_projector_drift_is_zero_for_equal_state_and_positive_for_change() -> None:
    initial = {"weight": torch.zeros(2, 2), "bias": torch.zeros(2)}
    equal = {name: value.clone() for name, value in initial.items()}
    changed = {"weight": torch.ones(2, 2), "bias": torch.zeros(2)}
    assert summarize_projector_drift(initial, equal)["absolute_l2"] == pytest.approx(0.0)
    assert summarize_projector_drift(initial, changed)["absolute_l2"] == pytest.approx(2.0)
    with pytest.raises(ValueError, match="keys|shape"):
        summarize_projector_drift(initial, {"weight": torch.zeros(3, 2), "bias": torch.zeros(2)})
