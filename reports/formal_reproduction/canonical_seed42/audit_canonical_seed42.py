#!/usr/bin/env python3
"""Mechanical final-artifact audit for the fixed MM26 canonical seed42 run."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import torch
import yaml


EXPECTED_COMMIT = "31b86c0d60c4bf2ed028edf1385ed5d2c9e89153"
EXPECTED_CACHE = {
    "schema_version": 1,
    "files": 99_334,
    "bytes": 1_310_102_478,
    "sha256": "6707900b5d4acb39752baeea11cd1e90d8d3394600b1fa3a6cc3984223860244",
}
EXPECTED_EVALUATOR_SHA = "013949f6371dc11a93f4e5b1df448601b98cf5590e7651d103600f981a4ded19"
EXPECTED_PREDICTION_KEYS = {
    "ids",
    "queries",
    "split_types",
    "sample_offsets",
    "segment_indices",
    "labels",
    "logits",
    "probabilities",
}
REQUIRED_FILES = {
    "best.pt",
    "best_validation_predictions.npz",
    "claim_level.txt",
    "config_resolved.yaml",
    "cuda_environment.json",
    "experiment_variant.json",
    "final_metrics.json",
    "git_state.json",
    "history.jsonl",
    "last.pt",
    "lock_hashes.json",
    "manifest_hashes.json",
    "official_evaluator_hash.json",
    "requirements_freeze.txt",
    "resolved_config.yaml",
    "runtime.json",
    "teacher_cache_hash.json",
    "test_predictions.npz",
    "train.log",
    "validation_pr_curve.npz",
    "validation_predictions.npz",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def all_finite(value: Any) -> bool:
    if isinstance(value, dict):
        return all(all_finite(item) for item in value.values())
    if isinstance(value, list):
        return all(all_finite(item) for item in value)
    if isinstance(value, float):
        return math.isfinite(value)
    return True


def audit_predictions(path: Path, expected_samples: int, errors: list[str]) -> dict[str, Any]:
    with np.load(path, allow_pickle=False) as payload:
        keys = set(payload.files)
        require(keys == EXPECTED_PREDICTION_KEYS, f"{path.name}: prediction key mismatch", errors)
        arrays = {name: np.asarray(payload[name]) for name in payload.files}
    ids = arrays["ids"]
    offsets = arrays["sample_offsets"]
    segments = arrays["segment_indices"]
    require(ids.size == expected_samples, f"{path.name}: sample count mismatch", errors)
    require(offsets.ndim == 1 and offsets.size == ids.size + 1, f"{path.name}: bad offsets", errors)
    require(offsets.size > 0 and int(offsets[0]) == 0, f"{path.name}: first offset is not zero", errors)
    counts = np.diff(offsets)
    require(np.all(counts == 10), f"{path.name}: not every sample has T=10", errors)
    total_segments = int(offsets[-1]) if offsets.size else 0
    require(total_segments == expected_samples * 10, f"{path.name}: total segment mismatch", errors)
    for name in ("segment_indices", "labels", "logits", "probabilities"):
        require(arrays[name].size == total_segments, f"{path.name}: {name} size mismatch", errors)
    if total_segments:
        expected_indices = np.tile(np.arange(10, dtype=np.int64), expected_samples)
        require(np.array_equal(segments.astype(np.int64), expected_indices), f"{path.name}: segment order mismatch", errors)
        for name in ("labels", "logits", "probabilities"):
            require(np.isfinite(arrays[name]).all(), f"{path.name}: {name} contains non-finite values", errors)
        require(
            np.all((arrays["probabilities"] >= 0.0) & (arrays["probabilities"] <= 1.0)),
            f"{path.name}: probabilities outside [0,1]",
            errors,
        )
    split_values, split_counts = np.unique(arrays["split_types"].astype(str), return_counts=True)
    return {
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "sample_count": int(ids.size),
        "segment_count": total_segments,
        "task_segments_per_sample": sorted(set(int(value) for value in counts.tolist())),
        "split_counts": {str(key): int(value) for key, value in zip(split_values, split_counts)},
        "arrays": {name: {"shape": list(value.shape), "dtype": str(value.dtype)} for name, value in arrays.items()},
    }


def checkpoint_summary(path: Path, errors: list[str]) -> dict[str, Any]:
    checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    require(isinstance(checkpoint, dict), f"{path.name}: checkpoint is not a mapping", errors)
    fingerprint = checkpoint.get("reproduction_fingerprint", {})
    summary = {
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "epoch": checkpoint.get("epoch"),
        "global_step": checkpoint.get("global_step"),
        "best_metric": checkpoint.get("best_metric"),
        "fingerprint": fingerprint,
        "keys": sorted(checkpoint),
    }
    del checkpoint
    gc.collect()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--git", default="git")
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    repo_root = output_dir.parents[2]
    errors: list[str] = []

    actual_files = {path.name for path in output_dir.iterdir() if path.is_file()}
    require(REQUIRED_FILES <= actual_files, f"missing files: {sorted(REQUIRED_FILES - actual_files)}", errors)
    require(not any(path.is_dir() for path in output_dir.iterdir()), "unexpected output subdirectory", errors)
    require(not (output_dir / "INCOMPATIBLE_RESUME.txt").exists(), "incompatible marker exists", errors)

    config = yaml.safe_load((output_dir / "resolved_config.yaml").read_text(encoding="utf-8"))
    protocol = {
        "task_segments": config["data"]["num_segments"],
        "max_position_segments": config["student"]["max_position_segments"],
        "student_frames_per_segment": config["data"]["visual_preprocessing"]["jpgs_per_segment"],
        "teacher_frames_per_segment": config["teacher_export"]["internvideo2"]["num_frames"],
        "test_views": config["evaluation"]["test_views"],
        "view_aggregation": config["evaluation"]["view_aggregation"],
        "temporal_resampling": config["data"]["temporal_resampling"],
        "seed": config["seed"],
        "epochs": config["training"]["epochs"],
        "max_batches_per_epoch": config["training"]["max_batches_per_epoch"],
    }
    require(protocol == {
        "task_segments": 10,
        "max_position_segments": 16,
        "student_frames_per_segment": 1,
        "teacher_frames_per_segment": 8,
        "test_views": 1,
        "view_aggregation": "none",
        "temporal_resampling": False,
        "seed": 42,
        "epochs": 30,
        "max_batches_per_epoch": 400,
    }, "resolved protocol mismatch", errors)
    require((output_dir / "claim_level.txt").read_text(encoding="utf-8").strip() == "paper_specified_reconstruction", "claim mismatch", errors)

    git_state = json.loads((output_dir / "git_state.json").read_text(encoding="utf-8"))
    require(git_state["head"]["stdout"] == EXPECTED_COMMIT, "recorded Git HEAD mismatch", errors)
    require(git_state["status"]["stdout"] == "", "recorded Git tree is dirty", errors)
    current_head = subprocess.check_output([args.git, "-C", str(repo_root), "rev-parse", "HEAD"], text=True).strip()
    current_status = subprocess.check_output(
        [args.git, "-C", str(repo_root), "status", "--porcelain", "--untracked-files=all"], text=True
    ).strip()
    require(current_head == EXPECTED_COMMIT, "current Git HEAD mismatch", errors)
    require(current_status == "", "current Git tree is dirty", errors)

    cache = json.loads((output_dir / "teacher_cache_hash.json").read_text(encoding="utf-8"))
    for key, expected in EXPECTED_CACHE.items():
        require(cache.get(key) == expected, f"cache {key} mismatch", errors)
    evaluator = json.loads((output_dir / "official_evaluator_hash.json").read_text(encoding="utf-8"))
    require(evaluator.get("source_exists") is True, "evaluator source missing", errors)
    require(evaluator.get("matches_lock") is True, "evaluator does not match lock", errors)
    require(evaluator.get("expected_sha256") == EXPECTED_EVALUATOR_SHA, "evaluator expected SHA mismatch", errors)
    require(evaluator.get("actual_sha256") == EXPECTED_EVALUATOR_SHA, "evaluator actual SHA mismatch", errors)

    history = [json.loads(line) for line in (output_dir / "history.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    require(len(history) == 30, "history does not contain 30 epochs", errors)
    require([row["epoch"] for row in history] == list(range(30)), "epoch sequence mismatch", errors)
    require([row["global_step"] for row in history] == [400 * (index + 1) for index in range(30)], "global-step sequence mismatch", errors)
    require(all_finite(history), "history contains non-finite values", errors)
    best_history = max(history, key=lambda row: row["validation"]["ap"])

    final_metrics = json.loads((output_dir / "final_metrics.json").read_text(encoding="utf-8"))
    require(all_finite(final_metrics), "final metrics contain non-finite values", errors)
    require(set(final_metrics) == {"validation_calibration", "validation", "test"}, "final metric groups mismatch", errors)
    for split in ("validation", "test"):
        require(set(final_metrics[split]["metrics"]) == {"total", "seen", "unseen"}, f"{split} groups mismatch", errors)
    require(
        math.isclose(final_metrics["validation"]["metrics"]["total"]["ap"], best_history["validation"]["ap"], rel_tol=0.0, abs_tol=1e-15),
        "final validation AP does not equal history best",
        errors,
    )
    best_threshold = final_metrics["validation_calibration"]["best_threshold"]
    require(final_metrics["validation"]["threshold"] == best_threshold, "validation threshold mismatch", errors)
    require(final_metrics["test"]["threshold"] == best_threshold, "test threshold mismatch", errors)

    predictions = {
        "best_validation_predictions.npz": audit_predictions(output_dir / "best_validation_predictions.npz", 5798, errors),
        "validation_predictions.npz": audit_predictions(output_dir / "validation_predictions.npz", 5798, errors),
        "test_predictions.npz": audit_predictions(output_dir / "test_predictions.npz", 5820, errors),
    }
    require(
        predictions["best_validation_predictions.npz"]["sha256"] == predictions["validation_predictions.npz"]["sha256"],
        "final validation predictions differ from saved best predictions",
        errors,
    )
    require(final_metrics["validation"]["metrics"]["total"]["sample_count"] == 5798, "validation metric sample count mismatch", errors)
    require(final_metrics["validation"]["metrics"]["total"]["segment_count"] == 57980, "validation metric segment count mismatch", errors)
    require(final_metrics["test"]["metrics"]["total"]["sample_count"] == 5820, "test metric sample count mismatch", errors)
    require(final_metrics["test"]["metrics"]["total"]["segment_count"] == 58200, "test metric segment count mismatch", errors)

    checkpoints = {
        "best.pt": checkpoint_summary(output_dir / "best.pt", errors),
        "last.pt": checkpoint_summary(output_dir / "last.pt", errors),
    }
    require(checkpoints["best.pt"]["epoch"] == best_history["epoch"], "best checkpoint epoch mismatch", errors)
    require(checkpoints["best.pt"]["global_step"] == best_history["global_step"], "best checkpoint step mismatch", errors)
    require(checkpoints["last.pt"]["epoch"] == 29, "last checkpoint epoch mismatch", errors)
    require(checkpoints["last.pt"]["global_step"] == 12000, "last checkpoint step mismatch", errors)

    file_manifest = {
        path.name: {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for path in sorted(output_dir.iterdir())
        if path.is_file() and path.name not in {"best.pt", "last.pt", "best_validation_predictions.npz", "validation_predictions.npz", "test_predictions.npz"}
    }
    result = {
        "schema_version": 1,
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "git_commit": current_head,
        "git_clean": current_status == "",
        "protocol": protocol,
        "claim_level": "paper_specified_reconstruction",
        "history": {
            "epoch_records": len(history),
            "final_global_step": history[-1]["global_step"] if history else None,
            "best_epoch_zero_based": best_history["epoch"] if history else None,
            "best_epoch_one_based": best_history["epoch"] + 1 if history else None,
            "best_validation_ap": best_history["validation"]["ap"] if history else None,
            "total_elapsed_seconds": sum(row["elapsed_seconds"] for row in history),
            "max_peak_memory_mb": max(row["peak_memory_mb"] for row in history),
            "final_learning_rate": history[-1]["learning_rate"] if history else None,
        },
        "cache": cache,
        "evaluator": evaluator,
        "checkpoints": checkpoints,
        "predictions": predictions,
        "final_metrics": final_metrics,
        "file_manifest": file_manifest,
    }
    rendered = json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
