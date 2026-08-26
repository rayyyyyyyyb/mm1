from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score


def _binary_mask(value: Sequence[int] | np.ndarray, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=np.int64).reshape(-1)
    if array.size == 0:
        raise ValueError(f"{name} must be nonempty")
    if not np.isin(array, [0, 1]).all():
        raise ValueError(f"{name} must contain only 0/1 values")
    return array


def binary_f1(prediction: Sequence[int] | np.ndarray, ground_truth: Sequence[int] | np.ndarray) -> float:
    pred = _binary_mask(prediction, "prediction")
    gt = _binary_mask(ground_truth, "ground_truth")
    if pred.shape != gt.shape:
        raise ValueError("prediction and ground_truth must have identical shapes")
    tp = int(np.sum((pred == 1) & (gt == 1)))
    fp = int(np.sum((pred == 1) & (gt == 0)))
    fn = int(np.sum((pred == 0) & (gt == 1)))
    denominator = 2 * tp + fp + fn
    return 1.0 if denominator == 0 else float(2 * tp / denominator)


def ovavel_segment_f1_query_background(
    pred_fg: Sequence[int] | np.ndarray,
    gt_fg: Sequence[int] | np.ndarray,
) -> float:
    pred_fg_array = _binary_mask(pred_fg, "pred_fg")
    gt_fg_array = _binary_mask(gt_fg, "gt_fg")
    if pred_fg_array.shape != gt_fg_array.shape:
        raise ValueError("pred/gt must be nonempty and have identical shapes")

    pred = np.stack([pred_fg_array, 1 - pred_fg_array], axis=0)
    gt = np.stack([gt_fg_array, 1 - gt_fg_array], axis=0)
    tp = np.sum(pred * gt, axis=1)
    fn = np.sum((1 - pred) * gt, axis=1)
    fp = np.sum(pred * (1 - gt), axis=1)
    active = ((tp + fp) != 0) | ((tp + fn) != 0)
    if not np.any(active):
        return 1.0
    scores = 2 * tp[active] / (2 * tp[active] + fp[active] + fn[active])
    return float(np.mean(scores))


def _events(mask: Sequence[int] | np.ndarray) -> list[tuple[int, int]]:
    values = _binary_mask(mask, "event mask")
    events: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(values.tolist() + [0]):
        if value == 1 and start is None:
            start = index
        elif value == 0 and start is not None:
            events.append((start, index))
            start = None
    return events


def _interval_iou(left: tuple[int, int], right: tuple[int, int]) -> float:
    intersection = max(0, min(left[1], right[1]) - max(left[0], right[0]))
    union = max(left[1], right[1]) - min(left[0], right[0])
    return 0.0 if union <= 0 else float(intersection / union)


def ovavel_event_f1(
    pred_fg: Sequence[int] | np.ndarray,
    gt_fg: Sequence[int] | np.ndarray,
    *,
    iou_threshold: float = 0.5,
) -> float:
    pred_array = _binary_mask(pred_fg, "pred_fg")
    gt_array = _binary_mask(gt_fg, "gt_fg")
    if pred_array.shape != gt_array.shape:
        raise ValueError("pred/gt must be nonempty and have identical shapes")
    pred_events = _events(pred_array)
    gt_events = _events(gt_array)
    if not pred_events and not gt_events:
        return 1.0

    # Match the upstream evaluator's intentionally non-exclusive semantics.
    tp = sum(
        any(_interval_iou(pred, gt) >= iou_threshold for gt in gt_events)
        for pred in pred_events
    )
    fp = len(pred_events) - tp
    fn = sum(
        not any(_interval_iou(pred, gt) >= iou_threshold for pred in pred_events)
        for gt in gt_events
    )
    denominator = 2 * tp + fp + fn
    return 1.0 if denominator == 0 else float(2 * tp / denominator)


def _validated_offsets(offsets: Sequence[int] | np.ndarray, segment_count: int) -> np.ndarray:
    values = np.asarray(offsets, dtype=np.int64).reshape(-1)
    if (
        values.size < 2
        or int(values[0]) != 0
        or int(values[-1]) != segment_count
        or np.any(np.diff(values) <= 0)
    ):
        raise ValueError("sample_offsets must start at 0, end at the segment count, and increase")
    return values


def compute_thresholded_ovavel_metrics(
    labels: Sequence[float] | np.ndarray,
    probabilities: Sequence[float] | np.ndarray,
    sample_offsets: Sequence[int] | np.ndarray,
    *,
    threshold: float,
) -> dict[str, Any]:
    """Apply official per-sample F1 definitions at an explicit frozen threshold.

    This is separate from ``compute_ovavel_metrics``, whose names and contract
    are fixed to the protocol comparison threshold of 0.5.
    """

    threshold_value = float(threshold)
    if not np.isfinite(threshold_value) or not 0.0 <= threshold_value <= 1.0:
        raise ValueError("threshold must be finite and within [0, 1]")
    labels_array = _binary_mask(np.asarray(labels, dtype=np.int64), "labels")
    probabilities_array = np.asarray(probabilities, dtype=np.float64).reshape(-1)
    if probabilities_array.shape != labels_array.shape:
        raise ValueError("labels and probabilities must have identical shapes")
    if not np.isfinite(probabilities_array).all():
        raise ValueError("probabilities contain NaN/Inf")
    if np.any((probabilities_array < 0.0) | (probabilities_array > 1.0)):
        raise ValueError("probabilities must lie within [0, 1]")
    offsets = _validated_offsets(sample_offsets, int(labels_array.size))
    predictions = (probabilities_array >= threshold_value).astype(np.int64)

    foreground_scores: list[float] = []
    segment_scores: list[float] = []
    event_scores: list[float] = []
    for start, end in zip(offsets[:-1], offsets[1:]):
        sample_pred = predictions[int(start) : int(end)]
        sample_gt = labels_array[int(start) : int(end)]
        foreground_scores.append(binary_f1(sample_pred, sample_gt))
        segment_scores.append(ovavel_segment_f1_query_background(sample_pred, sample_gt))
        event_scores.append(ovavel_event_f1(sample_pred, sample_gt))

    return {
        "threshold": threshold_value,
        "binary_micro_f1_at_threshold": binary_f1(predictions, labels_array),
        "query_fg_f1_macro_at_threshold": float(np.mean(foreground_scores)),
        "ovavel_segment_f1_at_threshold": float(np.mean(segment_scores)),
        "ovavel_event_f1_at_threshold": float(np.mean(event_scores)),
    }


def compute_ovavel_metrics(
    labels: Sequence[float] | np.ndarray,
    probabilities: Sequence[float] | np.ndarray,
    sample_offsets: Sequence[int] | np.ndarray,
    *,
    threshold: float = 0.5,
) -> dict[str, Any]:
    if float(threshold) != 0.5:
        raise ValueError("explicit @0.5 OV-AVEL metrics require threshold=0.5")
    labels_array = _binary_mask(np.asarray(labels, dtype=np.int64), "labels")
    probabilities_array = np.asarray(probabilities, dtype=np.float64).reshape(-1)
    if probabilities_array.shape != labels_array.shape:
        raise ValueError("labels and probabilities must have identical shapes")
    if not np.isfinite(probabilities_array).all():
        raise ValueError("probabilities contain NaN/Inf")
    thresholded = compute_thresholded_ovavel_metrics(
        labels_array,
        probabilities_array,
        sample_offsets,
        threshold=0.5,
    )

    has_both_classes = np.unique(labels_array).size == 2
    auroc = float(roc_auc_score(labels_array, probabilities_array)) if has_both_classes else None
    ap = (
        float(average_precision_score(labels_array, probabilities_array))
        if np.any(labels_array == 1)
        else 0.0
    )
    return {
        "threshold": 0.5,
        "ap": ap,
        "auroc": auroc,
        "binary_micro_f1_at_0_5": thresholded["binary_micro_f1_at_threshold"],
        "query_fg_f1_macro_at_0_5": thresholded["query_fg_f1_macro_at_threshold"],
        "ovavel_segment_f1_at_0_5": thresholded["ovavel_segment_f1_at_threshold"],
        "ovavel_event_f1_at_0_5": thresholded["ovavel_event_f1_at_threshold"],
    }
