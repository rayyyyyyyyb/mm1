#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import torch
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.diagnose_formal_predictions import (  # noqa: E402
    audit_prediction_payload,
)
from src.utils.temporal_protocol import (  # noqa: E402
    task_segments_from_config,
    validate_temporal_alignment,
)


ABLATION_MODES = ("original", "visual_zero", "audio_zero", "both_zero")
REQUIRED_PATHS = (
    "query_features",
    "visual_tokens",
    "audio_tokens",
    "fused_tokens_before_position",
    "shared_features",
    "decision_features",
    "segment_logits",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_receipt(path: Path) -> dict[str, Any]:
    source = path.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    return {
        "path": str(source),
        "bytes": source.stat().st_size,
        "sha256": _sha256(source),
    }


def apply_content_ablation(
    batch: Mapping[str, Any], mode: str
) -> dict[str, Any]:
    if mode not in ABLATION_MODES:
        raise ValueError(f"Unsupported ablation mode: {mode}")
    result = dict(batch)
    for name in ("frame", "spectrogram", "frame_valid", "audio_valid", "sequence_mask"):
        if name not in batch or not isinstance(batch[name], torch.Tensor):
            raise KeyError(f"Batch is missing tensor field: {name}")
    if mode in {"visual_zero", "both_zero"}:
        result["frame"] = torch.zeros_like(batch["frame"])
    if mode in {"audio_zero", "both_zero"}:
        result["spectrogram"] = torch.zeros_like(batch["spectrogram"])
    return result


def _tensor_scale_components(
    tensor: torch.Tensor, sequence_mask: torch.Tensor
) -> dict[str, Any]:
    if not isinstance(tensor, torch.Tensor):
        raise TypeError("Path output must be a tensor")
    mask = sequence_mask.detach().to(device=tensor.device).bool()
    if mask.ndim != 2:
        raise ValueError("sequence_mask must have shape [B,T]")
    if tensor.ndim == 2:
        values = tensor.unsqueeze(-1)
    elif tensor.ndim >= 3:
        values = tensor.reshape(tensor.shape[0], tensor.shape[1], -1)
    else:
        raise ValueError("Path tensor must have leading [B,T] dimensions")
    if tuple(values.shape[:2]) != tuple(mask.shape):
        raise ValueError(
            f"Path tensor leading shape {tuple(values.shape[:2])} does not match "
            f"sequence mask {tuple(mask.shape)}"
        )
    if not bool(torch.isfinite(values).all()):
        raise ValueError("Path tensor contains NaN/Inf")
    valid_rows = values[mask]
    if valid_rows.numel() == 0:
        raise ValueError("Path tensor has no valid rows")
    valid_rows = valid_rows.to(dtype=torch.float64)
    temporal_std_sum = 0.0
    temporal_sample_count = 0
    for sample_index in range(values.shape[0]):
        sample = values[sample_index, mask[sample_index]].to(dtype=torch.float64)
        if sample.shape[0] == 0:
            continue
        temporal_std_sum += float(sample.std(dim=0, unbiased=False).mean().item())
        temporal_sample_count += 1
    return {
        "shape": list(tensor.shape),
        "valid_rows": int(valid_rows.shape[0]),
        "feature_dim": int(valid_rows.shape[1]),
        "value_count": int(valid_rows.numel()),
        "absolute_sum": float(valid_rows.abs().sum().item()),
        "square_sum": float(valid_rows.square().sum().item()),
        "row_l2_sum": float(torch.linalg.vector_norm(valid_rows, dim=-1).sum().item()),
        "temporal_std_sum": temporal_std_sum,
        "temporal_sample_count": temporal_sample_count,
    }


def _finalize_scale_components(components: Mapping[str, Any]) -> dict[str, Any]:
    rows = int(components["valid_rows"])
    values = int(components["value_count"])
    samples = int(components["temporal_sample_count"])
    if rows <= 0 or values <= 0 or samples <= 0:
        raise ValueError("Scale components are empty")
    return {
        "valid_rows": rows,
        "feature_dim": int(components["feature_dim"]),
        "absolute_mean": float(components["absolute_sum"]) / values,
        "rms": float(np.sqrt(float(components["square_sum"]) / values)),
        "row_l2_mean": float(components["row_l2_sum"]) / rows,
        "within_sample_temporal_std_mean": float(components["temporal_std_sum"])
        / samples,
        "temporal_sample_count": samples,
    }


def summarize_tensor_scale(
    tensor: torch.Tensor, sequence_mask: torch.Tensor
) -> dict[str, Any]:
    components = _tensor_scale_components(tensor, sequence_mask)
    return {
        "shape": components["shape"],
        **_finalize_scale_components(components),
    }


def summarize_model_paths(
    outputs: Mapping[str, Any], sequence_mask: torch.Tensor
) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    for name in REQUIRED_PATHS:
        tensor = outputs.get(name)
        if tensor is None:
            raise RuntimeError(f"Student output is missing required diagnostic path: {name}")
        try:
            summaries[name] = summarize_tensor_scale(tensor, sequence_mask)
        except (TypeError, ValueError) as exc:
            raise type(exc)(f"Invalid diagnostic path {name}: {exc}") from exc
    return summaries


class _ScaleAccumulator:
    def __init__(self) -> None:
        self.valid_rows = 0
        self.feature_dim: int | None = None
        self.value_count = 0
        self.absolute_sum = 0.0
        self.square_sum = 0.0
        self.row_l2_sum = 0.0
        self.temporal_std_sum = 0.0
        self.temporal_sample_count = 0
        self.shapes: Counter[str] = Counter()

    def update(self, tensor: torch.Tensor, sequence_mask: torch.Tensor) -> None:
        values = _tensor_scale_components(tensor, sequence_mask)
        feature_dim = int(values["feature_dim"])
        if self.feature_dim is not None and feature_dim != self.feature_dim:
            raise ValueError(
                f"Path feature dimension changed: {self.feature_dim} -> {feature_dim}"
            )
        self.feature_dim = feature_dim
        self.valid_rows += int(values["valid_rows"])
        self.value_count += int(values["value_count"])
        self.absolute_sum += float(values["absolute_sum"])
        self.square_sum += float(values["square_sum"])
        self.row_l2_sum += float(values["row_l2_sum"])
        self.temporal_std_sum += float(values["temporal_std_sum"])
        self.temporal_sample_count += int(values["temporal_sample_count"])
        self.shapes["x".join(str(value) for value in values["shape"])] += 1

    def finalize(self) -> dict[str, Any]:
        return {
            "observed_batch_shapes": dict(sorted(self.shapes.items())),
            **_finalize_scale_components(
                {
                    "valid_rows": self.valid_rows,
                    "feature_dim": self.feature_dim,
                    "value_count": self.value_count,
                    "absolute_sum": self.absolute_sum,
                    "square_sum": self.square_sum,
                    "row_l2_sum": self.row_l2_sum,
                    "temporal_std_sum": self.temporal_std_sum,
                    "temporal_sample_count": self.temporal_sample_count,
                }
            ),
        }


def _batch_metadata(batch: Mapping[str, Any], batch_size: int) -> dict[str, list[str]]:
    ids = [str(value) for value in batch.get("id", [])]
    queries = [str(value) for value in batch.get("query", [])]
    split_types = [str(value).strip().lower() for value in batch.get("split_type", [])]
    if (
        len(ids) != batch_size
        or len(queries) != batch_size
        or len(split_types) != batch_size
    ):
        raise ValueError("Batch ids/queries/split_types must contain one value per sample")
    split_types = [value if value in {"seen", "unseen"} else "unknown" for value in split_types]
    return {
        "ids": ids,
        "queries": queries,
        "split_types": split_types,
    }


def _validate_task_prediction_payload(
    predictions: Mapping[str, np.ndarray], expected_segments: int
) -> None:
    sample_count = int(np.asarray(predictions["ids"]).size)
    offsets = np.asarray(predictions["sample_offsets"], dtype=np.int64).reshape(-1)
    if offsets.size != sample_count + 1 or offsets[0] != 0:
        raise ValueError("Prediction sample_offsets are malformed")
    counts = np.diff(offsets)
    if np.any(counts != int(expected_segments)):
        raise ValueError(
            f"Expected exactly {expected_segments} metric segments per sample, got {counts.tolist()}"
        )
    total = int(offsets[-1])
    for name in ("segment_indices", "labels", "logits", "probabilities"):
        values = np.asarray(predictions[name]).reshape(-1)
        if values.size != total:
            raise ValueError(f"Prediction field {name} does not match sample_offsets")
        if name in {"logits", "probabilities"} and not np.isfinite(values).all():
            raise ValueError(f"Prediction field {name} contains NaN/Inf")
    labels = np.asarray(predictions["labels"], dtype=np.float64)
    if not np.isin(labels, (0.0, 1.0)).all():
        raise ValueError("Prediction labels must be binary")
    official_indices = np.arange(int(expected_segments), dtype=np.int64)
    segment_indices = np.asarray(predictions["segment_indices"], dtype=np.int64)
    for start, end in zip(offsets[:-1], offsets[1:]):
        if not np.array_equal(segment_indices[int(start) : int(end)], official_indices):
            raise ValueError("Prediction segment indices do not preserve official order")


@torch.no_grad()
def _collect_ablation_modes(
    student: torch.nn.Module,
    loader: Iterable[Mapping[str, Any]],
    device: torch.device,
    *,
    modes: Sequence[str],
    expected_task_segments: int,
    path_modes: set[str],
    max_batches: int | None = None,
) -> tuple[dict[str, dict[str, np.ndarray]], dict[str, dict[str, Any]]]:
    selected_modes = tuple(modes)
    if not selected_modes or len(set(selected_modes)) != len(selected_modes):
        raise ValueError("Ablation modes must be non-empty and unique")
    unknown = sorted(set(selected_modes).difference(ABLATION_MODES))
    if unknown:
        raise ValueError(f"Unsupported ablation modes: {unknown}")
    if not path_modes.issubset(set(selected_modes)):
        raise ValueError("path_modes must be a subset of evaluated modes")
    student.eval()
    common: dict[str, list[Any]] = {
        "ids": [],
        "queries": [],
        "split_types": [],
        "segment_indices": [],
        "labels": [],
    }
    sample_offsets = [0]
    logits_by_mode: dict[str, list[float]] = {mode: [] for mode in selected_modes}
    scale_accumulators: dict[str, dict[str, _ScaleAccumulator]] = {
        mode: {name: _ScaleAccumulator() for name in REQUIRED_PATHS}
        for mode in path_modes
    }

    for batch_index, batch in enumerate(loader):
        if max_batches is not None and batch_index >= max_batches:
            break
        labels = batch["segment_label"].detach().cpu()
        mask = batch["sequence_mask"].detach().cpu().bool()
        if labels.ndim != 2 or mask.shape != labels.shape:
            raise ValueError("Batch labels and sequence_mask must share shape [B,T]")
        metadata = _batch_metadata(batch, int(labels.shape[0]))
        common["ids"].extend(metadata["ids"])
        common["queries"].extend(metadata["queries"])
        common["split_types"].extend(metadata["split_types"])

        reference_valid_indices: list[list[int]] = []
        for sample_index in range(labels.shape[0]):
            valid_indices = torch.nonzero(mask[sample_index], as_tuple=False).view(-1)
            indices = [int(value) for value in valid_indices.tolist()]
            reference_valid_indices.append(indices)
            common["segment_indices"].extend(indices)
            common["labels"].extend(
                float(value) for value in labels[sample_index, valid_indices].tolist()
            )
            sample_offsets.append(sample_offsets[-1] + len(indices))

        for mode in selected_modes:
            ablated = apply_content_ablation(batch, mode)
            outputs = student(
                frame=ablated["frame"].to(device),
                spectrogram=ablated["spectrogram"].to(device),
                text_embedding=ablated["text_embedding"].to(device),
                sequence_mask=ablated["sequence_mask"].to(device),
                frame_valid=ablated["frame_valid"].to(device),
                audio_valid=ablated["audio_valid"].to(device),
            )
            batch_logits = outputs.get("segment_logits")
            if not isinstance(batch_logits, torch.Tensor):
                raise RuntimeError("Student did not return tensor segment_logits")
            batch_logits = batch_logits.detach().cpu()
            validate_temporal_alignment(
                student_logits=batch_logits,
                labels=labels,
                sequence_mask=mask,
                task_segments=int(expected_task_segments),
            )
            if not bool(torch.isfinite(batch_logits).all()):
                raise ValueError(f"{mode} logits contain NaN/Inf")
            for sample_index, indices in enumerate(reference_valid_indices):
                logits_by_mode[mode].extend(
                    float(batch_logits[sample_index, index]) for index in indices
                )
            if mode in path_modes:
                summaries = summarize_model_paths(outputs, ablated["sequence_mask"])
                if set(summaries) != set(REQUIRED_PATHS):
                    raise RuntimeError("Path validation did not cover every required output")
                for name in REQUIRED_PATHS:
                    scale_accumulators[mode][name].update(
                        outputs[name], ablated["sequence_mask"]
                    )

    if len(sample_offsets) == 1:
        raise RuntimeError("No evaluation samples were collected")
    base = {
        "ids": np.asarray(common["ids"], dtype=str),
        "queries": np.asarray(common["queries"], dtype=str),
        "split_types": np.asarray(common["split_types"], dtype=str),
        "sample_offsets": np.asarray(sample_offsets, dtype=np.int64),
        "segment_indices": np.asarray(common["segment_indices"], dtype=np.int64),
        "labels": np.asarray(common["labels"], dtype=np.float64),
    }
    predictions_by_mode: dict[str, dict[str, np.ndarray]] = {}
    for mode in selected_modes:
        logits = np.asarray(logits_by_mode[mode], dtype=np.float64)
        predictions = {
            **base,
            "logits": logits,
            "probabilities": 1.0 / (1.0 + np.exp(-logits)),
        }
        _validate_task_prediction_payload(predictions, int(expected_task_segments))
        predictions_by_mode[mode] = predictions
    path_summaries = {
        mode: {
            name: accumulator.finalize()
            for name, accumulator in scale_accumulators[mode].items()
        }
        for mode in path_modes
    }
    return predictions_by_mode, path_summaries


def collect_ablation_predictions(
    student: torch.nn.Module,
    loader: Iterable[Mapping[str, Any]],
    device: torch.device,
    *,
    mode: str,
    expected_task_segments: int,
    collect_paths: bool,
    max_batches: int | None = None,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    predictions, paths = _collect_ablation_modes(
        student,
        loader,
        device,
        modes=(mode,),
        expected_task_segments=expected_task_segments,
        path_modes={mode} if collect_paths else set(),
        max_batches=max_batches,
    )
    return predictions[mode], paths.get(mode, {})


@torch.no_grad()
def collect_ablation_matrix(
    student: torch.nn.Module,
    loader: Iterable[Mapping[str, Any]],
    device: torch.device,
    *,
    expected_task_segments: int,
    max_batches: int | None = None,
) -> tuple[dict[str, dict[str, np.ndarray]], dict[str, Any]]:
    predictions, paths = _collect_ablation_modes(
        student,
        loader,
        device,
        modes=ABLATION_MODES,
        expected_task_segments=expected_task_segments,
        path_modes={"original"},
        max_batches=max_batches,
    )
    reference = predictions["original"]
    for mode in ABLATION_MODES[1:]:
        candidate = predictions[mode]
        for name in (
            "ids",
            "queries",
            "split_types",
            "sample_offsets",
            "segment_indices",
            "labels",
        ):
            if not np.array_equal(reference[name], candidate[name]):
                raise RuntimeError(f"Ablation {mode} changed evaluation field {name}")
    return predictions, paths["original"]


def _distribution(values: np.ndarray) -> dict[str, Any]:
    array = np.asarray(values, dtype=np.float64).reshape(-1)
    if array.size == 0:
        raise ValueError("Cannot summarize an empty distribution")
    return {
        "count": int(array.size),
        "mean": float(array.mean()),
        "std": float(array.std()),
        "quantiles": {
            str(q): float(np.quantile(array, q))
            for q in (0.0, 0.05, 0.25, 0.5, 0.75, 0.95, 1.0)
        },
    }


def summarize_prediction_response(
    predictions: Mapping[str, np.ndarray], *, threshold: float
) -> dict[str, Any]:
    audit = audit_prediction_payload(predictions, threshold=float(threshold))
    metrics = audit["groups"]["total"]
    offsets = np.asarray(predictions["sample_offsets"], dtype=np.int64)
    logits = np.asarray(predictions["logits"], dtype=np.float64)
    within_sample_std = np.asarray(
        [
            np.std(logits[int(start) : int(end)])
            for start, end in zip(offsets[:-1], offsets[1:])
        ],
        dtype=np.float64,
    )
    return {
        "sample_count": int(np.asarray(predictions["ids"]).size),
        "segment_count": int(logits.size),
        "threshold": float(threshold),
        "ap": metrics["global_segment_micro_ap"],
        "auroc": metrics["global_segment_micro_auroc"],
        "predicted_positive_rate": metrics["predicted_positive_rate_at_threshold"],
        "positive_rate": float(
            np.mean(np.asarray(predictions["labels"], dtype=np.float64))
        ),
        "within_sample_logit_std": _distribution(within_sample_std),
        "metrics": metrics,
    }


def _run_git(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _canonical_config_sha(config: Mapping[str, Any]) -> str:
    payload = json.dumps(
        dict(config), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _state_dict_sha256(module: torch.nn.Module) -> str:
    digest = hashlib.sha256()
    for name, tensor in sorted(module.state_dict().items()):
        contiguous = tensor.detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(contiguous.dtype).encode("ascii"))
        digest.update(json.dumps(list(contiguous.shape)).encode("ascii"))
        digest.update(contiguous.numpy().tobytes(order="C"))
    return digest.hexdigest()


def build_checkpoint_modality_report(
    *,
    config_path: str | Path,
    checkpoint_path: str | Path,
    device: torch.device,
    expected_segments: int,
    max_batches: int | None = None,
) -> dict[str, Any]:
    from scripts.train_ov_orthkd import build_model_and_loss, set_seed
    from src.data import create_ov_avel_data_loaders

    source_config = Path(config_path)
    source_checkpoint = Path(checkpoint_path)
    config = yaml.safe_load(source_config.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Resolved config must be a mapping")
    task_segments = task_segments_from_config(config)
    if task_segments != int(expected_segments):
        raise ValueError(
            f"Config task segments={task_segments}, expected={expected_segments}"
        )
    set_seed(
        int(config.get("seed", 42)),
        deterministic=bool(config.get("training", {}).get("deterministic", True)),
    )
    student, _loss_module = build_model_and_loss(config, device)
    checkpoint = torch.load(source_checkpoint, map_location="cpu", weights_only=True)
    if not isinstance(checkpoint, dict) or "student_state_dict" not in checkpoint:
        raise ValueError("Checkpoint is missing student_state_dict")
    checkpoint_config = checkpoint.get("config")
    if not isinstance(checkpoint_config, dict):
        raise ValueError("Checkpoint is missing its resolved config")
    source_config_sha = _canonical_config_sha(config)
    checkpoint_config_sha = _canonical_config_sha(checkpoint_config)
    if source_config_sha != checkpoint_config_sha:
        raise ValueError(
            "Resolved config does not exactly match the config embedded in checkpoint"
        )
    incompatible = student.load_state_dict(checkpoint["student_state_dict"], strict=True)
    if incompatible.missing_keys or incompatible.unexpected_keys:
        raise RuntimeError("Strict student state loading returned incompatible keys")
    train_loader, validation_loader, test_loader = create_ov_avel_data_loaders(config)
    del train_loader
    if test_loader is None:
        raise RuntimeError("Checkpoint diagnostic requires a test loader")

    split_reports: dict[str, Any] = {}
    for split_name, loader in (
        ("validation", validation_loader),
        ("test", test_loader),
    ):
        predictions, path_scales = collect_ablation_matrix(
            student,
            loader,
            device,
            expected_task_segments=task_segments,
            max_batches=max_batches,
        )
        split_reports[split_name] = {
            "modes": {
                mode: summarize_prediction_response(payload, threshold=0.5)
                for mode, payload in predictions.items()
            },
            "original_path_scales": path_scales,
        }

    fingerprint = checkpoint.get("reproduction_fingerprint")
    return {
        "schema_version": 1,
        "status": "PASS",
        "claim_level": "noncanonical_posthoc_checkpoint_diagnostic",
        "protocol": {
            "task_segments": task_segments,
            "temporal_conversion": "forbidden",
            "ablation_modes": list(ABLATION_MODES),
            "zeroing_semantics": (
                "selected_input_content_zeroed_validity_and_sequence_masks_preserved"
            ),
            "threshold": 0.5,
            "max_batches": max_batches,
        },
        "sources": {
            "resolved_config": _source_receipt(source_config),
            "checkpoint": _source_receipt(source_checkpoint),
        },
        "state_loading": {
            "strict": True,
            "missing_keys": list(incompatible.missing_keys),
            "unexpected_keys": list(incompatible.unexpected_keys),
            "resolved_config_canonical_sha256": source_config_sha,
            "checkpoint_config_canonical_sha256": checkpoint_config_sha,
            "loaded_student_state_sha256": _state_dict_sha256(student),
            "checkpoint_fingerprint_sha256": (
                fingerprint.get("sha256") if isinstance(fingerprint, dict) else None
            ),
        },
        "git": {
            "head": _run_git(["git", "rev-parse", "HEAD"]),
            "status": _run_git(["git", "status", "--short"]),
        },
        "splits": split_reports,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only checkpoint modality and path-scale diagnostics"
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--expected-segments", type=int, default=10)
    parser.add_argument("--max-batches", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")
    os.chdir(PROJECT_ROOT)
    report = build_checkpoint_modality_report(
        config_path=args.config,
        checkpoint_path=args.checkpoint,
        device=torch.device(args.device),
        expected_segments=args.expected_segments,
        max_batches=args.max_batches,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
