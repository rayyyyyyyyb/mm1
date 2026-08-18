#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from tempfile import mkdtemp
from typing import Any, Dict

import torch
from torch.optim import AdamW
from torch.optim.lr_scheduler import CosineAnnealingLR

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

from scripts.check_manifest import load_manifest, summarize_ov_avel
from scripts.train_ov_orthkd import build_model_and_loss, evaluate, load_config, maybe_resume, set_seed
from src.data import create_ov_avel_data_loaders


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a one-batch preflight for OV-OrthKD")
    parser.add_argument("--config", type=str, default="configs/ov_orthkd.yaml")
    parser.add_argument("--device", type=str, default=None)
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument("--probe-samples", type=int, default=4)
    parser.add_argument("--max-eval-batches", type=int, default=2)
    return parser.parse_args()


def _summary_for_manifest(path_str: str) -> Dict[str, Any]:
    records = load_manifest(path_str)
    if not records:
        raise ValueError(f"Manifest is empty: {path_str}")
    if "segment_labels" not in records[0]:
        raise ValueError(f"Expected OV-AVEL records in {path_str}")
    summary = summarize_ov_avel(records)
    summary["manifest_path"] = str(Path(path_str).resolve())
    return summary


def _probe_dataset(dataset, probe_samples: int) -> Dict[str, Any]:
    observed = {
        "samples_probed": 0,
        "max_segments": 0,
        "strong_teacher_feature_dim": None,
        "weak_teacher_feature_dim": None,
        "text_dim": None,
    }
    for index in range(min(len(dataset), max(1, int(probe_samples)))):
        sample = dataset[index]
        observed["samples_probed"] += 1
        observed["max_segments"] = max(observed["max_segments"], int(sample["segment_label"].shape[0]))
        observed["strong_teacher_feature_dim"] = int(sample["strong_teacher_features"].shape[-1])
        observed["weak_teacher_feature_dim"] = int(sample["weak_teacher_features"].shape[-1])
        observed["text_dim"] = int(sample["text_embedding"].shape[-1])
    return observed


def _run_train_probe(
    student,
    loss_module,
    optimizer,
    scheduler,
    scaler,
    train_loader,
    device: torch.device,
    use_amp: bool,
    grad_clip: float,
) -> Dict[str, Any]:
    batch = next(iter(train_loader))
    parameters = list(student.parameters()) + list(loss_module.parameters())

    student.train()
    loss_module.train()

    optimizer.zero_grad(set_to_none=True)
    with autocast_context(device.type, use_amp):
        outputs = student(
            frame=batch["frame"].to(device),
            spectrogram=batch["spectrogram"].to(device),
            text_embedding=batch["text_embedding"].to(device),
            sequence_mask=batch["sequence_mask"].to(device),
            frame_valid=batch["frame_valid"].to(device),
            audio_valid=batch["audio_valid"].to(device),
        )
        loss, stats = loss_module(
            student_segment_logits=outputs["segment_logits"],
            student_segment_features=outputs["segment_features"],
            strong_teacher_logits=batch["strong_teacher_logits"].to(device),
            strong_teacher_features=batch["strong_teacher_features"].to(device),
            weak_teacher_features=batch["weak_teacher_features"].to(device),
            text_embeddings=batch["text_embedding"].to(device),
            segment_labels=batch["segment_label"].to(device),
            sequence_mask=batch["sequence_mask"].to(device),
            strong_teacher_logit_mask=batch["strong_teacher_logit_mask"].to(device),
            strong_teacher_feature_mask=batch["strong_teacher_feature_mask"].to(device),
            weak_teacher_mask=(batch["weak_teacher_mask"] * batch["audio_valid"]).to(device),
            text_valid=batch["text_valid"].to(device),
        )

    scaler.scale(loss).backward()
    scaler.unscale_(optimizer)
    torch.nn.utils.clip_grad_norm_(parameters, grad_clip)
    scaler.step(optimizer)
    scaler.update()
    scheduler.step()

    return {
        "batch_size": int(batch["frame"].shape[0]),
        "padded_segments": int(batch["frame"].shape[1]),
        "loss": float(loss.detach()),
        "loss_breakdown": stats,
    }


def run_preflight(
    config: Dict[str, Any],
    device_name: str | None = None,
    output_dir: str | Path | None = None,
    probe_samples: int = 4,
    max_eval_batches: int = 2,
) -> Dict[str, Any]:
    set_seed(int(config.get("seed", 42)))
    device = torch.device(device_name or ("cuda" if torch.cuda.is_available() else "cpu"))

    summaries = {
        "train": _summary_for_manifest(config["data"]["train_manifest"]),
        "val": _summary_for_manifest(config["data"]["val_manifest"]),
    }
    if config["data"].get("test_manifest"):
        summaries["test"] = _summary_for_manifest(config["data"]["test_manifest"])

    train_loader, val_loader, test_loader = create_ov_avel_data_loaders(config)
    dataset_probe = {
        "train": _probe_dataset(train_loader.dataset, probe_samples),
        "val": _probe_dataset(val_loader.dataset, probe_samples),
    }

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

    train_probe = _run_train_probe(
        student=student,
        loss_module=loss_module,
        optimizer=optimizer,
        scheduler=scheduler,
        scaler=scaler,
        train_loader=train_loader,
        device=device,
        use_amp=use_amp,
        grad_clip=float(train_cfg.get("grad_clip", 1.0)),
    )
    val_metrics = evaluate(student, val_loader, device, max_batches=max_eval_batches)
    test_metrics = evaluate(student, test_loader, device, max_batches=max_eval_batches) if test_loader is not None else None

    if output_dir is None:
        output_path = Path(mkdtemp(prefix="ov_orthkd_preflight_"))
    else:
        output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output_path / "preflight_resume.pt"

    checkpoint = {
        "epoch": 0,
        "best_metric": float(val_metrics.get("ap", 0.0)),
        "student_state_dict": student.state_dict(),
        "loss_state_dict": loss_module.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "scheduler_state_dict": scheduler.state_dict(),
        "scaler_state_dict": scaler.state_dict() if use_amp else None,
        "config": config,
    }
    torch.save(checkpoint, checkpoint_path)

    resume_student, resume_loss = build_model_and_loss(config, device)
    resume_optimizer = AdamW(
        list(resume_student.parameters()) + list(resume_loss.parameters()),
        lr=float(train_cfg.get("learning_rate", 2e-4)),
        weight_decay=float(train_cfg.get("weight_decay", 1e-4)),
    )
    resume_scheduler = CosineAnnealingLR(resume_optimizer, T_max=int(train_cfg.get("epochs", 30)))
    resume_scaler = make_grad_scaler(device.type, use_amp)
    resume_epoch, resume_best = maybe_resume(
        student=resume_student,
        loss_module=resume_loss,
        optimizer=resume_optimizer,
        scheduler=resume_scheduler,
        scaler=resume_scaler,
        resume_path=str(checkpoint_path),
    )

    summary = {
        "device": str(device),
        "use_amp": use_amp,
        "manifest_summary": summaries,
        "dataset_probe": dataset_probe,
        "train_probe": train_probe,
        "val_metrics": val_metrics,
        "test_metrics": test_metrics,
        "resume_probe": {
            "checkpoint_path": str(checkpoint_path.resolve()),
            "resume_epoch": int(resume_epoch),
            "resume_best_metric": float(resume_best),
        },
    }
    if device.type == "cuda":
        summary["cuda_max_memory_mb"] = float(torch.cuda.max_memory_allocated(device) / (1024**2))

    return summary


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    summary = run_preflight(
        config=config,
        device_name=args.device,
        output_dir=args.output_dir,
        probe_samples=args.probe_samples,
        max_eval_batches=args.max_eval_batches,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
