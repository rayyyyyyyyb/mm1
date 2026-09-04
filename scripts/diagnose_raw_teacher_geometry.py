#!/usr/bin/env python3

"""Read-only raw teacher/projected target/student decision geometry audit.

The runner compares the cached [T,512] InternVideo2 features with the
checkpoint's projected target and student decision representation.  It never
constructs an optimizer, performs an update, or writes a checkpoint.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import torch
import torch.nn.functional as F
import yaml
from torch import nn
from torch.utils.data import DataLoader

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.diagnose_formal_predictions import (  # noqa: E402
    load_prediction_npz,
)
from scripts.diagnose_teacher_cache import (  # noqa: E402
    fit_linear_probe,
    load_feature_split,
)
from scripts.diagnose_visual_sum_posthoc import (  # noqa: E402
    _make_mixed_loader,
    select_mixed_sample_indices,
    sha256_file,
)
from src.utils.temporal_protocol import (  # noqa: E402
    task_segments_from_config,
    validate_temporal_alignment,
)


TASK_SEGMENTS = 10
RAW_TEACHER_DIM = 512
PROJECTION_DIM = 256


def _validate_feature_inputs(
    features: torch.Tensor, mask: torch.Tensor
) -> tuple[torch.Tensor, torch.Tensor]:
    if not isinstance(features, torch.Tensor) or not isinstance(mask, torch.Tensor):
        raise TypeError("features and mask must be tensors")
    if features.ndim != 3:
        raise ValueError("features must have shape [B,T,D]")
    if mask.ndim != 2 or tuple(mask.shape) != tuple(features.shape[:2]):
        raise ValueError("mask must have shape [B,T] matching features")
    if not bool(torch.isfinite(features).all()):
        raise ValueError("features contain NaN/Inf")
    mask_bool = mask.detach().to(device=features.device).bool()
    if not bool(mask_bool.any()):
        raise ValueError("mask contains no valid rows")
    return features, mask_bool


def summarize_feature_geometry(
    features: torch.Tensor, mask: torch.Tensor
) -> dict[str, Any]:
    """Summarize global scale and within-video temporal variation."""

    features, mask_bool = _validate_feature_inputs(features, mask)
    rows = features.detach()[mask_bool].to(dtype=torch.float64, device="cpu")
    centered_chunks: list[torch.Tensor] = []
    temporal_std_sum = 0.0
    temporal_samples = 0
    for sample_index in range(features.shape[0]):
        sample = features[sample_index, mask_bool[sample_index]].detach().to(
            dtype=torch.float64, device="cpu"
        )
        if sample.shape[0] == 0:
            continue
        centered = sample - sample.mean(dim=0, keepdim=True)
        centered_chunks.append(centered)
        temporal_std_sum += float(sample.std(dim=0, unbiased=False).mean())
        temporal_samples += 1
    if not centered_chunks:
        raise ValueError("features contain no valid temporal sample")
    centered_rows = torch.cat(centered_chunks, dim=0)
    return {
        "shape": list(features.shape),
        "valid_rows": int(rows.shape[0]),
        "feature_dim": int(rows.shape[1]),
        "absolute_mean": float(rows.abs().mean()),
        "rms": float(rows.square().mean().sqrt()),
        "row_l2_mean": float(torch.linalg.vector_norm(rows, dim=-1).mean()),
        "within_sample_temporal_std_mean": temporal_std_sum / temporal_samples,
        "temporal_sample_count": temporal_samples,
        "centered_temporal_variance_mean": float(centered_rows.var(dim=0, unbiased=False).mean()),
        "centered_row_l2_mean": float(
            torch.linalg.vector_norm(centered_rows, dim=-1).mean()
        ),
    }


def _pairwise_upper(values: torch.Tensor) -> torch.Tensor:
    distances = torch.cdist(values, values, p=2)
    upper = torch.triu_indices(values.shape[0], values.shape[0], offset=1)
    return distances[upper[0], upper[1]]


def pairwise_distance_correlation(
    source: torch.Tensor, target: torch.Tensor, mask: torch.Tensor
) -> dict[str, Any]:
    """Compare within-video temporal distance geometry using Pearson r."""

    source, source_mask = _validate_feature_inputs(source, mask)
    target, target_mask = _validate_feature_inputs(target, mask)
    if tuple(source.shape[:2]) != tuple(target.shape[:2]) or not torch.equal(
        source_mask, target_mask
    ):
        raise ValueError("source/target leading dimensions or masks differ")
    correlations: list[float] = []
    pair_weights: list[int] = []
    pair_count = 0
    for sample_index in range(source.shape[0]):
        valid = source_mask[sample_index]
        source_rows = source[sample_index, valid].detach().to(dtype=torch.float64)
        target_rows = target[sample_index, valid].detach().to(dtype=torch.float64)
        if source_rows.shape[0] < 3:
            continue
        source_distances = _pairwise_upper(source_rows)
        target_distances = _pairwise_upper(target_rows)
        source_centered = source_distances - source_distances.mean()
        target_centered = target_distances - target_distances.mean()
        denominator = float(
            torch.linalg.vector_norm(source_centered)
            * torch.linalg.vector_norm(target_centered)
        )
        if denominator <= 1e-12:
            continue
        correlation = float((source_centered * target_centered).sum()) / denominator
        if not math.isfinite(correlation):
            raise ValueError("pairwise correlation is non-finite")
        correlations.append(correlation)
        sample_pair_count = int(source_distances.numel())
        pair_weights.append(sample_pair_count)
        pair_count += sample_pair_count
    if not correlations:
        raise ValueError("No sample has non-degenerate pairwise distances")
    weighted = float(
        np.average(np.asarray(correlations), weights=np.asarray(pair_weights, dtype=np.float64))
    )
    return {
        "sample_count": len(correlations),
        "pair_count": pair_count,
        "pair_weighted_mean": weighted,
        "video_macro_mean": float(np.mean(correlations)),
        "video_macro_median": float(np.median(correlations)),
        "video_macro_min": float(np.min(correlations)),
        "video_macro_max": float(np.max(correlations)),
    }


def _effective_rank(singular_values: torch.Tensor) -> float:
    spectrum = singular_values.to(dtype=torch.float64).square()
    total = float(spectrum.sum())
    if total <= 0.0:
        return 0.0
    probabilities = spectrum / total
    positive = probabilities > 0.0
    return float((-(probabilities[positive] * probabilities[positive].log()).sum()).exp())


def summarize_projector_spectrum(
    projector: nn.Module, inputs: torch.Tensor | None = None
) -> dict[str, Any]:
    """Report every Linear spectrum and optional final-layer bias/input ratio."""

    if not isinstance(projector, nn.Module):
        raise TypeError("projector must be a torch module")
    linear_layers: list[dict[str, Any]] = []
    for name, module in projector.named_modules():
        if not isinstance(module, nn.Linear):
            continue
        weight = module.weight.detach().to(dtype=torch.float64, device="cpu")
        singular_values = torch.linalg.svdvals(weight)
        linear_layers.append(
            {
                "name": name or "<root>",
                "input_dim": int(module.in_features),
                "output_dim": int(module.out_features),
                "singular_values": [float(value) for value in singular_values.tolist()],
                "effective_rank": _effective_rank(singular_values),
                "weight_rms": float(weight.square().mean().sqrt()),
                "bias_l2": (
                    float(module.bias.detach().to(dtype=torch.float64).norm())
                    if module.bias is not None
                    else None
                ),
            }
        )
    if not linear_layers:
        raise ValueError("projector contains no Linear layers")
    output_name = linear_layers[-1]["name"]
    first_linear = next(
        module for module in projector.modules() if isinstance(module, nn.Linear)
    )
    output_layer = next(
        module
        for name, module in projector.named_modules()
        if isinstance(module, nn.Linear) and (name or "<root>") == output_name
    )
    output_bias = output_layer.bias
    output_bias_l2 = (
        float(output_bias.detach().to(dtype=torch.float64).norm())
        if output_bias is not None
        else None
    )
    report: dict[str, Any] = {
        "linear_layers": linear_layers,
        "output_linear_layer": output_name,
        "output_bias_l2": output_bias_l2,
        "output_weight_rms": linear_layers[-1]["weight_rms"],
        "output_bias_to_weight_rms_ratio": (
            output_bias_l2 / (linear_layers[-1]["weight_rms"] * math.sqrt(output_layer.in_features))
            if output_bias_l2 is not None and linear_layers[-1]["weight_rms"] > 0.0
            else None
        ),
    }
    if inputs is not None:
        if not isinstance(inputs, torch.Tensor) or inputs.ndim != 2:
            raise ValueError("projector inputs must have shape [N,D]")
        if inputs.shape[1] != first_linear.in_features:
            raise ValueError("projector input dimension mismatch")
        if not bool(torch.isfinite(inputs).all()):
            raise ValueError("projector inputs contain NaN/Inf")
        captured: list[torch.Tensor] = []

        def hook(_module: nn.Module, args: tuple[torch.Tensor, ...]) -> None:
            captured.append(args[0].detach())

        try:
            input_device = next(projector.parameters()).device
        except StopIteration:
            input_device = inputs.device
        projector_inputs = inputs.to(input_device)
        was_training = projector.training
        projector.eval()
        handle = output_layer.register_forward_pre_hook(hook)
        try:
            with torch.no_grad():
                projector(projector_inputs)
        finally:
            handle.remove()
            projector.train(was_training)
        if not captured:
            raise RuntimeError("Projector output-layer hook did not capture inputs")
        layer_input = captured[-1].to(dtype=torch.float64)
        weight = output_layer.weight.detach().to(
            device=layer_input.device, dtype=torch.float64
        )
        input_component = F.linear(layer_input, weight, bias=None)
        input_rms = float(input_component.square().mean().sqrt())
        report["output_input_component_rms"] = input_rms
        report["output_bias_to_input_component_rms_ratio"] = (
            output_bias_l2 / input_rms if output_bias_l2 is not None and input_rms > 0.0 else None
        )
    return report


def fit_linear_probe_metrics(
    train_features: np.ndarray,
    train_labels: np.ndarray,
    eval_features: np.ndarray,
    eval_labels: np.ndarray,
    *,
    random_state: int = 42,
) -> dict[str, Any]:
    """Fit the existing transparent train-split probe and return one eval row."""

    result = fit_linear_probe(
        train_features,
        train_labels,
        {"evaluation": (eval_features, eval_labels)},
        random_state=int(random_state),
    )
    evaluation = result["evaluation"]["evaluation"]
    return {
        "aggregation": "global_micro_over_official_task_segments",
        "feature_dim": int(np.asarray(train_features).shape[1]),
        "train_segments": int(np.asarray(train_labels).size),
        "evaluation": evaluation,
        "protocol": result["protocol"],
        "fit": result["fit"],
    }


def _source_receipt(path: Path) -> dict[str, Any]:
    source = path.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    return {"path": str(source), "bytes": source.stat().st_size, "sha256": sha256_file(source)}


def _teacher_cache_lock_receipt(path: Path | None) -> dict[str, Any]:
    """Return the immutable teacher-cache lock and its own source receipt."""

    if path is None:
        return {"status": "unavailable", "reason": "lock_path_not_supplied"}
    source = path.resolve()
    if not source.is_file():
        return {"status": "unavailable", "reason": "lock_file_not_found", "expected_path": str(source)}
    try:
        lock = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "unavailable", "reason": f"lock_file_unreadable:{type(exc).__name__}", "source": _source_receipt(source)}
    if not isinstance(lock, dict):
        raise ValueError(f"teacher cache lock is not a JSON object: {source}")
    return {"status": "PASS", "source": _source_receipt(source), "lock": lock}


def _canonical_mapping_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _state_dict_sha256(module: nn.Module) -> str:
    digest = hashlib.sha256()
    for name, tensor in sorted(module.state_dict().items()):
        value = tensor.detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(value.dtype).encode("ascii"))
        digest.update(json.dumps(list(value.shape)).encode("ascii"))
        digest.update(value.numpy().tobytes(order="C"))
    return digest.hexdigest()


def _strict_load(
    student: nn.Module,
    loss_module: nn.Module,
    path: Path,
    config: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(checkpoint, dict):
        raise ValueError(f"checkpoint is not a mapping: {path}")
    embedded = checkpoint.get("config")
    if not isinstance(embedded, dict) or _canonical_mapping_sha256(embedded) != _canonical_mapping_sha256(config):
        raise ValueError(f"checkpoint config mismatch: {path}")
    student_result = student.load_state_dict(checkpoint["student_state_dict"], strict=True)
    loss_result = loss_module.load_state_dict(checkpoint["loss_state_dict"], strict=True)
    if student_result.missing_keys or student_result.unexpected_keys or loss_result.missing_keys or loss_result.unexpected_keys:
        raise RuntimeError(f"strict state loading failed: {path}")
    return checkpoint, {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "global_step": int(checkpoint.get("global_step", -1)),
        "epoch": int(checkpoint.get("epoch", -1)),
        "student_state_sha256": _state_dict_sha256(student),
        "loss_state_sha256": _state_dict_sha256(loss_module),
        "strict_student": True,
        "strict_loss": True,
    }


def _collect_state_geometry(
    student: nn.Module,
    loss_module: nn.Module,
    loader: DataLoader,
    device: torch.device,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    student.eval()
    raw_parts: list[torch.Tensor] = []
    decision_parts: list[torch.Tensor] = []
    mask_parts: list[torch.Tensor] = []
    label_parts: list[torch.Tensor] = []
    for batch in loader:
        raw = batch["strong_teacher_features"].to(device)
        mask = (
            batch["sequence_mask"].to(device).bool()
            & batch["strong_teacher_feature_mask"].to(device).bool()
        )
        outputs = student(
            frame=batch["frame"].to(device),
            spectrogram=batch["spectrogram"].to(device),
            text_embedding=batch["text_embedding"].to(device),
            sequence_mask=batch["sequence_mask"].to(device),
            frame_valid=batch["frame_valid"].to(device),
            audio_valid=batch["audio_valid"].to(device),
        )
        decision = outputs.get("decision_features")
        logits = outputs.get("segment_logits")
        if not isinstance(decision, torch.Tensor) or not isinstance(logits, torch.Tensor):
            raise RuntimeError("state forward did not return decision/logits")
        labels = batch["segment_label"].to(device)
        validate_temporal_alignment(
            student_logits=logits,
            labels=labels,
            sequence_mask=batch["sequence_mask"].to(device).bool(),
            task_segments=TASK_SEGMENTS,
        )
        if raw.ndim != 3 or raw.shape[1:] != (TASK_SEGMENTS, RAW_TEACHER_DIM):
            raise ValueError(f"raw teacher feature shape is {tuple(raw.shape)}")
        if decision.ndim != 3 or decision.shape[1:] != (TASK_SEGMENTS, PROJECTION_DIM):
            raise ValueError(f"student decision shape is {tuple(decision.shape)}")
        raw_parts.append(raw.detach().cpu())
        decision_parts.append(decision.detach().cpu())
        mask_parts.append(mask.detach().cpu())
        label_parts.append(labels.detach().cpu())
    if not raw_parts:
        raise ValueError("geometry loader is empty")
    return (
        torch.cat(raw_parts, dim=0),
        torch.cat(decision_parts, dim=0),
        torch.cat(mask_parts, dim=0).bool(),
        torch.cat(label_parts, dim=0),
    )


def _project_numpy(
    projector: nn.Module,
    features: np.ndarray,
    device: torch.device,
    *,
    batch_size: int = 8192,
) -> np.ndarray:
    projector.eval()
    chunks: list[np.ndarray] = []
    with torch.no_grad():
        for start in range(0, features.shape[0], batch_size):
            tensor = torch.from_numpy(np.asarray(features[start : start + batch_size], dtype=np.float32)).to(device)
            value = projector(tensor).detach().cpu().numpy().astype(np.float32, copy=False)
            chunks.append(value)
    return np.concatenate(chunks, axis=0)


def _flatten_valid(features: torch.Tensor, mask: torch.Tensor) -> np.ndarray:
    return features[mask].detach().cpu().numpy().astype(np.float32, copy=False)


def _state_report(
    *,
    name: str,
    source: Mapping[str, Any],
    projector: nn.Module,
    raw: torch.Tensor,
    decision: torch.Tensor,
    mask: torch.Tensor,
    device: torch.device,
) -> dict[str, Any]:
    projected = projector(raw.to(device)).detach().cpu()
    source_hash_before = _state_dict_sha256(projector)
    raw_geometry = summarize_feature_geometry(raw, mask)
    projected_geometry = summarize_feature_geometry(projected, mask)
    decision_geometry = summarize_feature_geometry(decision, mask)
    report = {
        "available": True,
        "source": dict(source),
        "raw_teacher": raw_geometry,
        "projected_target": projected_geometry,
        "student_decision": decision_geometry,
        "pairwise_distance_correlation": {
            "raw_to_projected": pairwise_distance_correlation(raw, projected, mask),
            "projected_to_decision": pairwise_distance_correlation(projected, decision, mask),
            "raw_to_decision": pairwise_distance_correlation(raw, decision, mask),
        },
        "projector_spectrum": summarize_projector_spectrum(
            projector, torch.from_numpy(_flatten_valid(raw, mask))
        ),
        "projector_state_sha256_before": source_hash_before,
        "projector_state_sha256_after": _state_dict_sha256(projector),
    }
    if report["projector_state_sha256_before"] != report["projector_state_sha256_after"]:
        raise RuntimeError(f"state {name} projector mutated during read-only probe")
    return report


def _mixed_ids_and_loader(
    test_loader: DataLoader, test_predictions: Mapping[str, np.ndarray]
) -> tuple[list[str], DataLoader]:
    mixed_archive_indices = select_mixed_sample_indices(test_predictions)
    archive_ids = [str(value) for value in np.asarray(test_predictions["ids"]).tolist()]
    records = getattr(test_loader.dataset, "records", None)
    if not isinstance(records, list) or len(records) != len(archive_ids):
        raise ValueError("test dataset records do not match prediction archive")
    dataset_ids = [str(record.get("id", index)) for index, record in enumerate(records)]
    if set(dataset_ids) != set(archive_ids) or len(set(dataset_ids)) != len(dataset_ids):
        raise ValueError("test dataset IDs and prediction IDs differ")
    index_by_id = {value: index for index, value in enumerate(dataset_ids)}
    mixed_ids = [archive_ids[index] for index in mixed_archive_indices]
    return mixed_ids, _make_mixed_loader(test_loader, [index_by_id[value] for value in mixed_ids])


def build_raw_teacher_report(
    *,
    config_path: Path,
    best_checkpoint_path: Path,
    last_checkpoint_path: Path,
    test_predictions_path: Path,
    output_path: Path,
    device: torch.device,
    workers: int,
    probe_seed: int,
    step400_checkpoint_path: Path | None = None,
    teacher_cache_lock_path: Path | None = None,
) -> dict[str, Any]:
    if int(workers) < 1:
        raise ValueError("workers must be at least one")
    if output_path.exists() or output_path.with_name(output_path.name + ".tmp").exists():
        raise FileExistsError(f"refusing to overwrite output: {output_path}")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or task_segments_from_config(config) != TASK_SEGMENTS:
        raise ValueError("raw teacher geometry audit requires official T=10 config")
    from scripts.train_ov_orthkd import build_model_and_loss, set_seed
    from src.data import create_ov_avel_data_loaders

    set_seed(int(config.get("seed", 42)), deterministic=bool(config.get("training", {}).get("deterministic", True)))
    student, loss_module = build_model_and_loss(config, device)
    initial_student_hash = _state_dict_sha256(student)
    initial_loss_hash = _state_dict_sha256(loss_module)
    train_loader, _validation_loader, test_loader = create_ov_avel_data_loaders(config)
    del train_loader, _validation_loader
    saved_test = load_prediction_npz(test_predictions_path)
    mixed_ids, mixed_loader = _mixed_ids_and_loader(test_loader, saved_test)

    states: dict[str, dict[str, Any]] = {}
    initial_raw, initial_decision, initial_mask, initial_labels = _collect_state_geometry(
        student, loss_module, mixed_loader, device
    )
    initial_projector = getattr(loss_module, "strong_teacher_proj", None)
    if not isinstance(initial_projector, nn.Module):
        raise RuntimeError("loss has no strong_teacher_proj")
    states["initialization"] = _state_report(
        name="initialization",
        source={"available": True, "kind": "deterministic_rebuild_before_checkpoint_load"},
        projector=initial_projector,
        raw=initial_raw,
        decision=initial_decision,
        mask=initial_mask,
        device=device,
    )
    initial_state_after_hash = _state_dict_sha256(student)
    if initial_state_after_hash != initial_student_hash:
        raise RuntimeError("initial student mutated during geometry collection")
    if _state_dict_sha256(loss_module) != initial_loss_hash:
        raise RuntimeError("initial loss mutated during geometry collection")

    checkpoint_specs: list[tuple[str, Path | None]] = [("step400", step400_checkpoint_path)]
    if checkpoint_specs[0][1] is None:
        candidate = best_checkpoint_path.parent / "diagnostic_checkpoints" / "step_000400.pt"
        checkpoint_specs[0] = ("step400", candidate)
    checkpoint_specs.extend((("best", best_checkpoint_path), ("last", last_checkpoint_path)))
    checkpoint_receipts: dict[str, Any] = {}
    intentional_state_loads: list[str] = []
    source_mutation_detected = False
    for name, checkpoint_path in checkpoint_specs:
        if checkpoint_path is None or not checkpoint_path.is_file():
            states[name] = {
                "available": False,
                "reason": "checkpoint_not_available",
                "expected_path": str(checkpoint_path) if checkpoint_path is not None else None,
            }
            continue
        checkpoint, receipt = _strict_load(student, loss_module, checkpoint_path, config)
        checkpoint_receipts[name] = receipt
        intentional_state_loads.append(name)
        state_student_hash = _state_dict_sha256(student)
        state_loss_hash = _state_dict_sha256(loss_module)
        raw, decision, mask, labels = _collect_state_geometry(student, loss_module, mixed_loader, device)
        if _state_dict_sha256(student) != state_student_hash or _state_dict_sha256(loss_module) != state_loss_hash:
            raise RuntimeError(f"state {name} mutated during geometry collection")
        if not torch.equal(mask, initial_mask) or not torch.equal(labels, initial_labels):
            raise RuntimeError(f"state {name} changed the evaluation mask or labels")
        projector = getattr(loss_module, "strong_teacher_proj", None)
        if not isinstance(projector, nn.Module):
            raise RuntimeError(f"state {name} has no strong_teacher_proj")
        states[name] = _state_report(
            name=name,
            source=receipt,
            projector=projector,
            raw=raw,
            decision=decision,
            mask=mask,
            device=device,
        )
        states[name]["checkpoint_epoch"] = int(checkpoint.get("epoch", -1))
        states[name]["checkpoint_global_step"] = int(checkpoint.get("global_step", -1))

    # Train-split probes are applied only to raw and projected teacher features.
    data_cfg = config.get("data", {})
    path_root = Path(data_cfg.get("path_root", ".")).expanduser().resolve()
    train_manifest = path_root / str(data_cfg["train_manifest"])
    raw_train, raw_train_labels, train_receipt = load_feature_split(
        train_manifest,
        field="strong_teacher_features_path",
        expected_segments=TASK_SEGMENTS,
        expected_dim=RAW_TEACHER_DIM,
        workers=int(workers),
        project_root=path_root,
    )
    raw_eval, raw_eval_labels = _flatten_valid(initial_raw, initial_mask), initial_labels[initial_mask].numpy().astype(np.int64)
    linear_probes: dict[str, Any] = {
        "student_decision": {
            "status": "not_run",
            "reason": "No in-sample probe; train-split student decision extraction would require a separate full train forward.",
        }
    }
    for name in ("initialization", "best", "last"):
        if not states[name].get("available"):
            linear_probes[name] = {"status": "not_available"}
            continue
        checkpoint_path = {"best": best_checkpoint_path, "last": last_checkpoint_path}.get(name)
        if checkpoint_path is not None:
            _strict_load(student, loss_module, checkpoint_path, config)
        projector = loss_module.strong_teacher_proj
        raw_train_for_probe = raw_train
        eval_raw = raw_eval
        if name == "initialization":
            train_for_probe = raw_train_for_probe
            eval_for_probe = eval_raw
        else:
            train_for_probe = _project_numpy(projector, raw_train_for_probe, device)
            eval_for_probe = _project_numpy(projector, eval_raw, device)
        linear_probes[name] = {
            "status": "PASS",
            "feature_source": "raw_teacher" if name == "initialization" else "projected_teacher_target",
            "data": {"train": train_receipt, "evaluation": {"samples": len(mixed_ids), "segments": int(raw_eval_labels.size)}},
            "probe": fit_linear_probe_metrics(
                train_for_probe,
                raw_train_labels,
                eval_for_probe,
                raw_eval_labels,
                random_state=int(probe_seed),
            ),
        }

    if teacher_cache_lock_path is None:
        derived_lock = output_path.resolve().parent.parent / "teacher_cache_hash.json"
        teacher_cache_lock_path = derived_lock if derived_lock.is_file() else None
    report = {
        "schema_version": 1,
        "status": "PASS",
        "claim_level": "noncanonical_raw_teacher_geometry_audit",
        "scientific_success_claimed": False,
        "authorization": {
            "formal_full_training_authorized": False,
            "next_experiment_authorized": False,
            "decision": "raw_teacher_geometry_only_before_any_projector_or_full_change",
        },
        "protocol": {
            "task_segments": TASK_SEGMENTS,
            "temporal_conversion": "forbidden",
            "mixed_label_subset": "0 < positive labels < 10",
            "mixed_sample_count": len(mixed_ids),
            "mixed_segment_count": int(initial_mask.sum()),
            "optimizer_constructed": False,
            "optimizer_step_executed": False,
            "checkpoint_written": False,
            "in_sample_student_probe_forbidden": True,
        },
        "sources": {
            "resolved_config": _source_receipt(config_path),
            "best_checkpoint": checkpoint_receipts.get("best"),
            "last_checkpoint": checkpoint_receipts.get("last"),
            "step400_checkpoint": states["step400"],
            "test_predictions": _source_receipt(test_predictions_path),
            "teacher_cache_lock": _teacher_cache_lock_receipt(teacher_cache_lock_path),
            "train_manifest": _source_receipt(train_manifest),
        },
        "mixed_ids_sha256": hashlib.sha256("\n".join(mixed_ids).encode("utf-8")).hexdigest(),
        "states": states,
        "linear_probes": linear_probes,
        "state_hash_receipt": {
            "initial_student_sha256": initial_student_hash,
            "initial_loss_sha256": initial_loss_hash,
            "initial_after_geometry_student_sha256": initial_state_after_hash,
            "initial_after_geometry_loss_sha256": initial_loss_hash,
            "final_student_sha256": _state_dict_sha256(student),
            "final_loss_sha256": _state_dict_sha256(loss_module),
            "intentional_checkpoint_loads": intentional_state_loads,
            "source_mutation_detected": source_mutation_detected,
            "final_hash_comparison": "final state reflects the last intentional checkpoint load, when available; it is not expected to equal initialization",
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(output_path)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only raw teacher geometry audit")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--best-checkpoint", type=Path, required=True)
    parser.add_argument("--last-checkpoint", type=Path, required=True)
    parser.add_argument("--step400-checkpoint", type=Path, default=None)
    parser.add_argument("--test-predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--teacher-cache-lock", type=Path, default=None)
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--probe-seed", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")
    os.chdir(PROJECT_ROOT)
    build_raw_teacher_report(
        config_path=args.config,
        best_checkpoint_path=args.best_checkpoint,
        last_checkpoint_path=args.last_checkpoint,
        step400_checkpoint_path=args.step400_checkpoint,
        test_predictions_path=args.test_predictions,
        output_path=args.output,
        device=torch.device(args.device),
        workers=args.workers,
        probe_seed=args.probe_seed,
        teacher_cache_lock_path=args.teacher_cache_lock,
    )


if __name__ == "__main__":
    main()
