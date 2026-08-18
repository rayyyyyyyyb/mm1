#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np
import torch
import yaml
from sklearn.metrics import accuracy_score, average_precision_score, f1_score, roc_auc_score
from torch.optim import AdamW
from torch.optim.lr_scheduler import CosineAnnealingLR
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
from src.losses import OVOrthKDLoss
from src.models import OVOrthKDStudent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train OV-OrthKD for open-vocabulary audio-visual event localization")
    parser.add_argument("--config", type=str, default="configs/ov_orthkd.yaml")
    parser.add_argument("--resume", type=str, default=None)
    parser.add_argument("--eval-only", action="store_true")
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument("--max-train-steps", type=int, default=None)
    parser.add_argument("--max-eval-batches", type=int, default=None)
    parser.add_argument("--epochs", type=int, default=None)
    parser.add_argument("--early-stop-patience", type=int, default=None)
    parser.add_argument("--early-stop-min-delta", type=float, default=0.0)
    return parser.parse_args()


def load_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


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


def build_model_and_loss(config: Dict[str, Any], device: torch.device) -> Tuple[OVOrthKDStudent, OVOrthKDLoss]:
    data_cfg = config["data"]
    student_cfg = config["student"]
    loss_cfg = config["loss"]

    student = OVOrthKDStudent(
        visual_backbone=student_cfg["visual_backbone"],
        audio_backbone=student_cfg["audio_backbone"],
        text_dim=int(data_cfg.get("text_dim", 512)),
        fusion_dim=int(student_cfg.get("fusion_dim", 384)),
        temporal_layers=int(student_cfg.get("temporal_layers", 4)),
        temporal_heads=int(student_cfg.get("temporal_heads", 8)),
        temporal_dropout=float(student_cfg.get("temporal_dropout", 0.1)),
        max_segments=int(data_cfg.get("max_segments", 16)),
        pretrained=bool(student_cfg.get("pretrained", False)),
    ).to(device)

    loss_module = OVOrthKDLoss(
        student_dim=student.fusion_dim,
        strong_teacher_dim=int(data_cfg.get("strong_teacher_dim", 1024)),
        weak_teacher_dim=int(data_cfg.get("weak_teacher_dim", 768)),
        text_dim=int(data_cfg.get("text_dim", 512)),
        projection_dim=int(loss_cfg.get("projection_dim", 256)),
        temperature=float(loss_cfg.get("temperature", 2.0)),
        text_temperature=float(loss_cfg.get("text_temperature", 0.07)),
        alpha_bce=float(loss_cfg.get("alpha_bce", 1.0)),
        alpha_strong_logit=float(loss_cfg.get("alpha_strong_logit", 0.8)),
        alpha_weak_logit=float(loss_cfg.get("alpha_weak_logit", 0.0)),
        alpha_strong_feat=float(loss_cfg.get("alpha_strong_feat", 0.4)),
        alpha_weak_feat=float(loss_cfg.get("alpha_weak_feat", 0.25)),
        alpha_text_align=float(loss_cfg.get("alpha_text_align", 0.3)),
        alpha_orth=float(loss_cfg.get("alpha_orth", 0.15)),
        confidence_weighting=bool(loss_cfg.get("confidence_weighting", True)),
        confidence_scale=float(loss_cfg.get("confidence_scale", 2.0)),
    ).to(device)
    return student, loss_module


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
    loss_module: OVOrthKDLoss,
    optimizer: AdamW,
    scheduler: CosineAnnealingLR,
    scaler: Optional[TorchGradScaler],
    resume_path: Optional[str],
) -> Tuple[int, float]:
    if not resume_path:
        return 0, 0.0
    checkpoint = torch.load(resume_path, map_location="cpu")
    student.load_state_dict(checkpoint["student_state_dict"])
    loss_module.load_state_dict(checkpoint["loss_state_dict"])
    optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
    scheduler.load_state_dict(checkpoint["scheduler_state_dict"])
    if scaler is not None and checkpoint.get("scaler_state_dict") is not None:
        scaler.load_state_dict(checkpoint["scaler_state_dict"])
    return int(checkpoint.get("epoch", 0)) + 1, float(checkpoint.get("best_metric", 0.0))


def write_runtime_metadata(output_dir: Path, config: Dict[str, Any], device: torch.device) -> None:
    runtime = {
        "device": str(device),
        "torch_version": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "config": config,
    }
    with (output_dir / "runtime.json").open("w", encoding="utf-8") as handle:
        json.dump(runtime, handle, indent=2)
    with (output_dir / "resolved_config.yaml").open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False)


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    set_seed(int(config.get("seed", 42)))

    if args.output_dir:
        config.setdefault("logging", {})["log_dir"] = args.output_dir
    if args.epochs is not None:
        config.setdefault("training", {})["epochs"] = int(args.epochs)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    output_dir = Path(config["logging"]["log_dir"])
    logger = setup_logger(str(output_dir))
    write_runtime_metadata(output_dir, config, device)
    logger.info("Using device: %s", device)

    train_loader, val_loader, test_loader = create_ov_avel_data_loaders(config)
    student, loss_module = build_model_and_loss(config, device)

    train_cfg = config["training"]
    parameters = list(student.parameters()) + list(loss_module.parameters())
    optimizer = AdamW(
        parameters,
        lr=float(train_cfg.get("learning_rate", 2e-4)),
        weight_decay=float(train_cfg.get("weight_decay", 1e-4)),
    )
    scheduler = CosineAnnealingLR(optimizer, T_max=int(train_cfg.get("epochs", 30)))
    use_amp = bool(train_cfg.get("mixed_precision", True)) and device.type == "cuda"
    scaler = make_grad_scaler(device.type, use_amp)

    start_epoch, best_metric = maybe_resume(
        student=student,
        loss_module=loss_module,
        optimizer=optimizer,
        scheduler=scheduler,
        scaler=scaler,
        resume_path=args.resume,
    )

    if args.eval_only:
        val_metrics = evaluate(student, val_loader, device, max_batches=args.max_eval_batches)
        logger.info("Validation metrics: %s", val_metrics)
        if test_loader is not None:
            test_metrics = evaluate(student, test_loader, device, max_batches=args.max_eval_batches)
            logger.info("Test metrics: %s", test_metrics)
        return

    epochs = int(train_cfg.get("epochs", 30))
    grad_clip = float(train_cfg.get("grad_clip", 1.0))
    early_stop_patience = args.early_stop_patience if args.early_stop_patience is None else max(1, int(args.early_stop_patience))
    early_stop_min_delta = float(args.early_stop_min_delta)
    epochs_without_improvement = 0

    for epoch in range(start_epoch, epochs):
        student.train()
        loss_module.train()
        running_total = 0.0
        running_orth = 0.0
        step_count = 0

        progress = tqdm(train_loader, desc=f"epoch {epoch + 1}/{epochs}", leave=False)
        max_steps = args.max_train_steps if args.max_train_steps is not None else train_cfg.get("max_train_steps")
        for batch_idx, batch in enumerate(progress):
            if max_steps is not None and batch_idx >= max_steps:
                break

            frames = batch["frame"].to(device)
            spectrograms = batch["spectrogram"].to(device)
            text_embeddings = batch["text_embedding"].to(device)
            labels = batch["segment_label"].to(device)
            sequence_mask = batch["sequence_mask"].to(device)
            frame_valid = batch["frame_valid"].to(device)
            audio_valid = batch["audio_valid"].to(device)
            strong_teacher_logits = batch["strong_teacher_logits"].to(device)
            strong_teacher_features = batch["strong_teacher_features"].to(device)
            strong_teacher_logit_mask = batch["strong_teacher_logit_mask"].to(device)
            strong_teacher_feature_mask = batch["strong_teacher_feature_mask"].to(device)
            weak_teacher_features = batch["weak_teacher_features"].to(device)
            weak_teacher_mask = batch["weak_teacher_mask"].to(device) * audio_valid
            weak_teacher_logits = batch["weak_teacher_logits"].to(device)
            weak_teacher_logit_mask = batch["weak_teacher_logit_mask"].to(device) * audio_valid

            # Simulation for E4: If alpha_weak_logit > 0 but dataset has no weak logits,
            # use jittered strong teacher logits as a weak audio proxy.
            if loss_module.alpha_weak_logit > 0 and weak_teacher_logit_mask.sum() == 0:
                # Add temporal shift/noise to strong logits
                weak_teacher_logits = strong_teacher_logits.clone()
                noise = torch.randn_like(weak_teacher_logits) * 0.5
                weak_teacher_logits = weak_teacher_logits + noise
                weak_teacher_logit_mask = strong_teacher_logit_mask
            text_valid = batch["text_valid"].to(device)

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
                loss, stats = loss_module(
                    student_segment_logits=outputs["segment_logits"],
                    student_segment_features=outputs["segment_features"],
                    strong_teacher_logits=strong_teacher_logits,
                    strong_teacher_features=strong_teacher_features,
                    weak_teacher_logits=weak_teacher_logits,
                    weak_teacher_features=weak_teacher_features,
                    text_embeddings=text_embeddings,
                    segment_labels=labels,
                    sequence_mask=sequence_mask,
                    strong_teacher_logit_mask=strong_teacher_logit_mask,
                    strong_teacher_feature_mask=strong_teacher_feature_mask,
                    weak_teacher_mask=weak_teacher_mask,
                    text_valid=text_valid,
                )

            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(parameters, grad_clip)
            scaler.step(optimizer)
            scaler.update()

            running_total += stats["total"]
            running_orth += stats["orth"]
            step_count += 1
            progress.set_postfix(loss=f"{stats['total']:.4f}", orth=f"{stats['orth']:.6f}")

        scheduler.step()
        val_metrics = evaluate(student, val_loader, device, max_batches=args.max_eval_batches)
        mean_train_loss = running_total / max(step_count, 1)
        mean_train_orth = running_orth / max(step_count, 1)
        logger.info("Epoch %d train_loss=%.4f train_orth=%.6f val=%s", epoch + 1, mean_train_loss, mean_train_orth, val_metrics)

        selection_metric = val_metrics.get("ap", val_metrics.get("auroc", val_metrics["accuracy"]))
        if selection_metric > best_metric + early_stop_min_delta:
            best_metric = selection_metric
            epochs_without_improvement = 0
            checkpoint = {
                "epoch": epoch,
                "best_metric": best_metric,
                "student_state_dict": student.state_dict(),
                "loss_state_dict": loss_module.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "scheduler_state_dict": scheduler.state_dict(),
                "scaler_state_dict": scaler.state_dict() if use_amp else None,
                "config": config,
            }
            torch.save(checkpoint, output_dir / "best.pt")
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
                    break

    if test_loader is not None and (output_dir / "best.pt").exists():
        best_checkpoint = torch.load(output_dir / "best.pt", map_location=device)
        student.load_state_dict(best_checkpoint["student_state_dict"])
        test_metrics = evaluate(student, test_loader, device, max_batches=args.max_eval_batches)
        logger.info("Best validation metric: %.4f", best_metric)
        logger.info("Test metrics: %s", test_metrics)


if __name__ == "__main__":
    main()
