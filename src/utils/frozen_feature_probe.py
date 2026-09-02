"""Read-only frozen-feature probes for the post-S9 representation audit.

This module deliberately contains no student model, optimizer, checkpoint, or
backward operation.  It turns already-frozen ``[N, T, D]`` token arrays into
equal-capacity probe designs and evaluates ranking information on the official
``T=10`` task timeline.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.preprocessing import StandardScaler


ALPHA_GRID: tuple[float, ...] = (1e-5, 1e-4, 1e-3, 1e-2)
PROBE_NAMES: tuple[str, ...] = ("qp", "vqp", "aqp")
FUSION_BLOCKS = 4
VISUAL_SUCCESS_C = 0.020
VISUAL_SUCCESS_RANKING = 0.010
FAIL_C = 0.010
FAIL_RANKING = 0.005


def _as_feature_array(name: str, value: np.ndarray) -> np.ndarray:
    array = np.asarray(value, dtype=np.float32)
    if array.ndim != 3:
        raise ValueError(f"{name} must be [N,T,D], got {array.shape}")
    if array.shape[0] <= 0 or array.shape[1] <= 0 or array.shape[2] <= 0:
        raise ValueError(f"{name} must have positive N,T,D, got {array.shape}")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must contain only finite values")
    return array


def _normalize_position(position: np.ndarray, n: int, t: int, d: int) -> np.ndarray:
    array = np.asarray(position, dtype=np.float32)
    if array.ndim == 2:
        array = array[None, ...]
    if array.ndim != 3 or array.shape[1:] != (t, d):
        raise ValueError(f"position must be [T,D], [1,T,D], or [N,T,D] with T,D={(t, d)}")
    if array.shape[0] not in {1, n}:
        raise ValueError(f"position batch dimension must be 1 or {n}, got {array.shape[0]}")
    if not np.isfinite(array).all():
        raise ValueError("position must contain only finite values")
    if array.shape[0] == 1 and n != 1:
        array = np.broadcast_to(array, (n, t, d)).copy()
    return array


def build_probe_designs(
    visual: np.ndarray,
    audio: np.ndarray,
    query: np.ndarray,
    position: np.ndarray,
) -> dict[str, np.ndarray]:
    """Build the preregistered equal-capacity QP/VQP/AQP designs.

    Every design has four fusion-dimension blocks.  QP is explicitly padded as
    ``[0,q,0,p]`` so its logistic head has the same 4D parameter shape as VQP
    and AQP; this prevents a shorter control head from receiving a capacity
    advantage or disadvantage.
    """

    visual_array = _as_feature_array("visual", visual)
    audio_array = _as_feature_array("audio", audio)
    query_array = _as_feature_array("query", query)
    if not (visual_array.shape == audio_array.shape == query_array.shape):
        raise ValueError(
            "visual, audio, and query must have the same shape "
            f"(got {visual_array.shape}, {audio_array.shape}, {query_array.shape})"
        )
    n, t, d = visual_array.shape
    position_array = _normalize_position(position, n, t, d)
    zeros = np.zeros_like(visual_array)
    return {
        "qp": np.concatenate((zeros, query_array, zeros, position_array), axis=-1),
        "vqp": np.concatenate(
            (visual_array, query_array, visual_array * query_array, position_array),
            axis=-1,
        ),
        "aqp": np.concatenate(
            (audio_array, query_array, audio_array * query_array, position_array),
            axis=-1,
        ),
    }


def _validate_flat_inputs(
    labels: np.ndarray, scores: np.ndarray, offsets: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    y = np.asarray(labels, dtype=np.int64).reshape(-1)
    p = np.asarray(scores, dtype=np.float64).reshape(-1)
    boundaries = np.asarray(offsets, dtype=np.int64).reshape(-1)
    if y.size == 0 or p.size != y.size or not np.isin(y, (0, 1)).all():
        raise ValueError("labels and scores must be non-empty, aligned binary data")
    if not np.isfinite(p).all():
        raise ValueError("scores must contain only finite values")
    if (
        boundaries.size < 2
        or boundaries[0] != 0
        or boundaries[-1] != y.size
        or np.any(np.diff(boundaries) <= 0)
    ):
        raise ValueError("sample offsets must be strictly increasing and cover labels")
    return y, p, boundaries


def mixed_metrics(
    labels: np.ndarray, scores: np.ndarray, offsets: np.ndarray
) -> dict[str, Any]:
    """Compute ranking metrics on videos containing both label classes."""

    y, p, boundaries = _validate_flat_inputs(labels, scores, offsets)
    mixed_indices = [
        index
        for index, (start, end) in enumerate(zip(boundaries[:-1], boundaries[1:]))
        if np.unique(y[int(start) : int(end)]).size == 2
    ]
    if not mixed_indices:
        raise ValueError("mixed metrics require at least one mixed-label video")
    selected_y = np.concatenate(
        [y[int(boundaries[i]) : int(boundaries[i + 1])] for i in mixed_indices]
    )
    selected_p = np.concatenate(
        [p[int(boundaries[i]) : int(boundaries[i + 1])] for i in mixed_indices]
    )
    selected_offsets = np.asarray(
        [0]
        + [
            int(boundaries[i + 1] - boundaries[i])
            for i in mixed_indices
        ],
        dtype=np.int64,
    ).cumsum()
    hits = 0.0
    pairs = 0
    per_video: list[float] = []
    for start, end in zip(selected_offsets[:-1], selected_offsets[1:]):
        sample_y = selected_y[int(start) : int(end)]
        sample_p = selected_p[int(start) : int(end)]
        differences = sample_p[sample_y == 1][:, None] - sample_p[sample_y == 0][None, :]
        sample_pairs = int(differences.size)
        sample_hits = float((differences > 0).sum() + 0.5 * (differences == 0).sum())
        hits += sample_hits
        pairs += sample_pairs
        per_video.append(sample_hits / sample_pairs)
    return {
        "videos": len(mixed_indices),
        "segments": int(selected_y.size),
        "pairs": pairs,
        "mixed_ap": float(average_precision_score(selected_y, selected_p)),
        "mixed_auroc": float(roc_auc_score(selected_y, selected_p)),
        "mixed_pair_weighted": float(hits / pairs),
        "mixed_video_macro": float(np.mean(per_video)),
    }


def shuffle_metrics(
    labels: np.ndarray,
    scores: np.ndarray,
    offsets: np.ndarray,
    *,
    repeats: int = 100,
    seed: int = 42,
) -> dict[str, Any]:
    """Shuffle scores within each video without changing labels or offsets."""

    if int(repeats) <= 0:
        raise ValueError("repeats must be positive")
    y, p, boundaries = _validate_flat_inputs(labels, scores, offsets)
    baseline_ap = float(average_precision_score(y, p))
    baseline_auroc = float(roc_auc_score(y, p))
    rng = np.random.default_rng(int(seed))
    aps: list[float] = []
    aurocs: list[float] = []
    for _ in range(int(repeats)):
        shuffled = p.copy()
        for start, end in zip(boundaries[:-1], boundaries[1:]):
            shuffled[int(start) : int(end)] = rng.permutation(
                shuffled[int(start) : int(end)]
            )
        aps.append(float(average_precision_score(y, shuffled)))
        aurocs.append(float(roc_auc_score(y, shuffled)))
    return {
        "repeats": int(repeats),
        "seed": int(seed),
        "baseline_ap": baseline_ap,
        "baseline_auroc": baseline_auroc,
        "shuffle_ap_mean": float(np.mean(aps)),
        "shuffle_auroc_mean": float(np.mean(aurocs)),
        "shuffle_ap_drop": float(baseline_ap - np.mean(aps)),
        "shuffle_auroc_drop": float(baseline_auroc - np.mean(aurocs)),
    }


def choose_alpha(validation_results: Mapping[float, Mapping[str, float]]) -> float:
    """Choose alpha by mixed C, AP, AUROC, then stronger regularization."""

    if set(float(alpha) for alpha in validation_results) != set(ALPHA_GRID):
        raise ValueError(f"validation results must contain exactly {ALPHA_GRID}")
    for alpha, result in validation_results.items():
        for key in ("mixed_pair_weighted", "mixed_ap", "mixed_auroc"):
            value = float(result[key])
            if not np.isfinite(value):
                raise ValueError(f"validation result {key} for alpha={alpha} is not finite")
    return max(
        (float(alpha) for alpha in validation_results),
        key=lambda alpha: (
            float(validation_results[alpha]["mixed_pair_weighted"]),
            float(validation_results[alpha]["mixed_ap"]),
            float(validation_results[alpha]["mixed_auroc"]),
            alpha,
        ),
    )


def fit_logistic_probe(
    train_features: np.ndarray,
    train_labels: np.ndarray,
    *,
    alpha: float,
    random_state: int = 42,
) -> tuple[StandardScaler, SGDClassifier]:
    """Fit only a small readout; callers must never pass student parameters."""

    x = np.asarray(train_features, dtype=np.float32)
    y = np.asarray(train_labels, dtype=np.int64).reshape(-1)
    if x.ndim != 2 or x.shape[0] != y.size or x.shape[0] == 0:
        raise ValueError("train features/labels shape mismatch")
    if not np.isfinite(x).all() or not np.isin(y, (0, 1)).all():
        raise ValueError("train features/labels contain invalid values")
    if np.unique(y).size != 2:
        raise ValueError("probe training requires both binary classes")
    if float(alpha) <= 0.0 or not np.isfinite(float(alpha)):
        raise ValueError("alpha must be finite and positive")
    scaler = StandardScaler(copy=True)
    standardized = scaler.fit_transform(x)
    classifier = SGDClassifier(
        loss="log_loss",
        penalty="l2",
        alpha=float(alpha),
        fit_intercept=True,
        max_iter=2000,
        tol=1e-5,
        shuffle=True,
        random_state=int(random_state),
        learning_rate="optimal",
        early_stopping=False,
        class_weight=None,
        average=True,
        n_jobs=1,
    )
    classifier.fit(standardized, y)
    return scaler, classifier


def predict_probe_scores(
    scaler: StandardScaler, classifier: SGDClassifier, features: np.ndarray
) -> np.ndarray:
    x = np.asarray(features, dtype=np.float32)
    if x.ndim != 2 or not np.isfinite(x).all():
        raise ValueError("probe features must be finite [N,D]")
    return np.asarray(classifier.decision_function(scaler.transform(x)), dtype=np.float64)


def summarize_probe_outcome(
    qp: Mapping[str, float], vqp: Mapping[str, float], aqp: Mapping[str, float]
) -> dict[str, Any]:
    """Apply the pre-registered positive-control and visual-information gates."""

    def delta(candidate: Mapping[str, float], key: str) -> float:
        return float(candidate[key]) - float(qp[key])

    aqp_delta = {key: delta(aqp, key) for key in ("mixed_pair_weighted", "mixed_ap", "mixed_auroc")}
    vqp_delta = {key: delta(vqp, key) for key in ("mixed_pair_weighted", "mixed_ap", "mixed_auroc")}
    aqp_pass = aqp_delta["mixed_pair_weighted"] >= VISUAL_SUCCESS_C and (
        aqp_delta["mixed_ap"] >= VISUAL_SUCCESS_RANKING
        or aqp_delta["mixed_auroc"] >= VISUAL_SUCCESS_RANKING
    )
    vqp_pass = vqp_delta["mixed_pair_weighted"] >= VISUAL_SUCCESS_C and (
        vqp_delta["mixed_ap"] >= VISUAL_SUCCESS_RANKING
        or vqp_delta["mixed_auroc"] >= VISUAL_SUCCESS_RANKING
    )
    vqp_fail = (
        vqp_delta["mixed_pair_weighted"] < FAIL_C
        and vqp_delta["mixed_ap"] < FAIL_RANKING
        and vqp_delta["mixed_auroc"] < FAIL_RANKING
    ) or sum(value <= 0.0 for value in vqp_delta.values()) >= 2
    if not aqp_pass:
        status = "INVALID_POSITIVE_CONTROL"
    elif vqp_pass:
        status = "VISUAL_INFORMATION_DECODABLE"
    elif vqp_fail:
        status = "VISUAL_INFORMATION_NOT_DECODABLE"
    else:
        status = "INCONCLUSIVE"
    return {
        "status": status,
        "positive_control_pass": bool(aqp_pass),
        "visual_pass": bool(vqp_pass),
        "visual_fail": bool(vqp_fail),
        "aqp_delta_vs_qp": aqp_delta,
        "vqp_delta_vs_qp": vqp_delta,
        "thresholds": {
            "success_concordance": VISUAL_SUCCESS_C,
            "success_ap_or_auroc": VISUAL_SUCCESS_RANKING,
            "fail_concordance": FAIL_C,
            "fail_ap_and_auroc": FAIL_RANKING,
        },
    }
