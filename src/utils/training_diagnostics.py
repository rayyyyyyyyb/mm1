from __future__ import annotations

import math
from typing import Any, Mapping

import numpy as np
import torch
from torch import nn


_QUANTILES = (0.0, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 1.0)


def _distribution(values: torch.Tensor) -> dict[str, Any]:
    array = values.detach().to(dtype=torch.float64, device="cpu").reshape(-1).numpy()
    if array.size == 0:
        return {"count": 0, "mean": None, "std": None, "quantiles": {}}
    return {
        "count": int(array.size),
        "mean": float(array.mean()),
        "std": float(array.std()),
        "quantiles": {str(value): float(np.quantile(array, value)) for value in _QUANTILES},
    }


def _valid_rows(tensor: torch.Tensor, mask: torch.Tensor | None) -> torch.Tensor:
    if tensor.ndim < 2:
        raise ValueError("geometry tensor must have at least two dimensions")
    rows = tensor.detach().reshape(-1, tensor.shape[-1])
    if mask is None:
        return rows
    valid = mask.detach().to(device=tensor.device).bool().reshape(-1)
    if valid.numel() != rows.shape[0]:
        raise ValueError("mask does not match tensor row dimensions")
    return rows[valid]


def summarize_tensor_geometry(
    tensor: torch.Tensor,
    mask: torch.Tensor | None = None,
) -> dict[str, Any]:
    rows = _valid_rows(tensor, mask).to(dtype=torch.float64, device="cpu")
    if rows.numel() == 0:
        return {
            "shape": list(tensor.shape),
            "valid_rows": 0,
            "feature_dim": int(tensor.shape[-1]),
            "norm": _distribution(rows),
            "per_dimension_variance_mean": None,
            "effective_rank": 0.0,
        }
    centered = rows - rows.mean(dim=0, keepdim=True)
    singular_values = torch.linalg.svdvals(centered)
    spectrum = singular_values.square()
    total = float(spectrum.sum())
    if total <= 0.0:
        effective_rank = 0.0
    else:
        probabilities = spectrum / spectrum.sum()
        positive = probabilities > 0
        entropy = -(probabilities[positive] * probabilities[positive].log()).sum()
        effective_rank = float(entropy.exp())
    return {
        "shape": list(tensor.shape),
        "valid_rows": int(rows.shape[0]),
        "feature_dim": int(rows.shape[1]),
        "norm": _distribution(torch.linalg.vector_norm(rows, dim=-1)),
        "per_dimension_variance_mean": float(rows.var(dim=0, unbiased=False).mean()),
        "effective_rank": effective_rank,
    }


def summarize_temporal_logits(
    logits: torch.Tensor,
    labels: torch.Tensor,
    mask: torch.Tensor,
) -> dict[str, Any]:
    if logits.shape != labels.shape or logits.shape != mask.shape:
        raise ValueError("logits, labels and mask must have identical [B, T] shapes")
    if logits.ndim != 2:
        raise ValueError("temporal diagnostics require [B, T] tensors")
    valid = mask.detach().to(device=logits.device).bool()
    binary_labels = labels.detach().to(device=logits.device)
    if not torch.all((binary_labels[valid] == 0) | (binary_labels[valid] == 1)):
        raise ValueError("labels must be binary on valid segments")
    flat_logits = logits.detach()[valid]
    flat_labels = binary_labels[valid]
    within_sample = []
    for row_logits, row_mask in zip(logits.detach(), valid):
        values = row_logits[row_mask]
        if values.numel():
            within_sample.append(values.to(dtype=torch.float64).std(unbiased=False))
    within = (
        torch.stack(within_sample)
        if within_sample
        else torch.empty(0, dtype=torch.float64, device=logits.device)
    )
    return {
        "shape": list(logits.shape),
        "valid_segments": int(valid.sum()),
        "logits": _distribution(flat_logits),
        "probabilities": _distribution(torch.sigmoid(flat_logits)),
        "positive": _distribution(flat_logits[flat_labels == 1]),
        "negative": _distribution(flat_logits[flat_labels == 0]),
        "within_sample_logit_std": _distribution(within),
    }


def summarize_gate_weights(
    gate_weights: torch.Tensor,
    mask: torch.Tensor,
) -> dict[str, Any]:
    if gate_weights.ndim != 3 or gate_weights.shape[-1] != 2:
        raise ValueError("gate_weights must have shape [B, T, 2]")
    rows = _valid_rows(gate_weights, mask).to(dtype=torch.float64, device="cpu")
    if rows.numel() == 0:
        return {
            "valid_rows": 0,
            "visual": _distribution(rows),
            "audio": _distribution(rows),
            "entropy": _distribution(rows),
            "saturation_rate_at_0_95": None,
        }
    entropy = -(rows.clamp_min(1e-12) * rows.clamp_min(1e-12).log()).sum(dim=-1)
    return {
        "valid_rows": int(rows.shape[0]),
        "visual": _distribution(rows[:, 0]),
        "audio": _distribution(rows[:, 1]),
        "entropy": _distribution(entropy),
        "saturation_rate_at_0_95": float((rows.max(dim=-1).values >= 0.95).double().mean()),
    }


def module_gradient_norm(module: nn.Module) -> float:
    squared = 0.0
    for parameter in module.parameters():
        if parameter.grad is not None:
            gradient = parameter.grad.detach().to(dtype=torch.float64)
            squared += float(gradient.square().sum())
    return math.sqrt(squared)


def snapshot_parameters(module: nn.Module) -> dict[str, torch.Tensor]:
    return {
        name: parameter.detach().to(device="cpu", dtype=torch.float64).clone()
        for name, parameter in module.named_parameters()
    }


def parameter_drift(
    module: nn.Module,
    initial: Mapping[str, torch.Tensor],
) -> dict[str, float]:
    absolute_squared = 0.0
    initial_squared = 0.0
    current_names: set[str] = set()
    for name, parameter in module.named_parameters():
        current_names.add(name)
        if name not in initial:
            raise KeyError(f"initial parameter snapshot missing {name}")
        current = parameter.detach().to(device="cpu", dtype=torch.float64)
        reference = initial[name]
        if current.shape != reference.shape:
            raise ValueError(f"parameter shape changed for {name}")
        absolute_squared += float((current - reference).square().sum())
        initial_squared += float(reference.square().sum())
    if current_names != set(initial):
        raise KeyError("initial parameter snapshot contains stale names")
    absolute = math.sqrt(absolute_squared)
    baseline = math.sqrt(initial_squared)
    return {
        "absolute_l2": absolute,
        "relative_l2": absolute / max(baseline, 1e-12),
    }


def _module_map(student: nn.Module, loss_module: nn.Module) -> dict[str, nn.Module]:
    names = {
        "student_visual_encoder": "visual_encoder",
        "student_audio_encoder": "audio_encoder",
        "student_visual_projection": "visual_proj",
        "student_audio_projection": "audio_proj",
        "student_text_projection": "text_proj",
        "student_modality_gate": "modality_gate",
        "student_token_fusion": "token_fusion",
        "student_temporal_encoder": "temporal_encoder",
        "student_decision_projection": "decision_proj",
        "student_audio_aux_projection": "audio_aux_proj",
        "student_query_projection": "query_proj",
        "student_segment_head": "segment_head",
    }
    modules = {
        output_name: getattr(student, attribute)
        for output_name, attribute in names.items()
        if isinstance(getattr(student, attribute, None), nn.Module)
    }
    for name in ("strong_teacher_proj", "weak_teacher_proj", "text_teacher_proj"):
        module = getattr(loss_module, name, None)
        if isinstance(module, nn.Module):
            modules[f"loss_{name}"] = module
    return modules


def diagnostic_parameter_snapshots(
    student: nn.Module,
    loss_module: nn.Module,
) -> dict[str, dict[str, torch.Tensor]]:
    return {
        name: snapshot_parameters(module)
        for name, module in _module_map(student, loss_module).items()
        if name.startswith("loss_") or name == "student_segment_head"
    }


def collect_training_diagnostic(
    *,
    student: nn.Module,
    loss_module: nn.Module,
    outputs: Mapping[str, torch.Tensor | None],
    batch: Mapping[str, Any],
    initial_parameters: Mapping[str, Mapping[str, torch.Tensor]],
    epoch: int,
    batch_index: int,
    global_step: int,
) -> dict[str, Any]:
    logits = outputs["segment_logits"]
    if logits is None:
        raise RuntimeError("student output is missing segment_logits")
    device = logits.device
    sequence_mask = batch["sequence_mask"].to(device)
    labels = batch["segment_label"].to(device)
    modules = _module_map(student, loss_module)
    geometries = {
        name: summarize_tensor_geometry(value, sequence_mask)
        for name, value in {
            "shared": outputs.get("shared_features"),
            "decision": outputs.get("decision_features"),
            "audio_aux": outputs.get("audio_aux_features"),
            "query": outputs.get("query_features"),
        }.items()
        if value is not None
    }
    teacher_targets: dict[str, Any] = {}
    with torch.no_grad():
        strong_teacher_proj = getattr(loss_module, "strong_teacher_proj", None)
        if isinstance(strong_teacher_proj, nn.Module):
            strong = strong_teacher_proj(
                batch["strong_teacher_features"].to(device)
            )
            teacher_targets["strong"] = summarize_tensor_geometry(
                strong,
                sequence_mask * batch["strong_teacher_feature_mask"].to(device),
            )
        weak_teacher_proj = getattr(loss_module, "weak_teacher_proj", None)
        if isinstance(weak_teacher_proj, nn.Module):
            weak = weak_teacher_proj(batch["weak_teacher_features"].to(device))
            teacher_targets["weak"] = summarize_tensor_geometry(
                weak,
                sequence_mask
                * batch["weak_teacher_feature_mask"].to(device)
                * batch["audio_valid"].to(device),
            )
        text_teacher_proj = getattr(loss_module, "text_teacher_proj", None)
        if isinstance(text_teacher_proj, nn.Module):
            text = text_teacher_proj(batch["text_embedding"].to(device))
            teacher_targets["text"] = summarize_tensor_geometry(
                text,
                batch["text_valid"].to(device),
            )
        elif outputs.get("text_alignment_target") is not None:
            teacher_targets["text"] = summarize_tensor_geometry(
                outputs["text_alignment_target"],
                batch["text_valid"].to(device),
            )
    head = getattr(student, "segment_head", None)
    head_stats = None
    if head is not None:
        head_stats = {
            "weight_l2": float(head.weight.detach().to(dtype=torch.float64).norm()),
            "bias": (
                [float(value) for value in head.bias.detach().cpu().reshape(-1)]
                if head.bias is not None
                else None
            ),
        }
    return {
        "schema_version": 1,
        "epoch": int(epoch),
        "batch_index": int(batch_index),
        "global_step_before_update": int(global_step),
        "temporal_logits": summarize_temporal_logits(logits, labels, sequence_mask),
        "gates": summarize_gate_weights(outputs["gate_weights"], sequence_mask),
        "student_geometry": geometries,
        "teacher_target_geometry": teacher_targets,
        "gradient_l2_before_clip": {
            name: module_gradient_norm(module) for name, module in modules.items()
        },
        "parameter_drift_from_initial": {
            name: parameter_drift(modules[name], snapshot)
            for name, snapshot in initial_parameters.items()
        },
        "segment_head": head_stats,
    }
