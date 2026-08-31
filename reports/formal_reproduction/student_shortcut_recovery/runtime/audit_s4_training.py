#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml


EXPECTED_COMMIT = "74d211d34ace74ce3b74ea082a7dfd0379b251fb"
EXPECTED_CONFIG_SHA256 = "5b81218b55907a5dfb0419e62eff2128f0d08ce9301c97c081237f8c8f599b33"
EXPECTED_S3_COMMIT = "a0aa4d7ad4b98455e26a2fe6ff2537a321293233"
EXPECTED_SPLITS = {
    "validation": (5798, 57980),
    "test": (5820, 58200),
}
REQUIRED_OUTPUTS = (
    "best.pt",
    "last.pt",
    "final_metrics.json",
    "history.jsonl",
    "training_diagnostics.jsonl",
    "implementation_behavior.json",
    "resolved_config.yaml",
    "config_resolved.yaml",
    "validation_predictions.npz",
    "test_predictions.npz",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_text_sha256(path: Path) -> str:
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise AssertionError(f"Expected JSON object: {path}")
    return payload


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        if not line.strip():
            raise AssertionError(f"Blank JSONL line {line_number}: {path}")
        value = json.loads(line)
        if not isinstance(value, dict):
            raise AssertionError(f"Expected JSON object at line {line_number}: {path}")
        records.append(value)
    return records


def assert_finite(value: Any, path: str = "root") -> None:
    if isinstance(value, float):
        assert math.isfinite(value), f"non-finite value at {path}"
    elif isinstance(value, dict):
        for key, item in value.items():
            assert_finite(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_finite(item, f"{path}[{index}]")


def run_git(git: Path, repo: Path, *args: str) -> str:
    completed = subprocess.run(
        [str(git), "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def different_paths(left: Any, right: Any, prefix: str = "") -> set[str]:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        paths: set[str] = set()
        for key in set(left) | set(right):
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in left or key not in right:
                paths.add(path)
            else:
                paths.update(different_paths(left[key], right[key], path))
        return paths
    return set() if left == right else {prefix}


def normalize_control_identity(config: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(config)
    normalized["reproduction"]["variant"] = "NORMALIZED"
    normalized["logging"]["log_dir"] = "NORMALIZED"
    return normalized


def audit_prediction_npz(path: Path, samples: int, segments: int) -> dict[str, Any]:
    with np.load(path, allow_pickle=False) as payload:
        required = {
            "ids",
            "queries",
            "split_types",
            "sample_offsets",
            "segment_indices",
            "labels",
            "logits",
            "probabilities",
        }
        assert set(payload.files) == required, (path, payload.files)
        arrays = {name: np.asarray(payload[name]) for name in required}
    assert arrays["ids"].reshape(-1).size == samples
    assert arrays["queries"].reshape(-1).size == samples
    assert arrays["split_types"].reshape(-1).size == samples
    offsets = arrays["sample_offsets"].astype(np.int64, copy=False).reshape(-1)
    assert offsets.size == samples + 1
    assert offsets[0] == 0 and offsets[-1] == segments
    assert np.all(np.diff(offsets) == 10)
    indices = arrays["segment_indices"].astype(np.int64, copy=False).reshape(-1)
    assert indices.size == segments
    assert np.array_equal(
        indices.reshape(samples, 10), np.tile(np.arange(10), (samples, 1))
    )
    labels = arrays["labels"].astype(np.float64, copy=False).reshape(-1)
    logits = arrays["logits"].astype(np.float64, copy=False).reshape(-1)
    probabilities = arrays["probabilities"].astype(np.float64, copy=False).reshape(-1)
    assert labels.size == logits.size == probabilities.size == segments
    assert np.isin(labels, (0.0, 1.0)).all()
    assert np.isfinite(logits).all() and np.isfinite(probabilities).all()
    assert np.all((probabilities >= 0.0) & (probabilities <= 1.0))
    expected_probabilities = 1.0 / (1.0 + np.exp(-logits))
    assert np.allclose(probabilities, expected_probabilities, rtol=1e-7, atol=1e-8)
    return {
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "sample_count": samples,
        "segment_count": segments,
        "positive_rate": float(labels.mean()),
        "predicted_positive_rate_at_0_5": float((probabilities >= 0.5).mean()),
        "logit_min": float(logits.min()),
        "logit_max": float(logits.max()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--git", type=Path, required=True)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--candidate-verification", type=Path, required=True)
    parser.add_argument("--s3-training-audit", type=Path, required=True)
    parser.add_argument("--s3-posthoc-audit", type=Path, required=True)
    args = parser.parse_args()

    assert run_git(args.git, args.repo, "rev-parse", "HEAD") == EXPECTED_COMMIT
    assert run_git(
        args.git, args.repo, "status", "--porcelain=v1", "--untracked-files=all"
    ) == ""

    state = read_json(args.control / "worker_state.json")
    assert state["status"] == "completed" and state["exit_code"] == 0
    assert state["git_commit"] == EXPECTED_COMMIT
    assert state["config_sha256"] == EXPECTED_CONFIG_SHA256
    assert state["completed_phases"] == ["s4_training"]

    candidate = read_json(args.candidate_verification)
    assert candidate["status"] == "PASS"
    assert candidate["expected_commit"] == EXPECTED_COMMIT
    assert candidate["head_before"] == candidate["head_after"] == EXPECTED_COMMIT
    assert candidate["dirty_before"] == candidate["dirty_after"] == 0
    assert candidate["focused_pytest_exit"] == 0
    assert candidate["compileall_exit"] == 0
    assert candidate["pytest_exit"] == 0

    s3_training = read_json(args.s3_training_audit)
    s3_posthoc = read_json(args.s3_posthoc_audit)
    assert s3_training["status"] == s3_posthoc["status"] == "PASS"
    assert s3_training["git_commit"] == s3_posthoc["git_commit"] == EXPECTED_S3_COMMIT
    assert s3_training["task_segments"] == s3_posthoc["task_segments"] == 10
    assert s3_posthoc["training_audit"]["sha256"] == sha256(args.s3_training_audit)

    launch = read_json(args.control / "launch.json")
    assert launch["git_head"] == EXPECTED_COMMIT
    assert launch["config_sha256"] == EXPECTED_CONFIG_SHA256
    assert launch["sole_scientific_change_from_s0"] == "data.train_augment_true_to_false"
    assert launch["sequence"] == ["s4_training"]
    assert launch["candidate_verification_sha256"] == sha256(
        args.candidate_verification
    )
    assert launch["s3_training_audit_sha256"] == sha256(args.s3_training_audit)
    assert launch["s3_posthoc_audit_sha256"] == sha256(args.s3_posthoc_audit)

    config_path = (
        args.repo
        / "configs"
        / "diagnostics"
        / "recovery"
        / "ov_orthkd_s4_no_augment_seed42.yaml"
    )
    s0_path = (
        args.repo
        / "configs"
        / "diagnostics"
        / "causal"
        / "ov_orthkd_s0_learned_concat_seed42.yaml"
    )
    assert normalized_text_sha256(config_path) == EXPECTED_CONFIG_SHA256
    s4 = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    s0 = yaml.safe_load(s0_path.read_text(encoding="utf-8"))
    assert different_paths(
        normalize_control_identity(s0), normalize_control_identity(s4)
    ) == {"data.train_augment"}
    assert s0["data"]["train_augment"] is True
    assert s4["data"]["train_augment"] is False
    assert s4["student"]["pretrained"] is False
    assert s4["data"]["num_segments"] == 10
    assert s4["student"]["max_position_segments"] == 16
    assert s4["training"]["epochs"] == 3
    assert s4["training"]["max_batches_per_epoch"] == 400
    assert s4["training"]["scheduler"]["T_max"] == 30
    assert s4["evaluation"]["test_views"] == 1
    for key in (
        "alpha_strong_logit",
        "alpha_weak_logit",
        "alpha_strong_feat",
        "alpha_weak_feat",
        "alpha_text_align",
        "alpha_orth",
    ):
        assert float(s4["loss"][key]) == 0.0

    for name in REQUIRED_OUTPUTS:
        path = args.output / name
        assert path.is_file() and path.stat().st_size > 0, name
    resolved = yaml.safe_load(
        (args.output / "resolved_config.yaml").read_text(encoding="utf-8")
    )
    config_resolved = yaml.safe_load(
        (args.output / "config_resolved.yaml").read_text(encoding="utf-8")
    )
    behavior = read_json(args.output / "implementation_behavior.json")
    assert resolved == config_resolved
    assert resolved["runtime_implementation"] == behavior
    resolved_without_runtime = copy.deepcopy(resolved)
    del resolved_without_runtime["runtime_implementation"]
    resolved_log_dir = str(resolved_without_runtime["logging"]["log_dir"])
    source_log_dir = str(s4["logging"]["log_dir"])
    assert resolved_log_dir.replace("\\", "/") == source_log_dir.replace("\\", "/")
    resolved_without_runtime["logging"]["log_dir"] = source_log_dir
    assert resolved_without_runtime == s4
    assert resolved["data"]["train_augment"] is False
    assert resolved["student"]["pretrained"] is False
    assert resolved["data"]["num_segments"] == 10
    assert resolved["student"]["max_position_segments"] == 16

    history = read_jsonl(args.output / "history.jsonl")
    diagnostics = read_jsonl(args.output / "training_diagnostics.jsonl")
    assert len(history) == len(diagnostics) == 3
    assert [record["epoch"] for record in history] == [0, 1, 2]
    assert [record["global_step"] for record in history] == [400, 800, 1200]
    assert [record["epoch"] for record in diagnostics] == [0, 1, 2]
    assert [record["batch_index"] for record in diagnostics] == [0, 0, 0]
    assert [record["global_step_before_update"] for record in diagnostics] == [0, 400, 800]
    assert_finite(history, "history")
    assert_finite(diagnostics, "training_diagnostics")
    for record in history:
        validation = record["validation"]
        assert validation["sample_count"] == EXPECTED_SPLITS["validation"][0]
        assert validation["segment_count"] == EXPECTED_SPLITS["validation"][1]

    metrics = read_json(args.output / "final_metrics.json")
    assert_finite(metrics, "final_metrics")
    assert_finite(behavior, "implementation_behavior")
    for split, (samples, segments) in EXPECTED_SPLITS.items():
        total = metrics[split]["metrics"]["total"]
        assert total["sample_count"] == samples
        assert total["segment_count"] == segments
    assert behavior["student"]["path_mode"] == "explicit_projected"
    assert behavior["student"]["fusion_mode"] == "concat_mlp_query_conditioned"
    assert behavior["student"]["gate_mode"] == "learned_softmax"

    artifact_receipts = {
        name: {
            "bytes": (args.output / name).stat().st_size,
            "sha256": sha256(args.output / name),
        }
        for name in REQUIRED_OUTPUTS
        if not name.endswith("_predictions.npz")
    }
    prediction_receipts = {
        split: audit_prediction_npz(
            args.output / f"{split}_predictions.npz", samples, segments
        )
        for split, (samples, segments) in EXPECTED_SPLITS.items()
    }
    report = {
        "schema_version": 1,
        "status": "PASS",
        "claim_level": "noncanonical_s4_training_artifact_audit",
        "git_commit": EXPECTED_COMMIT,
        "task_segments": 10,
        "max_position_segments": 16,
        "sole_scientific_change_from_s0": "data.train_augment_true_to_false",
        "worker_state": state,
        "launch": {
            "bytes": (args.control / "launch.json").stat().st_size,
            "sha256": sha256(args.control / "launch.json"),
        },
        "candidate_verification": {
            "bytes": args.candidate_verification.stat().st_size,
            "sha256": sha256(args.candidate_verification),
        },
        "s3_training_audit": {
            "bytes": args.s3_training_audit.stat().st_size,
            "sha256": sha256(args.s3_training_audit),
        },
        "s3_posthoc_audit": {
            "bytes": args.s3_posthoc_audit.stat().st_size,
            "sha256": sha256(args.s3_posthoc_audit),
        },
        "history": history,
        "final_metrics": {
            "validation_ap": metrics["validation"]["metrics"]["total"]["ap"],
            "test_ap": metrics["test"]["metrics"]["total"]["ap"],
            "test_auroc": metrics["test"]["metrics"]["total"]["auroc"],
            "test_ovavel_segment_f1_at_0_5": metrics["test"]["metrics"]["total"][
                "ovavel_segment_f1_at_0_5"
            ],
        },
        "artifacts": artifact_receipts,
        "predictions": prediction_receipts,
    }
    args.audit_output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.audit_output.with_name(args.audit_output.name + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.audit_output)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
