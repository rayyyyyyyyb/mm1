"""Leakage-safe train-fit probes and boundary metrics for teacher signals."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score

from src.utils.frozen_feature_probe import fit_logistic_probe, predict_probe_scores


def evaluate_direct_visual_logit_gate(
    *,
    mixed_concordance: float | None,
    best_temporal_shift: int | float | None,
    shuffle_ap_drop: float | None,
    shuffle_auroc_drop: float | None,
) -> dict[str, Any]:
    """Apply the preregistered D3 gate to direct visual-teacher logits."""

    def finite_or(value: float | int | None, default: float) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return default
        return result if np.isfinite(result) else default

    concordance = finite_or(mixed_concordance, float("-inf"))
    shift = finite_or(best_temporal_shift, float("inf"))
    ap_drop = finite_or(shuffle_ap_drop, float("-inf"))
    auroc_drop = finite_or(shuffle_auroc_drop, float("-inf"))
    conditions = {
        "direct_mixed_concordance_ge_0.60": concordance >= 0.60,
        "direct_best_temporal_shift_eq_0": shift == 0,
        "direct_shuffle_ap_or_auroc_drop_ge_0.02": max(ap_drop, auroc_drop)
        >= 0.02,
    }
    return {
        "pass": all(conditions.values()),
        "conditions": conditions,
        "direct_mixed_video_macro_concordance": None
        if concordance == float("-inf")
        else concordance,
        "direct_best_temporal_shift": None if shift == float("inf") else shift,
        "direct_shuffle_ap_drop": None if ap_drop == float("-inf") else ap_drop,
        "direct_shuffle_auroc_drop": None
        if auroc_drop == float("-inf")
        else auroc_drop,
    }


def _finite_array(name: str, value: np.ndarray, ndim: int | None = None) -> np.ndarray:
    array = np.asarray(value)
    if ndim is not None and array.ndim != ndim:
        raise ValueError(f"{name} must have {ndim} dimensions, got {array.shape}")
    if array.size == 0 or not np.isfinite(array).all():
        raise ValueError(f"{name} must be non-empty and finite")
    return array


def _projection_matrix(input_dim: int, output_dim: int, seed: int, salt: int) -> np.ndarray:
    if input_dim <= 0 or output_dim <= 0:
        raise ValueError("projection dimensions must be positive")
    if input_dim == output_dim:
        return np.eye(input_dim, dtype=np.float32)
    rng = np.random.default_rng(int(seed) + 1009 * int(salt))
    matrix = rng.standard_normal((input_dim, output_dim), dtype=np.float32)
    matrix /= np.float32(np.sqrt(float(input_dim)))
    return matrix


def projection_matrix_sha256(matrix: np.ndarray) -> str:
    """Hash a projection matrix including dtype and shape metadata."""

    array = np.asarray(matrix)
    if array.ndim != 2 or not np.isfinite(array).all():
        raise ValueError("projection matrix must be finite and two-dimensional")
    digest = hashlib.sha256()
    contiguous = np.ascontiguousarray(array)
    digest.update(str(contiguous.dtype).encode("ascii"))
    digest.update(json.dumps(list(contiguous.shape)).encode("ascii"))
    digest.update(contiguous.tobytes(order="C"))
    return digest.hexdigest()


def build_common_space_maps(
    visual_input_dims: int | Sequence[int],
    query_input_dim: int,
    *,
    output_dim: int = 128,
    seed: int = 42,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create reusable visual/query maps once for a probe family.

    All visual passes with the same input dimension share one matrix, and all
    QP/VQP variants share one query matrix.  The returned receipt hashes every
    matrix so a probe cannot silently compare different coordinate systems.
    """

    if isinstance(visual_input_dims, (int, np.integer)):
        dimensions = [int(visual_input_dims)]
    else:
        dimensions = sorted({int(value) for value in visual_input_dims})
    if not dimensions or any(value <= 0 for value in dimensions):
        raise ValueError("visual_input_dims must contain positive dimensions")
    if int(query_input_dim) <= 0:
        raise ValueError("query_input_dim must be positive")
    visual_maps = {
        dimension: _projection_matrix(dimension, int(output_dim), int(seed), 1)
        for dimension in dimensions
    }
    query_map = _projection_matrix(int(query_input_dim), int(output_dim), int(seed), 2)
    receipt = {
        "seed": int(seed),
        "output_dim": int(output_dim),
        "visual_map_sha256": {
            str(dimension): projection_matrix_sha256(matrix)
            for dimension, matrix in visual_maps.items()
        },
        "query_map_sha256": projection_matrix_sha256(query_map),
    }
    return {"visual": visual_maps, "query": query_map}, receipt


def apply_common_space_maps(
    visual: np.ndarray,
    query: np.ndarray,
    maps: Mapping[str, Any],
) -> tuple[np.ndarray, np.ndarray]:
    """Apply a previously created map family without regenerating any map."""

    visual_array = _finite_array("visual", visual, 3).astype(np.float32, copy=False)
    query_array = _finite_array("query", query, 3).astype(np.float32, copy=False)
    if visual_array.shape[:2] != query_array.shape[:2]:
        raise ValueError("visual and query must share [B,T]")
    visual_maps = maps.get("visual")
    query_map = maps.get("query")
    if not isinstance(visual_maps, Mapping) or not isinstance(query_map, np.ndarray):
        raise ValueError("maps must contain visual mapping and query matrix")
    visual_map = visual_maps.get(int(visual_array.shape[-1]))
    if not isinstance(visual_map, np.ndarray):
        raise ValueError(
            f"no shared visual map for input dimension {visual_array.shape[-1]}"
        )
    if query_map.shape[0] != query_array.shape[-1]:
        raise ValueError("shared query map input dimension does not match query")
    return (
        np.matmul(visual_array, visual_map).astype(np.float32),
        np.matmul(query_array, query_map).astype(np.float32),
    )


def build_common_space(
    visual: np.ndarray,
    query: np.ndarray,
    *,
    output_dim: int = 128,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Map visual and query tensors to one fixed, label-independent space.

    The maps are seeded random linear maps (identity when dimensions already
    match), so no labels or validation examples influence the representation.
    Query embeddings and categorical query IDs are intentionally separate
    inputs; this function never accepts or derives IDs.
    """

    visual_array = _finite_array("visual", visual, 3).astype(np.float32, copy=False)
    query_array = _finite_array("query", query, 3).astype(np.float32, copy=False)
    if visual_array.shape[:2] != query_array.shape[:2]:
        raise ValueError("visual and query must share [B,T]")
    maps, maps_receipt = build_common_space_maps(
        int(visual_array.shape[-1]),
        int(query_array.shape[-1]),
        output_dim=int(output_dim),
        seed=int(seed),
    )
    visual_common, query_common = apply_common_space_maps(
        visual_array, query_array, maps
    )
    return visual_common.astype(np.float32), query_common.astype(np.float32), {
        "seed": int(seed),
        "output_dim": int(output_dim),
        "visual_input_dim": int(visual_array.shape[-1]),
        "query_input_dim": int(query_array.shape[-1]),
        "visual_map": "identity" if visual_array.shape[-1] == output_dim else "seeded_gaussian",
        "query_map": "identity" if query_array.shape[-1] == output_dim else "seeded_gaussian",
        "query_id_source": "separate_categorical_field",
        "projection_maps": maps_receipt,
    }


def _position_features(batch_size: int, segments: int) -> np.ndarray:
    positions = np.linspace(0.0, 1.0, int(segments), dtype=np.float32)
    angles = positions[:, None] * np.asarray([np.pi, 2.0 * np.pi], dtype=np.float32)[None, :]
    base = np.concatenate((positions[:, None], np.sin(angles), np.cos(angles)), axis=1)
    return np.broadcast_to(base[None, :, :], (batch_size, segments, 5)).copy()


def build_interaction_design(
    visual_common: np.ndarray,
    query_common: np.ndarray,
    positions: np.ndarray | None = None,
    *,
    mode: str,
) -> np.ndarray:
    """Build equal-capacity QP or query-conditioned interaction features."""

    visual = _finite_array("visual_common", visual_common, 3).astype(np.float32, copy=False)
    query = _finite_array("query_common", query_common, 3).astype(np.float32, copy=False)
    if visual.shape != query.shape:
        raise ValueError("visual_common and query_common must have identical [B,T,D] shapes")
    batch_size, segments, _ = visual.shape
    if positions is None:
        position = _position_features(batch_size, segments)
    else:
        position = _finite_array("positions", positions)
        if position.ndim == 2:
            position = np.broadcast_to(position[None, :, :], (batch_size, *position.shape)).copy()
        if position.shape[:2] != (batch_size, segments):
            raise ValueError("positions must match [B,T]")
        position = position.astype(np.float32, copy=False)
    zeros = np.zeros_like(visual)
    if mode == "qp":
        return np.concatenate((zeros, query, zeros, position), axis=-1)
    if mode == "interaction":
        return np.concatenate((visual, query, visual * query, position), axis=-1)
    raise ValueError(f"unsupported interaction design mode: {mode}")


def derive_all_transitions(labels: np.ndarray, mask: np.ndarray) -> dict[str, Any]:
    """Derive every valid adjacent transition, including disjoint windows."""

    y = np.asarray(labels, dtype=np.int64)
    valid = np.asarray(mask).astype(bool)
    if y.ndim != 2 or valid.shape != y.shape or not np.isin(y, (0, 1)).all():
        raise ValueError("labels and mask must be aligned binary [B,T]")
    transition_indices: list[list[int]] = []
    onset_indices: list[list[int]] = []
    offset_indices: list[list[int]] = []
    positive_window_count: list[int] = []
    for row, row_mask in zip(y, valid):
        transitions: list[int] = []
        onsets: list[int] = []
        offsets: list[int] = []
        runs = 0
        previous_positive = False
        for index, (current, is_valid) in enumerate(zip(row, row_mask)):
            if not is_valid:
                previous_positive = False
                continue
            positive = bool(current)
            if positive and not previous_positive:
                runs += 1
            if index > 0 and row_mask[index - 1]:
                previous = bool(row[index - 1])
                if positive != previous:
                    transitions.append(index)
                    (onsets if positive else offsets).append(index)
            previous_positive = positive
        transition_indices.append(transitions)
        onset_indices.append(onsets)
        offset_indices.append(offsets)
        positive_window_count.append(runs)
    return {
        "transition_indices": np.asarray(transition_indices, dtype=object),
        "onset_indices": np.asarray(onset_indices, dtype=object),
        "offset_indices": np.asarray(offset_indices, dtype=object),
        "positive_window_count": np.asarray(positive_window_count, dtype=np.int64),
        "single_window_continuous": bool(all(count <= 1 for count in positive_window_count)),
    }


def _safe_metric(metric: str, labels: np.ndarray, scores: np.ndarray) -> float | None:
    if labels.size == 0 or np.unique(labels).size < 2:
        return None
    if metric == "ap":
        return float(average_precision_score(labels, scores))
    if metric == "auroc":
        return float(roc_auc_score(labels, scores))
    raise ValueError(metric)


def _tie_aware_concordance(labels: np.ndarray, scores: np.ndarray, offsets: np.ndarray) -> dict[str, Any]:
    hits = 0.0
    pairs = 0
    video_values: list[float] = []
    for start, end in zip(offsets[:-1], offsets[1:]):
        row_labels = labels[int(start):int(end)]
        row_scores = scores[int(start):int(end)]
        positive = row_scores[row_labels == 1]
        negative = row_scores[row_labels == 0]
        if positive.size == 0 or negative.size == 0:
            continue
        differences = positive[:, None] - negative[None, :]
        row_pairs = int(differences.size)
        row_hits = float((differences > 0).sum() + 0.5 * (differences == 0).sum())
        hits += row_hits
        pairs += row_pairs
        video_values.append(row_hits / row_pairs)
    return {
        "pair_weighted_concordance": None if pairs == 0 else float(hits / pairs),
        "video_macro_concordance": None if not video_values else float(np.mean(video_values)),
        "mixed_videos": len(video_values),
        "mixed_pairs": pairs,
    }


def _mixed_flat(labels: np.ndarray, scores: np.ndarray, offsets: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    selected_labels: list[np.ndarray] = []
    selected_scores: list[np.ndarray] = []
    for start, end in zip(offsets[:-1], offsets[1:]):
        row_labels = labels[int(start):int(end)]
        row_scores = scores[int(start):int(end)]
        if np.unique(row_labels).size == 2:
            selected_labels.append(row_labels)
            selected_scores.append(row_scores)
    if not selected_labels:
        return np.asarray([], dtype=np.int64), np.asarray([], dtype=np.float64)
    return np.concatenate(selected_labels), np.concatenate(selected_scores)


def _per_query_macro(labels: np.ndarray, scores: np.ndarray, mask: np.ndarray, query_ids: np.ndarray) -> float | None:
    values: list[float] = []
    for query in np.unique(query_ids):
        rows = np.flatnonzero(query_ids == query)
        query_labels = labels[rows][mask[rows]]
        query_scores = scores[rows][mask[rows]]
        value = _safe_metric("ap", query_labels, query_scores)
        if value is not None:
            values.append(value)
    return None if not values else float(np.mean(values))


def _shuffle_summary(labels: np.ndarray, scores: np.ndarray, mask: np.ndarray, repeats: int, seed: int) -> dict[str, Any]:
    valid_labels = labels[mask]
    valid_scores = scores[mask]
    baseline_ap = _safe_metric("ap", valid_labels, valid_scores)
    baseline_auroc = _safe_metric("auroc", valid_labels, valid_scores)
    rng = np.random.default_rng(int(seed))
    aps: list[float] = []
    aurocs: list[float] = []
    for _ in range(int(repeats)):
        shuffled = scores.copy()
        for row in range(scores.shape[0]):
            valid_indices = np.flatnonzero(mask[row])
            shuffled[row, valid_indices] = rng.permutation(shuffled[row, valid_indices])
        shuffled_scores = shuffled[mask]
        ap = _safe_metric("ap", valid_labels, shuffled_scores)
        auroc = _safe_metric("auroc", valid_labels, shuffled_scores)
        if ap is not None:
            aps.append(ap)
        if auroc is not None:
            aurocs.append(auroc)
    return {
        "repeats": int(repeats),
        "seed": int(seed),
        "baseline_ap": baseline_ap,
        "baseline_auroc": baseline_auroc,
        "shuffle_ap_mean": None if not aps else float(np.mean(aps)),
        "shuffle_auroc_mean": None if not aurocs else float(np.mean(aurocs)),
        "shuffle_ap_drop": None if not aps or baseline_ap is None else float(baseline_ap - np.mean(aps)),
        "shuffle_auroc_drop": None if not aurocs or baseline_auroc is None else float(baseline_auroc - np.mean(aurocs)),
    }


def _transition_metrics(scores: np.ndarray, labels: np.ndarray, mask: np.ndarray) -> dict[str, float | None]:
    pair_mask = mask[:, 1:] & mask[:, :-1]
    differences = scores[:, 1:] - scores[:, :-1]
    transitions = labels[:, 1:] != labels[:, :-1]
    onset = (labels[:, 1:] == 1) & (labels[:, :-1] == 0)
    offset = (labels[:, 1:] == 0) & (labels[:, :-1] == 1)
    flat_mask = pair_mask.reshape(-1)
    magnitude = np.abs(differences).reshape(-1)[flat_mask]
    signed = differences.reshape(-1)[flat_mask]
    transition_flat = transitions.reshape(-1)[flat_mask].astype(np.int64)
    onset_flat = onset.reshape(-1)[flat_mask].astype(np.int64)
    offset_flat = offset.reshape(-1)[flat_mask].astype(np.int64)
    return {
        "all_transition_auroc": _safe_metric("auroc", transition_flat, magnitude),
        "onset_auroc": _safe_metric("auroc", onset_flat, signed),
        "offset_auroc": _safe_metric("auroc", offset_flat, -signed),
        "adjacent_valid_pairs": int(flat_mask.sum()),
        "transition_count": int(transition_flat.sum()),
    }


def direct_logit_shift_sweep(
    logits: np.ndarray,
    labels: np.ndarray,
    mask: np.ndarray,
    *,
    shifts: tuple[int, ...] = (-2, -1, 0, 1, 2),
) -> dict[str, Any]:
    """Evaluate cached direct logits against labels at explicit temporal shifts."""

    values = _finite_array("logits", logits, 2).astype(np.float64, copy=False)
    y = np.asarray(labels, dtype=np.int64)
    valid = np.asarray(mask).astype(bool)
    if y.shape != values.shape or valid.shape != y.shape or not np.isin(y, (0, 1)).all():
        raise ValueError("logits, labels, and mask must be aligned binary [B,T]")
    per_shift: dict[str, Any] = {}
    for shift in shifts:
        selected_y: list[np.ndarray] = []
        selected_scores: list[np.ndarray] = []
        selected_offsets = [0]
        for row in range(y.shape[0]):
            row_labels: list[int] = []
            row_scores: list[float] = []
            for target_index in range(y.shape[1]):
                source_index = target_index + int(shift)
                if valid[row, target_index] and 0 <= source_index < y.shape[1] and valid[row, source_index]:
                    row_labels.append(int(y[row, target_index]))
                    row_scores.append(float(values[row, source_index]))
            selected_y.append(np.asarray(row_labels, dtype=np.int64))
            selected_scores.append(np.asarray(row_scores, dtype=np.float64))
            selected_offsets.append(selected_offsets[-1] + len(row_labels))
        flat_y = np.concatenate(selected_y) if selected_y else np.asarray([], dtype=np.int64)
        flat_scores = np.concatenate(selected_scores) if selected_scores else np.asarray([], dtype=np.float64)
        boundaries = np.asarray(selected_offsets, dtype=np.int64)
        mixed_y, mixed_scores = _mixed_flat(flat_y, flat_scores, boundaries)
        per_shift[str(int(shift))] = {
            "shift": int(shift),
            "valid_segments": int(flat_y.size),
            "ap": _safe_metric("ap", flat_y, flat_scores),
            "auroc": _safe_metric("auroc", flat_y, flat_scores),
            "mixed": {
                **_tie_aware_concordance(flat_y, flat_scores, boundaries),
                "ap": _safe_metric("ap", mixed_y, mixed_scores),
                "auroc": _safe_metric("auroc", mixed_y, mixed_scores),
            },
        }
    best = max(
        per_shift.values(),
        key=lambda item: (
            -float("inf") if item["mixed"]["pair_weighted_concordance"] is None else item["mixed"]["pair_weighted_concordance"],
            -float("inf") if item["mixed"]["ap"] is None else item["mixed"]["ap"],
            -float("inf") if item["mixed"]["auroc"] is None else item["mixed"]["auroc"],
            -abs(int(item["shift"])),
        ),
    )
    return {
        "shifts": per_shift,
        "best_shift": int(best["shift"]),
        "status": "PASS" if int(best["shift"]) == 0 else "TEMPORAL_INDEX_ALIGNMENT_FAILURE",
    }


def score_signal_metrics(
    scores: np.ndarray,
    labels: np.ndarray,
    mask: np.ndarray,
    *,
    sample_ids: np.ndarray,
    query_ids: np.ndarray,
    offsets: np.ndarray,
    shuffle_repeats: int = 100,
    seed: int = 42,
) -> dict[str, Any]:
    """Score fixed segment values without fitting or mutating any state.

    This is the validation-only counterpart to :func:`fit_probe_and_score`.
    It is used for direct teacher logits so the direct and learned-probe paths
    report the same mixed, shuffle, query, and transition metrics.
    """

    score_array = _finite_array("scores", scores, 2).astype(np.float64, copy=False)
    label_array = np.asarray(labels, dtype=np.int64)
    mask_array = np.asarray(mask).astype(bool)
    if label_array.shape != score_array.shape or mask_array.shape != score_array.shape:
        raise ValueError("scores, labels, and mask must share [B,T]")
    if not np.isin(label_array, (0, 1)).all():
        raise ValueError("labels must be binary")
    ids = np.asarray(sample_ids).reshape(-1).astype(str)
    queries = np.asarray(query_ids).reshape(-1).astype(str)
    boundaries = np.asarray(offsets, dtype=np.int64).reshape(-1)
    if ids.size != label_array.shape[0] or queries.size != label_array.shape[0]:
        raise ValueError("sample_ids/query_ids must have one value per sample")
    if (
        boundaries.size != label_array.shape[0] + 1
        or boundaries[0] != 0
        or boundaries[-1] != int(mask_array.sum())
        or np.any(np.diff(boundaries) < 0)
    ):
        raise ValueError("offsets must cover valid rows")
    valid_labels = label_array[mask_array]
    valid_scores = score_array[mask_array]
    concordance = _tie_aware_concordance(valid_labels, valid_scores, boundaries)
    mixed_labels, mixed_scores = _mixed_flat(valid_labels, valid_scores, boundaries)
    return {
        "global": {
            "ap": _safe_metric("ap", valid_labels, valid_scores),
            "auroc": _safe_metric("auroc", valid_labels, valid_scores),
            "valid_segments": int(valid_labels.size),
        },
        "mixed": {
            **concordance,
            "ap": _safe_metric("ap", mixed_labels, mixed_scores),
            "auroc": _safe_metric("auroc", mixed_labels, mixed_scores),
            "valid_segments": int(mixed_labels.size),
        },
        "per_query_macro_ap": _per_query_macro(label_array, score_array, mask_array, queries),
        "shuffle": _shuffle_summary(
            label_array, score_array, mask_array, int(shuffle_repeats), int(seed)
        ),
        "transitions": _transition_metrics(score_array, label_array, mask_array),
        "sample_ids_sha256": _sha256_strings(ids),
        "query_ids_sha256": _sha256_strings(queries),
    }


def fit_probe_and_score(
    train_x: np.ndarray,
    train_y: np.ndarray,
    eval_x: np.ndarray,
    eval_y: np.ndarray,
    eval_mask: np.ndarray,
    *,
    sample_ids: np.ndarray,
    query_ids: np.ndarray,
    offsets: np.ndarray,
    seed: int = 42,
    alpha: float = 1e-4,
    shuffle_repeats: int = 100,
) -> dict[str, Any]:
    """Fit on train segments and evaluate only on a separate validation split."""

    train_features = _finite_array("train_x", train_x)
    train_labels = np.asarray(train_y, dtype=np.int64).reshape(-1)
    if train_features.ndim == 3:
        train_features = train_features.reshape(-1, train_features.shape[-1])
    if train_features.ndim != 2 or train_features.shape[0] != train_labels.size:
        raise ValueError("train_x/train_y shape mismatch")
    if not np.isin(train_labels, (0, 1)).all():
        raise ValueError("train_y must be binary")
    evaluation = _finite_array("eval_x", eval_x, 3).astype(np.float32, copy=False)
    labels = np.asarray(eval_y, dtype=np.int64)
    mask = np.asarray(eval_mask).astype(bool)
    if labels.ndim != 2 or mask.shape != labels.shape or evaluation.shape[:2] != labels.shape:
        raise ValueError("evaluation arrays must align as [B,T]")
    if not np.isin(labels, (0, 1)).all():
        raise ValueError("eval_y must be binary")
    ids = np.asarray(sample_ids).reshape(-1).astype(str)
    queries = np.asarray(query_ids).reshape(-1).astype(str)
    boundaries = np.asarray(offsets, dtype=np.int64).reshape(-1)
    if ids.size != labels.shape[0] or queries.size != labels.shape[0]:
        raise ValueError("sample_ids/query_ids must have one value per evaluation sample")
    if boundaries.size != labels.shape[0] + 1 or boundaries[0] != 0 or boundaries[-1] != int(mask.sum()):
        raise ValueError("offsets must cover valid evaluation rows")
    scaler, classifier = fit_logistic_probe(
        train_features,
        train_labels,
        alpha=float(alpha),
        random_state=int(seed),
    )
    scores = predict_probe_scores(scaler, classifier, evaluation.reshape(-1, evaluation.shape[-1])).reshape(labels.shape)
    metrics = score_signal_metrics(
        scores,
        labels,
        mask,
        sample_ids=ids,
        query_ids=queries,
        offsets=boundaries,
        shuffle_repeats=shuffle_repeats,
        seed=seed,
    )
    return {
        "probe": {
            "fit_segments": int(train_labels.size),
            "feature_dim": int(train_features.shape[-1]),
            "alpha": float(alpha),
            "seed": int(seed),
            "model": "StandardScaler + SGDClassifier(log_loss, l2, average=True)",
            "score_source": "validation_decision_function",
        },
        "metrics": {
            "global": metrics["global"],
            "mixed": metrics["mixed"],
            "per_query_macro_ap": metrics["per_query_macro_ap"],
            "shuffle": metrics["shuffle"],
            "transitions": metrics["transitions"],
        },
        "sample_ids_sha256": metrics["sample_ids_sha256"],
        "query_ids_sha256": metrics["query_ids_sha256"],
    }


def _sha256_strings(values: np.ndarray) -> str:
    import hashlib

    return hashlib.sha256("\n".join(str(value) for value in values.tolist()).encode("utf-8")).hexdigest()
