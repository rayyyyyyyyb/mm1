#!/usr/bin/env python3

"""Read-only attribution diagnostics for the completed Visual-only sum run.

This runner deliberately does not construct an optimizer, step a gradient, or
write a checkpoint.  It evaluates the saved best model on the official T=10
test samples whose labels contain both positive and negative segments, because
those samples identify whether visual content changes the ranking decision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import torch
import yaml
from torch.utils.data import DataLoader

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.diagnose_checkpoint_modalities import (  # noqa: E402
    REQUIRED_PATHS,
    _ScaleAccumulator,
    apply_content_ablation,
)
from scripts.diagnose_formal_predictions import (  # noqa: E402
    audit_prediction_payload,
    best_binary_f1_threshold,
    load_prediction_npz,
)
from src.data.ov_avel_dataset import ov_avel_collate_fn  # noqa: E402
from src.utils.temporal_protocol import (  # noqa: E402
    task_segments_from_config,
    validate_temporal_alignment,
)
from src.utils.training_diagnostics import summarize_tensor_geometry  # noqa: E402
from src.utils.zero_training_diagnostics import (  # noqa: E402
    _mixed_shuffle_summary,
    mixed_pairwise_concordance,
    temporally_shuffle_audio,
    validate_t10_predictions,
)


TASK_SEGMENTS = 10
INTERVENTION_MODES = (
    "original",
    "visual_zero",
    "audio_zero",
    "both_zero",
    "audio_temporal_shuffle",
)
CONTENT_MODES = {"original", "visual_zero", "audio_zero", "both_zero"}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_receipt(path: str | Path) -> dict[str, Any]:
    source = Path(path).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    return {"path": str(source), "bytes": source.stat().st_size, "sha256": sha256_file(source)}


def canonical_mapping_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def apply_posthoc_mode(
    batch: Mapping[str, Any], mode: str, *, seed: int, sample_offset: int
) -> dict[str, Any]:
    """Apply one intervention while preserving the official ten-segment axes."""

    if mode in CONTENT_MODES:
        return apply_content_ablation(batch, mode)
    if mode == "audio_temporal_shuffle":
        return temporally_shuffle_audio(
            batch, seed=int(seed), sample_offset=int(sample_offset)
        )
    raise ValueError(f"Unsupported post-hoc mode: {mode}")


def select_mixed_sample_indices(
    predictions: Mapping[str, np.ndarray], *, expected_segments: int = TASK_SEGMENTS
) -> list[int]:
    """Return archive sample positions with at least one positive and one negative label."""

    if int(expected_segments) != TASK_SEGMENTS:
        raise ValueError("This attribution diagnostic is locked to official T=10")
    slices = validate_t10_predictions(predictions)
    labels = np.asarray(predictions["labels"], dtype=np.int64).reshape(-1)
    selected: list[int] = []
    for index, sample in enumerate(slices):
        positive_count = int(labels[sample].sum())
        if 0 < positive_count < TASK_SEGMENTS:
            selected.append(index)
    if not selected:
        raise ValueError("The prediction archive contains no mixed-label samples")
    return selected


def summarize_projector_drift(
    initial: Mapping[str, torch.Tensor], current: Mapping[str, torch.Tensor]
) -> dict[str, float | None]:
    """Compute parameter drift with strict key/shape checks and no mutation."""

    if set(initial) != set(current):
        raise ValueError("Projector state keys differ")
    absolute_squared = 0.0
    initial_squared = 0.0
    for name in sorted(initial):
        before = initial[name]
        after = current[name]
        if not isinstance(before, torch.Tensor) or not isinstance(after, torch.Tensor):
            raise TypeError(f"Projector state {name} is not a tensor")
        if tuple(before.shape) != tuple(after.shape):
            raise ValueError(f"Projector state shape changed for {name}")
        before_fp64 = before.detach().to(device="cpu", dtype=torch.float64)
        after_fp64 = after.detach().to(device="cpu", dtype=torch.float64)
        absolute_squared += float((after_fp64 - before_fp64).square().sum())
        initial_squared += float(before_fp64.square().sum())
    absolute = float(np.sqrt(absolute_squared))
    baseline = float(np.sqrt(initial_squared))
    return {
        "absolute_l2": absolute,
        "relative_l2": (absolute / baseline) if baseline > 0.0 else None,
    }


def summarize_intervention_metrics(
    predictions: Mapping[str, Mapping[str, np.ndarray]],
    *,
    threshold: float,
    shuffle_repeats: int = 100,
    seed: int = 42,
) -> dict[str, Any]:
    """Summarize full split groups and mixed-label causal ranking effects."""

    if tuple(predictions) != tuple(mode for mode in INTERVENTION_MODES if mode in predictions):
        # Preserve a deterministic order while allowing the compact unit-test fixture.
        predictions = {name: predictions[name] for name in predictions}
    if not predictions:
        raise ValueError("At least one intervention prediction mode is required")
    reference_name = next(iter(predictions))
    reference = predictions[reference_name]
    validate_t10_predictions(reference)
    summaries: dict[str, Any] = {}
    concordance: dict[str, Any] = {}
    mixed_shuffle: dict[str, Any] = {}
    for mode, payload in predictions.items():
        validate_t10_predictions(payload)
        for field in (
            "ids",
            "queries",
            "split_types",
            "sample_offsets",
            "segment_indices",
            "labels",
        ):
            if not np.array_equal(reference[field], payload[field]):
                raise ValueError(f"Intervention mode {mode} changed aligned field {field}")
        audit = audit_prediction_payload(
            payload, threshold=float(threshold), expected_segments=TASK_SEGMENTS
        )
        summaries[mode] = audit
        concordance[mode] = mixed_pairwise_concordance(
            np.asarray(payload["labels"], dtype=np.int64),
            np.asarray(payload["probabilities"], dtype=np.float64),
            np.asarray(payload["sample_offsets"], dtype=np.int64),
        )
        mixed_shuffle[mode] = _mixed_shuffle_summary(
            np.asarray(payload["labels"], dtype=np.int64),
            np.asarray(payload["probabilities"], dtype=np.float64),
            np.asarray(payload["sample_offsets"], dtype=np.int64),
            repeats=int(shuffle_repeats),
            seed=int(seed),
        )

    baseline = summaries[reference_name]["groups"]["total"]
    deltas: dict[str, Any] = {}
    for mode, report in summaries.items():
        current = report["groups"]["total"]
        deltas[mode] = {
            "relative_to": reference_name,
            "ap_delta": float(current["global_segment_micro_ap"] - baseline["global_segment_micro_ap"]),
            "auroc_delta": float(current["global_segment_micro_auroc"] - baseline["global_segment_micro_auroc"]),
            "segment_f1_delta": float(
                current["ovavel_segment_f1_at_threshold"]
                - baseline["ovavel_segment_f1_at_threshold"]
            ),
            "event_f1_delta": float(
                current["ovavel_event_f1_at_threshold"]
                - baseline["ovavel_event_f1_at_threshold"]
            ),
        }
    return {
        "threshold": float(threshold),
        "modes": summaries,
        "deltas_from_original": deltas,
        "mixed_pairwise_concordance": concordance,
        "mixed_only_shuffle": mixed_shuffle,
    }


def _state_dict_sha256(module: torch.nn.Module) -> str:
    digest = hashlib.sha256()
    for name, tensor in sorted(module.state_dict().items()):
        value = tensor.detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(value.dtype).encode("ascii"))
        digest.update(json.dumps(list(value.shape)).encode("ascii"))
        digest.update(value.numpy().tobytes(order="C"))
    return digest.hexdigest()


def _strict_load(
    *,
    student: torch.nn.Module,
    loss_module: torch.nn.Module,
    path: Path,
    config: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(checkpoint, dict):
        raise ValueError(f"Checkpoint is not a mapping: {path}")
    embedded = checkpoint.get("config")
    if not isinstance(embedded, dict):
        raise ValueError(f"Checkpoint is missing embedded config: {path}")
    config_sha = canonical_mapping_sha256(config)
    if canonical_mapping_sha256(embedded) != config_sha:
        raise ValueError(f"Checkpoint config does not match resolved config: {path}")
    student_state = checkpoint.get("student_state_dict")
    loss_state = checkpoint.get("loss_state_dict")
    if not isinstance(student_state, dict) or not isinstance(loss_state, dict):
        raise ValueError(f"Checkpoint is missing student/loss state: {path}")
    student_result = student.load_state_dict(student_state, strict=True)
    loss_result = loss_module.load_state_dict(loss_state, strict=True)
    if student_result.missing_keys or student_result.unexpected_keys:
        raise RuntimeError(f"Strict student state load failed: {path}")
    if loss_result.missing_keys or loss_result.unexpected_keys:
        raise RuntimeError(f"Strict loss state load failed: {path}")
    return checkpoint, {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "global_step": int(checkpoint.get("global_step", -1)),
        "student_state_sha256": _state_dict_sha256(student),
        "loss_state_sha256": _state_dict_sha256(loss_module),
        "strict_student": True,
        "strict_loss": True,
    }


def _mode_metadata(batch: Mapping[str, Any], labels: torch.Tensor, mask: torch.Tensor) -> tuple[list[str], list[str], list[str]]:
    batch_size = int(labels.shape[0])
    ids = [str(value) for value in batch.get("id", [])]
    queries = [str(value) for value in batch.get("query", [])]
    split_types = [str(value).strip().lower() for value in batch.get("split_type", [])]
    if len(ids) != batch_size or len(queries) != batch_size or len(split_types) != batch_size:
        raise ValueError("Batch metadata must contain one id/query/split_type per sample")
    if labels.ndim != 2 or mask.shape != labels.shape or labels.shape[1] != TASK_SEGMENTS:
        raise ValueError("Post-hoc intervention requires [B,10] labels and mask")
    if not bool(mask.all()):
        raise ValueError("Mixed-label post-hoc loader must contain unpadded T=10 samples")
    return ids, queries, [value if value in {"seen", "unseen"} else "unknown" for value in split_types]


@torch.no_grad()
def collect_intervention_predictions(
    student: torch.nn.Module,
    loader: DataLoader,
    device: torch.device,
    *,
    seed: int,
    expected_ids: Sequence[str],
) -> tuple[dict[str, dict[str, np.ndarray]], dict[str, Any]]:
    student.eval()
    ids: list[str] = []
    queries: list[str] = []
    split_types: list[str] = []
    labels_flat: list[float] = []
    segment_indices: list[int] = []
    offsets = [0]
    logits_by_mode: dict[str, list[float]] = {mode: [] for mode in INTERVENTION_MODES}
    accumulators = {name: _ScaleAccumulator() for name in REQUIRED_PATHS}
    sample_offset = 0

    for batch in loader:
        labels = batch["segment_label"].detach().cpu()
        mask = batch["sequence_mask"].detach().cpu().bool()
        batch_ids, batch_queries, batch_split_types = _mode_metadata(batch, labels, mask)
        ids.extend(batch_ids)
        queries.extend(batch_queries)
        split_types.extend(batch_split_types)
        for sample_index in range(labels.shape[0]):
            indices = list(range(TASK_SEGMENTS))
            segment_indices.extend(indices)
            labels_flat.extend(float(value) for value in labels[sample_index].tolist())
            offsets.append(offsets[-1] + TASK_SEGMENTS)

        for mode in INTERVENTION_MODES:
            selected = apply_posthoc_mode(
                batch, mode, seed=int(seed), sample_offset=int(sample_offset)
            )
            outputs = student(
                frame=selected["frame"].to(device),
                spectrogram=selected["spectrogram"].to(device),
                text_embedding=selected["text_embedding"].to(device),
                sequence_mask=selected["sequence_mask"].to(device),
                frame_valid=selected["frame_valid"].to(device),
                audio_valid=selected["audio_valid"].to(device),
            )
            batch_logits = outputs.get("segment_logits")
            if not isinstance(batch_logits, torch.Tensor):
                raise RuntimeError(f"Mode {mode} did not return segment_logits")
            batch_labels = batch["segment_label"].to(device)
            batch_mask = batch["sequence_mask"].to(device).bool()
            validate_temporal_alignment(
                student_logits=batch_logits,
                labels=batch_labels,
                sequence_mask=batch_mask,
                task_segments=TASK_SEGMENTS,
            )
            if not bool(torch.isfinite(batch_logits).all()):
                raise ValueError(f"Mode {mode} produced non-finite logits")
            logits_by_mode[mode].extend(
                float(value) for value in batch_logits.detach().cpu().reshape(-1).tolist()
            )
            if mode == "original":
                for name in REQUIRED_PATHS:
                    tensor = outputs.get(name)
                    if not isinstance(tensor, torch.Tensor):
                        raise RuntimeError(f"Original output is missing path {name}")
                    accumulators[name].update(tensor, batch_mask)
        sample_offset += len(batch_ids)

    if ids != [str(value) for value in expected_ids]:
        raise RuntimeError("Intervention loader order does not match mixed archive IDs")
    common = {
        "ids": np.asarray(ids, dtype=str),
        "queries": np.asarray(queries, dtype=str),
        "split_types": np.asarray(split_types, dtype=str),
        "sample_offsets": np.asarray(offsets, dtype=np.int64),
        "segment_indices": np.asarray(segment_indices, dtype=np.int64),
        "labels": np.asarray(labels_flat, dtype=np.float64),
    }
    predictions: dict[str, dict[str, np.ndarray]] = {}
    for mode in INTERVENTION_MODES:
        logits = np.asarray(logits_by_mode[mode], dtype=np.float64)
        payload = {**common, "logits": logits, "probabilities": 1.0 / (1.0 + np.exp(-logits))}
        validate_t10_predictions(payload)
        predictions[mode] = payload
    path_summary = {
        name: accumulator.finalize() for name, accumulator in accumulators.items()
    }
    return predictions, path_summary


@torch.no_grad()
def summarize_checkpoint_geometry(
    student: torch.nn.Module,
    loss_module: torch.nn.Module,
    loader: DataLoader,
    device: torch.device,
) -> dict[str, Any]:
    """Summarize a fixed first mixed-label test batch for checkpoint comparison."""

    batch = next(iter(loader))
    outputs = student(
        frame=batch["frame"].to(device),
        spectrogram=batch["spectrogram"].to(device),
        text_embedding=batch["text_embedding"].to(device),
        sequence_mask=batch["sequence_mask"].to(device),
        frame_valid=batch["frame_valid"].to(device),
        audio_valid=batch["audio_valid"].to(device),
    )
    decision = outputs.get("decision_features")
    projector = getattr(loss_module, "strong_teacher_proj", None)
    if not isinstance(decision, torch.Tensor) or not isinstance(projector, torch.nn.Module):
        raise RuntimeError("Geometry probe requires decision features and strong projector")
    target = projector(batch["strong_teacher_features"].to(device).detach())
    mask = batch["sequence_mask"].to(device).bool()
    target_mask = mask & batch["strong_teacher_feature_mask"].to(device).bool()
    return {
        "scope": "first_mixed_label_test_batch",
        "batch_size": int(mask.shape[0]),
        "task_segments": TASK_SEGMENTS,
        "student_decision": summarize_tensor_geometry(decision, mask),
        "projected_visual_target": summarize_tensor_geometry(target, target_mask),
    }


def parse_training_diagnostic_trajectory(path: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("Training diagnostic rows must be JSON objects")
            records.append(value)
    if not records:
        raise ValueError(f"Training diagnostics are empty: {path}")
    unique: dict[int, dict[str, Any]] = {}
    duplicate_steps: list[int] = []
    for record in records:
        step = int(record.get("global_step_before_update", -1))
        if step < 0:
            raise ValueError("Training diagnostic row lacks global_step_before_update")
        if step in unique:
            duplicate_steps.append(step)
            continue
        decision = record.get("student_geometry", {}).get("decision", {})
        target = record.get("teacher_target_geometry", {}).get("strong", {})
        drift = record.get("parameter_drift_from_initial", {}).get(
            "loss_strong_teacher_proj", {}
        )
        unique[step] = {
            "epoch": int(record.get("epoch", -1)),
            "global_step_before_update": step,
            "student_decision_variance": decision.get("per_dimension_variance_mean"),
            "projected_visual_target_variance": target.get("per_dimension_variance_mean"),
            "target_projector_drift": drift,
            "source": "training_diagnostics_first_batch",
        }
    return {
        "unique_rows": [unique[step] for step in sorted(unique)],
        "duplicate_global_steps_ignored": sorted(set(duplicate_steps)),
        "raw_record_count": len(records),
    }


def _make_mixed_loader(base_loader: DataLoader, dataset_indices: Sequence[int]) -> DataLoader:
    return DataLoader(
        base_loader.dataset,
        batch_size=base_loader.batch_size,
        sampler=[int(value) for value in dataset_indices],
        num_workers=int(base_loader.num_workers),
        pin_memory=bool(base_loader.pin_memory),
        persistent_workers=bool(base_loader.persistent_workers and base_loader.num_workers > 0),
        collate_fn=ov_avel_collate_fn,
    )


def build_posthoc_report(
    *,
    config_path: Path,
    best_checkpoint_path: Path,
    last_checkpoint_path: Path,
    test_predictions_path: Path,
    validation_predictions_path: Path | None,
    training_diagnostics_path: Path,
    output_path: Path,
    device: torch.device,
    shuffle_seed: int,
    shuffle_repeats: int,
) -> dict[str, Any]:
    if output_path.exists() or output_path.with_name(output_path.name + ".tmp").exists():
        raise FileExistsError(f"Refusing to overwrite post-hoc output: {output_path}")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Resolved config must be a mapping")
    if task_segments_from_config(config) != TASK_SEGMENTS:
        raise ValueError("Post-hoc diagnostic requires official T=10 config")
    if shuffle_repeats < 1:
        raise ValueError("shuffle_repeats must be positive")

    from scripts.train_ov_orthkd import build_model_and_loss, set_seed
    from src.data import create_ov_avel_data_loaders

    set_seed(
        int(config.get("seed", 42)),
        deterministic=bool(config.get("training", {}).get("deterministic", True)),
    )
    student, loss_module = build_model_and_loss(config, device)
    initial_strong_projector = {
        name: value.detach().cpu().clone()
        for name, value in loss_module.strong_teacher_proj.state_dict().items()
    }
    train_loader, _validation_loader, test_loader = create_ov_avel_data_loaders(config)
    del train_loader, _validation_loader
    if not isinstance(test_loader, DataLoader):
        raise RuntimeError("Post-hoc diagnostic requires a test DataLoader")

    saved_test = load_prediction_npz(test_predictions_path)
    validate_t10_predictions(saved_test)
    mixed_archive_indices = select_mixed_sample_indices(saved_test)
    archive_ids = [str(value) for value in np.asarray(saved_test["ids"]).tolist()]
    dataset_records = getattr(test_loader.dataset, "records", None)
    if not isinstance(dataset_records, list) or len(dataset_records) != len(archive_ids):
        raise ValueError("Test dataset records do not match saved prediction sample count")
    dataset_ids = [str(record.get("id", index)) for index, record in enumerate(dataset_records)]
    if len(set(dataset_ids)) != len(dataset_ids) or set(dataset_ids) != set(archive_ids):
        raise ValueError("Saved prediction IDs and dataset record IDs differ")
    dataset_index_by_id = {value: index for index, value in enumerate(dataset_ids)}
    mixed_ids = [archive_ids[index] for index in mixed_archive_indices]
    mixed_dataset_indices = [dataset_index_by_id[value] for value in mixed_ids]
    mixed_loader = _make_mixed_loader(test_loader, mixed_dataset_indices)

    best_checkpoint, best_receipt = _strict_load(
        student=student,
        loss_module=loss_module,
        path=best_checkpoint_path,
        config=config,
    )
    best_state_before = _state_dict_sha256(student)
    best_geometry = summarize_checkpoint_geometry(student, loss_module, mixed_loader, device)
    best_projector_drift = summarize_projector_drift(
        initial_strong_projector,
        {name: value.detach().cpu() for name, value in loss_module.strong_teacher_proj.state_dict().items()},
    )

    last_checkpoint, last_receipt = _strict_load(
        student=student,
        loss_module=loss_module,
        path=last_checkpoint_path,
        config=config,
    )
    last_geometry = summarize_checkpoint_geometry(student, loss_module, mixed_loader, device)
    last_projector_drift = summarize_projector_drift(
        initial_strong_projector,
        {name: value.detach().cpu() for name, value in loss_module.strong_teacher_proj.state_dict().items()},
    )

    # Reload the best checkpoint before all intervention inference.
    _, _ = _strict_load(
        student=student,
        loss_module=loss_module,
        path=best_checkpoint_path,
        config=config,
    )
    intervention_predictions, path_scales = collect_intervention_predictions(
        student,
        mixed_loader,
        device,
        seed=int(shuffle_seed),
        expected_ids=mixed_ids,
    )
    best_state_after = _state_dict_sha256(student)
    if best_state_before != best_receipt["student_state_sha256"]:
        raise RuntimeError("Best state hash changed during geometry probing")
    if best_state_after != best_receipt["student_state_sha256"]:
        raise RuntimeError("Best state hash changed during intervention inference")

    # The saved original archive is the full test result; compare its mixed rows
    # with a fresh best-checkpoint forward to bind the intervention to that archive.
    saved_by_id = {
        str(value): index for index, value in enumerate(np.asarray(saved_test["ids"]).tolist())
    }
    fresh = intervention_predictions["original"]
    archive_logits: list[float] = []
    for sample_id in mixed_ids:
        source_index = saved_by_id[sample_id]
        start = int(saved_test["sample_offsets"][source_index])
        end = int(saved_test["sample_offsets"][source_index + 1])
        archive_logits.extend(float(value) for value in saved_test["logits"][start:end])
    fresh_logits = np.asarray(fresh["logits"], dtype=np.float64)
    archive_logits_array = np.asarray(archive_logits, dtype=np.float64)
    if fresh_logits.shape != archive_logits_array.shape:
        raise RuntimeError("Fresh mixed original logits have an unexpected shape")
    max_abs_diff = float(np.max(np.abs(fresh_logits - archive_logits_array)))
    if not np.allclose(fresh_logits, archive_logits_array, rtol=1e-5, atol=1e-5):
        raise RuntimeError(f"Fresh best-checkpoint logits disagree with saved archive: {max_abs_diff}")

    threshold = 0.5
    validation_receipt = None
    if validation_predictions_path is not None and validation_predictions_path.is_file():
        validation = load_prediction_npz(validation_predictions_path)
        validate_t10_predictions(validation)
        threshold = best_binary_f1_threshold(
            np.asarray(validation["labels"]), np.asarray(validation["probabilities"])
        )
        validation_receipt = source_receipt(validation_predictions_path)
    full_original = audit_prediction_payload(
        saved_test, threshold=float(threshold), expected_segments=TASK_SEGMENTS
    )
    intervention_metrics = summarize_intervention_metrics(
        intervention_predictions,
        threshold=float(threshold),
        shuffle_repeats=int(shuffle_repeats),
        seed=int(shuffle_seed),
    )
    trajectory = parse_training_diagnostic_trajectory(training_diagnostics_path)
    report = {
        "schema_version": 1,
        "status": "PASS",
        "claim_level": "noncanonical_visual_sum_posthoc_attribution",
        "scientific_success_claimed": False,
        "authorization": {
            "formal_full_training_authorized": False,
            "next_experiment_authorized": False,
            "decision": "posthoc_required_before_any_bounded_full",
        },
        "protocol": {
            "task_segments": TASK_SEGMENTS,
            "temporal_conversion": "forbidden",
            "intervention_modes": list(INTERVENTION_MODES),
            "intervention_subset": "test samples with 0 < positive labels < 10",
            "test_views": 1,
            "threshold": float(threshold),
            "shuffle_seed": int(shuffle_seed),
            "shuffle_repeats": int(shuffle_repeats),
            "optimizer_constructed": False,
            "optimizer_step_executed": False,
            "checkpoint_written": False,
        },
        "sources": {
            "resolved_config": source_receipt(config_path),
            "best_checkpoint": best_receipt,
            "last_checkpoint": last_receipt,
            "test_predictions": source_receipt(test_predictions_path),
            "validation_predictions": validation_receipt,
            "training_diagnostics": source_receipt(training_diagnostics_path),
        },
        "state_loading": {
            "best_checkpoint_global_step": int(best_checkpoint.get("global_step", -1)),
            "last_checkpoint_global_step": int(last_checkpoint.get("global_step", -1)),
            "best_checkpoint_strict": True,
            "last_checkpoint_strict": True,
            "best_state_unchanged_after_probe": best_state_after == best_receipt["student_state_sha256"],
        },
        "full_test_original_archive": full_original,
        "mixed_subset": {
            "sample_count": len(mixed_ids),
            "segment_count": len(mixed_ids) * TASK_SEGMENTS,
            "ids_sha256": hashlib.sha256("\n".join(mixed_ids).encode("utf-8")).hexdigest(),
            "archive_logits_max_abs_diff": max_abs_diff,
            "intervention_metrics": intervention_metrics,
            "original_path_scales": path_scales,
        },
        "checkpoint_geometry": {
            "training_diagnostics": trajectory,
            "best_checkpoint": {
                **best_geometry,
                "global_step": int(best_checkpoint.get("global_step", -1)),
                "strong_teacher_projector_drift": best_projector_drift,
            },
            "last_checkpoint": {
                **last_geometry,
                "global_step": int(last_checkpoint.get("global_step", -1)),
                "strong_teacher_projector_drift": last_projector_drift,
            },
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(output_path)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only Visual-only sum checkpoint attribution audit")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--best-checkpoint", type=Path, required=True)
    parser.add_argument("--last-checkpoint", type=Path, required=True)
    parser.add_argument("--test-predictions", type=Path, required=True)
    parser.add_argument("--validation-predictions", type=Path, default=None)
    parser.add_argument("--training-diagnostics", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--shuffle-seed", type=int, default=42)
    parser.add_argument("--shuffle-repeats", type=int, default=100)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")
    os.chdir(PROJECT_ROOT)
    report = build_posthoc_report(
        config_path=args.config,
        best_checkpoint_path=args.best_checkpoint,
        last_checkpoint_path=args.last_checkpoint,
        test_predictions_path=args.test_predictions,
        validation_predictions_path=args.validation_predictions,
        training_diagnostics_path=args.training_diagnostics,
        output_path=args.output,
        device=torch.device(args.device),
        shuffle_seed=args.shuffle_seed,
        shuffle_repeats=args.shuffle_repeats,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
