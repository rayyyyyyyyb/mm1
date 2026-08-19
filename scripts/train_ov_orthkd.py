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
from typing import Any, Dict, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
import yaml
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    f1_score,
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
from src.losses import OVOrthKDLoss, OVOrthKDLegacyLoss
from src.models import OVOrthKDStudent
from src.utils.reproduction_fingerprint import (
    build_reproduction_fingerprint,
    capture_rng_state,
    restore_rng_state,
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
) -> None:
    reproduction = config.get("reproduction", {})
    if not bool(reproduction.get("full_run_blocked", False)) or preflight:
        return
    if not allow_blocked:
        raise RuntimeError(
            "Paper reproduction full run is blocked by unresolved archival facts. "
            "Use smoke/preflight or explicitly acknowledge a non-canonical run."
        )
    if output_dir is None:
        raise ValueError("output_dir is required when overriding a blocked reproduction")

    output_path = Path(output_dir)
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
    if kind == "cosine":
        return CosineAnnealingLR(optimizer, T_max=epochs), "epoch"
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
        max_segments=int(data_cfg.get("max_segments", 16)),
        pretrained=bool(student_cfg.get("pretrained", False)),
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
        ).to(device)
    else:
        loss_module = OVOrthKDLegacyLoss(
            student_dim=student.fusion_dim,
            **common_loss_kwargs,
            text_temperature=float(loss_cfg.get("text_temperature", 0.07)),
        ).to(device)
    return student, loss_module


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
    valid = mask.bool().view(-1)
    return logits.view(-1)[valid].detach().cpu().numpy(), labels.view(-1)[valid].detach().cpu().numpy()


def compute_metrics(
    logits: np.ndarray,
    labels: np.ndarray,
) -> Dict[str, float]:
    if logits.size == 0 or labels.size == 0:
        return {
            "accuracy": 0.0,
            "f1": 0.0,
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
        "f1": float(f1_score(labels, preds, zero_division=0)),
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
    if "split_type" in batch:
        value = batch["split_type"][sample_index]
        if value not in (None, ""):
            return str(value).lower()
    meta = batch.get("meta", [])[sample_index] if batch.get("meta") else {}
    if isinstance(meta, dict):
        for key in ("split_type", "seen_unseen", "novelty"):
            value = meta.get(key)
            if value not in (None, ""):
                return str(value).lower()
    domain = batch.get("domain", [])[sample_index] if batch.get("domain") else "unknown"
    return str(domain).lower() if str(domain).lower() in {"seen", "unseen"} else "unknown"


@torch.no_grad()
def collect_predictions(
    student: OVOrthKDStudent,
    loader: Any,
    device: torch.device,
    max_batches: int | None = None,
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
    return {
        "ids": np.asarray(ids, dtype=str),
        "queries": np.asarray(queries, dtype=str),
        "split_types": np.asarray(split_types, dtype=str),
        "sample_offsets": np.asarray(sample_offsets, dtype=np.int64),
        "segment_indices": np.asarray(segment_indices, dtype=np.int64),
        "labels": np.asarray(labels, dtype=np.float64),
        "logits": logits_array,
        "probabilities": probabilities,
    }


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
        segment_mask = _sample_segment_mask(predictions, sample_mask)
        labels = predictions["labels"][segment_mask]
        probabilities = predictions["probabilities"][segment_mask]
        predicted = (probabilities >= threshold).astype(np.int64)
        if labels.size == 0:
            results[group_name] = {
                "threshold": float(threshold),
                "accuracy": 0.0,
                "f1": 0.0,
                "precision": 0.0,
                "recall": 0.0,
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
        results[group_name] = {
            "threshold": float(threshold),
            "accuracy": float(accuracy_score(labels, predicted)),
            "f1": float(f1_score(labels, predicted, zero_division=0)),
            "precision": float(precision_score(labels, predicted, zero_division=0)),
            "recall": float(recall_score(labels, predicted, zero_division=0)),
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
) -> tuple[Dict[str, np.ndarray], Dict[str, Any]]:
    predictions = collect_predictions(student, loader, device, max_batches=max_batches)
    metrics = compute_grouped_metrics(predictions, threshold=threshold)["total"]
    return predictions, metrics


def save_evaluation_artifacts(
    output_dir: str | Path,
    validation_predictions: Dict[str, np.ndarray],
    test_predictions: Dict[str, np.ndarray] | None = None,
) -> Dict[str, Any]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    save_predictions_npz(output_path / "validation_predictions.npz", validation_predictions)
    if test_predictions is None:
        return {
            "validation": {
                "threshold": 0.5,
                "metrics": compute_grouped_metrics(validation_predictions, threshold=0.5),
            }
        }

    save_predictions_npz(output_path / "test_predictions.npz", test_predictions)
    from scripts.evaluate_pr_f1 import evaluate_prediction_sets

    evaluation_report = evaluate_prediction_sets(validation_predictions, test_predictions)
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
) -> Tuple[int, float, int]:
    if not resume_path:
        return 0, 0.0, 0
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


def write_static_run_evidence(output_dir: Path, config: Dict[str, Any]) -> None:
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


def checkpoint_payload(
    *,
    epoch: int,
    global_step: int,
    best_metric: float,
    student: OVOrthKDStudent,
    loss_module: nn.Module,
    optimizer: AdamW,
    scheduler: torch.optim.lr_scheduler.LRScheduler,
    scaler: Optional[TorchGradScaler],
    config: Dict[str, Any],
    reproduction_fingerprint: Dict[str, Any],
    loader_generators: Dict[str, torch.Generator],
) -> Dict[str, Any]:
    return {
        "epoch": epoch,
        "global_step": global_step,
        "best_metric": best_metric,
        "implementation_mode": config.get("reproduction", {}).get(
            "implementation_mode", "legacy_collaboration"
        ),
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
    if args.output_dir:
        config.setdefault("logging", {})["log_dir"] = args.output_dir
    if args.epochs is not None:
        config.setdefault("training", {})["epochs"] = int(args.epochs)
    if args.max_batches_per_epoch is not None:
        config.setdefault("training", {})["max_batches_per_epoch"] = int(
            args.max_batches_per_epoch
        )
    if args.max_optimizer_steps is not None:
        config.setdefault("training", {})["max_optimizer_steps"] = int(
            args.max_optimizer_steps
        )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    output_dir = Path(config["logging"]["log_dir"])
    validate_repro_config(
        config,
        allow_blocked=args.allow_blocked_reproduction,
        preflight=False,
        output_dir=output_dir,
    )
    set_seed(
        int(config.get("seed", 42)),
        deterministic=bool(config.get("training", {}).get("deterministic", True)),
    )
    logger = setup_logger(str(output_dir))
    write_runtime_metadata(output_dir, config, device)
    write_static_run_evidence(output_dir, config)
    logger.info("Using device: %s", device)

    train_loader, val_loader, test_loader = create_ov_avel_data_loaders(config)
    student, loss_module = build_model_and_loss(config, device)

    loader_generators = {
        name: loader.generator
        for name, loader in {
            "train": train_loader,
            "val": val_loader,
            "test": test_loader,
        }.items()
        if loader is not None and loader.generator is not None
    }
    reproduction_fingerprint = build_reproduction_fingerprint(config)

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
        )
        logger.info("Validation metrics: %s", val_metrics)
        test_predictions = None
        if test_loader is not None:
            test_predictions = collect_predictions(
                student,
                test_loader,
                device,
                max_batches=args.max_eval_batches,
            )
        final_metrics = save_evaluation_artifacts(output_dir, val_predictions, test_predictions)
        if "test" in final_metrics:
            logger.info("Test metrics: %s", final_metrics["test"]["metrics"]["total"])
        (output_dir / "final_metrics.json").write_text(
            json.dumps(final_metrics, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return

    train_cfg = config["training"]
    parameters = list(student.parameters()) + list(loss_module.parameters())
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

    start_epoch, best_metric, global_step = maybe_resume(
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
    epochs_without_improvement = 0
    stop_training = False

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
            torch.nn.utils.clip_grad_norm_(parameters, grad_clip)
            scaler.step(optimizer)
            scaler.update()
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
        best_checkpoint = torch.load(output_dir / "best.pt", map_location=device)
        student.load_state_dict(best_checkpoint["student_state_dict"])
        validation_predictions = collect_predictions(
            student,
            val_loader,
            device,
            max_batches=args.max_eval_batches,
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
            )
            final_metrics = save_evaluation_artifacts(
                output_dir,
                validation_predictions,
                test_predictions,
            )
        else:
            final_metrics = save_evaluation_artifacts(
                output_dir,
                validation_predictions,
            )
        logger.info("Best validation metric: %.4f", best_metric)
        logger.info("Final metrics from best checkpoint: %s", final_metrics)
    (output_dir / "final_metrics.json").write_text(
        json.dumps(final_metrics, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
