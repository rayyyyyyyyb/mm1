"""Contracts and metrics for the preregistered D2A paired control."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import torch
import yaml
from sklearn.metrics import average_precision_score, roc_auc_score


D2A_NAME = "D2A_PAIRED_PRETRAINED_EARLY_DYNAMICS_400"
D2A_CHECKPOINTS = (0, 25, 50, 100, 200, 400)
D2A_INPUT_HASH_STEPS = (1, 10, 50, 100, 200, 400)
D2A_MODES = ("original", "visual_zero", "audio_zero")


def json_safe(value: Any) -> Any:
    """Represent non-finite diagnostic values without emitting invalid JSON."""

    if isinstance(value, float) and not np.isfinite(value):
        if np.isnan(value):
            return "NaN"
        return "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def summarize_receipt_range(
    rows: Sequence[Mapping[str, Any]], start: int, end: int
) -> dict[str, Any]:
    selected = [row for row in rows if start < int(row["attempted_step"]) <= end]
    if end > 0 and not selected:
        raise RuntimeError("missing optimizer receipts for checkpoint interval")
    result: dict[str, Any] = {
        "attempted_start_exclusive": start,
        "attempted_end": end,
    }
    for name in (
        "visual_encoder_grad_norm",
        "audio_encoder_grad_norm",
        "clip_coefficient",
    ):
        values = [float(row[name]) for row in selected]
        finite = [value for value in values if np.isfinite(value)]
        result[name] = {
            "count": len(values),
            "finite_count": len(finite),
            "nonfinite_count": len(values) - len(finite),
            "finite_mean": float(np.mean(finite)) if finite else None,
            "last": json_safe(values[-1]) if values else None,
        }
    result["applied_count"] = sum(bool(row["applied"]) for row in selected)
    result["overflow_count"] = sum(bool(row["overflow"]) for row in selected)
    return result


def build_fixed_batch_plan(
    dataset_size: int, batch_size: int, seed: int
) -> list[list[int]]:
    """Build the deterministic 400-batch index plan without touching model RNG."""

    if dataset_size < batch_size * 400:
        raise ValueError(
            f"D2A needs at least {batch_size * 400} training samples, got {dataset_size}"
        )
    generator = torch.Generator().manual_seed(int(seed))
    order = torch.randperm(dataset_size, generator=generator).tolist()
    return [
        [int(value) for value in order[start : start + batch_size]]
        for start in range(0, batch_size * 400, batch_size)
    ]


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _require_exact(mapping: Mapping[str, Any], key: str, expected: Any) -> None:
    if mapping.get(key) != expected:
        raise ValueError(f"{key} must equal {expected!r}, got {mapping.get(key)!r}")


def validate_d2a_wrapper(wrapper: Mapping[str, Any]) -> None:
    """Fail closed unless every preregistered D2A boundary is unchanged."""

    _require_exact(wrapper, "schema_version", 1)
    _require_exact(
        wrapper,
        "base_config",
        "configs/diagnostics/recovery/ov_orthkd_visual_only_sum_feature_seed42_no_workers.yaml",
    )
    control = wrapper.get("control")
    arms = wrapper.get("arms")
    asset = wrapper.get("pretrained_asset")
    overrides = wrapper.get("common_overrides")
    gate = wrapper.get("gate")
    on_pass = wrapper.get("on_pass")
    if not all(
        isinstance(value, Mapping)
        for value in (control, arms, asset, overrides, gate, on_pass)
    ):
        raise ValueError("D2A wrapper sections must be mappings")

    expected_control = {
        "name": D2A_NAME,
        "claim": "exact_visual_pretraining_initialization_effect_on_early_training_dynamics",
        "attempted_batches": 400,
        "checkpoints": list(D2A_CHECKPOINTS),
        "input_hash_steps": list(D2A_INPUT_HASH_STEPS),
        "evaluation_split": "validation",
        "evaluation_batch_size": 16,
        "temporal_shuffle_repeats": 100,
        "task_segments": 10,
        "test_evaluation": False,
        "second_seed": False,
        "formal_full": False,
        "old_d2_800_step": False,
        "resume_checkpoint": "paired_resume.pt",
        "sole_scientific_difference": "student.visual_pretrained_initialization",
    }
    for key, value in expected_control.items():
        _require_exact(control, key, value)

    _require_exact(
        arms,
        "random",
        {"visual_pretrained": False, "audio_pretrained": False},
    )
    _require_exact(
        arms,
        "pretrained",
        {"visual_pretrained": True, "audio_pretrained": False},
    )
    _require_exact(
        asset,
        "lock",
        "configs/locks/diagnostics/convnextv2_tiny_pretrained_asset.yaml",
    )
    _require_exact(
        asset,
        "load_mode",
        "same_seed_random_model_then_locked_visual_state_replace",
    )
    _require_exact(asset, "network_lookup", False)

    loss = overrides.get("loss") if isinstance(overrides, Mapping) else None
    training = overrides.get("training") if isinstance(overrides, Mapping) else None
    if not isinstance(loss, Mapping) or not isinstance(training, Mapping):
        raise ValueError("D2A common loss/training overrides are required")
    _require_exact(
        loss, "strong_teacher_projector_update_mode", "static_zero_lr_keep_grad"
    )
    _require_exact(loss, "weak_teacher_projector_update_mode", "trainable")
    _require_exact(loss, "text_teacher_projector_update_mode", "trainable")
    _require_exact(
        training,
        "gradient_clipping",
        {"scope": "optimizer_groups_with_positive_lr"},
    )

    expected_gate = {
        "primary_checkpoint": 400,
        "pretrained_minus_random_mixed_concordance_min": 0.020,
        "supporting_required_count": 2,
        "pretrained_decision_temporal_std_min": 0.003,
        "pretrained_temporal_shuffle_ap_or_auroc_drop_min": 0.010,
        "pretrained_visual_zero_mixed_concordance_drop_min": 0.010,
        "pretrained_validation_ap_floor_relative_to_random": -0.020,
        "pretrained_predicted_positive_rate_max_exclusive": 0.98,
    }
    for key, value in expected_gate.items():
        _require_exact(gate, key, value)
    _require_exact(
        on_pass,
        "authorize_only",
        "same_pretrained_arm_extension_to_800_applied_updates",
    )
    _require_exact(on_pass, "automatic_extension", False)
    _require_exact(on_pass, "test_evaluation", False)
    _require_exact(on_pass, "formal_full", False)


def _overlay(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(base))
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = _overlay(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _flatten(
    mapping: Mapping[str, Any], prefix: tuple[str, ...] = ()
) -> dict[tuple[str, ...], Any]:
    values: dict[tuple[str, ...], Any] = {}
    for key, value in mapping.items():
        path = (*prefix, str(key))
        if isinstance(value, Mapping):
            values.update(_flatten(value, path))
        else:
            values[path] = value
    return values


def _scientific_view(config: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(config))
    result.pop("reproduction", None)
    result.pop("logging", None)
    return result


def materialize_d2a_configs(
    wrapper_path: str | Path,
    repo_root: str | Path,
    output_root: str | Path,
    asset_root: str | Path,
) -> dict[str, Any]:
    wrapper_file = Path(wrapper_path).resolve()
    root = Path(repo_root).resolve()
    output = Path(output_root).resolve()
    wrapper = yaml.safe_load(wrapper_file.read_text(encoding="utf-8"))
    if not isinstance(wrapper, Mapping):
        raise ValueError("D2A wrapper must be a mapping")
    validate_d2a_wrapper(wrapper)
    base_path = root / str(wrapper["base_config"])
    base = yaml.safe_load(base_path.read_text(encoding="utf-8"))
    if not isinstance(base, Mapping):
        raise ValueError("D2A base config must be a mapping")
    common = _overlay(base, wrapper["common_overrides"])
    if int(common.get("seed", -1)) != 42:
        raise ValueError("D2A requires seed 42")
    if common.get("loss", {}).get("visual_l2_reduction") != (
        "sum_feature_then_masked_mean_segments"
    ):
        raise ValueError("D2A requires the C2 visual sum loss")
    training = common.get("training", {})
    if (
        int(training.get("max_batches_per_epoch", -1)) != 400
        or training.get("max_optimizer_steps") is not None
        or training.get("scheduler")
        != {"type": "CosineAnnealingLR", "T_max": 30, "interval": "epoch"}
    ):
        raise ValueError("D2A base training budget/scheduler differs from C2")
    data = common.setdefault("data", {})
    data.pop("test_manifest", None)
    if int(data.get("num_segments", -1)) != 10 or int(
        data.get("batch_size", -1)
    ) != 4:
        raise ValueError("D2A requires official T=10 and training batch size 4")
    if data.get("train_augment") is not True or int(data.get("num_workers", -1)) != 0:
        raise ValueError("D2A requires shared train augmentation with num_workers=0")
    common.setdefault("evaluation", {})["run_test"] = False

    resolved: dict[str, dict[str, Any]] = {}
    for role in ("random", "pretrained"):
        config = copy.deepcopy(common)
        student = config.setdefault("student", {})
        student.pop("pretrained", None)
        student.update(copy.deepcopy(dict(wrapper["arms"][role])))
        reproduction = config.setdefault("reproduction", {})
        reproduction.update(
            {
                "variant": f"{D2A_NAME}_{role}",
                "claim_level": "noncanonical_diagnostic",
                "diagnostic_only": True,
                "full_run_blocked": True,
                "d2a": {
                    "paired_role": role,
                    "attempted_batches": 400,
                    "validation_only": True,
                    "test_manifest_removed": True,
                    "pretrained_asset_lock": str(wrapper["pretrained_asset"]["lock"]),
                    "pretrained_asset_root": str(Path(asset_root).resolve()),
                    "locked_asset_applied": role == "pretrained",
                },
            }
        )
        config.setdefault("logging", {})["log_dir"] = str(output / role)
        resolved[role] = config

    left = _flatten(_scientific_view(resolved["random"]))
    right = _flatten(_scientific_view(resolved["pretrained"]))
    changed = sorted(
        path for path in set(left) | set(right) if left.get(path) != right.get(path)
    )
    expected_change = [("student", "visual_pretrained")]
    if changed != expected_change:
        raise ValueError(f"D2A pair differs outside visual initialization: {changed}")

    output.mkdir(parents=True, exist_ok=True)
    config_paths: dict[str, str] = {}
    config_hashes: dict[str, str] = {}
    for role, config in resolved.items():
        path = output / f"resolved_{role}.yaml"
        path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        config_paths[role] = str(path)
        config_hashes[role] = canonical_sha256(config)
    return {
        "wrapper": dict(wrapper),
        "wrapper_path": str(wrapper_file),
        "wrapper_sha256": sha256_file(wrapper_file),
        "base_config_path": str(base_path),
        "base_config_sha256": sha256_file(base_path),
        "configs": resolved,
        "config_paths": config_paths,
        "config_canonical_sha256": config_hashes,
        "scientific_changed_paths": ["student.visual_pretrained"],
    }


def _validate_prediction_payload(predictions: Mapping[str, np.ndarray]) -> None:
    required = {
        "ids",
        "queries",
        "sample_offsets",
        "segment_indices",
        "labels",
        "logits",
        "probabilities",
    }
    if not required <= set(predictions):
        raise ValueError(f"prediction fields missing: {sorted(required - set(predictions))}")
    offsets = np.asarray(predictions["sample_offsets"], dtype=np.int64).reshape(-1)
    labels = np.asarray(predictions["labels"], dtype=np.float64).reshape(-1)
    logits = np.asarray(predictions["logits"], dtype=np.float64).reshape(-1)
    probabilities = np.asarray(
        predictions["probabilities"], dtype=np.float64
    ).reshape(-1)
    if (
        offsets.size < 2
        or offsets[0] != 0
        or offsets[-1] != labels.size
        or np.any(np.diff(offsets) != 10)
        or labels.shape != logits.shape
        or labels.shape != probabilities.shape
    ):
        raise ValueError("D2A prediction payload must preserve aligned T=10 samples")
    if not np.isin(labels, (0.0, 1.0)).all() or not (
        np.isfinite(logits).all() and np.isfinite(probabilities).all()
    ):
        raise ValueError("D2A prediction payload contains invalid values")


def assert_prediction_identity(
    left: Mapping[str, np.ndarray], right: Mapping[str, np.ndarray]
) -> None:
    for name in (
        "ids",
        "queries",
        "split_types",
        "sample_offsets",
        "segment_indices",
        "labels",
    ):
        if not np.array_equal(np.asarray(left[name]), np.asarray(right[name])):
            raise ValueError(f"paired prediction identity differs at {name}")


def mixed_pair_weighted_concordance(
    predictions: Mapping[str, np.ndarray],
) -> tuple[float, int, int]:
    _validate_prediction_payload(predictions)
    offsets = np.asarray(predictions["sample_offsets"], dtype=np.int64)
    labels = np.asarray(predictions["labels"], dtype=np.int64)
    logits = np.asarray(predictions["logits"], dtype=np.float64)
    wins = 0.0
    pairs = 0
    samples = 0
    for start, end in zip(offsets[:-1], offsets[1:]):
        begin, finish = int(start), int(end)
        row_labels = labels[begin:finish]
        if row_labels.sum() <= 0 or row_labels.sum() >= row_labels.size:
            continue
        positive = logits[begin:finish][row_labels == 1]
        negative = logits[begin:finish][row_labels == 0]
        comparisons = positive[:, None] - negative[None, :]
        wins += float((comparisons > 0).sum()) + 0.5 * float(
            (comparisons == 0).sum()
        )
        pairs += int(comparisons.size)
        samples += 1
    if pairs == 0:
        raise ValueError("D2A validation contains no mixed-label comparison pairs")
    return wins / pairs, samples, pairs


def _metric_distribution(values: Sequence[float]) -> dict[str, float | int]:
    array = np.asarray(values, dtype=np.float64)
    return {
        "count": int(array.size),
        "mean": float(array.mean()),
        "std": float(array.std()),
        "minimum": float(array.min()),
        "maximum": float(array.max()),
    }


def mixed_temporal_shuffle_metrics(
    predictions: Mapping[str, np.ndarray], *, repeats: int, seed: int
) -> dict[str, Any]:
    _validate_prediction_payload(predictions)
    if int(repeats) <= 0:
        raise ValueError("shuffle repeats must be positive")
    offsets = np.asarray(predictions["sample_offsets"], dtype=np.int64)
    labels = np.asarray(predictions["labels"], dtype=np.int64)
    logits = np.asarray(predictions["logits"], dtype=np.float64)
    mixed_slices: list[tuple[int, int]] = []
    for start, end in zip(offsets[:-1], offsets[1:]):
        begin, finish = int(start), int(end)
        count = int(labels[begin:finish].sum())
        if 0 < count < finish - begin:
            mixed_slices.append((begin, finish))
    if not mixed_slices:
        raise ValueError("D2A validation contains no mixed-label samples")
    mixed_labels = np.concatenate([labels[start:end] for start, end in mixed_slices])
    original_logits = np.concatenate([logits[start:end] for start, end in mixed_slices])
    original_ap = float(average_precision_score(mixed_labels, original_logits))
    original_auroc = float(roc_auc_score(mixed_labels, original_logits))
    rng = np.random.default_rng(int(seed))
    shuffled_ap: list[float] = []
    shuffled_auroc: list[float] = []
    for _ in range(int(repeats)):
        shuffled = np.concatenate(
            [logits[start:end][rng.permutation(end - start)] for start, end in mixed_slices]
        )
        shuffled_ap.append(float(average_precision_score(mixed_labels, shuffled)))
        shuffled_auroc.append(float(roc_auc_score(mixed_labels, shuffled)))
    ap_distribution = _metric_distribution(shuffled_ap)
    auroc_distribution = _metric_distribution(shuffled_auroc)
    return {
        "semantics": "mixed_samples_labels_fixed_logits_permuted_within_each_video",
        "mixed_sample_count": len(mixed_slices),
        "repeats": int(repeats),
        "seed": int(seed),
        "original_ap": original_ap,
        "original_auroc": original_auroc,
        "shuffled_ap": ap_distribution,
        "shuffled_auroc": auroc_distribution,
        "ap_drop": original_ap - float(ap_distribution["mean"]),
        "auroc_drop": original_auroc - float(auroc_distribution["mean"]),
    }


def _mode_metrics(predictions: Mapping[str, np.ndarray]) -> dict[str, Any]:
    _validate_prediction_payload(predictions)
    labels = np.asarray(predictions["labels"], dtype=np.int64)
    logits = np.asarray(predictions["logits"], dtype=np.float64)
    probabilities = np.asarray(predictions["probabilities"], dtype=np.float64)
    concordance, mixed_samples, mixed_pairs = mixed_pair_weighted_concordance(
        predictions
    )
    return {
        "sample_count": int(np.asarray(predictions["ids"]).size),
        "segment_count": int(labels.size),
        "validation_ap": float(average_precision_score(labels, logits)),
        "validation_auroc": float(roc_auc_score(labels, logits)),
        "predicted_positive_rate": float(np.mean(probabilities >= 0.5)),
        "mixed_pair_weighted_concordance": concordance,
        "mixed_sample_count": mixed_samples,
        "mixed_pair_count": mixed_pairs,
    }


def summarize_d2a_evaluation(
    predictions_by_mode: Mapping[str, Mapping[str, np.ndarray]],
    path_scales: Mapping[str, Any],
    *,
    shuffle_repeats: int,
    shuffle_seed: int,
) -> dict[str, Any]:
    if set(predictions_by_mode) != set(D2A_MODES):
        raise ValueError("D2A evaluation requires original/visual_zero/audio_zero")
    reference = predictions_by_mode["original"]
    for mode in D2A_MODES:
        assert_prediction_identity(reference, predictions_by_mode[mode])
    modes = {
        mode: _mode_metrics(predictions_by_mode[mode]) for mode in D2A_MODES
    }
    shuffle = mixed_temporal_shuffle_metrics(
        reference, repeats=shuffle_repeats, seed=shuffle_seed
    )
    return {
        "protocol": {
            "split": "validation",
            "task_segments": 10,
            "modes": list(D2A_MODES),
            "test_evaluation": False,
        },
        "modes": modes,
        "paths": copy.deepcopy(dict(path_scales)),
        "mixed_temporal_shuffle": shuffle,
        "causal_deltas": {
            "visual_zero_mixed_concordance_drop": (
                modes["original"]["mixed_pair_weighted_concordance"]
                - modes["visual_zero"]["mixed_pair_weighted_concordance"]
            ),
            "audio_zero_mixed_concordance_drop": (
                modes["original"]["mixed_pair_weighted_concordance"]
                - modes["audio_zero"]["mixed_pair_weighted_concordance"]
            ),
        },
    }


def recompute_d2a_gate(
    random_snapshot: Mapping[str, Any],
    pretrained_snapshot: Mapping[str, Any],
    gate: Mapping[str, Any],
) -> dict[str, Any]:
    random_original = random_snapshot["modes"]["original"]
    pretrained_original = pretrained_snapshot["modes"]["original"]
    concordance_delta = float(
        pretrained_original["mixed_pair_weighted_concordance"]
    ) - float(random_original["mixed_pair_weighted_concordance"])
    decision_std = float(
        pretrained_snapshot["paths"]["decision_features"][
            "within_sample_temporal_std_mean"
        ]
    )
    shuffle = pretrained_snapshot["mixed_temporal_shuffle"]
    shuffle_signal = max(float(shuffle["ap_drop"]), float(shuffle["auroc_drop"]))
    visual_zero_drop = float(
        pretrained_snapshot["causal_deltas"][
            "visual_zero_mixed_concordance_drop"
        ]
    )
    validation_ap_delta = float(pretrained_original["validation_ap"]) - float(
        random_original["validation_ap"]
    )
    supporting = {
        "pretrained_decision_temporal_std": decision_std
        >= float(gate["pretrained_decision_temporal_std_min"]),
        "pretrained_mixed_shuffle_ap_or_auroc_drop": shuffle_signal
        >= float(gate["pretrained_temporal_shuffle_ap_or_auroc_drop_min"]),
        "pretrained_visual_zero_mixed_concordance_drop": visual_zero_drop
        >= float(gate["pretrained_visual_zero_mixed_concordance_drop_min"]),
    }
    requirements = {
        "pretrained_minus_random_mixed_concordance": concordance_delta
        >= float(gate["pretrained_minus_random_mixed_concordance_min"]),
        "supporting_criteria_count": sum(supporting.values())
        >= int(gate["supporting_required_count"]),
        "pretrained_validation_ap_floor": validation_ap_delta
        >= float(gate["pretrained_validation_ap_floor_relative_to_random"]),
        "pretrained_predicted_positive_rate": float(
            pretrained_original["predicted_positive_rate"]
        )
        < float(gate["pretrained_predicted_positive_rate_max_exclusive"]),
    }
    passed = all(requirements.values())
    return {
        "primary_checkpoint": 400,
        "observed": {
            "pretrained_minus_random_mixed_concordance": concordance_delta,
            "pretrained_decision_temporal_std": decision_std,
            "pretrained_shuffle_ap_drop": float(shuffle["ap_drop"]),
            "pretrained_shuffle_auroc_drop": float(shuffle["auroc_drop"]),
            "pretrained_visual_zero_mixed_concordance_drop": visual_zero_drop,
            "pretrained_minus_random_validation_ap": validation_ap_delta,
            "pretrained_predicted_positive_rate": float(
                pretrained_original["predicted_positive_rate"]
            ),
        },
        "supporting": supporting,
        "supporting_pass_count": sum(supporting.values()),
        "requirements": requirements,
        "pass": passed,
        "scientific_status": (
            "D2A_PRETRAINED_EARLY_DYNAMICS_PASS"
            if passed
            else "D2A_PRETRAINED_EARLY_DYNAMICS_FAIL"
        ),
        "authorization": {
            "same_pretrained_arm_extension_to_800_applied_updates": passed,
            "automatic_extension": False,
            "old_d2_800_step": False,
            "d3": False,
            "formal_full": False,
            "test_evaluation": False,
            "second_seed": False,
        },
    }


def _tensor_sha256(tensor: torch.Tensor) -> str:
    value = tensor.detach().cpu().contiguous()
    digest = hashlib.sha256()
    digest.update(str(value.dtype).encode("ascii"))
    digest.update(json.dumps(list(value.shape), separators=(",", ":")).encode("ascii"))
    digest.update(value.reshape(-1).view(torch.uint8).numpy().tobytes(order="C"))
    return digest.hexdigest()


def batch_input_receipt(batch: Mapping[str, Any]) -> dict[str, Any]:
    tensor_names = (
        "frame",
        "spectrogram",
        "text_embedding",
        "segment_label",
        "sequence_mask",
        "frame_valid",
        "audio_valid",
    )
    tensor_hashes = {
        name: _tensor_sha256(batch[name])
        for name in tensor_names
        if isinstance(batch.get(name), torch.Tensor)
    }
    metadata = {
        "ids": [str(value) for value in batch.get("id", [])],
        "queries": [str(value) for value in batch.get("query", [])],
        "selected_segment_indices": [
            [int(item) for item in values]
            for values in batch.get("selected_segment_indices", [])
        ],
    }
    return {
        "tensor_sha256": tensor_hashes,
        "metadata": metadata,
        "metadata_sha256": canonical_sha256(metadata),
        "composite_sha256": canonical_sha256(
            {"tensor_sha256": tensor_hashes, "metadata": metadata}
        ),
    }
