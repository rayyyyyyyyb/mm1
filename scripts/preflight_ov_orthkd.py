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
from scripts.train_ov_orthkd import (
    build_model_and_loss,
    build_scheduler,
    checkpoint_payload,
    compute_loss_for_batch,
    evaluate,
    load_config,
    maybe_resume,
    set_seed,
    validate_repro_config,
)
from src.data import create_ov_avel_data_loaders
from src.utils.reproduction_fingerprint import build_reproduction_fingerprint


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
    scheduler_interval: str,
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
        loss, stats = compute_loss_for_batch(loss_module, outputs, batch, device)

    scaler.scale(loss).backward()
    scaler.unscale_(optimizer)
    torch.nn.utils.clip_grad_norm_(parameters, grad_clip)
    scaler.step(optimizer)
    scaler.update()
    if scheduler_interval not in {"epoch", "optimizer_step"}:
        raise ValueError(f"Unsupported scheduler interval: {scheduler_interval}")
    scheduler.step()

    return {
        "batch_size": int(batch["frame"].shape[0]),
        "padded_segments": int(batch["frame"].shape[1]),
        "loss": float(loss.detach()),
        "loss_breakdown": stats,
        "scheduler_interval": scheduler_interval,
    }


def run_preflight(
    config: Dict[str, Any],
    device_name: str | None = None,
    output_dir: str | Path | None = None,
    probe_samples: int = 4,
    max_eval_batches: int = 2,
) -> Dict[str, Any]:
    validate_repro_config(
        config,
        allow_blocked=False,
        preflight=True,
        output_dir=output_dir,
    )
    set_seed(
        int(config.get("seed", 42)),
        deterministic=bool(config.get("training", {}).get("deterministic", True)),
    )
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
    scheduler, scheduler_interval = build_scheduler(
        optimizer,
        train_cfg,
        epochs=int(train_cfg.get("epochs", 30)),
        steps_per_epoch=max(len(train_loader), 1),
    )
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
        scheduler_interval=scheduler_interval,
    )
    val_metrics = evaluate(student, val_loader, device, max_batches=max_eval_batches)
    test_metrics = evaluate(student, test_loader, device, max_batches=max_eval_batches) if test_loader is not None else None

    if output_dir is None:
        output_path = Path(mkdtemp(prefix="ov_orthkd_preflight_"))
    else:
        output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output_path / "preflight_resume.pt"

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
    checkpoint = checkpoint_payload(
        epoch=0,
        global_step=1,
        best_metric=float(val_metrics.get("ap", 0.0)),
        student=student,
        loss_module=loss_module,
        optimizer=optimizer,
        scheduler=scheduler,
        scaler=scaler,
        config=config,
        reproduction_fingerprint=reproduction_fingerprint,
        loader_generators=loader_generators,
    )
    torch.save(checkpoint, checkpoint_path)

    resume_student, resume_loss = build_model_and_loss(config, device)
    resume_optimizer = AdamW(
        list(resume_student.parameters()) + list(resume_loss.parameters()),
        lr=float(train_cfg.get("learning_rate", 2e-4)),
        weight_decay=float(train_cfg.get("weight_decay", 1e-4)),
    )
    resume_scheduler, _ = build_scheduler(
        resume_optimizer,
        train_cfg,
        epochs=int(train_cfg.get("epochs", 30)),
        steps_per_epoch=max(len(train_loader), 1),
    )
    resume_scaler = make_grad_scaler(device.type, use_amp)
    resume_epoch, resume_best, resume_global_step = maybe_resume(
        student=resume_student,
        loss_module=resume_loss,
        optimizer=resume_optimizer,
        scheduler=resume_scheduler,
        scaler=resume_scaler,
        resume_path=str(checkpoint_path),
        expected_fingerprint=reproduction_fingerprint,
        loader_generators=loader_generators,
    )

    summary = {
        "preflight_only": True,
        "paper_result": False,
        "optimizer_steps": 1,
        "device": str(device),
        "use_amp": use_amp,
        "mock_only": bool(config.get("reproduction", {}).get("mock_only", False)),
        "implementation_mode": config.get("reproduction", {}).get(
            "implementation_mode", "legacy_collaboration"
        ),
        "manifest_summary": summaries,
        "dataset_probe": dataset_probe,
        "train_probe": train_probe,
        "val_metrics": val_metrics,
        "test_metrics": test_metrics,
        "resume_probe": {
            "checkpoint_path": str(checkpoint_path.resolve()),
            "resume_epoch": int(resume_epoch),
            "resume_best_metric": float(resume_best),
            "resume_global_step": int(resume_global_step),
            "reproduction_fingerprint_sha256": reproduction_fingerprint["sha256"],
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
