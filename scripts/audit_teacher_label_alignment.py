"""Read-only teacher/label boundary-alignment diagnostics for official T=10 data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score


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
    parser.add_argument("--manifest", type=Path, help="Official exported manifest; loads raw teacher/text arrays")
    parser.add_argument("--project-root", type=Path, default=None)
    parser.add_argument("--projector-checkpoint", action="append", default=[], metavar="NAME=PATH")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.manifest is not None:
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
