"""Read-only fixed-batch root-cause audit for static-target controls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np


def feature_geometry(features: np.ndarray, mask: np.ndarray) -> dict[str, Any]:
    values = np.asarray(features, dtype=np.float64)
    valid = np.asarray(mask).astype(bool)
    if values.ndim != 3 or valid.shape != values.shape[:2]:
        raise ValueError("features must be [B,T,D] and mask must be [B,T]")
    rows = values[valid]
    if rows.size == 0:
        raise ValueError("mask contains no valid rows")
    temporal_stds = []
    centered_rows = []
    for index in range(values.shape[0]):
        sample = values[index, valid[index]]
        if sample.shape[0] == 0:
            continue
        centered = sample - sample.mean(axis=0, keepdims=True)
        centered_rows.append(centered)
        temporal_stds.append(float(sample.std(axis=0).mean()))
    centered_all = np.concatenate(centered_rows, axis=0)
    total_l2 = float(np.linalg.norm(rows, axis=1).mean())
    centered_l2 = float(np.linalg.norm(centered_all, axis=1).mean())
    return {
        "shape": list(values.shape),
        "valid_rows": int(rows.shape[0]),
        "feature_dim": int(values.shape[-1]),
        "rms": float(np.sqrt(np.mean(rows * rows))),
        "within_sample_temporal_std_mean": float(np.mean(temporal_stds)),
        "centered_temporal_variance_mean": float(np.var(centered_all, axis=0).mean()),
        "centered_row_l2_mean": centered_l2,
        "total_row_l2_mean": total_l2,
        "centered_row_l2_to_total_row_l2": centered_l2 / max(total_l2, 1e-12),
    }


def gradient_cosine_matrix(gradients: Mapping[str, np.ndarray]) -> dict[str, dict[str, float | None]]:
    names = list(gradients)
    flat = {name: np.asarray(value, dtype=np.float64).reshape(-1) for name, value in gradients.items()}
    result: dict[str, dict[str, float | None]] = {}
    for left in names:
        result[left] = {}
        for right in names:
            if left == right:
                result[left][right] = 1.0
                continue
            if flat[left].shape != flat[right].shape:
                result[left][right] = None
                continue
            denominator = float(np.linalg.norm(flat[left]) * np.linalg.norm(flat[right]))
            result[left][right] = None if denominator <= 1e-12 else float(np.dot(flat[left], flat[right]) / denominator)
    return result


def _pairwise_distance_correlation(source: np.ndarray, target: np.ndarray, mask: np.ndarray) -> float | None:
    values = []
    for index in range(source.shape[0]):
        valid = np.asarray(mask[index]).astype(bool)
        left, right = source[index, valid], target[index, valid]
        if left.shape[0] < 3:
            continue
        left_distance = np.linalg.norm(left[:, None, :] - left[None, :, :], axis=-1)
        right_distance = np.linalg.norm(right[:, None, :] - right[None, :, :], axis=-1)
        upper = np.triu_indices(left.shape[0], 1)
        x, y = left_distance[upper], right_distance[upper]
        if np.std(x) <= 1e-12 or np.std(y) <= 1e-12:
            continue
        values.append(float(np.corrcoef(x, y)[0, 1]))
    return None if not values else float(np.mean(values))


def audit_arrays(data: Mapping[str, np.ndarray]) -> dict[str, Any]:
    required = {"raw_teacher", "projected_target", "decision", "logits", "labels", "mask"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"missing arrays: {sorted(missing)}")
    mask = np.asarray(data["mask"])
    labels = np.asarray(data["labels"])
    logits = np.asarray(data["logits"])
    if labels.shape != mask.shape or logits.shape != mask.shape or mask.shape[1] != 10:
        raise ValueError("root-cause audit requires official [B,10] labels/logits/mask")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "task_segments": 10,
        "geometry": {
            name: feature_geometry(np.asarray(data[name]), mask)
            for name in ("raw_teacher", "projected_target", "decision")
        },
        "projected_to_decision_distance_correlation": _pairwise_distance_correlation(
            np.asarray(data["projected_target"]), np.asarray(data["decision"]), mask
        ),
        "test_evaluation": False,
    }
    return payload


def render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Static-Target Root-Cause Audit",
        "",
        "Read-only audit; official task timeline is fixed at T=10 and test evaluation is disabled.",
        "",
        f"- Task segments: `{payload['task_segments']}`",
        f"- Projected-target to decision distance correlation: `{payload.get('projected_to_decision_distance_correlation')}`",
        "",
        "| Representation | Temporal std | Centered/total row L2 |",
        "|---|---:|---:|",
    ]
    for name, geometry in payload["geometry"].items():
        lines.append(f"| `{name}` | {geometry['within_sample_temporal_std_mean']:.8g} | {geometry['centered_row_l2_to_total_row_l2']:.8g} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()
    with np.load(args.input, allow_pickle=False) as loaded:
        payload = audit_arrays({name: loaded[name] for name in loaded.files})
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.output_md.write_text(render_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
