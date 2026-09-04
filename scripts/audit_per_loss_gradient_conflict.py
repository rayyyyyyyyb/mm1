"""Measure per-loss gradients on the same fixed student modules.

This is a read-only diagnostic.  It uses ``autograd.grad`` (never
``backward``), evaluates BCE, weighted visual feature loss, and weighted text
alignment on one batch, and reports pairwise cosines only where both vectors
have non-negligible norms.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn

from scripts.audit_feature_loss_runtime import _MODULE_ALIASES, _module_parameters, _student_inputs, _to_device


def _paper_text_alignment_terms(
    student_query_features: torch.Tensor,
    projected_text_target: torch.Tensor,
    segment_labels: torch.Tensor,
    eps: float = 1e-6,
) -> torch.Tensor:
    """Local copy of the paper-probability text term to keep the audit light.

    Importing the full loss module would eagerly import the optional timm
    vision dependency; this algebra is intentionally identical to the locked
    implementation and is covered by the loss tests.
    """

    with torch.autocast(device_type=student_query_features.device.type, enabled=False):
        query_fp32 = student_query_features.float()
        target_fp32 = projected_text_target.float()[:, None, :].expand_as(query_fp32)
        labels_fp32 = segment_labels.float()
        cosine = F.cosine_similarity(query_fp32, target_fp32, dim=-1)
        probability = ((cosine + 1.0) * 0.5).clamp(min=eps, max=1.0 - eps)
        return F.binary_cross_entropy(probability, labels_fp32, reduction="none")


def _masked_mean(values: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    if values.shape != mask.shape:
        raise ValueError(f"values/mask shape mismatch: {values.shape} vs {mask.shape}")
    work_mask = mask.to(dtype=values.dtype)
    return (values * work_mask).sum() / work_mask.sum().clamp_min(1.0)


def _loss_components(
    outputs: Mapping[str, torch.Tensor],
    loss_module: nn.Module,
    batch: Mapping[str, Any],
    device: torch.device,
) -> dict[str, torch.Tensor]:
    logits = outputs.get("segment_logits")
    decision = outputs.get("decision_features")
    query = outputs.get("query_features")
    if not all(isinstance(value, torch.Tensor) for value in (logits, decision, query)):
        raise ValueError("student output must contain segment_logits, decision_features, query_features")
    labels = _to_device(batch["segment_label"], device)
    sequence_mask = _to_device(batch["sequence_mask"], device)
    strong_mask = _to_device(batch["strong_teacher_feature_mask"], device)
    if not all(isinstance(value, torch.Tensor) for value in (labels, sequence_mask, strong_mask)):
        raise TypeError("loss-gradient audit requires tensor labels and masks")
    bce = _masked_mean(F.binary_cross_entropy_with_logits(logits, labels.float(), reduction="none"), sequence_mask)

    projector = getattr(loss_module, "strong_teacher_proj", None)
    strong_features = _to_device(batch["strong_teacher_features"], device)
    if not isinstance(projector, nn.Module) or not isinstance(strong_features, torch.Tensor):
        raise ValueError("loss module/batch must expose strong_teacher_proj and strong_teacher_features")
    target = projector(strong_features.detach())
    squared = (decision - target).pow(2)
    reduction = str(getattr(loss_module, "visual_l2_reduction", "mean_feature_then_masked_mean_segments"))
    visual_terms = squared.mean(dim=-1) if reduction == "mean_feature_then_masked_mean_segments" else squared.sum(dim=-1)
    if reduction not in {"mean_feature_then_masked_mean_segments", "sum_feature_then_masked_mean_segments"}:
        raise ValueError(f"unsupported visual_l2_reduction: {reduction}")
    visual = _masked_mean(visual_terms, sequence_mask * strong_mask)

    text_valid = _to_device(batch.get("text_valid", torch.ones(labels.shape[0])), device)
    text_embeddings = _to_device(batch.get("text_embedding"), device)
    if not isinstance(text_valid, torch.Tensor):
        raise TypeError("text_valid must be a tensor")
    if getattr(loss_module, "query_anchor_mode", "independent_loss_projection") == "shared_fusion_projection":
        text_target = outputs.get("text_alignment_target")
    else:
        text_projector = getattr(loss_module, "text_teacher_proj", None)
        if not isinstance(text_projector, nn.Module) or not isinstance(text_embeddings, torch.Tensor):
            raise ValueError("independent text alignment requires text_teacher_proj and text_embedding")
        text_target = text_projector(text_embeddings.detach())
    if not isinstance(text_target, torch.Tensor) or text_target.shape != query.shape[:1] + query.shape[2:]:
        raise ValueError(f"student query/text target shape mismatch: {getattr(query, 'shape', None)} vs {getattr(text_target, 'shape', None)}")
    mode = str(getattr(loss_module, "text_alignment_mode", "paper_probability"))
    if mode == "paper_probability":
        text_terms = _paper_text_alignment_terms(query, text_target, labels)
    elif mode == "legacy_logit_temperature":
        expanded = text_target[:, None, :].expand_as(query)
        text_logits = F.cosine_similarity(query, expanded, dim=-1) / float(getattr(loss_module, "temperature", 2.0))
        text_terms = F.binary_cross_entropy_with_logits(text_logits, labels.float(), reduction="none")
    else:
        raise ValueError(f"unsupported text_alignment_mode: {mode}")
    text = _masked_mean(text_terms, sequence_mask * text_valid[:, None])
    return {
        "bce": float(getattr(loss_module, "alpha_bce", 1.0)) * bce,
        "visual": float(getattr(loss_module, "alpha_strong_feat", 0.4)) * visual,
        "text": float(getattr(loss_module, "alpha_text_align", 0.8)) * text,
    }


def _gradient_vector(loss: torch.Tensor, parameters: list[nn.Parameter]) -> torch.Tensor:
    if not parameters or not loss.requires_grad:
        device = loss.device
        return torch.zeros(0, device=device, dtype=torch.float32)
    gradients = torch.autograd.grad(loss, parameters, allow_unused=True, retain_graph=True, create_graph=False)
    return torch.cat(
        [
            (gradient.detach().float().reshape(-1) if gradient is not None else torch.zeros(parameter.numel(), device=loss.device))
            for parameter, gradient in zip(parameters, gradients)
        ]
    )


def collect_loss_gradients(
    student: nn.Module,
    loss_module: nn.Module,
    batch: Mapping[str, Any],
    device: torch.device,
) -> dict[str, dict[str, Any]]:
    """Collect weighted loss gradients without changing parameters or ``.grad``."""

    previous_student_mode = student.training
    previous_loss_mode = loss_module.training
    try:
        student.eval()
        loss_module.eval()
        outputs = student(**_student_inputs(batch, device))
        components = _loss_components(outputs, loss_module, batch, device)
        resolved = {name: _module_parameters(student, aliases) for name, aliases in _MODULE_ALIASES.items()}
        payload: dict[str, dict[str, Any]] = {}
        for loss_name, value in components.items():
            gradients = {name: _gradient_vector(value, parameters) for name, parameters in resolved.items()}
            modules = {
                name: {
                    "norm": float(torch.linalg.vector_norm(vector).cpu()),
                    "parameter_count": int(vector.numel()),
                }
                for name, vector in gradients.items()
            }
            payload[loss_name] = {"value": float(value.detach().cpu()), "gradients": gradients, "modules": modules}
        return payload
    finally:
        student.train(previous_student_mode)
        loss_module.train(previous_loss_mode)


def _as_vector(value: Any) -> np.ndarray:
    if isinstance(value, torch.Tensor):
        return value.detach().float().cpu().numpy().reshape(-1)
    return np.asarray(value, dtype=np.float64).reshape(-1)


def _cosine(left: np.ndarray, right: np.ndarray, threshold: float = 1e-12) -> float | None:
    if left.shape != right.shape:
        return None
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denominator <= threshold:
        return None
    return float(np.dot(left, right) / denominator)


def summarize_pairwise_cosines(receipts: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    names = ("bce", "visual", "text")
    pair_names = (("bce", "visual"), ("text", "visual"), ("bce", "text"))
    pairs: dict[str, Any] = {}
    for left_name, right_name in pair_names:
        left_gradients = receipts.get(left_name, {}).get("gradients", {})
        right_gradients = receipts.get(right_name, {}).get("gradients", {})
        module_cosines = []
        for module_name in sorted(set(left_gradients) & set(right_gradients)):
            cosine = _cosine(_as_vector(left_gradients[module_name]), _as_vector(right_gradients[module_name]))
            if cosine is not None and np.isfinite(cosine):
                module_cosines.append(cosine)
        values = np.asarray(module_cosines, dtype=np.float64)
        pairs[f"{left_name}_vs_{right_name}"] = {
            "values": module_cosines,
            "finite_count": int(values.size),
            "mean": None if values.size == 0 else float(values.mean()),
            "median": None if values.size == 0 else float(np.median(values)),
            "negative_fraction": None if values.size == 0 else float(np.mean(values < 0.0)),
        }
    visual_pair = pairs["bce_vs_visual"]
    text_pair = pairs["text_vs_visual"]
    conflict = any(
        pair["median"] is not None and pair["median"] < -0.2
        for pair in (visual_pair, text_pair)
    )
    classification = "INTRINSIC_GRADIENT_CONFLICT" if conflict else "GRADIENT_CONFLICT_NOT_YET_IDENTIFIED"
    return {"losses": list(names), "pairs": pairs, "classification": classification}


def audit_model_checkpoint(
    config_path: str | Path,
    checkpoint_path: str | Path | None,
    *,
    output_dir: str | Path,
    max_batches: int = 1,
) -> dict[str, Any]:
    """Run one fixed train-batch gradient audit in the locked environment."""

    if max_batches != 1:
        raise ValueError("per-loss gradient audit is intentionally bounded to one batch")
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
        import hashlib

        checkpoint_sha = hashlib.sha256(Path(checkpoint_path).read_bytes()).hexdigest()
        load_evaluation_checkpoint(
            student=student,
            resume_path=str(checkpoint_path),
            expected_fingerprint=build_runtime_reproduction_fingerprint(config),
            allow_incompatible=True,
            incompatible_marker_path=Path(output_dir) / "INCOMPATIBLE_RESUME.txt",
        )
    train_loader, _, _ = create_ov_avel_data_loaders(config)
    batch = next(iter(train_loader))
    receipts = collect_loss_gradients(student, loss_module, batch, device)
    summary = summarize_pairwise_cosines(receipts)
    compact_receipts = {
        name: {"value": value["value"], "modules": value["modules"]}
        for name, value in receipts.items()
    }
    return {
        "schema_version": 1,
        "device": str(device),
        "checkpoint_sha256": checkpoint_sha,
        "batch_ids": [str(value) for value in batch.get("id", [])],
        "receipts": compact_receipts,
        "summary": summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="NPZ batch fixture; use --config for real model batches")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.config is not None:
        if args.input is not None:
            raise ValueError("use either --input or --config, not both")
        payload = audit_model_checkpoint(args.config, args.checkpoint, output_dir=args.output.parent, max_batches=1)
    else:
        if args.input is None or args.checkpoint is not None:
            raise ValueError("--input is required when --config is not supplied")
        with np.load(args.input, allow_pickle=False) as loaded:
            vectors = {
                name: {key.removeprefix(f"{name}_"): torch.from_numpy(loaded[key]) for key in loaded.files if key.startswith(f"{name}_")}
                for name in ("bce", "visual", "text")
            }
        payload = summarize_pairwise_cosines(vectors)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=lambda value: value.detach().cpu().tolist() if isinstance(value, torch.Tensor) else value) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, default=lambda value: value.detach().cpu().tolist() if isinstance(value, torch.Tensor) else value))


if __name__ == "__main__":
    main()
