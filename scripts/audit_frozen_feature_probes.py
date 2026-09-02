#!/usr/bin/env python3
"""Run the preregistered read-only frozen-feature probe audit.

The script extracts only projected visual/audio/query tokens from immutable
student checkpoints, fits disposable sklearn readouts, and writes resumable
per-checkpoint artifacts.  It never creates a student optimizer, calls
backward, switches the student to training mode, or writes a checkpoint.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import torch
import yaml
from sklearn.metrics import average_precision_score, roc_auc_score

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.frozen_feature_probe import (  # noqa: E402
    ALPHA_GRID,
    PROBE_NAMES,
    build_probe_designs,
    choose_alpha,
    fit_logistic_probe,
    mixed_metrics,
    predict_probe_scores,
    shuffle_metrics,
    summarize_probe_outcome,
)
from src.utils.temporal_protocol import task_segments_from_config  # noqa: E402


TASK_SEGMENTS = 10
FEATURE_BLOCKS = 4
SCHEMA_VERSION = 1


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _state_sha256(module: torch.nn.Module) -> str:
    digest = hashlib.sha256()
    for name, tensor in sorted(module.state_dict().items()):
        value = tensor.detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(value.dtype).encode("ascii"))
        digest.update(json.dumps(list(value.shape)).encode("ascii"))
        digest.update(value.numpy().tobytes(order="C"))
    return digest.hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    if temporary.exists():
        temporary.unlink()
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected mapping YAML: {path}")
    return value


def _validate_protocol(protocol_path: Path, *, shuffle_repeats: int, shuffle_seed: int) -> str:
    protocol = _load_yaml(protocol_path)
    if int(protocol.get("task_segments", -1)) != TASK_SEGMENTS:
        raise ValueError("Frozen probe protocol must lock official task_segments=10")
    if protocol.get("temporal_conversion") != "forbidden":
        raise ValueError("Frozen probe protocol must forbid temporal conversion")
    if int(protocol.get("feature_blocks", -1)) != FEATURE_BLOCKS:
        raise ValueError("Frozen probe protocol must use four equal feature blocks")
    if int(protocol.get("fusion_dim", -1)) != 384:
        raise ValueError("Frozen probe protocol must lock fusion_dim=384")
    if [float(value) for value in protocol.get("alpha_grid", [])] != list(ALPHA_GRID):
        raise ValueError("Frozen probe protocol alpha grid disagrees with implementation")
    shuffle = protocol.get("shuffle", {})
    if int(shuffle.get("repeats", -1)) != int(shuffle_repeats) or int(shuffle.get("seed", -1)) != int(shuffle_seed):
        raise ValueError("CLI shuffle settings must match frozen probe protocol")
    guards = protocol.get("guards", {})
    expected_guards = {
        "train_augmentation": False,
        "loader_shuffle": False,
        "student_mode": "eval_inference_mode",
        "student_optimizer_steps": 0,
        "student_backward_calls": 0,
        "checkpoint_writes": 0,
        "formal_student_training_started": False,
        "formal_full_authorized": False,
    }
    if any(guards.get(key) != expected for key, expected in expected_guards.items()):
        raise ValueError("Frozen probe protocol contains an unsafe guard value")
    gates = protocol.get("outcome_gates", {})
    if float(gates.get("success", {}).get("delta_concordance", -1)) != 0.02:
        raise ValueError("Frozen probe success concordance gate disagrees")
    if float(gates.get("success", {}).get("delta_ap_or_auroc", -1)) != 0.01:
        raise ValueError("Frozen probe success ranking gate disagrees")
    if float(gates.get("fail", {}).get("delta_concordance", -1)) != 0.01:
        raise ValueError("Frozen probe fail concordance gate disagrees")
    if float(gates.get("fail", {}).get("delta_ap_and_auroc", -1)) != 0.005:
        raise ValueError("Frozen probe fail ranking gate disagrees")
    return _sha256_file(protocol_path)


def _build_student(config: Mapping[str, Any], device: torch.device) -> Any:
    from src.models import OVOrthKDStudent

    data_cfg = config["data"]
    student_cfg = config["student"]
    implementation_mode = str(config.get("reproduction", {}).get("implementation_mode", ""))
    expected_path_mode = "explicit_projected" if implementation_mode == "camera_ready_explicit_paths" else "legacy_shared"
    path_mode = str(student_cfg.get("path_mode", expected_path_mode))
    if path_mode != expected_path_mode:
        raise ValueError(f"implementation_mode/path_mode mismatch: {implementation_mode}/{path_mode}")
    model = OVOrthKDStudent(
        visual_backbone=student_cfg["visual_backbone"],
        audio_backbone=student_cfg["audio_backbone"],
        text_dim=int(data_cfg.get("text_dim", 512)),
        fusion_dim=int(student_cfg.get("fusion_dim", 384)),
        projection_dim=int(student_cfg.get("projection_dim", config.get("loss", {}).get("projection_dim", 256))),
        path_mode=path_mode,
        temporal_layers=int(student_cfg.get("temporal_layers", 4)),
        temporal_heads=int(student_cfg.get("temporal_heads", 8)),
        temporal_dropout=float(student_cfg.get("temporal_dropout", 0.1)),
        temporal_path_mode=str(student_cfg.get("temporal_path_mode", "transformer")),
        max_position_segments=int(student_cfg.get("max_position_segments", 16)),
        pretrained=bool(student_cfg.get("pretrained", False)),
        fusion_mode=str(student_cfg.get("fusion_mode", "concat_mlp_query_conditioned")),
        gate_mode=str(student_cfg.get("gate_mode", "learned_softmax")),
        query_anchor_mode=str(config.get("loss", {}).get("query_anchor_mode", "independent_loss_projection")),
    ).to(device)
    return model


def _load_checkpoint(path: Path, config: Mapping[str, Any], device: torch.device) -> tuple[OVOrthKDStudent, dict[str, Any], str]:
    payload = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("student_state_dict"), Mapping):
        raise ValueError(f"Checkpoint has no student_state_dict mapping: {path}")
    embedded = payload.get("config")
    if not isinstance(embedded, Mapping) or _canonical_sha(embedded) != _canonical_sha(config):
        raise ValueError(f"Checkpoint config does not match source config: {path}")
    model = _build_student(config, device)
    incompatible = model.load_state_dict(payload["student_state_dict"], strict=True)
    if incompatible.missing_keys or incompatible.unexpected_keys:
        raise RuntimeError(f"Strict checkpoint load failed: {path}")
    model.eval()
    return model, payload, _sha256_file(path)


def _split_loader(config: Mapping[str, Any], split: str, batch_size: int, num_workers: int):
    from src.data import create_ov_avel_data_loaders

    frozen = copy.deepcopy(dict(config))
    frozen_data = frozen["data"]
    frozen_data["train_augment"] = False
    frozen_data["batch_size"] = int(batch_size)
    frozen_data["num_workers"] = int(num_workers)
    frozen_data["persistent_workers"] = False
    train_loader, val_loader, test_loader = create_ov_avel_data_loaders(frozen)
    loaders = {"train": train_loader, "val": val_loader, "test": test_loader}
    loader = loaders[split]
    if loader is None:
        raise ValueError(f"No loader for split={split}")
    # The factory intentionally shuffles train for optimization.  A frozen
    # audit must use the manifest's deterministic natural order instead.
    if split == "train":
        from torch.utils.data import DataLoader

        loader = DataLoader(
            loader.dataset,
            batch_size=int(batch_size),
            shuffle=False,
            num_workers=int(num_workers),
            pin_memory=bool(frozen_data.get("pin_memory", True)),
            persistent_workers=False,
            collate_fn=loader.collate_fn,
        )
    return loader


def _extract_base_features(
    model: OVOrthKDStudent,
    loader: Any,
    *,
    device: torch.device,
    expected_segments: int,
    output_path: Path,
    labels_path: Path,
    offsets_path: Path,
) -> dict[str, Any]:
    dataset_count = len(loader.dataset)
    total_rows = dataset_count * expected_segments
    fusion_dim = int(model.fusion_dim)
    base = np.lib.format.open_memmap(
        output_path, mode="w+", dtype=np.float32, shape=(total_rows, FEATURE_BLOCKS * fusion_dim)
    )
    labels = np.lib.format.open_memmap(labels_path, mode="w+", dtype=np.int8, shape=(total_rows,))
    offsets = np.arange(0, total_rows + 1, expected_segments, dtype=np.int64)
    np.save(offsets_path, offsets)
    cursor = 0
    sample_count = 0
    try:
        with torch.inference_mode():
            for batch in loader:
                frames = batch["frame"].to(device, non_blocking=True)
                spectrogram = batch["spectrogram"].to(device, non_blocking=True)
                text_embedding = batch["text_embedding"].to(device, non_blocking=True)
                sequence_mask = batch["sequence_mask"].to(device, non_blocking=True)
                frame_valid = batch["frame_valid"].to(device, non_blocking=True)
                audio_valid = batch["audio_valid"].to(device, non_blocking=True)
                if tuple(frames.shape[:2]) != (frames.shape[0], expected_segments):
                    raise ValueError(f"Expected frame shape [B,10,...], got {tuple(frames.shape)}")
                if not bool(torch.all(sequence_mask == 1)) or not bool(torch.all(frame_valid == 1)) or not bool(torch.all(audio_valid == 1)):
                    raise ValueError("Frozen probe requires all official T=10 modality rows valid")
                outputs = model(
                    frame=frames,
                    spectrogram=spectrogram,
                    text_embedding=text_embedding,
                    sequence_mask=sequence_mask,
                    frame_valid=frame_valid,
                    audio_valid=audio_valid,
                )
                visual = outputs["visual_tokens"]
                audio = outputs["audio_tokens"]
                query = outputs["text_tokens"]
                if not all(isinstance(value, torch.Tensor) for value in (visual, audio, query)):
                    raise RuntimeError("Student did not return visual/audio/text tokens")
                position = model.position_embedding[:, :expected_segments, :].expand(visual.shape[0], -1, -1)
                tensors = [value.detach().cpu().numpy() for value in (visual, audio, query, position)]
                if any(value.shape != (frames.shape[0], expected_segments, fusion_dim) for value in tensors):
                    raise ValueError("Frozen token shape is not [B,10,384]")
                batch_rows = frames.shape[0] * expected_segments
                end = cursor + batch_rows
                base[cursor:end] = np.concatenate(tensors, axis=-1).reshape(batch_rows, FEATURE_BLOCKS * fusion_dim)
                batch_labels = batch["segment_label"].detach().cpu().numpy().astype(np.int8, copy=False).reshape(-1)
                if batch_labels.size != batch_rows or not np.isin(batch_labels, (0, 1)).all():
                    raise ValueError("Frozen probe labels are not binary [B,10]")
                labels[cursor:end] = batch_labels
                cursor = end
                sample_count += int(frames.shape[0])
        if cursor != total_rows or sample_count != dataset_count:
            raise RuntimeError(f"Frozen extraction covered {sample_count}/{dataset_count} samples")
        base.flush()
        labels.flush()
    finally:
        del base
        del labels
    return {
        "samples": sample_count,
        "segments": total_rows,
        "task_segments": expected_segments,
        "fusion_dim": fusion_dim,
        "base_path": str(output_path.resolve()),
        "labels_path": str(labels_path.resolve()),
        "offsets_path": str(offsets_path.resolve()),
        "base_sha256": _sha256_file(output_path),
        "labels_sha256": _sha256_file(labels_path),
        "offsets_sha256": _sha256_file(offsets_path),
    }


def _design_from_base(base: np.ndarray, name: str, fusion_dim: int) -> np.ndarray:
    if base.ndim != 2 or base.shape[1] != FEATURE_BLOCKS * fusion_dim:
        raise ValueError(f"base feature shape mismatch: {base.shape}")
    visual = base[:, :fusion_dim]
    audio = base[:, fusion_dim : 2 * fusion_dim]
    query = base[:, 2 * fusion_dim : 3 * fusion_dim]
    position = base[:, 3 * fusion_dim :]
    zeros = np.zeros_like(visual)
    if name == "qp":
        return np.concatenate((zeros, query, zeros, position), axis=-1)
    if name == "vqp":
        return np.concatenate((visual, query, visual * query, position), axis=-1)
    if name == "aqp":
        return np.concatenate((audio, query, audio * query, position), axis=-1)
    raise ValueError(f"Unknown probe name: {name}")


def _evaluate(scores: np.ndarray, labels: np.ndarray, offsets: np.ndarray) -> dict[str, Any]:
    y = np.asarray(labels, dtype=np.int64).reshape(-1)
    p = np.asarray(scores, dtype=np.float64).reshape(-1)
    return {
        "segments": int(y.size),
        "positive_rate": float(y.mean()),
        "ap": float(average_precision_score(y, p)),
        "auroc": float(roc_auc_score(y, p)),
        "score_mean": float(p.mean()),
        "score_std": float(p.std()),
        **mixed_metrics(y, p, offsets),
    }


def _audit_checkpoint(
    *,
    name: str,
    role: str,
    config_path: Path,
    checkpoint_path: Path,
    output_dir: Path,
    device: torch.device,
    batch_size: int,
    num_workers: int,
    shuffle_repeats: int,
    shuffle_seed: int,
    expected_commit: str | None,
    protocol_path: Path,
    protocol_sha: str,
) -> dict[str, Any]:
    result_path = output_dir / f"{name}.json"
    if result_path.exists():
        return json.loads(result_path.read_text(encoding="utf-8"))
    config = _load_yaml(config_path)
    if task_segments_from_config(config) != TASK_SEGMENTS:
        raise ValueError(f"{name}: config is not official T=10")
    model, checkpoint, checkpoint_sha = _load_checkpoint(checkpoint_path, config, device)
    if expected_commit is not None and str(checkpoint.get("implementation_commit", expected_commit)) != expected_commit:
        raise ValueError(f"{name}: checkpoint implementation commit does not match expected commit")
    state_before = _state_sha256(model)
    model.eval()
    feature_dir = output_dir / "features" / name
    feature_dir.mkdir(parents=True, exist_ok=True)
    split_info: dict[str, Any] = {}
    for split in ("train", "val", "test"):
        base_path = feature_dir / f"{split}_base.npy"
        labels_path = feature_dir / f"{split}_labels.npy"
        offsets_path = feature_dir / f"{split}_offsets.npy"
        metadata_path = feature_dir / f"{split}.json"
        if metadata_path.exists() and base_path.exists() and labels_path.exists() and offsets_path.exists():
            split_info[split] = json.loads(metadata_path.read_text(encoding="utf-8"))
            continue
        loader = _split_loader(config, split, batch_size, num_workers)
        info = _extract_base_features(
            model,
            loader,
            device=device,
            expected_segments=TASK_SEGMENTS,
            output_path=base_path,
            labels_path=labels_path,
            offsets_path=offsets_path,
        )
        info.update({"split": split, "augmentation": False, "loader_shuffle": False})
        _atomic_json(metadata_path, info)
        split_info[split] = info
    state_after_extraction = _state_sha256(model)
    if state_before != state_after_extraction:
        raise RuntimeError(f"{name}: model state changed during read-only extraction")

    base_arrays = {
        split: np.load(split_info[split]["base_path"], mmap_mode="r")
        for split in ("train", "val", "test")
    }
    labels = {
        split: np.load(split_info[split]["labels_path"], mmap_mode="r")
        for split in ("train", "val", "test")
    }
    offsets = {
        split: np.load(split_info[split]["offsets_path"], mmap_mode="r")
        for split in ("train", "val", "test")
    }
    fusion_dim = int(model.fusion_dim)
    probe_results: dict[str, Any] = {}
    for probe_name in PROBE_NAMES:
        validation_by_alpha: dict[float, dict[str, float]] = {}
        fitted: dict[float, tuple[Any, Any]] = {}
        train_design = _design_from_base(base_arrays["train"], probe_name, fusion_dim)
        val_design = _design_from_base(base_arrays["val"], probe_name, fusion_dim)
        train_labels = np.asarray(labels["train"], dtype=np.int64)
        val_labels = np.asarray(labels["val"], dtype=np.int64)
        for alpha in ALPHA_GRID:
            scaler, classifier = fit_logistic_probe(
                train_design,
                train_labels,
                alpha=alpha,
                random_state=42,
            )
            val_scores = predict_probe_scores(scaler, classifier, val_design)
            val_eval = _evaluate(val_scores, val_labels, np.asarray(offsets["val"], dtype=np.int64))
            validation_by_alpha[float(alpha)] = {
                "mixed_pair_weighted": float(val_eval["mixed_pair_weighted"]),
                "mixed_ap": float(val_eval["mixed_ap"]),
                "mixed_auroc": float(val_eval["mixed_auroc"]),
                "ap": float(val_eval["ap"]),
                "auroc": float(val_eval["auroc"]),
            }
            fitted[float(alpha)] = (scaler, classifier)
        selected_alpha = choose_alpha(validation_by_alpha)
        scaler, classifier = fitted[selected_alpha]
        test_design = _design_from_base(base_arrays["test"], probe_name, fusion_dim)
        test_labels = np.asarray(labels["test"], dtype=np.int64)
        test_offsets = np.asarray(offsets["test"], dtype=np.int64)
        test_scores = predict_probe_scores(scaler, classifier, test_design)
        test_eval = _evaluate(test_scores, test_labels, test_offsets)
        test_shuffle = shuffle_metrics(
            test_labels,
            test_scores,
            test_offsets,
            repeats=shuffle_repeats,
            seed=shuffle_seed,
        )
        probe_results[probe_name] = {
            "protocol": {
                "classifier": "sklearn.linear_model.SGDClassifier",
                "loss": "log_loss",
                "penalty": "l2",
                "alpha_grid": list(ALPHA_GRID),
                "selected_alpha": selected_alpha,
                "feature_standardization": "train_split_standard_scaler",
                "random_state": 42,
                "max_iter": 2000,
                "tol": 1e-5,
                "average_parameters": True,
                "test_evaluations": 1,
            },
            "validation_by_alpha": {str(key): value for key, value in validation_by_alpha.items()},
            "test": {**test_eval, "shuffle": test_shuffle},
        }
        del train_design, val_design, test_design
    outcome = summarize_probe_outcome(
        probe_results["qp"]["test"],
        probe_results["vqp"]["test"],
        probe_results["aqp"]["test"],
    )
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "claim_level": "read_only_frozen_feature_probe_audit",
        "checkpoint": {
            "name": name,
            "role": role,
            "path": str(checkpoint_path.resolve()),
            "sha256": checkpoint_sha,
            "global_step": int(checkpoint.get("global_step", -1)),
            "config_path": str(config_path.resolve()),
            "config_sha256": _canonical_sha(config),
        },
        "protocol": {
            "task_segments": TASK_SEGMENTS,
            "protocol_path": str(protocol_path.resolve()),
            "protocol_sha256": protocol_sha,
            "temporal_conversion": "forbidden",
            "visual_audio_query_position_blocks": FEATURE_BLOCKS,
            "fusion_dim": fusion_dim,
            "feature_designs": {
                "qp": "[zero,q,zero,p]",
                "vqp": "[v,q,v*q,p]",
                "aqp": "[a,q,a*q,p]",
            },
            "train_augmentation": False,
            "loader_shuffle": False,
            "student_mode": "eval_inference_mode",
            "student_optimizer_steps": 0,
            "student_backward_calls": 0,
            "checkpoint_writes": 0,
            "shuffle_repeats": int(shuffle_repeats),
            "shuffle_seed": int(shuffle_seed),
        },
        "sources": {
            "state_sha256_before": state_before,
            "state_sha256_after_extraction": state_after_extraction,
            "state_unchanged": state_before == state_after_extraction,
            "splits": split_info,
        },
        "probes": probe_results,
        "outcome": outcome,
    }
    _atomic_json(result_path, result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--shuffle-repeats", type=int, default=100)
    parser.add_argument("--shuffle-seed", type=int, default=42)
    parser.add_argument("--expected-commit", default=None)
    parser.add_argument(
        "--checkpoint",
        action="append",
        required=True,
        metavar="NAME|ROLE|CONFIG|CHECKPOINT",
        help="repeat for s8_step1200|primary|config.yaml|checkpoint.pt (use | so Windows drive letters are safe)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.batch_size <= 0 or args.num_workers < 0:
        raise ValueError("batch-size must be positive and num-workers non-negative")
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    device = torch.device(args.device)
    protocol_sha = _validate_protocol(
        args.protocol.resolve(),
        shuffle_repeats=args.shuffle_repeats,
        shuffle_seed=args.shuffle_seed,
    )
    entries: list[tuple[str, str, Path, Path]] = []
    for value in args.checkpoint:
        parts = value.split("|", 3)
        if len(parts) != 4:
            raise ValueError(f"Invalid --checkpoint {value!r}; expected NAME|ROLE|CONFIG|CHECKPOINT")
        name, role, config, checkpoint = parts
        if name in {entry[0] for entry in entries}:
            raise ValueError(f"Duplicate checkpoint name: {name}")
        entries.append((name, role, Path(config).resolve(), Path(checkpoint).resolve()))
    records: dict[str, Any] = {}
    for name, role, config_path, checkpoint_path in entries:
        records[name] = _audit_checkpoint(
            name=name,
            role=role,
            config_path=config_path,
            checkpoint_path=checkpoint_path,
            output_dir=output,
            device=device,
            batch_size=args.batch_size,
            num_workers=args.num_workers,
            shuffle_repeats=args.shuffle_repeats,
            shuffle_seed=args.shuffle_seed,
            expected_commit=args.expected_commit,
            protocol_path=args.protocol.resolve(),
            protocol_sha=protocol_sha,
        )
    primary = [value for value in records.values() if value["checkpoint"]["role"] == "primary"]
    if len(primary) != 1:
        raise ValueError("Exactly one checkpoint must have role=primary")
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "claim_level": "read_only_frozen_feature_probe_audit",
        "protocol": {
            "task_segments": TASK_SEGMENTS,
            "protocol_path": str(args.protocol.resolve()),
            "protocol_sha256": protocol_sha,
            "alpha_grid": list(ALPHA_GRID),
            "test_evaluations": 1,
            "formal_student_training_started": False,
            "formal_full_authorized": False,
        },
        "primary": {
            "checkpoint": primary[0]["checkpoint"]["name"],
            "outcome": primary[0]["outcome"],
        },
        "checkpoints": {
            key: {
                "role": value["checkpoint"]["role"],
                "global_step": value["checkpoint"]["global_step"],
                "outcome": value["outcome"],
            }
            for key, value in records.items()
        },
    }
    _atomic_json(output / "summary.json", summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
