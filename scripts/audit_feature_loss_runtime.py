"""Read-only runtime decomposition of the visual feature-loss signal.

The module deliberately keeps the model and loss equations out of the audit's
aggregation logic.  It calls the locked student's forward path once, projects
the detached strong-teacher features exactly as the loss does, and applies the
proved mean/centered identity from :mod:`src.utils.feature_loss`.  No optimizer
or checkpoint state is touched.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import torch
from torch import nn

from src.utils.feature_loss import decompose_temporal_squared_error


_STUDENT_INPUTS = (
    "frame",
    "spectrogram",
    "text_embedding",
    "sequence_mask",
    "frame_valid",
    "audio_valid",
)

_MODULE_ALIASES = {
    "visual_encoder": ("visual_encoder", "visual_backbone", "frame_encoder"),
    "visual_projection": ("visual_projection", "visual_proj", "frame_projection"),
    "fusion": ("fusion", "token_fusion", "fusion_projection"),
    "temporal_encoder": ("temporal_encoder", "temporal"),
    "decision_projection": ("decision_projection", "decision_proj"),
    "segment_head": ("segment_head",),
}


def _to_device(value: Any, device: torch.device) -> Any:
    return value.to(device) if isinstance(value, torch.Tensor) else value


def _student_inputs(batch: Mapping[str, Any], device: torch.device) -> dict[str, Any]:
    missing = [key for key in _STUDENT_INPUTS if key not in batch]
    if missing:
        raise KeyError(f"runtime decomposition batch missing student inputs: {missing}")
    return {key: _to_device(batch[key], device) for key in _STUDENT_INPUTS}


def _module_parameters(module: nn.Module, aliases: tuple[str, ...]) -> list[nn.Parameter]:
    for alias in aliases:
        candidate = getattr(module, alias, None)
        if isinstance(candidate, nn.Module):
            return [parameter for parameter in candidate.parameters() if parameter.requires_grad]
    return []


def module_gradient_receipts(
    student: nn.Module,
    components: Mapping[str, torch.Tensor],
) -> dict[str, dict[str, dict[str, float | int | bool]]]:
    """Return per-component gradient norms for the named student modules.

    ``torch.autograd.grad`` is used instead of ``backward`` so the audit never
    changes ``parameter.grad``.  A missing or unused module is reported with a
    finite zero norm and does not make the audit fail.
    """

    resolved = {
        name: _module_parameters(student, aliases)
        for name, aliases in _MODULE_ALIASES.items()
    }
    receipts: dict[str, dict[str, dict[str, float | int | bool]]] = {}
    for component_name, component in components.items():
        if not isinstance(component, torch.Tensor):
            raise TypeError(f"component {component_name!r} must be a tensor")
        component_receipts: dict[str, dict[str, float | int | bool]] = {}
        for module_name, parameters in resolved.items():
            if not parameters or not component.requires_grad:
                norm = 0.0
            else:
                gradients = torch.autograd.grad(
                    component,
                    parameters,
                    allow_unused=True,
                    retain_graph=True,
                    create_graph=False,
                )
                squared = sum(
                    float(gradient.detach().float().square().sum().cpu())
                    for gradient in gradients
                    if gradient is not None
                )
                norm = float(np.sqrt(max(squared, 0.0)))
            component_receipts[module_name] = {
                "norm": norm,
                "nonzero": bool(norm > 0.0),
                "parameter_count": int(sum(parameter.numel() for parameter in parameters)),
            }
        receipts[component_name] = component_receipts
    return receipts


def _runtime_tensors(
    student: nn.Module,
    loss_module: nn.Module,
    batch: Mapping[str, Any],
    device: torch.device,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    previous_student_mode = student.training
    previous_loss_mode = loss_module.training
    try:
        # Evaluation mode prevents dropout and BatchNorm running-stat updates;
        # modes are restored in ``finally``.  Gradients remain enabled because
        # the caller may immediately request component-wise autograd receipts.
        student.eval()
        loss_module.eval()
        outputs = student(**_student_inputs(batch, device))
        decision = outputs.get("decision_features") if isinstance(outputs, Mapping) else None
        if not isinstance(decision, torch.Tensor):
            raise ValueError("student forward must return tensor decision_features")
        strong_features = _to_device(batch["strong_teacher_features"], device)
        sequence_mask = _to_device(batch["sequence_mask"], device)
        teacher_mask = _to_device(batch["strong_teacher_feature_mask"], device)
        labels = _to_device(batch["segment_label"], device)
        if not all(isinstance(value, torch.Tensor) for value in (strong_features, sequence_mask, teacher_mask, labels)):
            raise TypeError("runtime decomposition tensors must be torch tensors")
        projector = getattr(loss_module, "strong_teacher_proj", None)
        if not isinstance(projector, nn.Module):
            raise ValueError("loss module must expose strong_teacher_proj")
        target = projector(strong_features.detach())
        mask = sequence_mask * teacher_mask
        if decision.shape != target.shape:
            raise ValueError(
                "decision/target shape mismatch: "
                f"{tuple(decision.shape)} vs {tuple(target.shape)}"
            )
        if mask.shape != decision.shape[:2] or labels.shape != mask.shape:
            raise ValueError("runtime decomposition requires matching [B,T] masks and labels")
        return decision, target, mask, labels
    finally:
        student.train(previous_student_mode)
        loss_module.train(previous_loss_mode)


def _component_tensors(
    decision: torch.Tensor,
    target: torch.Tensor,
    mask: torch.Tensor,
) -> dict[str, torch.Tensor]:
    """Return differentiable normalized mean/centered components."""

    valid = mask.to(dtype=torch.bool)
    mean_terms: list[torch.Tensor] = []
    centered_terms: list[torch.Tensor] = []
    for index in range(decision.shape[0]):
        row = valid[index]
        count = int(row.sum().item())
        if count == 0:
            mean_terms.append(decision.new_zeros(()))
            centered_terms.append(decision.new_zeros(()))
            continue
        difference = decision[index, row] - target[index, row]
        mean_difference = difference.mean(dim=0)
        mean_terms.append(count * mean_difference.square().sum())
        centered_terms.append((difference - mean_difference).square().sum())
    denominator = max(int(valid.sum().item()) * int(decision.shape[-1]), 1)
    return {
        "mean": torch.stack(mean_terms).sum() / denominator,
        "centered": torch.stack(centered_terms).sum() / denominator,
    }


def decompose_runtime_batch(
    student: nn.Module,
    loss_module: nn.Module,
    batch: Mapping[str, Any],
    device: torch.device,
) -> dict[str, Any]:
    """Compute normalized mean/centered visual-loss components on one batch."""

    decision, target, mask, labels = _runtime_tensors(student, loss_module, batch, device)
    decomposition = decompose_temporal_squared_error(decision, target, mask, labels)
    valid_segments = int(mask.bool().sum().item())
    feature_dim = int(decision.shape[-1])
    reduction = str(getattr(loss_module, "visual_l2_reduction", "mean_feature_then_masked_mean_segments"))
    if reduction == "mean_feature_then_masked_mean_segments":
        denominator = max(valid_segments * feature_dim, 1)
    elif reduction == "sum_feature_then_masked_mean_segments":
        denominator = max(valid_segments, 1)
    else:
        raise ValueError(f"unsupported visual_l2_reduction: {reduction}")
    mean_term = float(decomposition["mean_term"].detach().cpu())
    centered_term = float(decomposition["temporal_term"].detach().cpu())
    total = float(decomposition["total"].detach().cpu())
    groups = decomposition["groups"]
    return {
        "schema_version": 1,
        "task_segments": int(decision.shape[1]),
        "valid_segments": valid_segments,
        "feature_dim": feature_dim,
        "visual_l2_reduction": reduction,
        "mean_term": mean_term,
        "centered_term": centered_term,
        "total": total,
        "identity_abs_error": abs(total - mean_term - centered_term),
        "normalization_denominator": denominator,
        "normalized_mean": mean_term / denominator,
        "normalized_centered": centered_term / denominator,
        "normalized_total": total / denominator,
        "groups": groups,
    }


def audit_model_checkpoint(
    config_path: str | Path,
    checkpoint_path: str | Path | None,
    *,
    output_dir: str | Path,
    max_batches: int = 1,
) -> dict[str, Any]:
    """Run one fixed train-batch audit in the locked runtime, without writes."""

    if max_batches != 1:
        raise ValueError("runtime audit is intentionally bounded to exactly one batch")
    # Heavy model/data imports stay inside the CLI path so pure unit tests do
    # not require optional vision packages.
    from scripts.train_ov_orthkd import (
        build_model_and_loss,
        build_runtime_reproduction_fingerprint,
        create_ov_avel_data_loaders,
        load_config,
        load_evaluation_checkpoint,
        set_seed,
    )

    config = load_config(str(config_path))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    set_seed(int(config.get("seed", 42)), deterministic=bool(config.get("training", {}).get("deterministic", True)))
    student, loss_module = build_model_and_loss(config, device)
    checkpoint_sha = None
    if checkpoint_path is not None:
        checkpoint_sha = _sha256_file(checkpoint_path)
        load_evaluation_checkpoint(
            student=student,
            resume_path=str(checkpoint_path),
            expected_fingerprint=build_runtime_reproduction_fingerprint(config),
            allow_incompatible=True,
            incompatible_marker_path=Path(output_dir) / "INCOMPATIBLE_RESUME.txt",
        )
    train_loader, _, _ = create_ov_avel_data_loaders(config)
    batch = next(iter(train_loader))
    result = decompose_runtime_batch(student, loss_module, batch, device)
    decision, target, mask, _ = _runtime_tensors(student, loss_module, batch, device)
    components = _component_tensors(decision, target.detach(), mask)
    result["gradient_receipts"] = module_gradient_receipts(student, components)
    result["checkpoint_sha256"] = checkpoint_sha
    result["device"] = str(device)
    result["batch_ids"] = [str(value) for value in batch.get("id", [])]
    return result


def _sha256_file(path: str | Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    raise TypeError(type(value).__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="NPZ with student, target, mask, labels arrays")
    parser.add_argument("--config", type=Path, help="Locked runtime config for a one-batch model audit")
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.config is not None:
        if args.input is not None:
            raise ValueError("use either --input or --config, not both")
        payload = audit_model_checkpoint(
            args.config,
            args.checkpoint,
            output_dir=args.output.parent,
            max_batches=1,
        )
    else:
        if args.input is None or args.checkpoint is not None:
            raise ValueError("--input is required for NPZ mode and cannot be combined with --checkpoint")
        with np.load(args.input, allow_pickle=False) as data:
            required = {"student", "target", "mask", "labels"}
            missing = required - set(data.files)
            if missing:
                raise ValueError(f"input NPZ missing arrays: {sorted(missing)}")
            student = torch.from_numpy(np.asarray(data["student"]))
            target = torch.from_numpy(np.asarray(data["target"]))
            mask = torch.from_numpy(np.asarray(data["mask"]))
            labels = torch.from_numpy(np.asarray(data["labels"]))
        result = decompose_temporal_squared_error(student, target, mask, labels)
        total = float(result["total"])
        mean_term = float(result["mean_term"])
        centered_term = float(result["temporal_term"])
        payload = {
            "schema_version": 1,
            "student_shape": list(student.shape),
            "target_shape": list(target.shape),
            "mask_shape": list(mask.shape),
            "mean_term": mean_term,
            "centered_term": centered_term,
            "total": total,
            "identity_abs_error": abs(total - mean_term - centered_term),
            "groups": result["groups"],
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, default=_json_default))


if __name__ == "__main__":
    main()
