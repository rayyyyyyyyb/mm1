"""Read-only teacher/label boundary-alignment diagnostics for official T=10 data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score

PROJECT_ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.teacher_signal_probe import (
    build_common_space,
    build_interaction_design,
    derive_all_transitions,
    direct_logit_shift_sweep,
    fit_probe_and_score,
)


def derive_boundaries(labels: np.ndarray, mask: np.ndarray) -> dict[str, np.ndarray]:
    """Derive inclusive onset/offset indices from official labels only.

    ``-1`` denotes a sample with no valid positive segment.  Invalid masked
    rows are never treated as positives and cannot create a boundary.
    """

    labels_array = np.asarray(labels)
    mask_array = np.asarray(mask).astype(bool)
    if labels_array.ndim != 2 or labels_array.shape != mask_array.shape:
        raise ValueError("labels and mask must have identical [B,T] shapes")
    batch_size = labels_array.shape[0]
    onset = np.full(batch_size, -1, dtype=np.int64)
    offset = np.full(batch_size, -1, dtype=np.int64)
    positive_count = np.zeros(batch_size, dtype=np.int64)
    for index in range(batch_size):
        positive = np.flatnonzero(mask_array[index] & (labels_array[index] > 0))
        positive_count[index] = int(positive.size)
        if positive.size:
            onset[index] = int(positive[0])
            offset[index] = int(positive[-1])
    return {
        "onset": onset,
        "offset": offset,
        "positive_count": positive_count,
        "mask": mask_array,
    }


def _safe_ap(labels: np.ndarray, scores: np.ndarray) -> float | None:
    if labels.size == 0 or np.unique(labels).size < 2:
        return None
    return float(average_precision_score(labels, scores))


def _safe_auroc(labels: np.ndarray, scores: np.ndarray) -> float | None:
    if labels.size == 0 or np.unique(labels).size < 2:
        return None
    return float(roc_auc_score(labels, scores))


def _metric_or_missing(value: Any) -> float:
    """Preserve valid zero-valued metrics while mapping only missing values."""

    return -1.0 if value is None else float(value)


def _flatten_valid(values: np.ndarray, mask: np.ndarray) -> np.ndarray:
    return np.asarray(values)[np.asarray(mask).astype(bool)]


def _pairwise_concordance(scores: np.ndarray, labels: np.ndarray, mask: np.ndarray) -> float | None:
    values: list[float] = []
    for row_scores, row_labels, row_mask in zip(scores, labels, mask):
        valid_scores = row_scores[row_mask]
        valid_labels = row_labels[row_mask]
        positive = valid_scores[valid_labels > 0]
        negative = valid_scores[valid_labels <= 0]
        if positive.size and negative.size:
            values.append(float((positive[:, None] > negative[None, :]).mean()))
    return None if not values else float(np.mean(values))


def _query_macro(scores: np.ndarray, labels: np.ndarray, mask: np.ndarray, queries: np.ndarray) -> float | None:
    query_array = np.asarray(queries)
    if query_array.ndim != 1 or query_array.shape[0] != labels.shape[0]:
        return None
    values: list[float] = []
    for query in np.unique(query_array):
        rows = np.flatnonzero(query_array == query)
        query_scores = _flatten_valid(scores[rows], mask[rows])
        query_labels = _flatten_valid(labels[rows], mask[rows])
        metric = _safe_ap(query_labels, query_scores)
        if metric is not None:
            values.append(metric)
    return None if not values else float(np.mean(values))


def _boundary_scores(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    values = np.asarray(values, dtype=np.float64)
    previous = np.concatenate([values[:, :1], values[:, :-1]], axis=1)
    following = np.concatenate([values[:, 1:], values[:, -1:]], axis=1)
    return np.linalg.norm(values - previous, axis=-1), np.linalg.norm(values - following, axis=-1)


def _boundary_targets(boundaries: Mapping[str, np.ndarray], task_segments: int) -> tuple[np.ndarray, np.ndarray]:
    mask = np.asarray(boundaries["mask"]).astype(bool)
    onset_target = np.zeros(mask.shape, dtype=np.int64)
    offset_target = np.zeros(mask.shape, dtype=np.int64)
    for index, value in enumerate(np.asarray(boundaries["onset"])):
        if int(value) >= 0:
            onset_target[index, int(value)] = 1
    for index, value in enumerate(np.asarray(boundaries["offset"])):
        if int(value) >= 0:
            offset_target[index, int(value)] = 1
    if mask.shape[1] != task_segments:
        raise ValueError("boundary target shape does not match task_segments")
    return onset_target, offset_target


def _representation_metrics(
    values: np.ndarray,
    labels: np.ndarray,
    boundaries: Mapping[str, np.ndarray],
    queries: np.ndarray,
) -> dict[str, Any]:
    mask = np.asarray(boundaries["mask"]).astype(bool)
    if values.ndim != 3 or values.shape[:2] != labels.shape or values.shape[:2] != mask.shape:
        raise ValueError("representations must have shape [B,T,D] matching labels/mask")
    scores = np.linalg.norm(values.astype(np.float64), axis=-1)
    flat_labels = _flatten_valid(labels, mask)
    flat_scores = _flatten_valid(scores, mask)
    onset_scores, offset_scores = _boundary_scores(values)
    onset_target, offset_target = _boundary_targets(boundaries, labels.shape[1])
    return {
        "shape": list(values.shape),
        "sample_count": int(values.shape[0]),
        "valid_segments": int(mask.sum()),
        "ap": _safe_ap(flat_labels, flat_scores),
        "auroc": _safe_auroc(flat_labels, flat_scores),
        "per_query_macro_ap": _query_macro(scores, labels, mask, queries),
        "positive_negative_concordance": _pairwise_concordance(scores, labels, mask),
        "onset_auroc": _safe_auroc(_flatten_valid(onset_target, mask), _flatten_valid(onset_scores, mask)),
        "offset_auroc": _safe_auroc(_flatten_valid(offset_target, mask), _flatten_valid(offset_scores, mask)),
    }


def evaluate_representations(
    representations: Mapping[str, np.ndarray],
    labels: np.ndarray,
    boundaries: Mapping[str, np.ndarray],
    queries: np.ndarray,
    offsets: np.ndarray | None,
) -> dict[str, Any]:
    """Evaluate raw/centered teacher representations and optional query concat."""

    labels_array = np.asarray(labels)
    mask = np.asarray(boundaries["mask"]).astype(bool)
    if labels_array.ndim != 2 or mask.shape != labels_array.shape:
        raise ValueError("labels and boundary mask must have identical [B,T] shapes")
    if labels_array.shape[1] != 10:
        raise ValueError("teacher alignment audit requires official T=10 labels")
    if offsets is not None:
        offset_array = np.asarray(offsets)
        if offset_array.ndim != 1 or offset_array.size != labels_array.shape[0] + 1:
            raise ValueError("offsets must have length B+1")
        if offset_array[0] != 0 or np.any(np.diff(offset_array) < 0) or int(offset_array[-1]) != int(mask.sum()):
            raise ValueError("offsets are not monotone or do not match valid rows")
    query_array = np.asarray(queries)
    if query_array.shape[0] != labels_array.shape[0]:
        raise ValueError("queries must have one row per sample")
    result: dict[str, Any] = {
        "schema_version": 1,
        "status": "NORM_HEURISTIC_ONLY",
        "scientific_status": "QUERY_ALIGNMENT_NOT_TESTED",
        "score_warning": "feature L2 norm is descriptive only; no learned probe is fit",
        "task_segments": 10,
        "representations": {},
        "query_concat_available": bool(query_array.ndim == 2 and np.issubdtype(query_array.dtype, np.number)),
    }
    for name, representation in representations.items():
        values = np.asarray(representation)
        metrics = _representation_metrics(values, labels_array, boundaries, query_array)
        result["representations"][name] = metrics
        centered = values.astype(np.float64) - values.astype(np.float64).mean(axis=1, keepdims=True)
        result["representations"][f"centered_{name}"] = _representation_metrics(
            centered, labels_array, boundaries, query_array
        )
        if result["query_concat_available"]:
            query_numeric = query_array.astype(np.float64)
            augmented = np.concatenate([values.astype(np.float64), np.broadcast_to(query_numeric[:, None, :], (values.shape[0], values.shape[1], query_numeric.shape[1]))], axis=-1)
            result["representations"][f"{name}+query"] = _representation_metrics(
                augmented, labels_array, boundaries, query_array
            )
            result["representations"][f"centered_{name}+query"] = _representation_metrics(
                np.concatenate([centered, np.broadcast_to(query_numeric[:, None, :], (values.shape[0], values.shape[1], query_numeric.shape[1]))], axis=-1),
                labels_array,
                boundaries,
                query_array,
            )
    return result


def _record_path(record: Mapping[str, Any], field: str, project_root: Path | None) -> Path:
    value = Path(str(record[field]))
    if not value.is_absolute() and project_root is not None:
        value = project_root / value
    return value


def _load_manifest_arrays(
    manifest: str | Path,
    *,
    project_root: str | Path | None = None,
    workers: int = 1,
) -> dict[str, Any]:
    """Load complete official train/validation arrays without model state."""

    from concurrent.futures import ThreadPoolExecutor

    manifest_path = Path(manifest)
    root = Path(project_root) if project_root is not None else None
    records = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not records:
        raise ValueError(f"manifest is empty: {manifest_path}")

    def load(record: Mapping[str, Any]) -> dict[str, Any]:
        sample_id = str(record.get("id", ""))
        labels = np.asarray(record.get("segment_labels"), dtype=np.int64)
        if labels.shape != (10,) or not np.isin(labels, (0, 1)).all():
            raise ValueError(f"{sample_id}: expected binary labels [10]")
        feature_path = _record_path(record, "strong_teacher_features_path", root)
        logit_path = _record_path(record, "strong_teacher_logits_path", root)
        query_path = _record_path(record, "text_embedding_path", root)
        features = np.asarray(np.load(feature_path, allow_pickle=False), dtype=np.float32)
        logits = np.asarray(np.load(logit_path, allow_pickle=False), dtype=np.float32).reshape(-1)
        query = np.asarray(np.load(query_path, allow_pickle=False), dtype=np.float32).reshape(-1)
        if features.shape != (10, 512) or logits.shape != (10,) or query.ndim != 1:
            raise ValueError(f"{sample_id}: unexpected teacher/query shapes")
        if not (np.isfinite(features).all() and np.isfinite(logits).all() and np.isfinite(query).all()):
            raise ValueError(f"{sample_id}: teacher/query arrays contain NaN/Inf")
        return {
            "id": sample_id,
            "query_id": str(record.get("query", "")),
            "features": features,
            "logits": logits,
            "query": query,
            "labels": labels,
        }

    if int(workers) > 1:
        with ThreadPoolExecutor(max_workers=int(workers)) as executor:
            rows = list(executor.map(load, records))
    else:
        rows = [load(record) for record in records]
    labels = np.stack([row["labels"] for row in rows])
    return {
        "manifest": str(manifest_path.resolve()),
        "ids": np.asarray([row["id"] for row in rows], dtype=str),
        "query_ids": np.asarray([row["query_id"] for row in rows], dtype=str),
        "queries": np.stack([row["query"] for row in rows]).astype(np.float32),
        "features": np.stack([row["features"] for row in rows]).astype(np.float32),
        "logits": np.stack([row["logits"] for row in rows]).astype(np.float32),
        "labels": labels,
        "mask": np.ones_like(labels, dtype=bool),
        "records": records,
        "sample_offsets": np.arange(0, labels.shape[0] * 10 + 1, 10, dtype=np.int64),
        "counts": {
            "samples": int(labels.shape[0]),
            "segments": int(labels.size),
            "k0": int((labels.sum(axis=1) == 0).sum()),
            "kmid": int(((labels.sum(axis=1) > 0) & (labels.sum(axis=1) < 10)).sum()),
            "k10": int((labels.sum(axis=1) == 10).sum()),
            "positive_rate": float(labels.mean()),
        },
    }


def _center_per_sample(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=np.float32)
    return array - array.mean(axis=1, keepdims=True)


def _transition_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    windows = np.asarray(value["positive_window_count"], dtype=np.int64)
    transition_indices = value["transition_indices"]
    onset_indices = value["onset_indices"]
    offset_indices = value["offset_indices"]
    return {
        "samples": int(windows.size),
        "samples_with_positive": int((windows > 0).sum()),
        "samples_multi_window": int((windows > 1).sum()),
        "single_window_continuous": bool(value["single_window_continuous"]),
        "total_transitions": int(sum(len(row) for row in transition_indices.tolist())),
        "total_onsets": int(sum(len(row) for row in onset_indices.tolist())),
        "total_offsets": int(sum(len(row) for row in offset_indices.tolist())),
        "positive_window_histogram": {
            str(int(key)): int(count)
            for key, count in zip(*np.unique(windows, return_counts=True))
        },
    }


def _load_static_projected(features: np.ndarray, checkpoint: str | Path) -> tuple[np.ndarray, dict[str, Any]]:
    import torch
    from src.models.ov_orthkd import ProjectionHead

    path = Path(checkpoint)
    payload = torch.load(path, map_location="cpu", weights_only=True)
    state = payload.get("loss_state_dict") if isinstance(payload, Mapping) else None
    if not isinstance(state, Mapping):
        raise ValueError(f"{path}: checkpoint has no loss_state_dict")
    prefix = "strong_teacher_proj."
    projector_state = {key[len(prefix):]: value for key, value in state.items() if key.startswith(prefix)}
    if not projector_state:
        raise ValueError(f"{path}: strong_teacher_proj state is missing")
    projector = ProjectionHead(512, 256)
    projector.load_state_dict(projector_state, strict=True)
    projector.eval()
    with torch.inference_mode():
        flat = torch.from_numpy(np.asarray(features, dtype=np.float32).reshape(-1, 512))
        projected = projector(flat).numpy().reshape(features.shape[0], features.shape[1], 256)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return projected.astype(np.float32), {"path": str(path), "sha256": digest, "shape": list(projected.shape)}


def _probe_result(
    train_values: np.ndarray,
    val_values: np.ndarray,
    train: Mapping[str, Any],
    validation: Mapping[str, Any],
    *,
    name: str,
    seed: int,
    shuffle_repeats: int,
) -> dict[str, Any]:
    result = fit_probe_and_score(
        train_values,
        train["labels"],
        val_values,
        validation["labels"],
        validation["mask"],
        sample_ids=validation["ids"],
        query_ids=validation["query_ids"],
        offsets=validation["sample_offsets"],
        seed=seed,
        shuffle_repeats=shuffle_repeats,
    )
    result["name"] = name
    return result


def audit_train_fit(
    train_manifest: str | Path,
    validation_manifest: str | Path,
    *,
    initial_projector_checkpoint: str | Path,
    project_root: str | Path | None = None,
    workers: int = 1,
    seed: int = 42,
    shuffle_repeats: int = 100,
    common_dim: int = 128,
) -> dict[str, Any]:
    """Run the corrected train-fit/validation-eval teacher signal audit."""

    train = _load_manifest_arrays(train_manifest, project_root=project_root, workers=workers)
    validation = _load_manifest_arrays(validation_manifest, project_root=project_root, workers=workers)
    train_ids = [str(value) for value in np.asarray(train["ids"]).tolist()]
    validation_ids = [str(value) for value in np.asarray(validation["ids"]).tolist()]
    if len(set(train_ids)) != len(train_ids) or len(set(validation_ids)) != len(validation_ids):
        raise ValueError("train and validation manifests must not contain duplicate sample IDs")
    overlap = sorted(set(train_ids).intersection(validation_ids))
    if overlap:
        raise ValueError(f"train/validation sample ID overlap detected: {overlap[:5]}")
    train_features = train["features"]
    val_features = validation["features"]
    train_queries = np.broadcast_to(train["queries"][:, None, :], (train["labels"].shape[0], 10, train["queries"].shape[1])).copy()
    val_queries = np.broadcast_to(validation["queries"][:, None, :], (validation["labels"].shape[0], 10, validation["queries"].shape[1])).copy()
    train_projected, projector_receipt = _load_static_projected(train_features, initial_projector_checkpoint)
    val_projected, _ = _load_static_projected(val_features, initial_projector_checkpoint)

    probes: dict[str, Any] = {}
    for name, train_values, val_values in (
        ("raw_teacher", train_features, val_features),
        ("centered_raw_teacher", _center_per_sample(train_features), _center_per_sample(val_features)),
        ("static_projected_initial", train_projected, val_projected),
        ("centered_static_projected_initial", _center_per_sample(train_projected), _center_per_sample(val_projected)),
        ("cached_visual_direct_logits", train["logits"][..., None], validation["logits"][..., None]),
    ):
        probes[name] = _probe_result(
            train_values, val_values, train, validation, name=name, seed=seed, shuffle_repeats=shuffle_repeats
        )

    train_zero_visual = np.zeros((train_features.shape[0], 10, 1), dtype=np.float32)
    val_zero_visual = np.zeros((val_features.shape[0], 10, 1), dtype=np.float32)
    _, query_common_train, common_receipt = build_common_space(
        train_zero_visual, train_queries, output_dim=common_dim, seed=seed
    )
    _, query_common_val, _ = build_common_space(
        val_zero_visual, val_queries, output_dim=common_dim, seed=seed
    )
    train_qp_visual = np.zeros_like(query_common_train)
    val_qp_visual = np.zeros_like(query_common_val)
    probes["qp"] = _probe_result(
        build_interaction_design(train_qp_visual, query_common_train, mode="qp"),
        build_interaction_design(val_qp_visual, query_common_val, mode="qp"),
        train,
        validation,
        name="qp",
        seed=seed,
        shuffle_repeats=shuffle_repeats,
    )

    for name, train_values, val_values, map_seed in (
        ("raw_teacher_query_interaction", train_features, val_features, seed),
        ("static_projected_initial_query_interaction", train_projected, val_projected, seed + 11),
    ):
        train_common, train_query, mapping_receipt = build_common_space(
            train_values, train_queries, output_dim=common_dim, seed=map_seed
        )
        val_common, val_query, _ = build_common_space(
            val_values, val_queries, output_dim=common_dim, seed=map_seed
        )
        probes[name] = _probe_result(
            build_interaction_design(train_common, train_query, mode="interaction"),
            build_interaction_design(val_common, val_query, mode="interaction"),
            train,
            validation,
            name=name,
            seed=seed,
            shuffle_repeats=shuffle_repeats,
        )
        probes[name]["common_space"] = mapping_receipt

    transitions = {
        "train": _transition_summary(derive_all_transitions(train["labels"], train["mask"])),
        "validation": _transition_summary(derive_all_transitions(validation["labels"], validation["mask"])),
    }
    direct_shift = direct_logit_shift_sweep(
        validation["logits"], validation["labels"], validation["mask"], shifts=(-2, -1, 0, 1, 2)
    )
    direct_mixed = probes["cached_visual_direct_logits"]["metrics"]["mixed"]
    direct_shuffle = probes["cached_visual_direct_logits"]["metrics"]["shuffle"]
    qp_mixed = probes["qp"]["metrics"]["mixed"]
    vqp_mixed = probes["raw_teacher_query_interaction"]["metrics"]["mixed"]
    teacher_gate = {
        "direct_mixed_concordance_ge_0.60": bool(_metric_or_missing(direct_mixed["pair_weighted_concordance"]) >= 0.60),
        "direct_shuffle_drop_ge_0.02": bool(
            max(_metric_or_missing(direct_shuffle["shuffle_ap_drop"]), _metric_or_missing(direct_shuffle["shuffle_auroc_drop"])) >= 0.02
        ),
        "teacher_query_delta_c_ge_0.02": bool(
            _metric_or_missing(vqp_mixed["pair_weighted_concordance"]) - _metric_or_missing(qp_mixed["pair_weighted_concordance"]) >= 0.02
        ),
        "teacher_query_delta_ap_or_auroc_ge_0.01": bool(
            max(
                _metric_or_missing(vqp_mixed["ap"]) - _metric_or_missing(probes["qp"]["metrics"]["mixed"]["ap"]),
                _metric_or_missing(vqp_mixed["auroc"]) - _metric_or_missing(probes["qp"]["metrics"]["mixed"]["auroc"]),
            ) >= 0.01
        ),
    }
    teacher_healthy = all(teacher_gate.values()) and direct_shift["status"] == "PASS"
    return {
        "schema_version": 2,
        "status": "PASS",
        "scientific_status": "TEACHER_BOUNDARY_SIGNAL_HEALTHY" if teacher_healthy else "BLOCKED_BY_TEACHER_LABEL_ALIGNMENT",
        "claim_level": "train_fit_validation_eval_teacher_signal_probe",
        "protocol": {
            "task_segments": 10,
            "temporal_conversion": "forbidden",
            "train_fit_split": str(Path(train_manifest).resolve()),
            "validation_eval_split": str(Path(validation_manifest).resolve()),
            "probe_model": "StandardScaler + SGDClassifier(log_loss, l2, average=True)",
            "common_space_dim": int(common_dim),
            "query_conditioning": "[v,q,v*q,position] with fixed label-independent maps",
            "shuffle_repeats": int(shuffle_repeats),
            "seed": int(seed),
            "optimizer_constructed": False,
            "checkpoint_written": False,
        },
        "data": {"train": train["counts"], "validation": validation["counts"]},
        "query_fields": {
            "query_id_field": "manifest.query",
            "query_embedding_field": "manifest.text_embedding_path",
            "train_unique_query_ids": int(np.unique(train["query_ids"]).size),
            "validation_unique_query_ids": int(np.unique(validation["query_ids"]).size),
            "raw_video_hashes": {"available": False, "reason": "official manifest has no raw-video hash field"},
        },
        "projector": projector_receipt,
        "common_space": common_receipt,
        "probes": probes,
        "transitions": transitions,
        "direct_logit_shift_sweep": direct_shift,
        "teacher_gate": teacher_gate,
        "teacher_gate_pass": bool(teacher_healthy),
    }


def raw_video_query_multiplicity(raw_video_hashes: np.ndarray, queries: np.ndarray) -> dict[str, Any]:
    hashes = np.asarray(raw_video_hashes).astype(str)
    query_array = np.asarray(queries).astype(str)
    if hashes.shape != query_array.shape:
        raise ValueError("raw_video_hashes and queries must have equal shape")
    pairs = {f"{video}:{query}" for video, query in zip(hashes, query_array)}
    videos = {video for video in hashes}
    return {
        "samples": int(hashes.size),
        "unique_raw_video_hashes": int(len(videos)),
        "unique_video_query_pairs": int(len(pairs)),
        "query_multiplicity_per_video_max": int(max((sum(video == value for value in hashes) for video in videos), default=0)),
        "raw_video_hash_sha256": hashlib.sha256("\n".join(hashes.tolist()).encode()).hexdigest(),
    }


def audit_manifest(
    manifest: str | Path,
    *,
    project_root: str | Path | None = None,
    projector_checkpoints: Mapping[str, str | Path] | None = None,
    workers: int = 1,
) -> dict[str, Any]:
    """Load official feature/text paths and audit the mixed-label validation rows.

    The manifest supplies the labels and query embeddings; no annotation is
    inferred.  A projector checkpoint is used only to create a static target
    representation, never to update it.
    """

    from concurrent.futures import ThreadPoolExecutor

    root = Path(project_root) if project_root is not None else Path(manifest).resolve().parent
    records = [json.loads(line) for line in Path(manifest).read_text(encoding="utf-8").splitlines() if line.strip()]
    if not records:
        raise ValueError("manifest is empty")

    def load(record: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray, str]:
        labels = np.asarray(record["segment_labels"], dtype=np.int64)
        if labels.shape != (10,):
            raise ValueError(f"{record.get('id', '<unknown>')}: labels must be [10]")
        feature_path = Path(str(record["strong_teacher_features_path"]))
        if not feature_path.is_absolute():
            feature_path = root / feature_path
        features = np.asarray(np.load(feature_path, allow_pickle=False), dtype=np.float32)
        if features.shape != (10, 512) or not np.isfinite(features).all():
            raise ValueError(f"{record.get('id', '<unknown>')}: strong teacher features must be finite [10,512]")
        query_path = Path(str(record["text_embedding_path"]))
        if not query_path.is_absolute():
            query_path = root / query_path
        query = np.asarray(np.load(query_path, allow_pickle=False), dtype=np.float32).reshape(-1)
        if query.ndim != 1 or not np.isfinite(query).all():
            raise ValueError(f"{record.get('id', '<unknown>')}: text embedding must be finite [D]")
        return features, labels, query, str(record.get("id", ""))

    if workers > 1:
        with ThreadPoolExecutor(max_workers=int(workers)) as executor:
            rows = list(executor.map(load, records))
    else:
        rows = [load(record) for record in records]
    features = np.stack([row[0] for row in rows])
    labels = np.stack([row[1] for row in rows])
    queries = np.stack([row[2] for row in rows])
    mixed = (labels.sum(axis=1) > 0) & (labels.sum(axis=1) < 10)
    features, labels, queries = features[mixed], labels[mixed], queries[mixed]
    mask = np.ones(labels.shape, dtype=bool)
    boundaries = derive_boundaries(labels, mask)
    representations: dict[str, np.ndarray] = {"raw": features}
    projector_receipts: dict[str, Any] = {}
    for name, checkpoint in (projector_checkpoints or {}).items():
        import hashlib

        import torch
        from src.models.ov_orthkd import ProjectionHead

        checkpoint_path = Path(checkpoint)
        payload = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
        state = payload.get("loss_state_dict") if isinstance(payload, Mapping) else None
        if not isinstance(state, Mapping):
            raise ValueError(f"{checkpoint_path}: checkpoint has no loss_state_dict")
        projector = ProjectionHead(512, 256)
        prefix = "strong_teacher_proj."
        projector_state = {key[len(prefix):]: value for key, value in state.items() if key.startswith(prefix)}
        if not projector_state:
            raise ValueError(f"{checkpoint_path}: strong_teacher_proj state is missing")
        projector.load_state_dict(projector_state, strict=True)
        projector.eval()
        with torch.no_grad():
            projected = projector(torch.from_numpy(features)).numpy().astype(np.float32)
        representations[f"static_projected_{name}"] = projected
        projector_receipts[name] = {
            "path": str(checkpoint_path),
            "sha256": hashlib.sha256(checkpoint_path.read_bytes()).hexdigest(),
            "shape": list(projected.shape),
        }
    offsets = np.arange(0, labels.shape[0] * 10 + 1, 10, dtype=np.int64)
    result = evaluate_representations(representations, labels, boundaries, queries, offsets)
    result["manifest"] = str(Path(manifest).resolve())
    result["mixed_label_samples"] = int(labels.shape[0])
    result["projector_receipts"] = projector_receipts
    result["raw_video_query_multiplicity"] = {
        "available": False,
        "reason": "official exported manifest does not provide raw_video_hashes; no multiplicity is guessed",
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="NPZ with labels, mask, queries, offsets and representation arrays")
    parser.add_argument("--train-manifest", type=Path, help="Official train manifest for probe fitting")
    parser.add_argument("--validation-manifest", type=Path, help="Official validation manifest for probe evaluation")
    parser.add_argument("--initial-projector-checkpoint", type=Path, help="Static projector checkpoint used as initialization target")
    parser.add_argument("--common-dim", type=int, default=128)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--shuffle-repeats", type=int, default=100)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--manifest", type=Path, help="Official exported manifest; loads raw teacher/text arrays")
    parser.add_argument("--project-root", type=Path, default=None)
    parser.add_argument("--projector-checkpoint", action="append", default=[], metavar="NAME=PATH")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.train_manifest is not None or args.validation_manifest is not None:
        if args.train_manifest is None or args.validation_manifest is None or args.initial_projector_checkpoint is None:
            raise ValueError("train-fit mode requires --train-manifest, --validation-manifest, and --initial-projector-checkpoint")
        payload = audit_train_fit(
            args.train_manifest,
            args.validation_manifest,
            initial_projector_checkpoint=args.initial_projector_checkpoint,
            project_root=args.project_root,
            workers=args.workers,
            seed=args.seed,
            shuffle_repeats=args.shuffle_repeats,
            common_dim=args.common_dim,
        )
    elif args.manifest is not None:
        checkpoints = {}
        for item in args.projector_checkpoint:
            if "=" not in item:
                raise ValueError("--projector-checkpoint expects NAME=PATH")
            name, path = item.split("=", 1)
            checkpoints[name] = path
        payload = audit_manifest(
            args.manifest,
            project_root=args.project_root,
            projector_checkpoints=checkpoints,
            workers=args.workers,
        )
    else:
        if args.input is None or args.projector_checkpoint:
            raise ValueError("--input is required when --manifest is not supplied")
        with np.load(args.input, allow_pickle=False) as loaded:
            labels = loaded["labels"]
            mask = loaded["mask"]
            queries = loaded["queries"]
            offsets = loaded["sample_offsets"] if "sample_offsets" in loaded.files else None
            boundaries = derive_boundaries(labels, mask)
            representations = {
                name: loaded[name]
                for name in loaded.files
                if name not in {"labels", "mask", "queries", "sample_offsets", "raw_video_hashes"}
            }
            payload = evaluate_representations(representations, labels, boundaries, queries, offsets)
            if "raw_video_hashes" in loaded.files:
                payload["raw_video_query_multiplicity"] = raw_video_query_multiplicity(loaded["raw_video_hashes"], queries)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
