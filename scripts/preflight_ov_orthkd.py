#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import mkdtemp
from typing import Any, Dict

import torch
import yaml
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
from src.utils.temporal_protocol import build_temporal_shape_receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a one-batch preflight for OV-OrthKD")
    parser.add_argument("--config", type=str, default="configs/ov_orthkd.yaml")
    parser.add_argument("--device", type=str, default=None)
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument("--probe-samples", type=int, default=4)
    parser.add_argument("--max-eval-batches", type=int, default=2)
    parser.add_argument(
        "--real-data",
        action="store_true",
        help="Require the canonical readiness gate and label this as the one real-data preflight",
    )
    parser.add_argument(
        "--optimizer-steps",
        type=int,
        default=1,
        help="Bounded optimizer-step count; R2 permits exactly one",
    )
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
        "observed_task_segments": 0,
        "strong_teacher_feature_dim": None,
        "weak_teacher_feature_dim": None,
        "text_dim": None,
    }
    for index in range(min(len(dataset), max(1, int(probe_samples)))):
        sample = dataset[index]
        observed["samples_probed"] += 1
        observed["observed_task_segments"] = max(
            observed["observed_task_segments"],
            int(sample["segment_label"].shape[0]),
        )
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
    real_data: bool,
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
        temporal_shape_receipt = None
        if real_data or int(batch["segment_label"].shape[1]) == 10:
            temporal_shape_receipt = build_temporal_shape_receipt(
                visual_input=batch["frame"],
                audio_input=batch["spectrogram"],
                visual_teacher_features=batch["strong_teacher_features"],
                audio_teacher_features=batch["weak_teacher_features"],
                labels=batch["segment_label"],
                student_logits=outputs["segment_logits"],
                sequence_mask=batch["sequence_mask"],
            )
        loss, stats = compute_loss_for_batch(loss_module, outputs, batch, device)

    scaler.scale(loss).backward()
    scaler.unscale_(optimizer)

    named_parameters = [
        (f"student.{name}", parameter)
        for name, parameter in student.named_parameters()
        if parameter.requires_grad
    ] + [
        (f"loss.{name}", parameter)
        for name, parameter in loss_module.named_parameters()
        if parameter.requires_grad
    ]
    missing_gradients = [name for name, parameter in named_parameters if parameter.grad is None]
    nonfinite_gradients = [
        name
        for name, parameter in named_parameters
        if parameter.grad is not None and not bool(torch.isfinite(parameter.grad).all())
    ]
    losses_finite = bool(torch.isfinite(loss.detach())) and all(
        torch.isfinite(torch.tensor(value, dtype=torch.float64)).item()
        for value in stats.values()
    )
    if real_data and not losses_finite:
        raise RuntimeError("Real-data preflight produced a non-finite loss")
    if real_data and nonfinite_gradients:
        raise RuntimeError(
            "Real-data preflight produced non-finite gradients: "
            + ", ".join(nonfinite_gradients)
        )
    if real_data and missing_gradients:
        raise RuntimeError(
            "Real-data preflight has trainable parameters without gradients: "
            + ", ".join(missing_gradients)
        )

    disabled_logit_losses: Dict[str, bool] = {}
    for loss_name, alpha_name in (
        ("strong_logit", "alpha_strong_logit"),
        ("weak_logit", "alpha_weak_logit"),
    ):
        if float(getattr(loss_module, alpha_name, 0.0)) == 0.0:
            disabled_logit_losses[loss_name] = stats.get(loss_name) == 0.0
    if real_data and not all(disabled_logit_losses.values()):
        raise RuntimeError("A disabled logit loss was not exactly zero")

    torch.nn.utils.clip_grad_norm_(parameters, grad_clip)
    scaler.step(optimizer)
    scaler.update()
    if scheduler_interval not in {"epoch", "optimizer_step"}:
        raise ValueError(f"Unsupported scheduler interval: {scheduler_interval}")
    scheduler.step()

    split_types = [str(value) for value in batch.get("split_type", [])]
    recognized_split_types = all(value in {"seen", "unseen"} for value in split_types)
    if real_data and (not split_types or not recognized_split_types):
        raise RuntimeError(
            "Real-data preflight batch must contain only normalized seen/unseen split_type values"
        )

    return {
        "batch_size": int(batch["frame"].shape[0]),
        "padded_segments": int(batch["frame"].shape[1]),
        "loss": float(loss.detach()),
        "loss_breakdown": stats,
        "losses_finite": losses_finite,
        "forward_completed": True,
        "backward_completed": True,
        "optimizer_step_completed": True,
        "scheduler_interval": scheduler_interval,
        "temporal_shape_receipt": temporal_shape_receipt,
        "input_shapes": {
            key: list(batch[key].shape)
            for key in ("frame", "spectrogram", "text_embedding", "sequence_mask")
        },
        "teacher_artifact_shapes": {
            key: list(batch[key].shape)
            for key in (
                "strong_teacher_logits",
                "strong_teacher_features",
                "weak_teacher_features",
                "text_embedding",
            )
        },
        "split_types": split_types,
        "split_types_normalized": recognized_split_types,
        "gradient_check": {
            "trainable_parameter_count": len(named_parameters),
            "parameters_with_gradients": len(named_parameters) - len(missing_gradients),
            "parameters_without_gradients": missing_gradients,
            "nonfinite_gradients": nonfinite_gradients,
            "all_received_gradients_finite": not missing_gradients and not nonfinite_gradients,
        },
        "disabled_logit_losses_exact_zero": disabled_logit_losses,
    }


def _expected_temporal_length(config: Dict[str, Any]) -> int | None:
    reproduction = config.get("reproduction", {})
    readiness = reproduction.get("readiness", {}) if isinstance(reproduction, dict) else {}
    lock_path = readiness.get("data_lock") if isinstance(readiness, dict) else None
    if not lock_path:
        return None
    resolved = Path(lock_path)
    if not resolved.is_absolute():
        project_root = Path(reproduction.get("project_root", PROJECT_ROOT))
        if not project_root.is_absolute():
            project_root = PROJECT_ROOT / project_root
        resolved = project_root.resolve() / resolved
    document = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    metadata = document.get("metadata", document.get("official_metadata", {}))
    histogram = metadata.get("segment_length_histogram", {}) if isinstance(metadata, dict) else {}
    nonzero = [int(length) for length, count in histogram.items() if int(count) > 0]
    return nonzero[0] if len(nonzero) == 1 else None


def _real_preflight_report_path(config: Dict[str, Any]) -> Path:
    reproduction = config.get("reproduction", {})
    readiness = reproduction.get("readiness", {}) if isinstance(reproduction, dict) else {}
    value = readiness.get("real_preflight") if isinstance(readiness, dict) else None
    if not isinstance(value, str) or not value:
        raise RuntimeError("Real preflight requires reproduction.readiness.real_preflight")
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    project_root = Path(reproduction.get("project_root", PROJECT_ROOT)).expanduser()
    if not project_root.is_absolute():
        project_root = PROJECT_ROOT / project_root
    return (project_root.resolve() / path).resolve()


def _claim_real_preflight_invocation(
    config: Dict[str, Any], *, optimizer_steps: int
) -> Path:
    if int(optimizer_steps) != 1:
        raise ValueError("R3 real preflight requires exactly 1 optimizer step")
    report_path = _real_preflight_report_path(config)
    marker_path = report_path.with_name(report_path.stem + ".invocation.json")
    if report_path.exists() or marker_path.exists():
        raise RuntimeError(
            "The single R3 real preflight invocation has already been claimed; "
            f"report={report_path.exists()} marker={marker_path.exists()}"
        )
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "status": "started",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "invocation_count_this_stage": 1,
        "optimizer_steps_planned": 1,
        "report_path": str(report_path),
    }
    try:
        with marker_path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    except FileExistsError as exc:
        raise RuntimeError("The single R3 real preflight invocation has already been claimed") from exc
    return marker_path


def _forward_after_resume(student, loader, device: torch.device) -> Dict[str, Any]:
    batch = next(iter(loader))
    student.eval()
    with torch.inference_mode():
        outputs = student(
            frame=batch["frame"].to(device),
            spectrogram=batch["spectrogram"].to(device),
            text_embedding=batch["text_embedding"].to(device),
            sequence_mask=batch["sequence_mask"].to(device),
            frame_valid=batch["frame_valid"].to(device),
            audio_valid=batch["audio_valid"].to(device),
        )
    tensor_outputs = {key: value for key, value in outputs.items() if isinstance(value, torch.Tensor)}
    finite = all(bool(torch.isfinite(value).all()) for value in tensor_outputs.values())
    if not finite:
        raise RuntimeError("Post-resume forward produced non-finite outputs")
    return {
        "passed": True,
        "finite": True,
        "output_shapes": {key: list(value.shape) for key, value in tensor_outputs.items()},
    }


def run_preflight(
    config: Dict[str, Any],
    device_name: str | None = None,
    output_dir: str | Path | None = None,
    probe_samples: int = 4,
    max_eval_batches: int = 2,
    real_data: bool = False,
    optimizer_steps: int = 1,
) -> Dict[str, Any]:
    if int(optimizer_steps) != 1:
        raise ValueError("R2 bounded preflight requires exactly 1 optimizer step")
    reproduction = config.get("reproduction", {})
    mock_only = bool(reproduction.get("mock_only", False))
    claim_level = str(reproduction.get("claim_level", "")).lower()
    if real_data and mock_only:
        raise RuntimeError("A mock-only config cannot be labeled as real data")
    if (
        claim_level in {"archival_exact", "paper_specified_reconstruction"}
        and not mock_only
        and not real_data
    ):
        raise RuntimeError("A formal reproduction preflight requires the explicit --real-data flag")
    validate_repro_config(
        config,
        allow_blocked=False,
        preflight=True,
        output_dir=output_dir,
        require_canonical_readiness=real_data,
    )
    invocation_marker = (
        _claim_real_preflight_invocation(config, optimizer_steps=optimizer_steps)
        if real_data
        else None
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
        real_data=real_data,
    )
    if real_data:
        val_metrics = None
        test_metrics = None
    else:
        val_metrics = evaluate(student, val_loader, device, max_batches=max_eval_batches)
        test_metrics = (
            evaluate(student, test_loader, device, max_batches=max_eval_batches)
            if test_loader is not None
            else None
        )

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
        best_metric=float(val_metrics.get("ap", 0.0)) if val_metrics is not None else 0.0,
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
    resume_epoch, resume_best, resume_global_step, resume_early_stop_counter = maybe_resume(
        student=resume_student,
        loss_module=resume_loss,
        optimizer=resume_optimizer,
        scheduler=resume_scheduler,
        scaler=resume_scaler,
        resume_path=str(checkpoint_path),
        expected_fingerprint=reproduction_fingerprint,
        loader_generators=loader_generators,
    )
    resume_forward = _forward_after_resume(resume_student, val_loader, device)

    expected_temporal_length = _expected_temporal_length(config) if real_data else None
    if real_data and expected_temporal_length is None:
        raise RuntimeError("Canonical data lock must define one exact temporal length for real preflight")
    if real_data and train_probe["padded_segments"] != expected_temporal_length:
        raise RuntimeError(
            "Real-data temporal length does not match the data lock: "
            f"batch={train_probe['padded_segments']} lock={expected_temporal_length}"
        )

    summary = {
        "schema_version": 1,
        "status": "passed",
        "preflight_only": True,
        "paper_result": False,
        "real_data": bool(real_data),
        "formal_metrics_emitted": False,
        "invocation_count_this_stage": 1 if real_data else 0,
        "optimizer_steps": int(optimizer_steps),
        "invocation_marker": str(invocation_marker) if invocation_marker else None,
        "batch_count": 1,
        "forward_completed": True,
        "backward_completed": True,
        "checkpoint_resume_completed": True,
        "losses_finite": train_probe["losses_finite"],
        "device": str(device),
        "use_amp": use_amp,
        "mock_only": mock_only,
        "implementation_mode": config.get("reproduction", {}).get(
            "implementation_mode", "legacy_collaboration"
        ),
        "manifest_summary": summaries,
        "dataset_probe": dataset_probe,
        "train_probe": train_probe,
        "expected_temporal_length_from_data_lock": expected_temporal_length,
        "val_metrics": val_metrics,
        "test_metrics": test_metrics,
        "resume_probe": {
            "checkpoint_path": str(checkpoint_path.resolve()),
            "resume_epoch": int(resume_epoch),
            "resume_best_metric": float(resume_best),
            "resume_global_step": int(resume_global_step),
            "resume_early_stop_counter": int(resume_early_stop_counter),
            "reproduction_fingerprint_sha256": reproduction_fingerprint["sha256"],
            "forward_after_resume": resume_forward,
        },
    }
    if device.type == "cuda":
        summary["cuda_max_memory_mb"] = float(torch.cuda.max_memory_allocated(device) / (1024**2))
        summary["peak_cuda_memory_bytes"] = int(torch.cuda.max_memory_allocated(device))
    else:
        summary["peak_cuda_memory_bytes"] = None

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
        real_data=args.real_data,
        optimizer_steps=args.optimizer_steps,
    )
    if args.real_data:
        report_path = _real_preflight_report_path(config)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        partial_path = report_path.with_suffix(report_path.suffix + ".partial")
        partial_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        partial_path.replace(report_path)
        marker_path = Path(str(summary["invocation_marker"]))
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        marker.update(
            {
                "status": "completed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "optimizer_steps_completed": 1,
                "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
            }
        )
        marker_partial = marker_path.with_suffix(marker_path.suffix + ".partial")
        marker_partial.write_text(
            json.dumps(marker, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        marker_partial.replace(marker_path)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
