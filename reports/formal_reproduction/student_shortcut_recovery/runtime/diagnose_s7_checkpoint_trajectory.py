#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import torch
import yaml
from sklearn.metrics import average_precision_score


EXPECTED_COMMIT = "a7f0dc06d6a98493c0d03f1caa2059e31c50b648"
CHECKPOINT_STEPS = (400, 800, 1200)
S0_REFERENCE = {
    "global_test_ap": 0.7487446823980081,
    "mean_centered_test_ap": 0.6376356327985894,
    "per_query_macro_test_ap": 0.6243702016586737,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise AssertionError(f"Expected JSON object: {path}")
    return value


def canonical_config_sha(config: Mapping[str, Any]) -> str:
    payload = json.dumps(
        dict(config), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def run_git(git: Path, repo: Path, *args: str) -> str:
    completed = subprocess.run(
        [str(git), "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def safe_ap(labels: np.ndarray, probabilities: np.ndarray) -> float:
    y = np.asarray(labels, dtype=np.int64).reshape(-1)
    p = np.asarray(probabilities, dtype=np.float64).reshape(-1)
    assert y.size == p.size and y.size > 0
    assert np.isin(y, (0, 1)).all() and np.isfinite(p).all()
    return float(average_precision_score(y, p)) if np.any(y == 1) else 0.0


def per_query_macro_ap(predictions: Mapping[str, np.ndarray]) -> dict[str, Any]:
    queries = np.asarray(predictions["queries"]).astype(str).reshape(-1)
    offsets = np.asarray(predictions["sample_offsets"], dtype=np.int64).reshape(-1)
    labels = np.asarray(predictions["labels"], dtype=np.int64).reshape(-1)
    probabilities = np.asarray(
        predictions["probabilities"], dtype=np.float64
    ).reshape(-1)
    assert offsets.size == queries.size + 1
    query_labels: dict[str, list[np.ndarray]] = {}
    query_probabilities: dict[str, list[np.ndarray]] = {}
    for index, query in enumerate(queries):
        start, end = int(offsets[index]), int(offsets[index + 1])
        query_labels.setdefault(query, []).append(labels[start:end])
        query_probabilities.setdefault(query, []).append(probabilities[start:end])
    values = {
        query: safe_ap(
            np.concatenate(query_labels[query]),
            np.concatenate(query_probabilities[query]),
        )
        for query in sorted(query_labels)
    }
    return {
        "query_count": len(values),
        "macro_ap": float(np.mean(list(values.values()))),
        "minimum_ap": float(min(values.values())),
        "maximum_ap": float(max(values.values())),
        "per_query": values,
    }


def label_conditioned_logits(predictions: Mapping[str, np.ndarray]) -> dict[str, float]:
    labels = np.asarray(predictions["labels"], dtype=np.int64).reshape(-1)
    logits = np.asarray(predictions["logits"], dtype=np.float64).reshape(-1)
    assert labels.size == logits.size
    assert np.any(labels == 1) and np.any(labels == 0)
    return {
        "positive_mean": float(logits[labels == 1].mean()),
        "negative_mean": float(logits[labels == 0].mean()),
        "positive_minus_negative": float(
            logits[labels == 1].mean() - logits[labels == 0].mean()
        ),
    }


def compression_receipt(path_scales: Mapping[str, Any]) -> dict[str, float]:
    shared = float(path_scales["shared_features"]["within_sample_temporal_std_mean"])
    decision = float(
        path_scales["decision_features"]["within_sample_temporal_std_mean"]
    )
    logits = float(path_scales["segment_logits"]["within_sample_temporal_std_mean"])
    return {
        "temporal_input_shared_std": shared,
        "decision_std": decision,
        "logit_std": logits,
        "shared_to_decision_compression_factor": shared / max(decision, 1e-30),
        "shared_to_logit_compression_factor": shared / max(logits, 1e-30),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--git", type=Path, required=True)
    parser.add_argument("--training-output", type=Path, required=True)
    parser.add_argument("--training-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--shuffle-repeats", type=int, default=100)
    args = parser.parse_args()

    assert args.shuffle_repeats > 0
    assert run_git(args.git, args.repo, "rev-parse", "HEAD") == EXPECTED_COMMIT
    assert (
        run_git(args.git, args.repo, "status", "--porcelain=v1", "--untracked-files=all")
        == ""
    )
    training_audit = read_json(args.training_audit)
    assert training_audit["status"] == "PASS"
    assert training_audit["git_commit"] == EXPECTED_COMMIT
    assert training_audit["task_segments"] == 10
    assert training_audit["sole_scientific_change_from_s0"] == (
        "student.temporal_path_mode_transformer_to_identity_passthrough"
    )
    config_path = args.training_output / "resolved_config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert isinstance(config, dict)
    assert config["data"]["num_segments"] == 10
    assert config["student"]["temporal_path_mode"] == "identity_passthrough"

    sys.path.insert(0, str(args.repo.resolve()))
    os.chdir(args.repo)
    from scripts.diagnose_checkpoint_modalities import (  # noqa: PLC0415
        collect_ablation_matrix,
        summarize_prediction_response,
    )
    from scripts.diagnose_student_shortcuts import (  # noqa: PLC0415
        mean_center_logits,
        temporal_shuffle_diagnostic,
    )
    from scripts.train_ov_orthkd import (  # noqa: PLC0415
        build_model_and_loss,
        set_seed,
    )
    from src.data import create_ov_avel_data_loaders  # noqa: PLC0415

    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")
    device = torch.device(args.device)
    set_seed(
        int(config.get("seed", 42)),
        deterministic=bool(config.get("training", {}).get("deterministic", True)),
    )
    student, _loss_module = build_model_and_loss(config, device)
    train_loader, validation_loader, test_loader = create_ov_avel_data_loaders(config)
    del train_loader, validation_loader
    assert test_loader is not None

    checkpoint_reports: dict[str, Any] = {}
    for step in CHECKPOINT_STEPS:
        checkpoint_path = (
            args.training_output
            / "diagnostic_checkpoints"
            / f"step_{step:06d}.pt"
        )
        checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
        assert checkpoint["global_step"] == step
        assert canonical_config_sha(checkpoint["config"]) == canonical_config_sha(config)
        incompatible = student.load_state_dict(
            checkpoint["student_state_dict"], strict=True
        )
        assert not incompatible.missing_keys and not incompatible.unexpected_keys
        del checkpoint
        set_seed(
            int(config.get("seed", 42)),
            deterministic=bool(
                config.get("training", {}).get("deterministic", True)
            ),
        )
        predictions, path_scales = collect_ablation_matrix(
            student,
            test_loader,
            device,
            expected_task_segments=10,
        )
        original = predictions["original"]
        modes = {
            mode: summarize_prediction_response(payload, threshold=0.5)
            for mode, payload in predictions.items()
        }
        labels = np.asarray(original["labels"], dtype=np.int64)
        logits = np.asarray(original["logits"], dtype=np.float64)
        offsets = np.asarray(original["sample_offsets"], dtype=np.int64)
        centered_logits = mean_center_logits(logits, offsets)
        centered_ap = safe_ap(labels, 1.0 / (1.0 + np.exp(-centered_logits)))
        shuffle = temporal_shuffle_diagnostic(
            original,
            repeats=args.shuffle_repeats,
            seed=42,
        )
        compression = compression_receipt(path_scales)
        query_report = per_query_macro_ap(original)
        assert abs(
            query_report["macro_ap"]
            - float(modes["original"]["metrics"]["per_query_macro_ap"])
        ) <= 1e-15
        original_ap = float(modes["original"]["ap"])
        both_zero_ap = float(modes["both_zero"]["ap"])
        shuffle_mean_ap = float(shuffle["ap_distribution"]["mean"])
        checkpoint_reports[str(step)] = {
            "checkpoint": {
                "path": str(checkpoint_path.resolve()),
                "bytes": checkpoint_path.stat().st_size,
                "sha256": sha256(checkpoint_path),
                "global_step": step,
            },
            "modes": modes,
            "original_path_scales": path_scales,
            "label_conditioned_logits": label_conditioned_logits(original),
            "mean_centered": {
                "ap": centered_ap,
                "delta_from_original": centered_ap - original_ap,
            },
            "per_query": query_report,
            "temporal_shuffle": shuffle,
            "causal_deltas": {
                "shuffle_ap_drop": original_ap - shuffle_mean_ap,
                "both_zero_ap_drop": original_ap - both_zero_ap,
                "visual_zero_ap_drop": original_ap
                - float(modes["visual_zero"]["ap"]),
                "audio_zero_ap_drop": original_ap
                - float(modes["audio_zero"]["ap"]),
            },
            "compression": compression,
        }

    best_step = int(training_audit["checkpoint_roles"]["best"]["global_step"])
    best_original_ap = float(checkpoint_reports[str(best_step)]["modes"]["original"]["ap"])
    training_test_ap = float(training_audit["final_metrics"]["test_ap"])
    assert abs(best_original_ap - training_test_ap) <= 1e-12

    def step_supports_shared_encoder_cause(step: int) -> bool:
        report = checkpoint_reports[str(step)]
        return bool(
            report["label_conditioned_logits"]["positive_minus_negative"] > 0.0
            and report["causal_deltas"]["shuffle_ap_drop"] >= 0.02
            and report["causal_deltas"]["both_zero_ap_drop"] >= 0.03
            and report["modes"]["original"]["within_sample_logit_std"]["mean"]
            >= 0.01
            and report["compression"]["shared_to_decision_compression_factor"]
            < 100.0
            and report["compression"]["shared_to_logit_compression_factor"] < 100.0
        )

    best = checkpoint_reports[str(best_step)]
    causal_decision = {
        "criteria_source": "approved_web_review_S7_plan",
        "step_400_supports_shared_encoder_major_cause": step_supports_shared_encoder_cause(
            400
        ),
        "step_800_supports_shared_encoder_major_cause": step_supports_shared_encoder_cause(
            800
        ),
        "simultaneous_step_400_and_800_support": (
            step_supports_shared_encoder_cause(400)
            and step_supports_shared_encoder_cause(800)
        ),
        "stronger_recovery_at_best": {
            "predicted_positive_rate_below_0_98": (
                best["modes"]["original"]["predicted_positive_rate"] < 0.98
            ),
            "centered_ap_above_s0": (
                best["mean_centered"]["ap"]
                > S0_REFERENCE["mean_centered_test_ap"]
            ),
            "per_query_macro_ap_above_s0": (
                best["per_query"]["macro_ap"]
                > S0_REFERENCE["per_query_macro_test_ap"]
            ),
        },
        "failure_signals": {
            "step_400_shuffle_drop_below_0_01": (
                checkpoint_reports["400"]["causal_deltas"]["shuffle_ap_drop"]
                < 0.01
            ),
            "step_400_both_zero_retains_at_least_98_percent": (
                checkpoint_reports["400"]["modes"]["both_zero"]["ap"]
                >= 0.98 * checkpoint_reports["400"]["modes"]["original"]["ap"]
            ),
            "step_400_positive_not_above_negative": (
                checkpoint_reports["400"]["label_conditioned_logits"][
                    "positive_minus_negative"
                ]
                <= 0.0
            ),
        },
    }
    report = {
        "schema_version": 1,
        "status": "PASS",
        "claim_level": "noncanonical_s7_checkpoint_trajectory_diagnostic",
        "protocol": {
            "task_segments": 10,
            "temporal_conversion": "forbidden",
            "checkpoints": list(CHECKPOINT_STEPS),
            "content_ablation_modes": [
                "original",
                "visual_zero",
                "audio_zero",
                "both_zero",
            ],
            "shuffle_repeats": args.shuffle_repeats,
            "test_views": 1,
        },
        "git_commit": EXPECTED_COMMIT,
        "sources": {
            "training_audit": {
                "path": str(args.training_audit.resolve()),
                "bytes": args.training_audit.stat().st_size,
                "sha256": sha256(args.training_audit),
            },
            "resolved_config": {
                "path": str(config_path.resolve()),
                "bytes": config_path.stat().st_size,
                "sha256": sha256(config_path),
            },
        },
        "s0_reference": S0_REFERENCE,
        "best_step": best_step,
        "checkpoint_reports": checkpoint_reports,
        "causal_decision": causal_decision,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
