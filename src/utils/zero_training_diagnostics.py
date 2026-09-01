from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

import numpy as np
import torch
from sklearn.metrics import average_precision_score, roc_auc_score


TASK_SEGMENTS = 10
_PREDICTION_FIELDS = (
    "ids",
    "queries",
    "split_types",
    "sample_offsets",
    "segment_indices",
    "labels",
    "logits",
    "probabilities",
)
_ALIGNMENT_FIELDS = (
    "ids",
    "queries",
    "split_types",
    "sample_offsets",
    "segment_indices",
    "labels",
)


def validate_t10_predictions(
    predictions: Mapping[str, np.ndarray],
) -> list[slice]:
    missing = [name for name in _PREDICTION_FIELDS if name not in predictions]
    if missing:
        raise ValueError(f"Prediction payload is missing fields: {missing}")
    ids = np.asarray(predictions["ids"]).astype(str).reshape(-1)
    queries = np.asarray(predictions["queries"]).astype(str).reshape(-1)
    split_types = np.asarray(predictions["split_types"]).astype(str).reshape(-1)
    if ids.size == 0 or queries.size != ids.size or split_types.size != ids.size:
        raise ValueError("ids/queries/split_types must contain one value per sample")
    if len(set(ids.tolist())) != ids.size:
        raise ValueError("Prediction ids must be unique")
    if any(not value.strip() for value in ids) or any(
        not value.strip() for value in queries
    ):
        raise ValueError("Prediction ids and queries must be non-empty")

    offsets = np.asarray(predictions["sample_offsets"], dtype=np.int64).reshape(-1)
    if offsets.size != ids.size + 1 or offsets[0] != 0:
        raise ValueError("Prediction sample_offsets are malformed")
    counts = np.diff(offsets)
    if np.any(counts != TASK_SEGMENTS):
        raise ValueError(
            f"Each prediction sample must contain exactly {TASK_SEGMENTS} task segments"
        )
    total = int(offsets[-1])
    if total != ids.size * TASK_SEGMENTS:
        raise ValueError("Prediction sample_offsets total is inconsistent")

    labels = np.asarray(predictions["labels"], dtype=np.float64).reshape(-1)
    logits = np.asarray(predictions["logits"], dtype=np.float64).reshape(-1)
    probabilities = np.asarray(
        predictions["probabilities"], dtype=np.float64
    ).reshape(-1)
    segment_indices = np.asarray(
        predictions["segment_indices"], dtype=np.int64
    ).reshape(-1)
    if any(values.size != total for values in (labels, logits, probabilities, segment_indices)):
        raise ValueError("Prediction segment fields do not match sample_offsets")
    if not np.isin(labels, (0.0, 1.0)).all():
        raise ValueError("Prediction labels must be finite binary values")
    if not np.isfinite(logits).all() or not np.isfinite(probabilities).all():
        raise ValueError("Prediction scores contain NaN/Inf")
    if np.any(probabilities < 0.0) or np.any(probabilities > 1.0):
        raise ValueError("Prediction probabilities must lie in [0,1]")
    expected_probabilities = 1.0 / (
        1.0 + np.exp(-np.clip(logits, -80.0, 80.0))
    )
    if not np.allclose(
        probabilities, expected_probabilities, rtol=1e-6, atol=1e-8
    ):
        raise ValueError("Prediction probabilities must match sigmoid of logits")

    official = np.arange(TASK_SEGMENTS, dtype=np.int64)
    slices: list[slice] = []
    for start, end in zip(offsets[:-1], offsets[1:]):
        sample = slice(int(start), int(end))
        if not np.array_equal(segment_indices[sample], official):
            raise ValueError("Prediction segment indices must preserve official T=10 order")
        slices.append(sample)
    return slices


def _distribution(values: np.ndarray) -> dict[str, Any]:
    array = np.asarray(values, dtype=np.float64).reshape(-1)
    if array.size == 0 or not np.isfinite(array).all():
        raise ValueError("Cannot summarize an empty or non-finite distribution")
    return {
        "count": int(array.size),
        "mean": float(array.mean()),
        "std": float(array.std()),
        "min": float(array.min()),
        "max": float(array.max()),
        "quantiles": {
            str(q): float(np.quantile(array, q))
            for q in (0.0, 0.05, 0.25, 0.5, 0.75, 0.95, 1.0)
        },
    }


def _classification_summary(
    labels: np.ndarray, probabilities: np.ndarray, *, threshold: float
) -> dict[str, Any]:
    y = np.asarray(labels, dtype=np.int64).reshape(-1)
    p = np.asarray(probabilities, dtype=np.float64).reshape(-1)
    if y.size == 0 or p.size != y.size:
        raise ValueError("Labels and probabilities must be non-empty and aligned")
    classes = np.unique(y)
    ap = float(average_precision_score(y, p)) if np.any(y == 1) else 0.0
    auroc: float | None
    auroc_reason: str | None
    if classes.size == 2:
        auroc = float(roc_auc_score(y, p))
        auroc_reason = None
    else:
        auroc = None
        auroc_reason = "undefined_single_class_labels"
    return {
        "segment_count": int(y.size),
        "positive_rate": float(y.mean()),
        "ap": ap,
        "auroc": auroc,
        "auroc_reason": auroc_reason,
        "threshold": float(threshold),
        "predicted_positive_rate": float(np.mean(p >= float(threshold))),
        "score_distribution": _distribution(p),
    }


def mixed_pairwise_concordance(
    labels: np.ndarray, scores: np.ndarray, offsets: np.ndarray
) -> dict[str, Any]:
    y = np.asarray(labels, dtype=np.int64).reshape(-1)
    p = np.asarray(scores, dtype=np.float64).reshape(-1)
    boundaries = np.asarray(offsets, dtype=np.int64).reshape(-1)
    if y.size == 0 or p.size != y.size or not np.isin(y, (0, 1)).all():
        raise ValueError("Pairwise labels/scores must be aligned finite binary data")
    if not np.isfinite(p).all():
        raise ValueError("Pairwise scores contain NaN/Inf")
    if (
        boundaries.size < 2
        or boundaries[0] != 0
        or boundaries[-1] != y.size
        or np.any(np.diff(boundaries) <= 0)
    ):
        raise ValueError("Pairwise sample_offsets are malformed")

    hits = 0.0
    pair_count = 0
    per_video: list[float] = []
    for start, end in zip(boundaries[:-1], boundaries[1:]):
        sample_y = y[int(start) : int(end)]
        positive_count = int(sample_y.sum())
        if positive_count == 0 or positive_count == sample_y.size:
            continue
        sample_p = p[int(start) : int(end)]
        differences = (
            sample_p[sample_y == 1][:, None] - sample_p[sample_y == 0][None, :]
        )
        sample_hits = float(
            (differences > 0).sum() + 0.5 * (differences == 0).sum()
        )
        sample_pairs = int(differences.size)
        hits += sample_hits
        pair_count += sample_pairs
        per_video.append(sample_hits / sample_pairs)
    if not per_video or pair_count <= 0:
        raise ValueError("Pairwise concordance requires at least one mixed-label sample")
    return {
        "videos": len(per_video),
        "pairs": pair_count,
        "pair_weighted": hits / pair_count,
        "video_macro_mean": float(np.mean(per_video)),
    }


def _subset_arrays(
    predictions: Mapping[str, np.ndarray],
    slices: Sequence[slice],
    sample_indices: Sequence[int],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    labels = np.asarray(predictions["labels"], dtype=np.int64)
    probabilities = np.asarray(predictions["probabilities"], dtype=np.float64)
    selected_labels = [labels[slices[index]] for index in sample_indices]
    selected_probabilities = [probabilities[slices[index]] for index in sample_indices]
    if not selected_labels:
        raise ValueError("Requested prediction stratum is empty")
    lengths = [values.size for values in selected_labels]
    return (
        np.concatenate(selected_labels),
        np.concatenate(selected_probabilities),
        np.concatenate(([0], np.cumsum(lengths))).astype(np.int64),
    )


def _mixed_shuffle_summary(
    labels: np.ndarray,
    probabilities: np.ndarray,
    offsets: np.ndarray,
    *,
    repeats: int,
    seed: int,
) -> dict[str, Any]:
    if repeats <= 0:
        raise ValueError("shuffle_repeats must be positive")
    baseline_ap = float(average_precision_score(labels, probabilities))
    baseline_auroc = float(roc_auc_score(labels, probabilities))
    rng = np.random.default_rng(int(seed))
    shuffled_ap: list[float] = []
    shuffled_auroc: list[float] = []
    for _ in range(int(repeats)):
        shuffled = probabilities.copy()
        for start, end in zip(offsets[:-1], offsets[1:]):
            begin, finish = int(start), int(end)
            shuffled[begin:finish] = probabilities[begin:finish][
                rng.permutation(finish - begin)
            ]
        shuffled_ap.append(float(average_precision_score(labels, shuffled)))
        shuffled_auroc.append(float(roc_auc_score(labels, shuffled)))
    ap_values = np.asarray(shuffled_ap, dtype=np.float64)
    auroc_values = np.asarray(shuffled_auroc, dtype=np.float64)
    return {
        "sample_count": int(offsets.size - 1),
        "segment_count": int(labels.size),
        "repeats": int(repeats),
        "seed": int(seed),
        "semantics": "mixed_labels_fixed_scores_permuted_within_each_mixed_sample",
        "ap": {
            "baseline": baseline_ap,
            "shuffled": _distribution(ap_values),
            "mean_drop": baseline_ap - float(ap_values.mean()),
        },
        "auroc": {
            "baseline": baseline_auroc,
            "shuffled": _distribution(auroc_values),
            "mean_drop": baseline_auroc - float(auroc_values.mean()),
        },
    }


def summarize_label_strata(
    predictions_by_mode: Mapping[str, Mapping[str, np.ndarray]],
    *,
    shuffle_repeats: int,
    seed: int,
    threshold: float,
) -> dict[str, Any]:
    if not predictions_by_mode:
        raise ValueError("At least one prediction mode is required")
    reference_mode = next(iter(predictions_by_mode))
    reference = predictions_by_mode[reference_mode]
    slices = validate_t10_predictions(reference)
    for mode, predictions in predictions_by_mode.items():
        validate_t10_predictions(predictions)
        for field in _ALIGNMENT_FIELDS:
            if not np.array_equal(reference[field], predictions[field]):
                raise ValueError(f"Prediction mode {mode} changed aligned field {field}")

    labels = np.asarray(reference["labels"], dtype=np.int64)
    positive_counts = np.asarray(
        [int(labels[sample].sum()) for sample in slices], dtype=np.int64
    )
    groups = {
        "k0": np.flatnonzero(positive_counts == 0).tolist(),
        "mixed": np.flatnonzero(
            (positive_counts > 0) & (positive_counts < TASK_SEGMENTS)
        ).tolist(),
        "k10": np.flatnonzero(positive_counts == TASK_SEGMENTS).tolist(),
    }
    if any(not indices for indices in groups.values()):
        raise ValueError("Label strata require non-empty k0, mixed, and k10 groups")

    strata: dict[str, Any] = {}
    for group_name, indices in groups.items():
        modes: dict[str, Any] = {}
        for mode, predictions in predictions_by_mode.items():
            group_labels, group_scores, _ = _subset_arrays(
                predictions, slices, indices
            )
            modes[mode] = _classification_summary(
                group_labels, group_scores, threshold=float(threshold)
            )
        strata[group_name] = {
            "sample_count": len(indices),
            "sample_fraction": len(indices) / len(slices),
            "modes": modes,
        }

    mixed_shuffle: dict[str, Any] = {}
    concordance: dict[str, Any] = {}
    for mode, predictions in predictions_by_mode.items():
        mixed_labels, mixed_scores, mixed_offsets = _subset_arrays(
            predictions, slices, groups["mixed"]
        )
        mixed_shuffle[mode] = _mixed_shuffle_summary(
            mixed_labels,
            mixed_scores,
            mixed_offsets,
            repeats=int(shuffle_repeats),
            seed=int(seed),
        )
        concordance[mode] = mixed_pairwise_concordance(
            labels=np.asarray(predictions["labels"], dtype=np.int64),
            scores=np.asarray(predictions["probabilities"], dtype=np.float64),
            offsets=np.asarray(predictions["sample_offsets"], dtype=np.int64),
        )

    histogram = Counter(int(value) for value in positive_counts)
    return {
        "task_segments": TASK_SEGMENTS,
        "sample_count": len(slices),
        "segment_count": int(labels.size),
        "positive_count_histogram": {
            str(index): int(histogram.get(index, 0))
            for index in range(TASK_SEGMENTS + 1)
        },
        "strata": strata,
        "mixed_only_shuffle": mixed_shuffle,
        "mixed_pairwise_concordance": concordance,
    }


def build_audio_donor_maps(
    ids: Sequence[str], queries: Sequence[str]
) -> dict[str, np.ndarray]:
    sample_ids = [str(value) for value in ids]
    sample_queries = [str(value) for value in queries]
    if not sample_ids or len(sample_ids) != len(sample_queries):
        raise ValueError("Audio donor ids/queries must be non-empty and aligned")
    if len(set(sample_ids)) != len(sample_ids):
        raise ValueError("Audio donor ids must be unique")
    if any(not value.strip() for value in sample_ids + sample_queries):
        raise ValueError("Audio donor ids/queries must be non-empty strings")

    groups: dict[str, list[int]] = {}
    for index, query in enumerate(sample_queries):
        groups.setdefault(query, []).append(index)
    singleton = sorted(query for query, indices in groups.items() if len(indices) < 2)
    if singleton:
        raise ValueError(f"same-query donor cannot cover singleton queries: {singleton}")
    same_query = np.empty(len(sample_ids), dtype=np.int64)
    for query in sorted(groups):
        indices = sorted(groups[query], key=lambda index: sample_ids[index])
        for position, index in enumerate(indices):
            same_query[index] = indices[(position + 1) % len(indices)]

    largest_group = max(len(indices) for indices in groups.values())
    if largest_group * 2 > len(sample_ids):
        raise ValueError("different-query bijection is impossible for the largest query group")
    ordered = sorted(
        range(len(sample_ids)),
        key=lambda index: (sample_queries[index], sample_ids[index]),
    )
    rotated = ordered[largest_group:] + ordered[:largest_group]
    different_query = np.empty(len(sample_ids), dtype=np.int64)
    for index, donor in zip(ordered, rotated):
        different_query[index] = donor
    if any(
        sample_queries[index] == sample_queries[int(donor)]
        for index, donor in enumerate(different_query)
    ):
        raise RuntimeError("Deterministic different-query rotation violated its contract")
    return {
        "same_query": same_query,
        "different_query": different_query,
    }


def temporally_shuffle_audio(
    batch: Mapping[str, Any], *, seed: int, sample_offset: int
) -> dict[str, Any]:
    spectrogram = batch.get("spectrogram")
    audio_valid = batch.get("audio_valid")
    if not isinstance(spectrogram, torch.Tensor) or not isinstance(
        audio_valid, torch.Tensor
    ):
        raise ValueError("Audio shuffle requires tensor spectrogram and audio_valid")
    if spectrogram.ndim < 3 or audio_valid.ndim != 2:
        raise ValueError("Audio tensors must have leading [B,T] dimensions")
    if tuple(spectrogram.shape[:2]) != tuple(audio_valid.shape):
        raise ValueError("spectrogram/audio_valid leading shapes differ")

    result = dict(batch)
    shuffled_spectrogram = spectrogram.clone()
    shuffled_valid = audio_valid.clone()
    permutations: list[list[int]] = []
    sequence_length = int(spectrogram.shape[1])
    for sample_index in range(int(spectrogram.shape[0])):
        rng = np.random.default_rng(
            np.random.SeedSequence([int(seed), int(sample_offset) + sample_index])
        )
        permutation = rng.permutation(sequence_length)
        if sequence_length > 1 and np.array_equal(
            permutation, np.arange(sequence_length)
        ):
            permutation = np.roll(permutation, 1)
        spec_index = torch.as_tensor(
            permutation, dtype=torch.long, device=spectrogram.device
        )
        valid_index = spec_index.to(device=audio_valid.device)
        shuffled_spectrogram[sample_index] = spectrogram[sample_index].index_select(
            0, spec_index
        )
        shuffled_valid[sample_index] = audio_valid[sample_index].index_select(
            0, valid_index
        )
        permutations.append([int(value) for value in permutation.tolist()])
    result["spectrogram"] = shuffled_spectrogram
    result["audio_valid"] = shuffled_valid
    result["_audio_temporal_permutations"] = permutations
    return result
