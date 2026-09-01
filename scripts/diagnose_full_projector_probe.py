#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

import torch
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.temporal_protocol import task_segments_from_config  # noqa: E402


def _module_state_sha256(module: torch.nn.Module) -> str:
    digest = hashlib.sha256()
    for name, tensor in sorted(module.state_dict().items()):
        value = tensor.detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(value.dtype).encode("ascii"))
        digest.update(json.dumps(list(value.shape)).encode("ascii"))
        digest.update(value.numpy().tobytes(order="C"))
    return digest.hexdigest()


def _tensor_sha256(tensor: torch.Tensor) -> str:
    value = tensor.detach().cpu().contiguous()
    digest = hashlib.sha256()
    digest.update(str(value.dtype).encode("ascii"))
    digest.update(json.dumps(list(value.shape)).encode("ascii"))
    digest.update(value.numpy().tobytes(order="C"))
    return digest.hexdigest()


def _module_gradient_l2(module: torch.nn.Module) -> float:
    squared = 0.0
    found = False
    for parameter in module.parameters():
        if parameter.grad is None:
            continue
        found = True
        gradient = parameter.grad.detach().to(dtype=torch.float64)
        if not bool(torch.isfinite(gradient).all()):
            raise ValueError("Projector gradient contains NaN/Inf")
        squared += float(gradient.square().sum())
    if not found:
        raise ValueError("Projector received no gradient")
    return math.sqrt(squared)


def _target_variance(target: torch.Tensor, mask: torch.Tensor) -> float:
    rows = target.detach()[mask.bool()].to(dtype=torch.float64)
    if rows.numel() == 0:
        raise ValueError("Target variance requires at least one valid row")
    return float(rows.var(dim=0, unbiased=False).mean())


def _validate_probe_inputs(
    *,
    projector: torch.nn.Module,
    decision_features: torch.Tensor,
    teacher_features: torch.Tensor,
    mask: torch.Tensor,
    learning_rate: float,
) -> tuple[int, int]:
    if not isinstance(projector, torch.nn.Module):
        raise TypeError("projector must be a torch module")
    if decision_features.ndim != 3 or teacher_features.ndim != 3:
        raise ValueError("Decision and teacher features must have shape [B,T,D]")
    if tuple(decision_features.shape[:2]) != tuple(teacher_features.shape[:2]):
        raise ValueError("Decision and teacher leading shapes differ")
    if mask.ndim != 2 or tuple(mask.shape) != tuple(decision_features.shape[:2]):
        raise ValueError("Mask must match feature [B,T] dimensions")
    if not bool(mask.bool().any()):
        raise ValueError("Probe mask contains no valid rows")
    if not all(
        bool(torch.isfinite(value).all())
        for value in (decision_features, teacher_features, mask)
    ):
        raise ValueError("Probe tensors contain NaN/Inf")
    if not math.isfinite(float(learning_rate)) or float(learning_rate) <= 0.0:
        raise ValueError("learning_rate must be finite and positive")
    if any(parameter.grad is not None for parameter in projector.parameters()):
        raise ValueError("Source projector must have empty gradient fields")
    if not any(parameter.requires_grad for parameter in projector.parameters()):
        raise ValueError("Source projector has no trainable parameters")
    return int(decision_features.shape[-1]), int(mask.bool().sum())


def _masked_feature_loss(
    decision: torch.Tensor,
    target: torch.Tensor,
    mask: torch.Tensor,
    *,
    reduction: str,
) -> torch.Tensor:
    squared = (decision - target).square()
    if reduction == "mean_feature_then_masked_mean_segments":
        terms = squared.mean(dim=-1)
    elif reduction == "sum_feature_then_masked_mean_segments":
        terms = squared.sum(dim=-1)
    else:
        raise ValueError(f"Unsupported reduction: {reduction}")
    weights = mask.to(device=terms.device, dtype=terms.dtype)
    return (terms * weights).sum() / weights.sum().clamp_min(1.0)


def _reduction_probe(
    *,
    projector: torch.nn.Module,
    decision_features: torch.Tensor,
    teacher_features: torch.Tensor,
    mask: torch.Tensor,
    reduction: str,
) -> dict[str, Any]:
    clone = copy.deepcopy(projector)
    clone.zero_grad(set_to_none=True)
    decision = decision_features.detach().clone().requires_grad_(True)
    target = clone(teacher_features.detach())
    if target.shape != decision.shape:
        raise ValueError(
            f"Projected teacher shape {tuple(target.shape)} != decision shape {tuple(decision.shape)}"
        )
    loss = _masked_feature_loss(
        decision, target, mask, reduction=reduction
    )
    loss.backward()
    if decision.grad is None or not bool(torch.isfinite(decision.grad).all()):
        raise ValueError("Student-decision gradient is missing or non-finite")
    return {
        "loss": float(loss.detach()),
        "gradient_l2": {
            "projector": _module_gradient_l2(clone),
            "student_decision": float(
                decision.grad.detach().to(dtype=torch.float64).norm()
            ),
        },
        "projected_target_variance": _target_variance(target, mask),
    }


def probe_strong_projector(
    *,
    projector: torch.nn.Module,
    decision_features: torch.Tensor,
    teacher_features: torch.Tensor,
    mask: torch.Tensor,
    learning_rate: float,
) -> dict[str, Any]:
    feature_dimension, valid_rows = _validate_probe_inputs(
        projector=projector,
        decision_features=decision_features,
        teacher_features=teacher_features,
        mask=mask,
        learning_rate=learning_rate,
    )
    source_before = _module_state_sha256(projector)
    reductions = {
        reduction: _reduction_probe(
            projector=projector,
            decision_features=decision_features,
            teacher_features=teacher_features,
            mask=mask,
            reduction=reduction,
        )
        for reduction in (
            "mean_feature_then_masked_mean_segments",
            "sum_feature_then_masked_mean_segments",
        )
    }
    mean = reductions["mean_feature_then_masked_mean_segments"]
    summed = reductions["sum_feature_then_masked_mean_segments"]
    for name, result in reductions.items():
        checked = (
            float(result["loss"]),
            float(result["gradient_l2"]["projector"]),
            float(result["gradient_l2"]["student_decision"]),
        )
        if any(not math.isfinite(value) or value <= 0.0 for value in checked):
            raise ValueError(
                f"Reduction {name} did not produce finite non-zero loss/gradients"
            )
    expected_factor = float(feature_dimension)
    ratios = {
        "loss": summed["loss"] / mean["loss"],
        "projector_gradient": (
            summed["gradient_l2"]["projector"]
            / mean["gradient_l2"]["projector"]
        ),
        "student_decision_gradient": (
            summed["gradient_l2"]["student_decision"]
            / mean["gradient_l2"]["student_decision"]
        ),
    }
    if any(
        not math.isclose(value, expected_factor, rel_tol=1e-9, abs_tol=1e-10)
        for value in ratios.values()
    ):
        raise RuntimeError("Mean/sum loss or gradient ratio is not feature dimension")

    update_clone = copy.deepcopy(projector)
    update_clone.zero_grad(set_to_none=True)
    decision_parameter = torch.nn.Parameter(decision_features.detach().clone())
    optimizer = torch.optim.AdamW(
        [*update_clone.parameters(), decision_parameter],
        lr=float(learning_rate),
    )
    clone_before = _module_state_sha256(update_clone)
    decision_before = _tensor_sha256(decision_parameter)
    target_before = update_clone(teacher_features.detach())
    variance_before = _target_variance(target_before, mask)
    update_loss = _masked_feature_loss(
        decision_parameter,
        target_before,
        mask,
        reduction="sum_feature_then_masked_mean_segments",
    )
    update_loss.backward()
    optimizer.step()
    clone_after = _module_state_sha256(update_clone)
    decision_after = _tensor_sha256(decision_parameter)
    with torch.no_grad():
        target_after = update_clone(teacher_features.detach())
    variance_after = _target_variance(target_after, mask)
    source_after = _module_state_sha256(projector)
    if source_before != source_after:
        raise RuntimeError("Disposable probe mutated the source projector")
    if clone_before == clone_after:
        raise RuntimeError("Disposable AdamW step did not change projector clone state")
    if decision_before == decision_after:
        raise RuntimeError("Disposable AdamW step did not change decision clone state")
    if any(parameter.grad is not None for parameter in projector.parameters()):
        raise RuntimeError("Disposable probe populated source projector gradients")

    return {
        "feature_dimension": feature_dimension,
        "valid_rows": valid_rows,
        "reductions": reductions,
        "mean_to_sum_expected_factor": expected_factor,
        "mean_to_sum_observed_ratios": ratios,
        "source_projector": {
            "state_sha256_before": source_before,
            "state_sha256_after": source_after,
            "gradients_remained_none": True,
        },
        "disposable_adamw_step": {
            "optimizer": "AdamW",
            "learning_rate": float(learning_rate),
            "weight_decay": float(optimizer.param_groups[0]["weight_decay"]),
            "reduction": "sum_feature_then_masked_mean_segments",
            "loss_before_step": float(update_loss.detach()),
            "clone_state_sha256_before": clone_before,
            "clone_state_sha256_after": clone_after,
            "clone_state_changed": True,
            "decision_sha256_before": decision_before,
            "decision_sha256_after": decision_after,
            "decision_changed": True,
            "target_variance_before": variance_before,
            "target_variance_after": variance_after,
            "source_state_unchanged": True,
            "persisted": False,
        },
    }


def _sha256_file(path: Path) -> str:
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
        "sha256": _sha256_file(source),
    }


def _canonical_mapping_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Disposable one-batch Full strong-projector gradient probe"
    )
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--git", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    temporary = output.with_name(output.name + ".tmp")
    if output.exists() or temporary.exists():
        raise FileExistsError(f"Refusing to overwrite probe output: {output}")
    repo = args.repo.resolve()
    if _run_git(args.git, repo, "rev-parse", "HEAD") != args.expected_commit:
        raise RuntimeError("Probe repository is not at expected commit")
    if _run_git(
        args.git, repo, "status", "--porcelain=v1", "--untracked-files=all"
    ):
        raise RuntimeError("Probe repository must be clean")
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")
    device = torch.device(args.device)

    sys.path.insert(0, str(repo))
    os.chdir(repo)
    from scripts.train_ov_orthkd import build_model_and_loss, set_seed  # noqa: PLC0415
    from src.data import create_ov_avel_data_loaders  # noqa: PLC0415

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or task_segments_from_config(config) != 10:
        raise ValueError("Full projector probe requires exact official T=10 config")
    config_sha = _canonical_mapping_sha256(config)
    set_seed(
        int(config.get("seed", 42)),
        deterministic=bool(config.get("training", {}).get("deterministic", True)),
    )
    student, loss_module = build_model_and_loss(config, device)
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    if not isinstance(checkpoint, dict):
        raise ValueError("Checkpoint is not a mapping")
    embedded_config = checkpoint.get("config")
    if not isinstance(embedded_config, Mapping) or _canonical_mapping_sha256(
        embedded_config
    ) != config_sha:
        raise ValueError("Full checkpoint config does not match source config")
    student_incompatible = student.load_state_dict(
        checkpoint["student_state_dict"], strict=True
    )
    loss_incompatible = loss_module.load_state_dict(
        checkpoint["loss_state_dict"], strict=True
    )
    if (
        student_incompatible.missing_keys
        or student_incompatible.unexpected_keys
        or loss_incompatible.missing_keys
        or loss_incompatible.unexpected_keys
    ):
        raise RuntimeError("Strict Full checkpoint state loading failed")
    projector = getattr(loss_module, "strong_teacher_proj", None)
    if not isinstance(projector, torch.nn.Module):
        raise RuntimeError("Full loss has no strong_teacher_proj")
    source_projector_sha = _module_state_sha256(projector)

    train_loader, validation_loader, test_loader = create_ov_avel_data_loaders(config)
    del validation_loader, test_loader
    try:
        batch = next(iter(train_loader))
    except StopIteration as exc:
        raise RuntimeError("Full train loader is empty") from exc
    student.eval()
    with torch.no_grad():
        outputs = student(
            frame=batch["frame"].to(device),
            spectrogram=batch["spectrogram"].to(device),
            text_embedding=batch["text_embedding"].to(device),
            sequence_mask=batch["sequence_mask"].to(device),
            frame_valid=batch["frame_valid"].to(device),
            audio_valid=batch["audio_valid"].to(device),
        )
    decision = outputs.get("decision_features")
    if not isinstance(decision, torch.Tensor):
        raise RuntimeError("Full student did not return decision_features")
    teacher = batch["strong_teacher_features"].to(device)
    mask = (
        batch["sequence_mask"] * batch["strong_teacher_feature_mask"]
    ).to(device)
    learning_rate = float(config.get("training", {}).get("learning_rate", 0.0))
    probe = probe_strong_projector(
        projector=projector,
        decision_features=decision,
        teacher_features=teacher,
        mask=mask,
        learning_rate=learning_rate,
    )
    if _module_state_sha256(projector) != source_projector_sha:
        raise RuntimeError("Real-batch probe mutated loaded Full projector")
    report = {
        "schema_version": 1,
        "status": "PASS",
        "claim_level": "disposable_one_batch_full_projector_probe",
        "protocol": {
            "task_segments": 10,
            "temporal_conversion": "forbidden",
            "batch_index": 0,
            "optimizer_steps_on_source": 0,
            "optimizer_steps_on_disposable_clone": 1,
            "updated_checkpoint_written": False,
        },
        "git": {
            "implementation_commit": args.expected_commit,
            "status": "clean",
        },
        "sources": {
            "config": _source_receipt(args.config),
            "checkpoint": _source_receipt(args.checkpoint),
            "checkpoint_global_step": int(checkpoint.get("global_step", -1)),
            "strict_student_state_load": True,
            "strict_loss_state_load": True,
            "source_projector_state_sha256": source_projector_sha,
        },
        "batch": {
            "sample_count": int(decision.shape[0]),
            "task_segments": int(decision.shape[1]),
            "strong_teacher_dimension": int(teacher.shape[-1]),
            "projection_dimension": int(decision.shape[-1]),
            "valid_rows": int(mask.bool().sum()),
        },
        "probe": probe,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
