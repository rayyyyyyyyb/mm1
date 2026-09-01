#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import torch
import yaml
from PIL import Image
from torch.utils.data import DataLoader

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.diagnose_checkpoint_modalities import (  # noqa: E402
    apply_content_ablation,
)
from src.data.ov_avel_dataset import ov_avel_collate_fn  # noqa: E402
from src.utils.temporal_protocol import task_segments_from_config  # noqa: E402
from src.utils.zero_training_diagnostics import (  # noqa: E402
    build_audio_donor_maps,
    summarize_label_strata,
    temporally_shuffle_audio,
    validate_t10_predictions,
)


TASK_SEGMENTS = 10
TIMELINE_STATE_LABELS = (
    "reconstructed_zero_step",
    "step_000400",
    "step_000800",
    "step_001200",
)
TIMELINE_CHECKPOINT_STEPS = (400, 800, 1200)
GATE_GRID = (
    (0.0, 1.0),
    (0.25, 0.75),
    (0.5, 0.5),
    (0.75, 0.25),
    (1.0, 0.0),
)
CONTENT_MODES = (
    "content_original",
    "content_visual_zero",
    "content_audio_zero",
    "content_both_zero",
)
AUDIO_INTERVENTION_MODES = (
    "same_query_donor",
    "different_query_donor",
    "temporal_shuffle",
)


def sha256_file(path: str | Path) -> str:
    source = Path(path)
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_receipt(path: str | Path) -> dict[str, Any]:
    source = Path(path).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    return {
        "path": str(source),
        "bytes": source.stat().st_size,
        "sha256": sha256_file(source),
    }


def canonical_mapping_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_identity_gate_config(
    config: Mapping[str, Any], *, expected_gate_mode: str
) -> None:
    """Fail closed on the two identity-path causal cells supported by this audit."""
    if expected_gate_mode not in {"learned_softmax", "fixed_equal"}:
        raise ValueError(f"Unsupported expected gate_mode: {expected_gate_mode}")
    if task_segments_from_config(config) != TASK_SEGMENTS:
        raise ValueError("Identity-path diagnostic requires official T=10")
    student = config.get("student")
    if not isinstance(student, Mapping):
        raise ValueError("Identity-path diagnostic requires a student config")
    if student.get("temporal_path_mode") != "identity_passthrough":
        raise ValueError("Expected identity_passthrough temporal path")
    if student.get("gate_mode") != expected_gate_mode:
        raise ValueError(
            "Resolved student.gate_mode does not match the explicitly expected "
            f"gate_mode {expected_gate_mode}"
        )


def state_dict_sha256(module: torch.nn.Module) -> str:
    digest = hashlib.sha256()
    for name, tensor in sorted(module.state_dict().items()):
        value = tensor.detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(value.dtype).encode("ascii"))
        digest.update(json.dumps(list(value.shape)).encode("ascii"))
        digest.update(value.numpy().tobytes(order="C"))
    return digest.hexdigest()


def _canonical_sequence_digest(frame_hashes: Sequence[str]) -> str:
    payload = json.dumps(
        [
            {"segment_index": index, "sha256": value}
            for index, value in enumerate(frame_hashes)
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def audit_frame_sequence(frame_paths: Sequence[str | Path]) -> dict[str, Any]:
    paths = [Path(value).resolve() for value in frame_paths]
    if len(paths) != TASK_SEGMENTS:
        raise ValueError("Official visual content audit requires exactly 10 frames")
    if any(not path.is_file() for path in paths):
        missing = [str(path) for path in paths if not path.is_file()]
        raise FileNotFoundError(f"Missing audited frame files: {missing}")

    frame_hashes = [sha256_file(path) for path in paths]
    grouped: dict[str, list[int]] = {}
    for index, value in enumerate(frame_hashes):
        grouped.setdefault(value, []).append(index)
    duplicate_groups = [indices for indices in grouped.values() if len(indices) > 1]
    duplicate_groups.sort(key=lambda indices: tuple(indices))

    pixels: list[np.ndarray] = []
    shapes: list[list[int]] = []
    for path in paths:
        with Image.open(path) as image:
            array = np.asarray(image.convert("RGB"), dtype=np.float64)
        if array.ndim != 3 or array.shape[-1] != 3 or not np.isfinite(array).all():
            raise ValueError(f"Invalid RGB frame: {path}")
        pixels.append(array)
        shapes.append([int(value) for value in array.shape])
    adjacent_mad: list[float] = []
    for left, right in zip(pixels[:-1], pixels[1:]):
        if left.shape != right.shape:
            raise ValueError("Adjacent official frames have inconsistent pixel shapes")
        adjacent_mad.append(float(np.mean(np.abs(left - right))))

    return {
        "frame_count": TASK_SEGMENTS,
        "frame_sha256": frame_hashes,
        "canonical_sha256": _canonical_sequence_digest(frame_hashes),
        "pixel_shapes": shapes,
        "exact_duplicate_file_count": TASK_SEGMENTS - len(grouped),
        "exact_duplicate_groups": duplicate_groups,
        "adjacent_pixel_mean_absolute_difference": adjacent_mad,
    }


def _record_frame_paths(dataset: Any, record: Mapping[str, Any]) -> list[Path]:
    labels = np.asarray(record.get("segment_labels"), dtype=np.float64).reshape(-1)
    if labels.size != TASK_SEGMENTS:
        raise ValueError("Test record does not contain exactly 10 official labels")
    value = (
        record.get("segment_frame_paths")
        or record.get("frame_groups")
        or record.get("frame_paths")
        or record.get("frames")
    )
    normalized = dataset._normalize_segment_frame_paths(value, TASK_SEGMENTS)
    if len(normalized) != TASK_SEGMENTS or any(path is None for path in normalized):
        raise ValueError("Test record does not resolve to exactly 10 official frames")
    return [dataset._resolve_path(path) for path in normalized]


def audit_test_frame_content(dataset: Any, *, image_examples: int) -> dict[str, Any]:
    if image_examples < 1:
        raise ValueError("image_examples must be positive")
    records = getattr(dataset, "records", None)
    if not isinstance(records, list) or not records:
        raise ValueError("Test dataset must expose non-empty manifest records")

    full_digest = hashlib.sha256()
    global_hash_counts: Counter[str] = Counter()
    sequence_duplicate_extras = 0
    videos_with_sequence_duplicates = 0
    adjacent_values: list[float] = []
    examples: list[dict[str, Any]] = []
    first_duplicate_example: dict[str, Any] | None = None
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise ValueError(f"Invalid test record at index {index}")
        record_id = str(record.get("id", index))
        report = audit_frame_sequence(_record_frame_paths(dataset, record))
        canonical_entry = json.dumps(
            {
                "dataset_index": index,
                "id": record_id,
                "frame_sha256": report["frame_sha256"],
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        full_digest.update(len(canonical_entry).to_bytes(8, "big"))
        full_digest.update(canonical_entry)
        global_hash_counts.update(report["frame_sha256"])
        duplicate_count = int(report["exact_duplicate_file_count"])
        sequence_duplicate_extras += duplicate_count
        videos_with_sequence_duplicates += int(duplicate_count > 0)
        adjacent_values.extend(report["adjacent_pixel_mean_absolute_difference"])
        compact = {
            "dataset_index": index,
            "id": record_id,
            **report,
        }
        if len(examples) < image_examples:
            examples.append(compact)
        if duplicate_count > 0 and first_duplicate_example is None:
            first_duplicate_example = compact

    if first_duplicate_example is not None and all(
        example["dataset_index"] != first_duplicate_example["dataset_index"]
        for example in examples
    ):
        if len(examples) == image_examples:
            examples[-1] = first_duplicate_example
        else:
            examples.append(first_duplicate_example)
    adjacent = np.asarray(adjacent_values, dtype=np.float64)
    if adjacent.size != len(records) * (TASK_SEGMENTS - 1):
        raise RuntimeError("Full visual content audit did not cover every adjacent pair")
    return {
        "semantics": "official_test_jpg_file_bytes_and_decoded_rgb_pixels",
        "video_count": len(records),
        "frame_count": len(records) * TASK_SEGMENTS,
        "task_segments": TASK_SEGMENTS,
        "full_canonical_sha256": full_digest.hexdigest(),
        "global_exact_duplicate_file_count": sum(
            count - 1 for count in global_hash_counts.values() if count > 1
        ),
        "within_video_exact_duplicate_file_count": sequence_duplicate_extras,
        "videos_with_within_video_exact_duplicates": videos_with_sequence_duplicates,
        "adjacent_pixel_mean_absolute_difference": {
            "count": int(adjacent.size),
            "mean": float(adjacent.mean()),
            "minimum": float(adjacent.min()),
            "maximum": float(adjacent.max()),
        },
        "deterministic_examples": examples,
    }


def verify_reconstructed_zero_step(
    stored_diagnostic: Mapping[str, Any], student: torch.nn.Module
) -> dict[str, Any]:
    if int(stored_diagnostic.get("global_step_before_update", -1)) != 0:
        raise ValueError("Stored training diagnostic is not global step zero")
    stored_head = stored_diagnostic.get("segment_head")
    head = getattr(student, "segment_head", None)
    if not isinstance(stored_head, Mapping) or not isinstance(head, torch.nn.Linear):
        raise ValueError("Stored or reconstructed segment head is unavailable")
    actual_weight_l2 = float(head.weight.detach().to(dtype=torch.float64).norm())
    stored_weight_l2 = float(stored_head.get("weight_l2", float("nan")))
    if not math.isclose(
        actual_weight_l2, stored_weight_l2, rel_tol=1e-12, abs_tol=1e-12
    ):
        raise ValueError("Reconstructed segment-head weight L2 disagrees with step zero")
    actual_bias = (
        [float(value) for value in head.bias.detach().cpu().reshape(-1)]
        if head.bias is not None
        else None
    )
    stored_bias = stored_head.get("bias")
    if actual_bias is None or not isinstance(stored_bias, list) or len(actual_bias) != len(stored_bias):
        raise ValueError("Reconstructed segment-head bias shape disagrees with step zero")
    if any(
        not math.isclose(actual, float(expected), rel_tol=1e-12, abs_tol=1e-12)
        for actual, expected in zip(actual_bias, stored_bias)
    ):
        raise ValueError("Reconstructed segment-head bias disagrees with step zero")
    return {
        "identity": "reconstructed_zero_step",
        "saved_checkpoint_claim": False,
        "stored_global_step_before_update": 0,
        "segment_head": {
            "weight_l2": actual_weight_l2,
            "bias": actual_bias,
        },
        "student_state_sha256": state_dict_sha256(student),
    }


def fusion_input_block_norms(student: torch.nn.Module) -> dict[str, Any]:
    if getattr(student, "fusion_mode", None) != "concat_mlp_query_conditioned":
        raise ValueError("Fusion block audit requires concat_mlp_query_conditioned")
    token_fusion = getattr(student, "token_fusion", None)
    if not isinstance(token_fusion, torch.nn.Sequential) or len(token_fusion) < 2:
        raise ValueError("Student concat fusion module is unavailable")
    linear = token_fusion[1]
    if not isinstance(linear, torch.nn.Linear):
        raise ValueError("Concat fusion first affine module is not Linear")
    fusion_dim = int(getattr(student, "fusion_dim"))
    expected_shape = (fusion_dim, 3 * fusion_dim)
    if tuple(linear.weight.shape) != expected_shape:
        raise ValueError(
            f"Concat first-linear shape {tuple(linear.weight.shape)} != {expected_shape}"
        )
    order = ["visual", "audio", "query"]
    blocks: dict[str, Any] = {}
    for index, name in enumerate(order):
        block = linear.weight.detach()[:, index * fusion_dim : (index + 1) * fusion_dim]
        blocks[name] = {
            "column_start": index * fusion_dim,
            "column_end_exclusive": (index + 1) * fusion_dim,
            "column_count": fusion_dim,
            "frobenius_l2": float(block.to(dtype=torch.float64).norm()),
        }
    return {
        "block_order": order,
        "semantics": "token_fusion_first_linear_columns_after_concat_layernorm",
        "first_linear_shape": list(linear.weight.shape),
        "first_linear_frobenius_l2": float(
            linear.weight.detach().to(dtype=torch.float64).norm()
        ),
        "blocks": blocks,
    }


def _model_device(student: torch.nn.Module) -> torch.device:
    try:
        return next(student.parameters()).device
    except StopIteration as exc:
        raise ValueError("Student has no parameters") from exc


def _forward_batch(
    student: torch.nn.Module,
    batch: Mapping[str, Any],
    *,
    forced_gate_weights: tuple[float, float] | None = None,
) -> dict[str, torch.Tensor | None]:
    device = _model_device(student)
    return student(
        frame=batch["frame"].to(device),
        spectrogram=batch["spectrogram"].to(device),
        text_embedding=batch["text_embedding"].to(device),
        sequence_mask=batch["sequence_mask"].to(device),
        frame_valid=batch["frame_valid"].to(device),
        audio_valid=batch["audio_valid"].to(device),
        forced_gate_weights=forced_gate_weights,
    )


def input_jacobian_norms(
    student: torch.nn.Module,
    batch: Mapping[str, Any],
    *,
    forced_gate_weights: tuple[float, float] | None = None,
) -> dict[str, Any]:
    if any(parameter.grad is not None for parameter in student.parameters()):
        raise ValueError("Jacobian audit requires parameters with empty .grad fields")
    before_hash = state_dict_sha256(student)
    was_training = student.training
    student.eval()
    with torch.enable_grad():
        outputs = _forward_batch(
            student, batch, forced_gate_weights=forced_gate_weights
        )
        logits = outputs.get("segment_logits")
        inputs = {
            "visual": outputs.get("visual_tokens"),
            "audio": outputs.get("audio_tokens"),
            "query": outputs.get("text_tokens"),
        }
        if not isinstance(logits, torch.Tensor) or any(
            not isinstance(value, torch.Tensor) for value in inputs.values()
        ):
            raise RuntimeError("Student is missing tensors required for Jacobian audit")
        mask = batch["sequence_mask"].to(device=logits.device).bool()
        if mask.shape != logits.shape:
            raise ValueError("sequence_mask and segment logits shapes differ")
        valid_logits = logits[mask]
        squared = {name: 0.0 for name in inputs}
        ordered_inputs = tuple(inputs.values())
        for index in range(valid_logits.numel()):
            gradients = torch.autograd.grad(
                valid_logits[index],
                ordered_inputs,
                retain_graph=index + 1 < valid_logits.numel(),
                create_graph=False,
                allow_unused=False,
            )
            for name, gradient in zip(inputs, gradients):
                squared[name] += float(
                    gradient.detach().to(dtype=torch.float64).square().sum()
                )
    student.train(was_training)
    if any(parameter.grad is not None for parameter in student.parameters()):
        raise RuntimeError("Jacobian audit unexpectedly populated parameter gradients")
    after_hash = state_dict_sha256(student)
    if before_hash != after_hash:
        raise RuntimeError("Jacobian audit mutated student parameters or buffers")
    return {
        "input_order": ["visual", "audio", "query"],
        "semantics": "exact_frobenius_norm_of_valid_segment_logit_jacobian",
        "valid_output_count": int(valid_logits.numel()),
        "l2": {name: math.sqrt(value) for name, value in squared.items()},
        "student_state_sha256_before": before_hash,
        "student_state_sha256_after": after_hash,
        "parameter_gradients_remained_none": True,
    }


def apply_audio_intervention(
    batch: Mapping[str, Any],
    *,
    mode: str,
    donor_batch: Mapping[str, Any] | None = None,
    seed: int = 42,
    sample_offset: int = 0,
) -> dict[str, Any]:
    if mode not in AUDIO_INTERVENTION_MODES:
        raise ValueError(f"Unsupported audio intervention: {mode}")
    if mode == "temporal_shuffle":
        if donor_batch is not None:
            raise ValueError("temporal_shuffle does not accept a donor batch")
        return temporally_shuffle_audio(
            batch, seed=int(seed), sample_offset=int(sample_offset)
        )
    if donor_batch is None:
        raise ValueError(f"{mode} requires a donor batch")
    source_spectrogram = batch.get("spectrogram")
    source_valid = batch.get("audio_valid")
    donor_spectrogram = donor_batch.get("spectrogram")
    donor_valid = donor_batch.get("audio_valid")
    if not all(
        isinstance(value, torch.Tensor)
        for value in (
            source_spectrogram,
            source_valid,
            donor_spectrogram,
            donor_valid,
        )
    ):
        raise ValueError("Audio donor intervention requires tensor audio fields")
    if (
        source_spectrogram.shape != donor_spectrogram.shape
        or source_valid.shape != donor_valid.shape
        or tuple(source_spectrogram.shape[:2]) != tuple(source_valid.shape)
    ):
        raise ValueError("Audio donor source/donor shape mismatch")
    result = dict(batch)
    result["spectrogram"] = donor_spectrogram.clone()
    result["audio_valid"] = donor_valid.clone()
    return result


def reserve_output_paths(output: str | Path, prediction_output: str | Path) -> None:
    output_path = Path(output).resolve()
    prediction_path = Path(prediction_output).resolve()
    if output_path == prediction_path:
        raise ValueError("JSON and prediction outputs must be distinct")
    for path in (output_path, prediction_path):
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite output: {path}")
        temporary = path.with_name(path.name + ".tmp")
        if temporary.exists():
            raise FileExistsError(f"Refusing stale temporary output: {temporary}")


class _TemporalAccumulator:
    def __init__(self) -> None:
        self.valid_rows = 0
        self.feature_dim: int | None = None
        self.square_sum = 0.0
        self.value_count = 0
        self.row_l2_sum = 0.0
        self.temporal_std_sum = 0.0
        self.temporal_sample_count = 0
        self.shapes: Counter[str] = Counter()

    def update(self, tensor: torch.Tensor, mask: torch.Tensor) -> None:
        values = tensor.detach().reshape(tensor.shape[0], tensor.shape[1], -1)
        valid = mask.detach().to(device=values.device).bool()
        if tuple(values.shape[:2]) != tuple(valid.shape):
            raise ValueError("Timeline tensor and mask leading shapes differ")
        if not bool(torch.isfinite(values).all()):
            raise ValueError("Timeline tensor contains NaN/Inf")
        feature_dim = int(values.shape[-1])
        if self.feature_dim is not None and self.feature_dim != feature_dim:
            raise ValueError("Timeline feature dimension changed")
        self.feature_dim = feature_dim
        rows = values[valid].to(dtype=torch.float64)
        self.valid_rows += int(rows.shape[0])
        self.value_count += int(rows.numel())
        self.square_sum += float(rows.square().sum())
        self.row_l2_sum += float(torch.linalg.vector_norm(rows, dim=-1).sum())
        for sample_index in range(values.shape[0]):
            sample = values[sample_index, valid[sample_index]].to(dtype=torch.float64)
            if sample.shape[0] == 0:
                continue
            self.temporal_std_sum += float(sample.std(dim=0, unbiased=False).mean())
            self.temporal_sample_count += 1
        self.shapes["x".join(str(value) for value in tensor.shape)] += 1

    def finalize(self) -> dict[str, Any]:
        if self.valid_rows == 0 or self.feature_dim is None:
            raise RuntimeError("Timeline accumulator is empty")
        return {
            "observed_batch_shapes": dict(sorted(self.shapes.items())),
            "valid_rows": self.valid_rows,
            "feature_dim": self.feature_dim,
            "root_mean_square": math.sqrt(self.square_sum / self.value_count),
            "row_l2_mean": self.row_l2_sum / self.valid_rows,
            "within_sample_temporal_std_mean": (
                self.temporal_std_sum / self.temporal_sample_count
            ),
        }


@torch.no_grad()
def collect_timeline_summary(
    student: torch.nn.Module,
    loader: Iterable[Mapping[str, Any]],
    device: torch.device,
) -> dict[str, Any]:
    student.eval()
    accumulators = {
        "raw_visual_pixels": _TemporalAccumulator(),
        "visual_backbone_features": _TemporalAccumulator(),
        "visual_projected_tokens": _TemporalAccumulator(),
    }
    samples = 0
    for batch in loader:
        outputs = _forward_batch(student, batch)
        mask = batch["sequence_mask"]
        accumulators["raw_visual_pixels"].update(batch["frame"], mask)
        for output_name, accumulator_name in (
            ("visual_backbone_features", "visual_backbone_features"),
            ("visual_tokens", "visual_projected_tokens"),
        ):
            tensor = outputs.get(output_name)
            if not isinstance(tensor, torch.Tensor):
                raise RuntimeError(f"Student did not return {output_name}")
            accumulators[accumulator_name].update(tensor, mask.to(device))
        samples += int(mask.shape[0])
    if samples == 0:
        raise RuntimeError("Timeline audit saw no test samples")
    return {
        "sample_count": samples,
        "task_segments": TASK_SEGMENTS,
        "paths": {name: value.finalize() for name, value in accumulators.items()},
    }


def _prediction_metadata(batch: Mapping[str, Any]) -> dict[str, Any]:
    labels = batch["segment_label"].detach().cpu()
    mask = batch["sequence_mask"].detach().cpu().bool()
    if labels.shape != mask.shape or labels.ndim != 2:
        raise ValueError("Prediction batch labels/mask must share [B,T]")
    if labels.shape[1] != TASK_SEGMENTS or not bool(mask.all()):
        raise ValueError("Zero-training audit requires unpadded official T=10 batches")
    return {
        "ids": [str(value) for value in batch["id"]],
        "queries": [str(value) for value in batch["query"]],
        "split_types": [str(value) for value in batch["split_type"]],
        "labels": labels.numpy().reshape(-1).tolist(),
        "segment_indices": list(range(TASK_SEGMENTS)) * int(labels.shape[0]),
        "batch_size": int(labels.shape[0]),
    }


def _validate_forced_gates(
    outputs: Mapping[str, Any], batch: Mapping[str, Any], ratio: tuple[float, float]
) -> None:
    weights = outputs.get("gate_weights")
    if not isinstance(weights, torch.Tensor):
        raise RuntimeError("Forced-gate forward did not return gate weights")
    validity = torch.stack(
        [batch["frame_valid"], batch["audio_valid"]], dim=-1
    ).to(device=weights.device, dtype=weights.dtype)
    requested = weights.new_tensor(ratio).view(1, 1, 2)
    weighted = requested * validity
    denominator = weighted.sum(dim=-1, keepdim=True)
    fallback = validity / validity.sum(dim=-1, keepdim=True).clamp_min(1.0)
    expected = torch.where(
        denominator > 0,
        weighted / denominator.clamp_min(1e-12),
        fallback,
    )
    expected = torch.where(
        validity.sum(dim=-1, keepdim=True) == 0,
        torch.full_like(expected, 0.5),
        expected,
    )
    if not torch.equal(weights, expected):
        raise RuntimeError("Model did not apply the literal forced-gate ratio")


def _mode_batch(
    batch: Mapping[str, Any],
    mode: str,
    *,
    same_donor: Mapping[str, Any],
    different_donor: Mapping[str, Any],
    seed: int,
    sample_offset: int,
) -> tuple[dict[str, Any], tuple[float, float] | None]:
    if mode in CONTENT_MODES:
        ablation = {
            "content_original": "original",
            "content_visual_zero": "visual_zero",
            "content_audio_zero": "audio_zero",
            "content_both_zero": "both_zero",
        }[mode]
        return apply_content_ablation(batch, ablation), None
    if mode.startswith("gate_v"):
        pieces = mode.split("_")
        visual = int(pieces[1][1:]) / 100.0
        audio = int(pieces[2][1:]) / 100.0
        content = "visual_zero" if pieces[3:] == ["visual", "zero"] else "original"
        return apply_content_ablation(batch, content), (visual, audio)
    if mode == "audio_same_query_donor":
        return apply_audio_intervention(
            batch, mode="same_query_donor", donor_batch=same_donor
        ), None
    if mode == "audio_different_query_donor":
        return apply_audio_intervention(
            batch, mode="different_query_donor", donor_batch=different_donor
        ), None
    if mode == "audio_temporal_shuffle":
        return apply_audio_intervention(
            batch,
            mode="temporal_shuffle",
            seed=seed,
            sample_offset=sample_offset,
        ), None
    raise ValueError(f"Unknown prediction mode: {mode}")


def _gate_mode_name(ratio: tuple[float, float], content: str) -> str:
    visual = int(round(ratio[0] * 100))
    audio = int(round(ratio[1] * 100))
    suffix = "original" if content == "original" else "visual_zero"
    return f"gate_v{visual:03d}_a{audio:03d}_{suffix}"


def intervention_mode_names() -> tuple[str, ...]:
    gate_modes = tuple(
        _gate_mode_name(ratio, content)
        for ratio in GATE_GRID
        for content in ("original", "visual_zero")
    )
    return CONTENT_MODES + gate_modes + (
        "audio_same_query_donor",
        "audio_different_query_donor",
        "audio_temporal_shuffle",
    )


def _donor_loader(loader: DataLoader, indices: np.ndarray) -> DataLoader:
    return DataLoader(
        loader.dataset,
        batch_size=loader.batch_size,
        sampler=[int(value) for value in indices.tolist()],
        num_workers=int(loader.num_workers),
        pin_memory=bool(loader.pin_memory),
        persistent_workers=bool(loader.persistent_workers and loader.num_workers > 0),
        collate_fn=ov_avel_collate_fn,
    )


@torch.no_grad()
def collect_intervention_predictions(
    student: torch.nn.Module,
    loader: DataLoader,
    device: torch.device,
    *,
    donor_maps: Mapping[str, np.ndarray],
    seed: int,
) -> dict[str, dict[str, np.ndarray]]:
    del device
    modes = intervention_mode_names()
    logits_by_mode: dict[str, list[float]] = {mode: [] for mode in modes}
    ids: list[str] = []
    queries: list[str] = []
    split_types: list[str] = []
    labels: list[float] = []
    segment_indices: list[int] = []
    offsets = [0]
    same_loader = _donor_loader(loader, np.asarray(donor_maps["same_query"]))
    different_loader = _donor_loader(loader, np.asarray(donor_maps["different_query"]))
    student.eval()
    sample_offset = 0
    iterators = zip(loader, same_loader, different_loader)
    for batch, same_donor, different_donor in iterators:
        metadata = _prediction_metadata(batch)
        expected_same_ids = [
            str(loader.dataset.records[int(donor_maps["same_query"][sample_offset + i])].get("id", ""))
            for i in range(metadata["batch_size"])
        ]
        expected_different_ids = [
            str(loader.dataset.records[int(donor_maps["different_query"][sample_offset + i])].get("id", ""))
            for i in range(metadata["batch_size"])
        ]
        if [str(value) for value in same_donor["id"]] != expected_same_ids:
            raise RuntimeError("Same-query donor loader order changed")
        if [str(value) for value in different_donor["id"]] != expected_different_ids:
            raise RuntimeError("Different-query donor loader order changed")
        ids.extend(metadata["ids"])
        queries.extend(metadata["queries"])
        split_types.extend(metadata["split_types"])
        labels.extend(metadata["labels"])
        segment_indices.extend(metadata["segment_indices"])
        for _ in range(metadata["batch_size"]):
            offsets.append(offsets[-1] + TASK_SEGMENTS)

        for mode in modes:
            selected, forced = _mode_batch(
                batch,
                mode,
                same_donor=same_donor,
                different_donor=different_donor,
                seed=seed,
                sample_offset=sample_offset,
            )
            outputs = _forward_batch(
                student, selected, forced_gate_weights=forced
            )
            logits = outputs.get("segment_logits")
            if not isinstance(logits, torch.Tensor) or tuple(logits.shape) != tuple(
                batch["segment_label"].shape
            ):
                raise RuntimeError(f"Invalid logits for intervention mode {mode}")
            if not bool(torch.isfinite(logits).all()):
                raise ValueError(f"Non-finite logits for intervention mode {mode}")
            if forced is not None:
                _validate_forced_gates(outputs, selected, forced)
            logits_by_mode[mode].extend(
                float(value) for value in logits.detach().cpu().reshape(-1).tolist()
            )
        sample_offset += metadata["batch_size"]
    if sample_offset != len(loader.dataset):
        raise RuntimeError("Intervention matrix did not cover the full test dataset")

    common = {
        "ids": np.asarray(ids, dtype=str),
        "queries": np.asarray(queries, dtype=str),
        "split_types": np.asarray(split_types, dtype=str),
        "sample_offsets": np.asarray(offsets, dtype=np.int64),
        "segment_indices": np.asarray(segment_indices, dtype=np.int64),
        "labels": np.asarray(labels, dtype=np.float64),
    }
    predictions: dict[str, dict[str, np.ndarray]] = {}
    for mode in modes:
        logits = np.asarray(logits_by_mode[mode], dtype=np.float64)
        payload = {
            **common,
            "logits": logits,
            "probabilities": 1.0 / (1.0 + np.exp(-logits)),
        }
        validate_t10_predictions(payload)
        predictions[mode] = payload
    reference = predictions[modes[0]]
    for mode in modes[1:]:
        for field in (
            "ids",
            "queries",
            "split_types",
            "sample_offsets",
            "segment_indices",
            "labels",
        ):
            if not np.array_equal(reference[field], predictions[mode][field]):
                raise RuntimeError(f"Intervention mode {mode} changed {field}")
    return predictions


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    if any(not isinstance(record, dict) for record in records):
        raise ValueError(f"Expected JSON objects in {path}")
    return records


def _run_git(git: Path, repo: Path, *args: str) -> str:
    completed = subprocess.run(
        [str(git), "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip())
    return completed.stdout.strip()


def _load_checkpoint_state(
    student: torch.nn.Module,
    path: Path,
    *,
    expected_step: int,
    config_sha256: str,
) -> dict[str, Any]:
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(checkpoint, dict) or int(checkpoint.get("global_step", -1)) != expected_step:
        raise ValueError(f"Checkpoint does not bind global step {expected_step}: {path}")
    embedded = checkpoint.get("config")
    if not isinstance(embedded, Mapping) or canonical_mapping_sha256(embedded) != config_sha256:
        raise ValueError(f"Checkpoint config mismatch: {path}")
    incompatible = student.load_state_dict(checkpoint["student_state_dict"], strict=True)
    if incompatible.missing_keys or incompatible.unexpected_keys:
        raise RuntimeError(f"Strict checkpoint load failed: {path}")
    return {
        **source_receipt(path),
        "global_step": expected_step,
        "student_state_sha256": state_dict_sha256(student),
        "strict_state_load": True,
    }


def _first_batch(loader: Iterable[Mapping[str, Any]]) -> Mapping[str, Any]:
    try:
        return next(iter(loader))
    except StopIteration as exc:
        raise RuntimeError("Test loader is empty") from exc


def _prediction_archive_arrays(
    predictions: Mapping[str, Mapping[str, np.ndarray]]
) -> dict[str, np.ndarray]:
    names = list(predictions)
    reference = predictions[names[0]]
    return {
        "mode_names": np.asarray(names, dtype=str),
        "ids": np.asarray(reference["ids"]),
        "queries": np.asarray(reference["queries"]),
        "split_types": np.asarray(reference["split_types"]),
        "sample_offsets": np.asarray(reference["sample_offsets"]),
        "segment_indices": np.asarray(reference["segment_indices"]),
        "labels": np.asarray(reference["labels"]),
        "logits": np.stack([np.asarray(predictions[name]["logits"]) for name in names]),
        "probabilities": np.stack(
            [np.asarray(predictions[name]["probabilities"]) for name in names]
        ),
    }


def _prediction_metric_report(
    predictions: Mapping[str, Mapping[str, np.ndarray]],
    *,
    shuffle_repeats: int,
    seed: int,
) -> dict[str, Any]:
    return summarize_label_strata(
        predictions,
        shuffle_repeats=shuffle_repeats,
        seed=seed,
        threshold=0.5,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Identity-path A-E read-only zero/near-zero-training diagnostics"
    )
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--git", type=Path, required=True)
    parser.add_argument("--training-output", type=Path, required=True)
    parser.add_argument("--training-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prediction-output", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument(
        "--expected-gate-mode",
        choices=("learned_softmax", "fixed_equal"),
        default="learned_softmax",
    )
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--shuffle-repeats", type=int, default=100)
    parser.add_argument("--image-examples", type=int, default=8)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    reserve_output_paths(args.output, args.prediction_output)
    if args.shuffle_repeats < 1 or args.image_examples < 1:
        raise ValueError("shuffle-repeats and image-examples must be positive")
    repo = args.repo.resolve()
    if _run_git(args.git, repo, "rev-parse", "HEAD") != args.expected_commit:
        raise RuntimeError("Diagnostic repository is not at expected commit")
    if _run_git(
        args.git, repo, "status", "--porcelain=v1", "--untracked-files=all"
    ):
        raise RuntimeError("Diagnostic repository must be clean")
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")
    device = torch.device(args.device)

    sys.path.insert(0, str(repo))
    os.chdir(repo)
    from scripts.train_ov_orthkd import build_model_and_loss, set_seed  # noqa: PLC0415
    from src.data import create_ov_avel_data_loaders  # noqa: PLC0415

    training_audit = _read_json(args.training_audit)
    if training_audit.get("status") != "PASS" or int(training_audit.get("task_segments", -1)) != TASK_SEGMENTS:
        raise ValueError("Identity-path training audit is not a PASS T=10 receipt")
    config_path = args.training_output / "resolved_config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Identity-path resolved config must be a mapping")
    validate_identity_gate_config(
        config, expected_gate_mode=args.expected_gate_mode
    )
    config_sha = canonical_mapping_sha256(config)
    seed = int(config.get("seed", 42))
    set_seed(
        seed,
        deterministic=bool(config.get("training", {}).get("deterministic", True)),
    )
    student, _loss_module = build_model_and_loss(config, device)
    del _loss_module
    reconstructed_state_sha = state_dict_sha256(student)
    diagnostics_path = args.training_output / "training_diagnostics.jsonl"
    diagnostics = _read_jsonl(diagnostics_path)
    if not diagnostics:
        raise ValueError("Identity-path training diagnostics are empty")
    reconstructed_receipt = verify_reconstructed_zero_step(diagnostics[0], student)
    if reconstructed_receipt["student_state_sha256"] != reconstructed_state_sha:
        raise RuntimeError("Reconstructed zero-step identity changed during verification")

    train_loader, validation_loader, test_loader = create_ov_avel_data_loaders(config)
    del train_loader, validation_loader
    if not isinstance(test_loader, DataLoader):
        raise RuntimeError("Identity-path audit requires a test DataLoader")
    test_records = test_loader.dataset.records
    ids = [str(record.get("id", index)) for index, record in enumerate(test_records)]
    queries = [
        str(record.get("query", record.get("text_query", "unknown event")))
        for record in test_records
    ]
    donor_maps = build_audio_donor_maps(ids, queries)
    donor_receipt = {
        "sample_count": len(ids),
        "same_query": {
            "is_bijection": sorted(donor_maps["same_query"].tolist()) == list(range(len(ids))),
            "query_relation_verified": all(
                queries[index] == queries[int(donor)]
                for index, donor in enumerate(donor_maps["same_query"])
            ),
        },
        "different_query": {
            "is_bijection": sorted(donor_maps["different_query"].tolist()) == list(range(len(ids))),
            "query_relation_verified": all(
                queries[index] != queries[int(donor)]
                for index, donor in enumerate(donor_maps["different_query"])
            ),
        },
        "mapping_sha256": hashlib.sha256(
            np.stack(
                [donor_maps["same_query"], donor_maps["different_query"]], axis=0
            ).astype("<i8").tobytes()
        ).hexdigest(),
    }
    if not all(
        donor_receipt[name][field]
        for name in ("same_query", "different_query")
        for field in ("is_bijection", "query_relation_verified")
    ):
        raise RuntimeError("Audio donor maps failed integrity checks")

    visual_content = audit_test_frame_content(
        test_loader.dataset, image_examples=args.image_examples
    )
    first_batch = _first_batch(test_loader)
    timeline: dict[str, Any] = {}
    timeline_sources: dict[str, Any] = {}
    timeline["reconstructed_zero_step"] = {
        "source": reconstructed_receipt,
        "visual_timeline": collect_timeline_summary(student, test_loader, device),
        "fusion_input_blocks": fusion_input_block_norms(student),
        "first_test_batch_input_jacobians": input_jacobian_norms(student, first_batch),
    }
    for step, label in zip(TIMELINE_CHECKPOINT_STEPS, TIMELINE_STATE_LABELS[1:]):
        checkpoint_path = (
            args.training_output / "diagnostic_checkpoints" / f"step_{step:06d}.pt"
        )
        checkpoint_receipt = _load_checkpoint_state(
            student,
            checkpoint_path,
            expected_step=step,
            config_sha256=config_sha,
        )
        timeline_sources[label] = checkpoint_receipt
        timeline[label] = {
            "source": checkpoint_receipt,
            "visual_timeline": collect_timeline_summary(student, test_loader, device),
            "fusion_input_blocks": fusion_input_block_norms(student),
            "first_test_batch_input_jacobians": input_jacobian_norms(student, first_batch),
        }

    best_step = int(training_audit["checkpoint_roles"]["best"]["global_step"])
    best_path = args.training_output / "best.pt"
    best_receipt = _load_checkpoint_state(
        student,
        best_path,
        expected_step=best_step,
        config_sha256=config_sha,
    )
    predictions = collect_intervention_predictions(
        student,
        test_loader,
        device,
        donor_maps=donor_maps,
        seed=seed,
    )
    metric_report = _prediction_metric_report(
        predictions,
        shuffle_repeats=args.shuffle_repeats,
        seed=seed,
    )

    archive = _prediction_archive_arrays(predictions)
    prediction_path = args.prediction_output.resolve()
    prediction_path.parent.mkdir(parents=True, exist_ok=True)
    prediction_temporary = prediction_path.with_name(prediction_path.name + ".tmp")
    with prediction_temporary.open("wb") as handle:
        np.savez_compressed(handle, **archive)
    prediction_temporary.replace(prediction_path)

    report = {
        "schema_version": 1,
        "status": "PASS",
        "claim_level": (
            "read_only_s7_zero_near_zero_training_diagnostics"
            if args.expected_gate_mode == "learned_softmax"
            else "read_only_identity_fixed_equal_zero_near_zero_training_diagnostics"
        ),
        "protocol": {
            "task_segments": TASK_SEGMENTS,
            "temporal_conversion": "forbidden",
            "timeline_states": list(TIMELINE_STATE_LABELS),
            "zero_step_identity": "reconstructed_not_saved_checkpoint",
            "gate_grid": [list(value) for value in GATE_GRID],
            "gate_content_modes": ["original", "visual_zero"],
            "audio_modes": {
                "original": "content_original",
                "same_query_donor": "audio_same_query_donor",
                "different_query_donor": "audio_different_query_donor",
                "temporal_shuffle": "audio_temporal_shuffle",
            },
            "seed": seed,
            "test_views": 1,
            "expected_gate_mode": args.expected_gate_mode,
            "shuffle_repeats": args.shuffle_repeats,
        },
        "git": {
            "implementation_commit": args.expected_commit,
            "status": "clean",
        },
        "sources": {
            "training_audit": source_receipt(args.training_audit),
            "resolved_config": source_receipt(config_path),
            "training_diagnostics": source_receipt(diagnostics_path),
            "best_checkpoint": best_receipt,
            "timeline_checkpoints": timeline_sources,
            "prediction_archive": source_receipt(prediction_path),
        },
        "reconstructed_zero_step": reconstructed_receipt,
        "test_visual_content_audit": visual_content,
        "audio_donor_maps": donor_receipt,
        "timeline": timeline,
        "intervention_mode_names": list(predictions),
        "intervention_metrics": metric_report,
        "mutation_guards": {
            "optimizer_constructed": False,
            "optimizer_step_executed": False,
            "checkpoint_written": False,
            "loaded_student_state_sha256_after": state_dict_sha256(student),
            "matches_best_checkpoint_loaded_state": (
                state_dict_sha256(student) == best_receipt["student_state_sha256"]
            ),
        },
    }
    if not report["mutation_guards"]["matches_best_checkpoint_loaded_state"]:
        raise RuntimeError("A-E diagnostics mutated the loaded best checkpoint state")
    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output_path)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
