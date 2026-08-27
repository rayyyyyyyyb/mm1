#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import platform
import random
import subprocess
import sys
import time
import warnings
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import numpy as np
import torch
import torch.nn as nn
import yaml
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from torch.optim import AdamW
from torch.optim.lr_scheduler import CosineAnnealingLR, StepLR
from tqdm import tqdm

try:
    from torch.amp import GradScaler as TorchGradScaler

    def make_grad_scaler(device_type: str, enabled: bool) -> TorchGradScaler:
        return TorchGradScaler(device=device_type, enabled=enabled)

    def autocast_context(device_type: str, enabled: bool):
        return torch.amp.autocast(device_type=device_type, enabled=enabled)

except (ImportError, AttributeError):
    from torch.cuda.amp import GradScaler as TorchGradScaler
    from torch.cuda.amp import autocast as cuda_autocast

    def make_grad_scaler(device_type: str, enabled: bool) -> TorchGradScaler:
        del device_type
        return TorchGradScaler(enabled=enabled)

    def autocast_context(device_type: str, enabled: bool):
        del device_type
        return cuda_autocast(enabled=enabled)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.data import create_ov_avel_data_loaders
from src.data.split_types import normalize_split_type, split_type_from_record
from src.evaluation.ovavel_metrics import (
    binary_f1,
    compute_ovavel_metrics,
    compute_thresholded_ovavel_metrics,
)
from src.losses import OVOrthKDLoss, OVOrthKDLegacyLoss
from src.models import OVOrthKDStudent
from src.utils.atomic_artifacts import canonical_tree_hash
from src.utils.canonical_readiness import validate_canonical_readiness
from src.utils.temporal_protocol import (
    task_segments_from_config,
    validate_temporal_alignment,
)
from src.utils.temporal_protocol import max_position_segments_from_config
from src.utils.reproduction_fingerprint import (
    build_reproduction_fingerprint,
    capture_rng_state,
    restore_rng_state,
)
from src.utils.training_diagnostics import (
    collect_training_diagnostic,
    diagnostic_parameter_snapshots,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train OV-OrthKD for open-vocabulary audio-visual event localization")
    parser.add_argument("--config", type=str, default="configs/ov_orthkd.yaml")
    parser.add_argument("--resume", type=str, default=None)
    parser.add_argument("--eval-only", action="store_true")
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument("--max-train-steps", type=int, default=None)
    parser.add_argument("--max-batches-per-epoch", type=int, default=None)
    parser.add_argument("--max-optimizer-steps", type=int, default=None)
    parser.add_argument("--max-eval-batches", type=int, default=None)
    parser.add_argument("--epochs", type=int, default=None)
    parser.add_argument("--early-stop-patience", type=int, default=None)
    parser.add_argument("--early-stop-min-delta", type=float, default=None)
    parser.add_argument("--allow-blocked-reproduction", action="store_true")
    parser.add_argument("--allow-incompatible-resume", action="store_true")
    return parser.parse_args()


def load_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def apply_cli_config_overrides(config: Dict[str, Any], args: argparse.Namespace) -> None:
    """Apply every config-affecting CLI value before readiness and fingerprinting."""

    if args.output_dir:
        config.setdefault("logging", {})["log_dir"] = args.output_dir
    training = config.setdefault("training", {})
    if args.epochs is not None:
        training["epochs"] = int(args.epochs)
    if args.max_batches_per_epoch is not None:
        training["max_batches_per_epoch"] = int(args.max_batches_per_epoch)
    if args.max_optimizer_steps is not None:
        training["max_optimizer_steps"] = int(args.max_optimizer_steps)
    if args.max_train_steps is not None:
        if args.max_batches_per_epoch is not None and int(args.max_train_steps) != int(
            args.max_batches_per_epoch
        ):
            raise ValueError("--max-train-steps conflicts with --max-batches-per-epoch")
        training["max_batches_per_epoch"] = int(args.max_train_steps)
    if args.early_stop_patience is not None:
        training["early_stop_patience"] = int(args.early_stop_patience)
    if args.early_stop_min_delta is not None:
        training["early_stop_min_delta"] = float(args.early_stop_min_delta)


def set_seed(seed: int, deterministic: bool = True) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    if deterministic:
        os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True
        torch.use_deterministic_algorithms(True, warn_only=False)
        torch.backends.cuda.enable_flash_sdp(False)
        torch.backends.cuda.enable_mem_efficient_sdp(False)
        torch.backends.cuda.enable_math_sdp(True)
    else:
        torch.backends.cudnn.benchmark = True
        torch.backends.cudnn.deterministic = False
        torch.use_deterministic_algorithms(False)
        torch.backends.cuda.enable_flash_sdp(True)
        torch.backends.cuda.enable_mem_efficient_sdp(True)
        torch.backends.cuda.enable_math_sdp(True)


def validate_repro_config(
    config: Dict[str, Any],
    *,
    allow_blocked: bool,
    preflight: bool,
    output_dir: str | Path | None = None,
    require_canonical_readiness: bool = False,
    max_eval_batches: int | None = None,
    eval_only: bool = False,
    resume_path: str | Path | None = None,
    allow_incompatible_resume: bool = False,
    max_train_steps: int | None = None,
) -> None:
    reproduction = config.get("reproduction", {})
    claim_level = str(reproduction.get("claim_level", "")).strip().lower()
    formal_claims = {"archival_exact", "paper_specified_reconstruction"}
    if claim_level and claim_level not in formal_claims and not bool(reproduction.get("mock_only", False)):
        raise RuntimeError(f"Unsupported formal reproduction claim_level: {claim_level}")
    if max_eval_batches is not None and claim_level in formal_claims:
        raise RuntimeError(
            "Refusing partial formal evaluation: --max-eval-batches is diagnostic-only and "
            "cannot produce formal validation/test artifacts"
        )
    if not preflight and claim_level in formal_claims:
        if eval_only and not resume_path:
            raise RuntimeError("Formal eval-only requires --resume with a compatible checkpoint")
        if allow_incompatible_resume:
            raise RuntimeError("Formal claims forbid incompatible resume overrides")
        training = config.get("training", {})
        max_batches = training.get("max_batches_per_epoch") if isinstance(training, Mapping) else None
        max_optimizer = training.get("max_optimizer_steps") if isinstance(training, Mapping) else None
        if (
            claim_level == "paper_specified_reconstruction"
            and reproduction.get("asset_download_lock_required") is True
        ):
            if max_batches != 400:
                raise RuntimeError(
                    "Paper-specified reconstruction requires exactly 400 batches per epoch"
                )
            if max_optimizer is not None or max_train_steps is not None:
                raise RuntimeError(
                    "Refusing truncated formal training: optimizer-step and CLI limits must be null"
                )
        elif any(value is not None for value in (max_batches, max_optimizer, max_train_steps)):
            raise RuntimeError(
                "Refusing truncated formal training: all batch/optimizer-step limits must be null"
            )
    if preflight and not require_canonical_readiness:
        return
    if claim_level in formal_claims:
        validate_canonical_readiness(
            config,
            require_real_preflight=not preflight,
        )
    if preflight:
        return
    if not bool(reproduction.get("full_run_blocked", False)):
        return
    if not allow_blocked:
        raise RuntimeError(
            "Paper reproduction full run is blocked by unresolved archival facts. "
            "Use smoke/preflight or explicitly acknowledge a non-canonical run."
        )
    if output_dir is None:
        raise ValueError("output_dir is required when overriding a blocked reproduction")

    output_path = Path(output_dir)
    namespace = {part.lower() for part in output_path.parts}
    if not namespace.intersection({"diagnostic", "noncanonical", "noncanonical_diagnostic"}):
        raise ValueError(
            "Blocked-run overrides require a diagnostic/noncanonical output namespace"
        )
    output_path.mkdir(parents=True, exist_ok=True)
    facts = reproduction.get("blocked_archival_facts", [])
    lines = [
        "NON-CANONICAL UNRESOLVED RUN",
        "",
        "This run explicitly overrides reproduction.full_run_blocked.",
        "It must not be reported as the canonical ACM MM 2026 reproduction.",
        "",
        "Unresolved archival facts:",
    ]
    lines.extend(f"- {fact}" for fact in facts)
    (output_path / "NON_CANONICAL_UNRESOLVED_RUN.txt").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def build_scheduler(
    optimizer: torch.optim.Optimizer,
    train_cfg: Dict[str, Any],
    epochs: int,
    steps_per_epoch: int,
) -> tuple[torch.optim.lr_scheduler.LRScheduler, str]:
    del steps_per_epoch
    scheduler_cfg = train_cfg.get("scheduler", {})
    kind = str(scheduler_cfg.get("type", "cosine")).lower()
    if kind in {"cosine", "cosineannealinglr"}:
        interval = str(scheduler_cfg.get("interval", "epoch"))
        if interval != "epoch":
            raise ValueError("CosineAnnealingLR must use epoch interval for conference reproduction")
        return CosineAnnealingLR(
            optimizer,
            T_max=int(scheduler_cfg.get("T_max", epochs)),
        ), "epoch"
    if kind == "step":
        interval = str(scheduler_cfg.get("interval", "epoch"))
        if interval not in {"epoch", "optimizer_step"}:
            raise ValueError(f"Unsupported scheduler interval: {interval}")
        return (
            StepLR(
                optimizer,
                step_size=int(scheduler_cfg["step_size"]),
                gamma=float(scheduler_cfg.get("gamma", 0.1)),
            ),
            interval,
        )
    if kind in {"unresolved", "blocked"}:
        raise RuntimeError(
            "Paper reproduction scheduler is unresolved. Recover the archived setting "
            "before launching a full run."
        )
    raise ValueError(f"Unsupported scheduler type: {kind}")


def resolve_training_limits(
    train_cfg: Dict[str, Any],
    deprecated_max_train_steps: int | None,
) -> tuple[int | None, int | None]:
    max_batches = train_cfg.get("max_batches_per_epoch")
    max_optimizer_steps = train_cfg.get("max_optimizer_steps")
    if deprecated_max_train_steps is not None:
        warnings.warn(
            "--max-train-steps is deprecated and means max batches per epoch; "
            "use --max-batches-per-epoch instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        max_batches = deprecated_max_train_steps
    return (
        int(max_batches) if max_batches is not None else None,
        int(max_optimizer_steps) if max_optimizer_steps is not None else None,
    )


def resolve_early_stopping(
    train_cfg: Dict[str, Any],
    cli_patience: int | None,
    cli_min_delta: float | None,
) -> tuple[int | None, float]:
    patience = train_cfg.get("early_stop_patience") if cli_patience is None else cli_patience
    min_delta = train_cfg.get("early_stop_min_delta", 0.0) if cli_min_delta is None else cli_min_delta
    return (
        max(1, int(patience)) if patience is not None else None,
        float(min_delta),
    )


def require_real_weak_logits(alpha_weak_logit: float, weak_teacher_logit_mask: torch.Tensor) -> None:
    if alpha_weak_logit > 0 and weak_teacher_logit_mask.sum().item() <= 0:
        raise RuntimeError(
            "alpha_weak_logit > 0, but the batch contains no real weak-teacher logits. "
            "Synthetic logits are forbidden in paper reproduction."
        )


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def setup_logger(log_dir: str) -> logging.Logger:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("ov_orthkd")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler(Path(log_dir) / "train.log")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


def build_model_and_loss(config: Dict[str, Any], device: torch.device) -> Tuple[OVOrthKDStudent, nn.Module]:
    data_cfg = config["data"]
    student_cfg = config["student"]
    loss_cfg = config["loss"]
    implementation_mode = str(
        config.get("reproduction", {}).get("implementation_mode", "legacy_collaboration")
    )
    mode_to_path = {
        "camera_ready_explicit_paths": "explicit_projected",
        "legacy_collaboration": "legacy_shared",
    }
    if implementation_mode not in mode_to_path:
        raise ValueError(f"Unsupported implementation_mode: {implementation_mode}")
    expected_path_mode = mode_to_path[implementation_mode]
    path_mode = str(student_cfg.get("path_mode", expected_path_mode))
    if path_mode != expected_path_mode:
        raise ValueError(
            f"implementation_mode {implementation_mode} requires student.path_mode "
            f"{expected_path_mode}, got {path_mode}"
        )
    projection_dim = int(student_cfg.get("projection_dim", loss_cfg.get("projection_dim", 256)))
    query_anchor_mode = str(
        loss_cfg.get("query_anchor_mode", "independent_loss_projection")
    )

    student = OVOrthKDStudent(
        visual_backbone=student_cfg["visual_backbone"],
        audio_backbone=student_cfg["audio_backbone"],
        text_dim=int(data_cfg.get("text_dim", 512)),
        fusion_dim=int(student_cfg.get("fusion_dim", 384)),
        projection_dim=projection_dim,
        path_mode=path_mode,
        temporal_layers=int(student_cfg.get("temporal_layers", 4)),
        temporal_heads=int(student_cfg.get("temporal_heads", 8)),
        temporal_dropout=float(student_cfg.get("temporal_dropout", 0.1)),
        max_position_segments=max_position_segments_from_config(config),
        pretrained=bool(student_cfg.get("pretrained", False)),
        fusion_mode=str(
            student_cfg.get("fusion_mode", "concat_mlp_query_conditioned")
        ),
        gate_mode=str(student_cfg.get("gate_mode", "learned_softmax")),
        query_anchor_mode=query_anchor_mode,
    ).to(device)

    common_loss_kwargs = {
        "strong_teacher_dim": int(data_cfg.get("strong_teacher_dim", 1024)),
        "weak_teacher_dim": int(data_cfg.get("weak_teacher_dim", 768)),
        "text_dim": int(data_cfg.get("text_dim", 512)),
        "projection_dim": projection_dim,
        "temperature": float(loss_cfg.get("temperature", 2.0)),
        "alpha_bce": float(loss_cfg.get("alpha_bce", 1.0)),
        "alpha_strong_logit": float(
            loss_cfg.get(
                "alpha_strong_logit",
                0.8 if implementation_mode == "legacy_collaboration" else 0.0,
            )
        ),
        "alpha_weak_logit": float(loss_cfg.get("alpha_weak_logit", 0.0)),
        "alpha_strong_feat": float(loss_cfg.get("alpha_strong_feat", 0.4)),
        "alpha_weak_feat": float(
            loss_cfg.get(
                "alpha_weak_feat",
                0.25 if implementation_mode == "legacy_collaboration" else 0.1,
            )
        ),
        "alpha_text_align": float(
            loss_cfg.get(
                "alpha_text_align",
                0.3 if implementation_mode == "legacy_collaboration" else 0.8,
            )
        ),
        "alpha_orth": float(
            loss_cfg.get(
                "alpha_orth",
                0.15 if implementation_mode == "legacy_collaboration" else 0.5,
            )
        ),
        "confidence_weighting": bool(loss_cfg.get("confidence_weighting", True)),
        "confidence_scale": float(loss_cfg.get("confidence_scale", 2.0)),
    }
    if implementation_mode == "camera_ready_explicit_paths":
        loss_module = OVOrthKDLoss(
            **common_loss_kwargs,
            text_alignment_mode=str(loss_cfg.get("text_alignment_mode", "paper_probability")),
            visual_l2_reduction=str(
                loss_cfg.get(
                    "visual_l2_reduction",
                    "mean_feature_then_masked_mean_segments",
                )
            ),
            teacher_target_projector_trainable=bool(
                loss_cfg.get("teacher_target_projector_trainable", True)
            ),
            query_anchor_mode=query_anchor_mode,
        ).to(device)
    else:
        loss_module = OVOrthKDLegacyLoss(
            student_dim=student.fusion_dim,
            **common_loss_kwargs,
            text_temperature=float(loss_cfg.get("text_temperature", 0.07)),
        ).to(device)
    return student, loss_module


def _module_parameter_behavior(module: nn.Module | None) -> Dict[str, Any]:
    if module is None:
        return {
            "present": False,
            "parameters": 0,
            "trainable_parameters": 0,
        }
    parameters = list(module.parameters())
    return {
        "present": True,
        "parameters": int(sum(parameter.numel() for parameter in parameters)),
        "trainable_parameters": int(
            sum(parameter.numel() for parameter in parameters if parameter.requires_grad)
        ),
    }


def runtime_implementation_behavior(
    student: nn.Module,
    loss_module: nn.Module,
) -> Dict[str, Any]:
    target_projectors = {
        name: _module_parameter_behavior(
            getattr(loss_module, name, None)
            if isinstance(getattr(loss_module, name, None), nn.Module)
            else None
        )
        for name in (
            "strong_teacher_proj",
            "weak_teacher_proj",
            "text_teacher_proj",
        )
    }
    present_projectors = [
        value for value in target_projectors.values() if value["present"]
    ]
    projectors_trainable = (
        all(
            value["trainable_parameters"] == value["parameters"]
            for value in present_projectors
        )
        if present_projectors
        else None
    )
    student_parameters = list(student.parameters())
    loss_parameters = list(loss_module.parameters())
    return {
        "schema_version": 1,
        "student": {
            "class": type(student).__name__,
            "path_mode": getattr(student, "path_mode", None),
            "fusion_mode": getattr(student, "fusion_mode", None),
            "gate_mode": getattr(student, "gate_mode", None),
            "query_anchor_mode": getattr(student, "query_anchor_mode", None),
            "fusion_dim": getattr(student, "fusion_dim", None),
            "projection_dim": getattr(student, "projection_dim", None),
            "modality_gate_present": isinstance(
                getattr(student, "modality_gate", None), nn.Module
            ),
            "token_fusion_present": isinstance(
                getattr(student, "token_fusion", None), nn.Module
            ),
        },
        "loss": {
            "class": type(loss_module).__name__,
            "visual_l2_reduction": getattr(
                loss_module, "visual_l2_reduction", None
            ),
            "query_anchor_mode": getattr(loss_module, "query_anchor_mode", None),
            "teacher_target_projector_trainable": projectors_trainable,
            "target_projectors": target_projectors,
        },
        "parameters": {
            "student": {
                "parameters": int(
                    sum(parameter.numel() for parameter in student_parameters)
                ),
                "trainable_parameters": int(
                    sum(
                        parameter.numel()
                        for parameter in student_parameters
                        if parameter.requires_grad
                    )
                ),
            },
            "loss": {
                "parameters": int(
                    sum(parameter.numel() for parameter in loss_parameters)
                ),
                "trainable_parameters": int(
                    sum(
                        parameter.numel()
                        for parameter in loss_parameters
                        if parameter.requires_grad
                    )
                ),
            },
        },
    }


def attach_runtime_implementation_behavior(
    *,
    config: Dict[str, Any],
    student: nn.Module,
    loss_module: nn.Module,
    output_dir: Path,
) -> Dict[str, Any]:
    behavior = runtime_implementation_behavior(student, loss_module)
    config["runtime_implementation"] = behavior
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "implementation_behavior.json").write_text(
        json.dumps(behavior, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return behavior


def trainable_model_and_loss_parameters(
    student: nn.Module,
    loss_module: nn.Module,
) -> list[nn.Parameter]:
    return [
        parameter
        for parameter in list(student.parameters()) + list(loss_module.parameters())
        if parameter.requires_grad
    ]


def compute_loss_for_batch(
    loss_module: nn.Module,
    outputs: Dict[str, torch.Tensor | None],
    batch: Dict[str, Any],
    device: torch.device,
) -> tuple[torch.Tensor, Dict[str, float]]:
    audio_valid = batch["audio_valid"].to(device)
    weak_teacher_logit_mask = batch["weak_teacher_logit_mask"].to(device) * audio_valid
    require_real_weak_logits(
        float(getattr(loss_module, "alpha_weak_logit", 0.0)),
        weak_teacher_logit_mask,
    )

    common = {
        "student_segment_logits": outputs["segment_logits"],
        "strong_teacher_logits": batch["strong_teacher_logits"].to(device),
        "strong_teacher_features": batch["strong_teacher_features"].to(device),
        "weak_teacher_logits": batch["weak_teacher_logits"].to(device),
        "weak_teacher_features": batch["weak_teacher_features"].to(device),
        "text_embeddings": batch["text_embedding"].to(device),
        "segment_labels": batch["segment_label"].to(device),
        "sequence_mask": batch["sequence_mask"].to(device),
        "strong_teacher_logit_mask": batch["strong_teacher_logit_mask"].to(device),
        "strong_teacher_feature_mask": batch["strong_teacher_feature_mask"].to(device),
        "text_valid": batch["text_valid"].to(device),
    }
    if isinstance(loss_module, OVOrthKDLegacyLoss):
        return loss_module(
            **common,
            student_segment_features=outputs["segment_features"],
            weak_teacher_mask=batch["weak_teacher_feature_mask"].to(device) * audio_valid,
        )

    for key in ("decision_features", "audio_aux_features", "query_features"):
        if outputs[key] is None:
            raise RuntimeError(f"Camera-ready loss requires student output: {key}")
    return loss_module(
        **common,
        student_decision_features=outputs["decision_features"],
        student_audio_aux_features=outputs["audio_aux_features"],
        student_query_features=outputs["query_features"],
        student_text_anchor=outputs.get("text_alignment_target"),
        weak_teacher_logit_mask=weak_teacher_logit_mask,
        weak_teacher_feature_mask=(
            batch["weak_teacher_feature_mask"].to(device) * audio_valid
        ),
    )


def _flatten_valid_segments(
    logits: torch.Tensor,
    labels: torch.Tensor,
    mask: torch.Tensor,
) -> Tuple[np.ndarray, np.ndarray]:
    validate_temporal_alignment(
        student_logits=logits,
        labels=labels,
        sequence_mask=mask,
    )
    valid = mask.bool().view(-1)
    return logits.view(-1)[valid].detach().cpu().numpy(), labels.view(-1)[valid].detach().cpu().numpy()


def compute_metrics(
    logits: np.ndarray,
    labels: np.ndarray,
) -> Dict[str, float]:
    if logits.size == 0 or labels.size == 0:
        return {
            "accuracy": 0.0,
            "binary_micro_f1_at_0_5": 0.0,
            "ap": 0.0,
            "auroc": 0.0,
            "mean_logit": 0.0,
            "mean_prob": 0.0,
            "pred_positive_rate": 0.0,
            "label_positive_rate": 0.0,
        }
    probs = 1.0 / (1.0 + np.exp(-logits))
    preds = (probs >= 0.5).astype(np.int64)

    metrics = {
        "accuracy": float(accuracy_score(labels, preds)),
        "binary_micro_f1_at_0_5": binary_f1(preds, labels),
        "ap": float(average_precision_score(labels, probs)),
        "mean_logit": float(np.mean(logits)),
        "mean_prob": float(np.mean(probs)),
        "pred_positive_rate": float(np.mean(preds)),
        "label_positive_rate": float(np.mean(labels)),
    }
    try:
        metrics["auroc"] = float(roc_auc_score(labels, probs))
    except ValueError:
        metrics["auroc"] = 0.0
    return metrics


def _batch_split_type(batch: Dict[str, Any], sample_index: int) -> str:
    record: Dict[str, Any] = {}
    for key in ("split_type", "seen_unseen", "novelty", "cls_type"):
        values = batch.get(key)
        if values is not None:
            record[key] = values[sample_index]
    meta = batch.get("meta", [])[sample_index] if batch.get("meta") else {}
    if isinstance(meta, dict):
        record["meta"] = meta
    split_type = split_type_from_record(record)
    if split_type != "unknown":
        return split_type
    domain = batch.get("domain", [])[sample_index] if batch.get("domain") else "unknown"
    try:
        return normalize_split_type(domain, allow_unknown=True)
    except ValueError:
        return "unknown"


@torch.no_grad()
def collect_predictions(
    student: OVOrthKDStudent,
    loader: Any,
    device: torch.device,
    max_batches: int | None = None,
    expected_task_segments: int | None = None,
) -> Dict[str, np.ndarray]:
    student.eval()
    ids: list[str] = []
    queries: list[str] = []
    split_types: list[str] = []
    sample_offsets = [0]
    segment_indices: list[int] = []
    labels: list[float] = []
    logits: list[float] = []

    for batch_index, batch in enumerate(loader):
        if max_batches is not None and batch_index >= max_batches:
            break
        outputs = student(
            frame=batch["frame"].to(device),
            spectrogram=batch["spectrogram"].to(device),
            text_embedding=batch["text_embedding"].to(device),
            sequence_mask=batch["sequence_mask"].to(device),
            frame_valid=batch["frame_valid"].to(device),
            audio_valid=batch["audio_valid"].to(device),
        )
        batch_logits = outputs["segment_logits"]
        if batch_logits is None:
            raise RuntimeError("Student did not return segment_logits")
        batch_logits = batch_logits.detach().cpu()
        batch_labels = batch["segment_label"].detach().cpu()
        batch_mask = batch["sequence_mask"].detach().cpu().bool()
        validate_temporal_alignment(
            student_logits=batch_logits,
            labels=batch_labels,
            sequence_mask=batch_mask,
            task_segments=expected_task_segments,
        )

        for sample_index in range(batch_logits.shape[0]):
            valid_indices = torch.nonzero(batch_mask[sample_index], as_tuple=False).view(-1)
            ids.append(str(batch["id"][sample_index]))
            queries.append(str(batch["query"][sample_index]))
            split_types.append(_batch_split_type(batch, sample_index))
            segment_indices.extend(int(index) for index in valid_indices.tolist())
            logits.extend(float(value) for value in batch_logits[sample_index, valid_indices].tolist())
            labels.extend(float(value) for value in batch_labels[sample_index, valid_indices].tolist())
            sample_offsets.append(len(logits))

    logits_array = np.asarray(logits, dtype=np.float64)
    probabilities = 1.0 / (1.0 + np.exp(-logits_array))
    predictions = {
        "ids": np.asarray(ids, dtype=str),
        "queries": np.asarray(queries, dtype=str),
        "split_types": np.asarray(split_types, dtype=str),
        "sample_offsets": np.asarray(sample_offsets, dtype=np.int64),
        "segment_indices": np.asarray(segment_indices, dtype=np.int64),
        "labels": np.asarray(labels, dtype=np.float64),
        "logits": logits_array,
        "probabilities": probabilities,
    }
    if expected_task_segments is not None:
        validate_prediction_task_segments(predictions, expected_task_segments)
    return predictions


def validate_prediction_task_segments(
    predictions: Dict[str, np.ndarray],
    expected_task_segments: int,
) -> None:
    """Fail before metrics if a formal sample is not exactly official T=10."""

    expected = int(expected_task_segments)
    offsets = np.asarray(predictions["sample_offsets"], dtype=np.int64)
    sample_count = int(np.asarray(predictions["ids"]).size)
    if offsets.ndim != 1 or offsets.size != sample_count + 1 or offsets[0] != 0:
        raise ValueError("Prediction sample_offsets are malformed")
    segment_counts = np.diff(offsets)
    if np.any(segment_counts != expected):
        raise ValueError(
            f"Formal OV-AVEBench evaluation requires exactly {expected} metric "
            f"segments per sample; got counts {segment_counts.tolist()}"
        )
    total_segments = int(offsets[-1])
    for name in ("segment_indices", "labels", "logits", "probabilities"):
        if np.asarray(predictions[name]).size != total_segments:
            raise ValueError(
                f"Prediction field {name} does not match sample_offsets total "
                f"{total_segments}"
            )
    segment_indices = np.asarray(predictions["segment_indices"], dtype=np.int64)
    official_indices = np.arange(expected, dtype=np.int64)
    for sample_index in range(sample_count):
        start = int(offsets[sample_index])
        end = int(offsets[sample_index + 1])
        if not np.array_equal(segment_indices[start:end], official_indices):
            raise ValueError(
                "Formal OV-AVEBench metric input must preserve ordered official "
                f"segment indices 0..{expected - 1} for sample {sample_index}"
            )


def save_predictions_npz(path: str | Path, predictions: Dict[str, np.ndarray]) -> None:
    required = (
        "ids",
        "queries",
        "split_types",
        "sample_offsets",
        "segment_indices",
        "labels",
        "logits",
        "probabilities",
    )
    missing = [name for name in required if name not in predictions]
    if missing:
        raise KeyError(f"Prediction payload missing fields: {missing}")
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output_path, **{name: predictions[name] for name in required})


def _sample_segment_mask(predictions: Dict[str, np.ndarray], sample_mask: np.ndarray) -> np.ndarray:
    offsets = predictions["sample_offsets"]
    segment_mask = np.zeros(int(offsets[-1]) if offsets.size else 0, dtype=bool)
    for sample_index in np.flatnonzero(sample_mask):
        segment_mask[int(offsets[sample_index]) : int(offsets[sample_index + 1])] = True
    return segment_mask


def _subset_samples(
    predictions: Dict[str, np.ndarray], sample_mask: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    labels: list[np.ndarray] = []
    probabilities: list[np.ndarray] = []
    offsets = [0]
    source_offsets = predictions["sample_offsets"]
    for sample_index in np.flatnonzero(sample_mask):
        start = int(source_offsets[sample_index])
        end = int(source_offsets[sample_index + 1])
        labels.append(predictions["labels"][start:end])
        probabilities.append(predictions["probabilities"][start:end])
        offsets.append(offsets[-1] + end - start)
    if not labels:
        return (
            np.asarray([], dtype=np.float64),
            np.asarray([], dtype=np.float64),
            np.asarray([0], dtype=np.int64),
        )
    return np.concatenate(labels), np.concatenate(probabilities), np.asarray(offsets, dtype=np.int64)


def compute_grouped_metrics(
    predictions: Dict[str, np.ndarray],
    threshold: float,
) -> Dict[str, Dict[str, Any]]:
    split_types = np.char.lower(predictions["split_types"].astype(str))
    groups = {
        "total": np.ones(split_types.shape[0], dtype=bool),
        "seen": split_types == "seen",
        "unseen": split_types == "unseen",
    }
    results: Dict[str, Dict[str, Any]] = {}
    for group_name, sample_mask in groups.items():
        labels, probabilities, group_offsets = _subset_samples(predictions, sample_mask)
        predicted = (probabilities >= threshold).astype(np.int64)
        if labels.size == 0:
            results[group_name] = {
                "threshold": float(threshold),
                "accuracy": 0.0,
                "binary_micro_f1_at_0_5": 0.0,
                "query_fg_f1_macro_at_0_5": 0.0,
                "ovavel_segment_f1_at_0_5": 0.0,
                "ovavel_event_f1_at_0_5": 0.0,
                "binary_micro_f1_at_threshold": 0.0,
                "query_fg_f1_macro_at_threshold": 0.0,
                "ovavel_segment_f1_at_threshold": 0.0,
                "ovavel_event_f1_at_threshold": 0.0,
                "binary_precision_at_threshold": 0.0,
                "binary_recall_at_threshold": 0.0,
                "ap": 0.0,
                "auroc": None,
                "auroc_available": False,
                "positive_rate": 0.0,
                "predicted_positive_rate": 0.0,
                "sample_count": int(sample_mask.sum()),
                "segment_count": 0,
            }
            continue

        unique_labels = np.unique(labels)
        auroc_available = unique_labels.size == 2
        if np.any(labels == 1):
            ap = float(average_precision_score(labels, probabilities))
        else:
            ap = 0.0
        fixed_metrics = compute_ovavel_metrics(labels, probabilities, group_offsets, threshold=0.5)
        thresholded_metrics = compute_thresholded_ovavel_metrics(
            labels,
            probabilities,
            group_offsets,
            threshold=threshold,
        )
        results[group_name] = {
            **fixed_metrics,
            **thresholded_metrics,
            "threshold": float(threshold),
            "accuracy": float(accuracy_score(labels, predicted)),
            "binary_micro_f1_at_threshold": binary_f1(predicted, labels),
            "binary_precision_at_threshold": float(
                precision_score(labels, predicted, zero_division=0)
            ),
            "binary_recall_at_threshold": float(recall_score(labels, predicted, zero_division=0)),
            "ap": ap,
            "auroc": float(roc_auc_score(labels, probabilities)) if auroc_available else None,
            "auroc_available": bool(auroc_available),
            "positive_rate": float(np.mean(labels)),
            "predicted_positive_rate": float(np.mean(predicted)),
            "sample_count": int(sample_mask.sum()),
            "segment_count": int(labels.size),
        }
    return results


def evaluate_with_predictions(
    student: OVOrthKDStudent,
    loader: Any,
    device: torch.device,
    max_batches: int | None = None,
    threshold: float = 0.5,
    expected_task_segments: int | None = None,
) -> tuple[Dict[str, np.ndarray], Dict[str, Any]]:
    predictions = collect_predictions(
        student,
        loader,
        device,
        max_batches=max_batches,
        expected_task_segments=expected_task_segments,
    )
    metrics = compute_grouped_metrics(predictions, threshold=threshold)["total"]
    return predictions, metrics


def save_evaluation_artifacts(
    output_dir: str | Path,
    validation_predictions: Dict[str, np.ndarray],
    test_predictions: Dict[str, np.ndarray] | None = None,
    expected_task_segments: int | None = None,
) -> Dict[str, Any]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    if expected_task_segments is not None:
        validate_prediction_task_segments(
            validation_predictions,
            expected_task_segments,
        )
    save_predictions_npz(output_path / "validation_predictions.npz", validation_predictions)
    if test_predictions is None:
        return {
            "validation": {
                "threshold": 0.5,
                "metrics": compute_grouped_metrics(validation_predictions, threshold=0.5),
            }
        }

    if expected_task_segments is not None:
        validate_prediction_task_segments(test_predictions, expected_task_segments)
    save_predictions_npz(output_path / "test_predictions.npz", test_predictions)
    from scripts.evaluate_pr_f1 import evaluate_prediction_sets

    evaluation_report = evaluate_prediction_sets(
        validation_predictions,
        test_predictions,
        expected_task_segments=expected_task_segments,
    )
    calibration = evaluation_report["validation_calibration"]
    np.savez_compressed(
        output_path / "validation_pr_curve.npz",
        precision=calibration["precision"],
        recall=calibration["recall"],
        thresholds=calibration["thresholds"],
    )
    return {
        "validation_calibration": {
            key: value
            for key, value in calibration.items()
            if key not in {"precision", "recall", "thresholds"}
        },
        "validation": evaluation_report["validation"],
        "test": evaluation_report["test"],
    }


@torch.no_grad()
def evaluate(
    student: OVOrthKDStudent,
    loader: torch.utils.data.DataLoader,
    device: torch.device,
    max_batches: Optional[int] = None,
) -> Dict[str, float]:
    student.eval()
    all_logits: list[np.ndarray] = []
    all_labels: list[np.ndarray] = []

    for batch_idx, batch in enumerate(loader):
        if max_batches is not None and batch_idx >= max_batches:
            break
        outputs = student(
            frame=batch["frame"].to(device),
            spectrogram=batch["spectrogram"].to(device),
            text_embedding=batch["text_embedding"].to(device),
            sequence_mask=batch["sequence_mask"].to(device),
            frame_valid=batch["frame_valid"].to(device),
            audio_valid=batch["audio_valid"].to(device),
        )
        logits_np, labels_np = _flatten_valid_segments(
            outputs["segment_logits"].detach().cpu(),
            batch["segment_label"].detach().cpu(),
            batch["sequence_mask"].detach().cpu(),
        )
        all_logits.append(logits_np)
        all_labels.append(labels_np)

    logits = np.concatenate(all_logits, axis=0)
    labels = np.concatenate(all_labels, axis=0)
    return compute_metrics(logits, labels)


def maybe_resume(
    student: OVOrthKDStudent,
    loss_module: nn.Module,
    optimizer: AdamW,
    scheduler: torch.optim.lr_scheduler.LRScheduler,
    scaler: Optional[TorchGradScaler],
    resume_path: Optional[str],
    expected_fingerprint: Dict[str, Any] | None = None,
    loader_generators: Dict[str, torch.Generator] | None = None,
    allow_incompatible: bool = False,
    incompatible_marker_path: str | Path | None = None,
) -> Tuple[int, float, int, int]:
    if not resume_path:
        return 0, 0.0, 0, 0
    checkpoint = torch.load(resume_path, map_location="cpu", weights_only=True)
    checkpoint_fingerprint = checkpoint.get("reproduction_fingerprint")
    checkpoint_sha = (
        checkpoint_fingerprint.get("sha256")
        if isinstance(checkpoint_fingerprint, dict)
        else None
    )
    current_sha = (
        expected_fingerprint.get("sha256")
        if isinstance(expected_fingerprint, dict)
        else None
    )
    if expected_fingerprint is not None and checkpoint_sha != current_sha:
        message = (
            "Resume fingerprint mismatch: "
            f"checkpoint={checkpoint_sha or '<missing>'} current={current_sha or '<missing>'}"
        )
        if not allow_incompatible:
            raise RuntimeError(message)
        if incompatible_marker_path is None:
            raise ValueError(
                "incompatible_marker_path is required when allowing incompatible resume"
            )
        marker_path = Path(incompatible_marker_path)
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text(
            "NON-CANONICAL INCOMPATIBLE RESUME\n\n" + message + "\n",
            encoding="utf-8",
        )
    student.load_state_dict(checkpoint["student_state_dict"])
    loss_module.load_state_dict(checkpoint["loss_state_dict"])
    optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
    scheduler.load_state_dict(checkpoint["scheduler_state_dict"])
    if scaler is not None and checkpoint.get("scaler_state_dict") is not None:
        scaler.load_state_dict(checkpoint["scaler_state_dict"])
    rng_state = checkpoint.get("rng_state")
    if rng_state is None:
        raise RuntimeError("Resume checkpoint is missing required RNG and loader-generator state")
    restore_rng_state(rng_state, loader_generators)
    return (
        int(checkpoint.get("epoch", 0)) + 1,
        float(checkpoint.get("best_metric", 0.0)),
        int(checkpoint.get("global_step", 0)),
        int(checkpoint.get("epochs_without_improvement", 0)),
    )


def load_evaluation_checkpoint(
    *,
    student: OVOrthKDStudent,
    resume_path: str,
    expected_fingerprint: Dict[str, Any],
    allow_incompatible: bool,
    incompatible_marker_path: str | Path,
) -> None:
    checkpoint = torch.load(resume_path, map_location="cpu", weights_only=True)
    checkpoint_fingerprint = checkpoint.get("reproduction_fingerprint")
    checkpoint_sha = (
        checkpoint_fingerprint.get("sha256")
        if isinstance(checkpoint_fingerprint, dict)
        else None
    )
    current_sha = expected_fingerprint.get("sha256")
    if checkpoint_sha != current_sha:
        message = (
            "Resume fingerprint mismatch: "
            f"checkpoint={checkpoint_sha or '<missing>'} current={current_sha or '<missing>'}"
        )
        if not allow_incompatible:
            raise RuntimeError(message)
        marker_path = Path(incompatible_marker_path)
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text(
            "NON-CANONICAL INCOMPATIBLE RESUME\n\n" + message + "\n",
            encoding="utf-8",
        )
    student.load_state_dict(checkpoint["student_state_dict"])


def write_runtime_metadata(output_dir: Path, config: Dict[str, Any], device: torch.device) -> None:
    seed = int(config.get("seed", 42))
    deterministic = bool(config.get("training", {}).get("deterministic", True))
    runtime = {
        "python": sys.version,
        "platform": platform.platform(),
        "device": str(device),
        "torch_version": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cuda_version": torch.version.cuda,
        "cudnn_version": torch.backends.cudnn.version() if torch.cuda.is_available() else None,
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "gpu_capability": torch.cuda.get_device_capability(0) if torch.cuda.is_available() else None,
        "gpu_count": torch.cuda.device_count(),
        "seed": seed,
        "deterministic": deterministic,
    }
    with (output_dir / "runtime.json").open("w", encoding="utf-8") as handle:
        json.dump(runtime, handle, indent=2)
    with (output_dir / "resolved_config.yaml").open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False)


def _run_evidence_command(command: list[str]) -> Dict[str, Any]:
    try:
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
    except OSError as exc:
        return {
            "command": command,
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
        }


def build_runtime_reproduction_fingerprint(config: Mapping[str, Any]) -> Dict[str, Any]:
    """Build the invocation-invariant fingerprint shared by training and evaluation."""

    reproduction_cfg = config.get("reproduction", {})
    readiness_cfg = reproduction_cfg.get("readiness", {}) if isinstance(reproduction_cfg, Mapping) else {}
    if not isinstance(readiness_cfg, Mapping):
        readiness_cfg = {}
    fingerprint_lock_paths = {
        name: value
        for name, value in readiness_cfg.items()
        if name in {
            "data_lock",
            "archival_lock",
            "teacher_lock",
            "preprocessing_lock",
            "evaluator_lock",
            "download_lock",
        }
    }
    fingerprint_evidence_paths = {
        name: value
        for name, value in readiness_cfg.items()
        if name in {"exported_audit", "readiness_receipt"}
    }
    git_head = _run_evidence_command(["git", "rev-parse", "HEAD"])
    git_status = _run_evidence_command(["git", "status", "--short"])
    return build_reproduction_fingerprint(
        config,
        lock_paths=fingerprint_lock_paths,
        evidence_paths=fingerprint_evidence_paths,
        git_state={
            "commit": git_head.get("stdout", ""),
            "dirty": bool(git_status.get("stdout", "")),
        },
        run_mode="conference_experiment",
        variant=str(reproduction_cfg.get("variant", "unspecified"))
        if isinstance(reproduction_cfg, Mapping)
        else "unspecified",
    )


def write_static_run_evidence(output_dir: Path, config: Dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    git_state = {
        "head": _run_evidence_command(["git", "rev-parse", "HEAD"]),
        "branch": _run_evidence_command(["git", "branch", "--show-current"]),
        "status": _run_evidence_command(["git", "status", "--short"]),
        "diff_stat": _run_evidence_command(["git", "diff", "--stat"]),
    }
    (output_dir / "git_state.json").write_text(
        json.dumps(git_state, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    reproduction_cfg = config.get("reproduction", {})
    declared_claim_level = str(reproduction_cfg.get("claim_level", "unspecified"))
    git_dirty = bool(git_state["status"].get("stdout", ""))
    diagnostic_override = (output_dir / "NON_CANONICAL_UNRESOLVED_RUN.txt").is_file()
    effective_claim_level = (
        "noncanonical_diagnostic" if git_dirty or diagnostic_override else declared_claim_level
    )
    (output_dir / "config_resolved.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False),
        encoding="utf-8",
    )
    (output_dir / "claim_level.txt").write_text(effective_claim_level + "\n", encoding="utf-8")
    experiment_variant = {
        "variant": str(reproduction_cfg.get("variant", "unspecified")),
        "declared_claim_level": declared_claim_level,
        "effective_claim_level": effective_claim_level,
        "git_dirty": git_dirty,
        "diagnostic_override": diagnostic_override,
    }
    (output_dir / "experiment_variant.json").write_text(
        json.dumps(experiment_variant, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    freeze = _run_evidence_command([sys.executable, "-m", "pip", "freeze"])
    freeze_text = freeze["stdout"]
    if freeze["returncode"] != 0:
        freeze_text += f"\n# pip freeze failed: {freeze['stderr']}\n"
    (output_dir / "requirements_freeze.txt").write_text(
        freeze_text.rstrip() + "\n",
        encoding="utf-8",
    )

    data_cfg = config.get("data", {})
    path_root = Path(data_cfg.get("path_root", ".")).expanduser().resolve()
    manifest_hashes: Dict[str, Any] = {}
    for split in ("train", "val", "test"):
        raw_path = data_cfg.get(f"{split}_manifest")
        if not raw_path:
            continue
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = path_root / path
        path = path.resolve()
        manifest_hashes[split] = {
            "path": str(path),
            "sha256": sha256_file(path) if path.exists() else None,
            "exists": path.exists(),
        }
    (output_dir / "manifest_hashes.json").write_text(
        json.dumps(manifest_hashes, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    readiness_cfg = reproduction_cfg.get("readiness", {})
    lock_hashes: Dict[str, Any] = {}
    for name, raw_path in sorted(readiness_cfg.items()):
        if not str(name).endswith("_lock") or not raw_path:
            continue
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = path_root / path
        path = path.resolve()
        lock_hashes[str(name)] = {
            "path": str(path),
            "exists": path.is_file(),
            "sha256": sha256_file(path) if path.is_file() else None,
        }
    (output_dir / "lock_hashes.json").write_text(
        json.dumps(lock_hashes, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    cache_value = config.get("teacher_export", {}).get("artifact_dir")
    cache_path = Path(cache_value).expanduser() if cache_value else None
    if cache_path is not None and not cache_path.is_absolute():
        cache_path = path_root / cache_path
    if cache_path is not None:
        cache_path = cache_path.resolve()
    if cache_path is not None and cache_path.is_dir():
        teacher_cache_hash = {
            "path": str(cache_path),
            "exists": True,
            **canonical_tree_hash(cache_path),
        }
    else:
        teacher_cache_hash = {
            "path": str(cache_path) if cache_path is not None else None,
            "exists": False,
            "schema_version": 1,
            "files": 0,
            "bytes": 0,
            "sha256": None,
        }
    (output_dir / "teacher_cache_hash.json").write_text(
        json.dumps(teacher_cache_hash, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    evaluator_summary: Dict[str, Any] = {
        "lock_path": None,
        "source_path": None,
        "expected_sha256": None,
        "actual_sha256": None,
        "source_exists": False,
        "matches_lock": False,
    }
    evaluator_lock_info = lock_hashes.get("evaluator_lock")
    if evaluator_lock_info and evaluator_lock_info["exists"]:
        evaluator_lock_path = Path(evaluator_lock_info["path"])
        evaluator_lock = yaml.safe_load(evaluator_lock_path.read_text(encoding="utf-8")) or {}
        source_value = evaluator_lock.get("source_file")
        source_path = Path(source_value).expanduser() if source_value else None
        if source_path is not None and not source_path.is_absolute():
            source_path = path_root / source_path
        if source_path is not None:
            source_path = source_path.resolve()
        expected_sha = evaluator_lock.get("source_sha256")
        actual_sha = sha256_file(source_path) if source_path is not None and source_path.is_file() else None
        evaluator_summary = {
            "lock_path": str(evaluator_lock_path),
            "source_path": str(source_path) if source_path is not None else None,
            "expected_sha256": expected_sha,
            "actual_sha256": actual_sha,
            "source_exists": bool(source_path is not None and source_path.is_file()),
            "matches_lock": bool(expected_sha and actual_sha and expected_sha == actual_sha),
        }
    (output_dir / "official_evaluator_hash.json").write_text(
        json.dumps(evaluator_summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    cuda_environment = {
        "python": sys.version,
        "platform": platform.platform(),
        "torch": torch.__version__,
        "cuda_compiled": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "cudnn": torch.backends.cudnn.version() if torch.backends.cudnn.is_available() else None,
        "device_count": torch.cuda.device_count(),
        "devices": [
            {
                "index": index,
                "name": torch.cuda.get_device_name(index),
                "capability": list(torch.cuda.get_device_capability(index)),
            }
            for index in range(torch.cuda.device_count())
        ],
        "cublas_workspace_config": os.environ.get("CUBLAS_WORKSPACE_CONFIG"),
    }
    (output_dir / "cuda_environment.json").write_text(
        json.dumps(cuda_environment, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def checkpoint_payload(
    *,
    epoch: int,
    global_step: int,
    best_metric: float,
    epochs_without_improvement: int = 0,
    student: OVOrthKDStudent,
    loss_module: nn.Module,
    optimizer: AdamW,
    scheduler: torch.optim.lr_scheduler.LRScheduler,
    scaler: Optional[TorchGradScaler],
    config: Dict[str, Any],
    reproduction_fingerprint: Dict[str, Any],
    loader_generators: Dict[str, torch.Generator],
) -> Dict[str, Any]:
    actual_behavior = runtime_implementation_behavior(student, loss_module)
    recorded_behavior = config.get("runtime_implementation")
    if recorded_behavior is not None and recorded_behavior != actual_behavior:
        raise RuntimeError(
            "runtime implementation behavior changed after the resolved config "
            "and fingerprint were recorded"
        )
    return {
        "epoch": epoch,
        "global_step": global_step,
        "best_metric": best_metric,
        "epochs_without_improvement": int(epochs_without_improvement),
        "implementation_mode": config.get("reproduction", {}).get(
            "implementation_mode", "legacy_collaboration"
        ),
        "runtime_implementation": actual_behavior,
        "student_state_dict": student.state_dict(),
        "loss_state_dict": loss_module.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "scheduler_state_dict": scheduler.state_dict(),
        "scaler_state_dict": scaler.state_dict() if scaler is not None else None,
        "reproduction_fingerprint": reproduction_fingerprint,
        "rng_state": capture_rng_state(loader_generators),
        "config": config,
    }


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    apply_cli_config_overrides(config, args)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    output_dir = Path(config["logging"]["log_dir"])
    validate_repro_config(
        config,
        allow_blocked=args.allow_blocked_reproduction,
        preflight=False,
        output_dir=output_dir,
        max_eval_batches=args.max_eval_batches,
        eval_only=bool(args.eval_only),
        resume_path=args.resume,
        allow_incompatible_resume=bool(args.allow_incompatible_resume),
        max_train_steps=args.max_train_steps,
    )
    set_seed(
        int(config.get("seed", 42)),
        deterministic=bool(config.get("training", {}).get("deterministic", True)),
    )
    logger = setup_logger(str(output_dir))
    logger.info("Using device: %s", device)

    student, loss_module = build_model_and_loss(config, device)
    attach_runtime_implementation_behavior(
        config=config,
        student=student,
        loss_module=loss_module,
        output_dir=output_dir,
    )
    write_runtime_metadata(output_dir, config, device)
    write_static_run_evidence(output_dir, config)
    train_loader, val_loader, test_loader = create_ov_avel_data_loaders(config)

    loader_generators = {
        name: loader.generator
        for name, loader in {
            "train": train_loader,
            "val": val_loader,
            "test": test_loader,
        }.items()
        if loader is not None and loader.generator is not None
    }
    reproduction_cfg = config.get("reproduction", {})
    claim_level = str(reproduction_cfg.get("claim_level", "")).strip().lower()
    expected_metric_task_segments = (
        task_segments_from_config(config)
        if claim_level in {"archival_exact", "paper_specified_reconstruction"}
        else None
    )
    reproduction_fingerprint = build_runtime_reproduction_fingerprint(config)

    if args.eval_only:
        if args.resume:
            load_evaluation_checkpoint(
                student=student,
                resume_path=args.resume,
                expected_fingerprint=reproduction_fingerprint,
                allow_incompatible=bool(args.allow_incompatible_resume),
                incompatible_marker_path=output_dir / "INCOMPATIBLE_RESUME.txt",
            )
        val_predictions, val_metrics = evaluate_with_predictions(
            student,
            val_loader,
            device,
            max_batches=args.max_eval_batches,
            expected_task_segments=expected_metric_task_segments,
        )
        logger.info("Validation metrics: %s", val_metrics)
        test_predictions = None
        if test_loader is not None:
            test_predictions = collect_predictions(
                student,
                test_loader,
                device,
                max_batches=args.max_eval_batches,
                expected_task_segments=expected_metric_task_segments,
            )
        final_metrics = save_evaluation_artifacts(
            output_dir,
            val_predictions,
            test_predictions,
            expected_task_segments=expected_metric_task_segments,
        )
        if "test" in final_metrics:
            logger.info("Test metrics: %s", final_metrics["test"]["metrics"]["total"])
        (output_dir / "final_metrics.json").write_text(
            json.dumps(final_metrics, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return

    train_cfg = config["training"]
    parameters = trainable_model_and_loss_parameters(student, loss_module)
    optimizer = AdamW(
        parameters,
        lr=float(train_cfg.get("learning_rate", 2e-4)),
        weight_decay=float(train_cfg.get("weight_decay", 1e-4)),
    )
    epochs = int(train_cfg.get("epochs", 30))
    scheduler, scheduler_interval = build_scheduler(
        optimizer,
        train_cfg,
        epochs=epochs,
        steps_per_epoch=max(len(train_loader), 1),
    )
    use_amp = bool(train_cfg.get("mixed_precision", True)) and device.type == "cuda"
    scaler = make_grad_scaler(device.type, use_amp)

    start_epoch, best_metric, global_step, epochs_without_improvement = maybe_resume(
        student=student,
        loss_module=loss_module,
        optimizer=optimizer,
        scheduler=scheduler,
        scaler=scaler,
        resume_path=args.resume,
        expected_fingerprint=reproduction_fingerprint,
        loader_generators=loader_generators,
        allow_incompatible=bool(args.allow_incompatible_resume),
        incompatible_marker_path=output_dir / "INCOMPATIBLE_RESUME.txt",
    )
    if not args.resume:
        best_metric = float("-inf")

    grad_clip = float(train_cfg.get("grad_clip", 1.0))
    early_stop_patience, early_stop_min_delta = resolve_early_stopping(
        train_cfg,
        args.early_stop_patience,
        args.early_stop_min_delta,
    )
    max_batches_per_epoch, max_optimizer_steps = resolve_training_limits(
        train_cfg,
        deprecated_max_train_steps=args.max_train_steps,
    )
    if args.max_train_steps is not None:
        logger.warning(
            "--max-train-steps is deprecated; interpreting it as max batches per epoch."
        )
    stop_training = False
    diagnostic_cfg = config.get("logging", {}).get("training_diagnostics", {})
    diagnostics_enabled = bool(diagnostic_cfg.get("enabled", False))
    diagnostic_max_epochs = int(diagnostic_cfg.get("max_epochs", 0))
    diagnostic_batches_per_epoch = int(diagnostic_cfg.get("batches_per_epoch", 0))
    if diagnostics_enabled and (
        diagnostic_max_epochs <= 0 or diagnostic_batches_per_epoch <= 0
    ):
        raise ValueError(
            "logging.training_diagnostics max_epochs and batches_per_epoch must be "
            "positive when enabled"
        )
    diagnostic_path = output_dir / str(
        diagnostic_cfg.get("output_file", "training_diagnostics.jsonl")
    )
    initial_diagnostic_parameters = (
        diagnostic_parameter_snapshots(student, loss_module)
        if diagnostics_enabled
        else {}
    )

    for epoch in range(start_epoch, epochs):
        if max_optimizer_steps is not None and global_step >= max_optimizer_steps:
            break
        epoch_started = time.perf_counter()
        if device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(device)
        student.train()
        loss_module.train()
        running_stats: Dict[str, float] = {}
        step_count = 0

        progress = tqdm(train_loader, desc=f"epoch {epoch + 1}/{epochs}", leave=False)
        for batch_idx, batch in enumerate(progress):
            if max_batches_per_epoch is not None and batch_idx >= max_batches_per_epoch:
                break
            if max_optimizer_steps is not None and global_step >= max_optimizer_steps:
                stop_training = True
                break

            frames = batch["frame"].to(device)
            spectrograms = batch["spectrogram"].to(device)
            text_embeddings = batch["text_embedding"].to(device)
            sequence_mask = batch["sequence_mask"].to(device)
            frame_valid = batch["frame_valid"].to(device)
            audio_valid = batch["audio_valid"].to(device)

            optimizer.zero_grad(set_to_none=True)
            with autocast_context(device.type, use_amp):
                outputs = student(
                    frame=frames,
                    spectrogram=spectrograms,
                    text_embedding=text_embeddings,
                    sequence_mask=sequence_mask,
                    frame_valid=frame_valid,
                    audio_valid=audio_valid,
                )
                loss, stats = compute_loss_for_batch(loss_module, outputs, batch, device)

            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            diagnostic_record = None
            if (
                diagnostics_enabled
                and epoch < diagnostic_max_epochs
                and batch_idx < diagnostic_batches_per_epoch
            ):
                diagnostic_record = collect_training_diagnostic(
                    student=student,
                    loss_module=loss_module,
                    outputs=outputs,
                    batch=batch,
                    initial_parameters=initial_diagnostic_parameters,
                    epoch=epoch,
                    batch_index=batch_idx,
                    global_step=global_step,
                )
            torch.nn.utils.clip_grad_norm_(parameters, grad_clip)
            scaler.step(optimizer)
            scaler.update()
            if diagnostic_record is not None:
                with diagnostic_path.open("a", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(diagnostic_record, ensure_ascii=False) + "\n"
                    )
            if scheduler_interval == "optimizer_step":
                scheduler.step()

            step_count += 1
            global_step += 1
            for name, value in stats.items():
                running_stats[name] = running_stats.get(name, 0.0) + value
            progress.set_postfix(loss=f"{stats['total']:.4f}", orth=f"{stats['orth']:.6f}")

        if step_count == 0:
            logger.info("No optimizer steps executed at epoch %d; stopping.", epoch + 1)
            break
        if scheduler_interval == "epoch":
            scheduler.step()
        val_predictions, val_metrics = evaluate_with_predictions(
            student,
            val_loader,
            device,
            max_batches=args.max_eval_batches,
            expected_task_segments=expected_metric_task_segments,
        )
        mean_stats = {name: value / step_count for name, value in running_stats.items()}
        logger.info(
            "Epoch %d global_step=%d train=%s val=%s",
            epoch + 1,
            global_step,
            mean_stats,
            val_metrics,
        )

        selection_metric = val_metrics.get("ap", val_metrics.get("auroc", val_metrics["accuracy"]))
        saved_best = selection_metric > best_metric + early_stop_min_delta
        if saved_best:
            best_metric = selection_metric
            epochs_without_improvement = 0
            checkpoint = checkpoint_payload(
                epoch=epoch,
                global_step=global_step,
                best_metric=best_metric,
                epochs_without_improvement=epochs_without_improvement,
                student=student,
                loss_module=loss_module,
                optimizer=optimizer,
                scheduler=scheduler,
                scaler=scaler,
                config=config,
                reproduction_fingerprint=reproduction_fingerprint,
                loader_generators=loader_generators,
            )
            torch.save(checkpoint, output_dir / "best.pt")
            save_predictions_npz(
                output_dir / "best_validation_predictions.npz",
                val_predictions,
            )
            logger.info("New best checkpoint at epoch %d with val_ap=%.4f", epoch + 1, best_metric)
        else:
            epochs_without_improvement += 1
            if early_stop_patience is not None:
                logger.info(
                    "No improvement for %d epoch(s); best_val_ap=%.4f current_val_ap=%.4f",
                    epochs_without_improvement,
                    best_metric,
                    selection_metric,
                )
                if epochs_without_improvement >= early_stop_patience:
                    logger.info(
                        "Early stopping triggered at epoch %d (patience=%d, min_delta=%.6f)",
                        epoch + 1,
                        early_stop_patience,
                        early_stop_min_delta,
                    )
                    stop_training = True

        last_checkpoint = checkpoint_payload(
            epoch=epoch,
            global_step=global_step,
            best_metric=best_metric,
            epochs_without_improvement=epochs_without_improvement,
            student=student,
            loss_module=loss_module,
            optimizer=optimizer,
            scheduler=scheduler,
            scaler=scaler,
            config=config,
            reproduction_fingerprint=reproduction_fingerprint,
            loader_generators=loader_generators,
        )
        torch.save(last_checkpoint, output_dir / "last.pt")
        history_record = {
            "epoch": epoch,
            "global_step": global_step,
            "learning_rate": float(optimizer.param_groups[0]["lr"]),
            "train_loss": mean_stats,
            "validation": val_metrics,
            "saved_best": saved_best,
            "elapsed_seconds": time.perf_counter() - epoch_started,
            "peak_memory_mb": (
                float(torch.cuda.max_memory_allocated(device) / (1024**2))
                if device.type == "cuda"
                else 0.0
            ),
        }
        with (output_dir / "history.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(history_record, ensure_ascii=False) + "\n")

        if max_optimizer_steps is not None and global_step >= max_optimizer_steps:
            stop_training = True
        if stop_training:
            break

    final_metrics: Dict[str, Any] = {}
    if (output_dir / "best.pt").exists():
        best_checkpoint = torch.load(output_dir / "best.pt", map_location=device, weights_only=True)
        student.load_state_dict(best_checkpoint["student_state_dict"])
        validation_predictions = collect_predictions(
            student,
            val_loader,
            device,
            max_batches=args.max_eval_batches,
            expected_task_segments=expected_metric_task_segments,
        )
        save_predictions_npz(
            output_dir / "best_validation_predictions.npz",
            validation_predictions,
        )
        if test_loader is not None:
            test_predictions = collect_predictions(
                student,
                test_loader,
                device,
                max_batches=args.max_eval_batches,
                expected_task_segments=expected_metric_task_segments,
            )
            final_metrics = save_evaluation_artifacts(
                output_dir,
                validation_predictions,
                test_predictions,
                expected_task_segments=expected_metric_task_segments,
            )
        else:
            final_metrics = save_evaluation_artifacts(
                output_dir,
                validation_predictions,
                expected_task_segments=expected_metric_task_segments,
            )
        logger.info("Best validation metric: %.4f", best_metric)
        logger.info("Final metrics from best checkpoint: %s", final_metrics)
    (output_dir / "final_metrics.json").write_text(
        json.dumps(final_metrics, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
