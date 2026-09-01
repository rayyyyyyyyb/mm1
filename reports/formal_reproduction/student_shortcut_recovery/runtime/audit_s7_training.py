#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import gc
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import torch
import yaml


EXPECTED_COMMIT = "a7f0dc06d6a98493c0d03f1caa2059e31c50b648"
EXPECTED_CONFIG_SHA256 = (
    "26e3f21504d7ce3f9a5498b8c89073fc910db80cbdf058c4b6a397b8735518b6"
)
EXPECTED_S4_COMMIT = "74d211d34ace74ce3b74ea082a7dfd0379b251fb"
EXPECTED_SPLITS = {
    "validation": (5798, 57980),
    "test": (5820, 58200),
}
CHECKPOINT_STEPS = (400, 800, 1200)
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
    "diagnostic_checkpoints/step_000400.pt",
    "diagnostic_checkpoints/step_000800.pt",
    "diagnostic_checkpoints/step_001200.pt",
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
        assert line.strip(), f"Blank JSONL line {line_number}: {path}"
        value = json.loads(line)
        assert isinstance(value, dict), f"Expected object at line {line_number}"
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


def normalize_scientific_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(config)
    normalized["reproduction"]["variant"] = "NORMALIZED"
    normalized["logging"]["log_dir"] = "NORMALIZED"
    normalized["student"].setdefault("temporal_path_mode", "transformer")
    normalized["logging"]["training_diagnostics"].pop("checkpoint_steps", None)
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
    assert np.array_equal(
        indices.reshape(samples, 10), np.tile(np.arange(10), (samples, 1))
    )
    labels = arrays["labels"].astype(np.float64, copy=False).reshape(-1)
    logits = arrays["logits"].astype(np.float64, copy=False).reshape(-1)
    probabilities = arrays["probabilities"].astype(np.float64, copy=False).reshape(-1)
    assert labels.size == logits.size == probabilities.size == segments
    assert np.isin(labels, (0.0, 1.0)).all()
    assert np.isfinite(logits).all() and np.isfinite(probabilities).all()
    assert np.allclose(
        probabilities,
        1.0 / (1.0 + np.exp(-logits)),
        rtol=1e-7,
        atol=1e-8,
    )
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


def state_dict_sha256(state: Mapping[str, torch.Tensor]) -> str:
    digest = hashlib.sha256()
    for name, tensor in sorted(state.items()):
        value = tensor.detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(value.dtype).encode("ascii"))
        digest.update(json.dumps(list(value.shape)).encode("ascii"))
        digest.update(value.numpy().tobytes(order="C"))
    return digest.hexdigest()


def audit_checkpoint_trajectory(
    output: Path, source_config: dict[str, Any]
) -> tuple[dict[str, Any], dict[int, str]]:
    reference_temporal: dict[str, torch.Tensor] | None = None
    previous_head_weight: torch.Tensor | None = None
    head_changed = False
    state_hashes: dict[int, str] = {}
    receipts: dict[str, Any] = {}
    fingerprint_sha: str | None = None
    for step in CHECKPOINT_STEPS:
        path = output / "diagnostic_checkpoints" / f"step_{step:06d}.pt"
        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
        assert checkpoint["global_step"] == step
        assert checkpoint["epoch"] == step // 400 - 1
        assert checkpoint["config"] == source_config
        assert checkpoint["runtime_implementation"]["student"][
            "temporal_path_mode"
        ] == "identity_passthrough"
        fingerprint = checkpoint["reproduction_fingerprint"]
        assert isinstance(fingerprint, dict) and isinstance(
            fingerprint.get("sha256"), str
        )
        if fingerprint_sha is None:
            fingerprint_sha = fingerprint["sha256"]
        assert fingerprint["sha256"] == fingerprint_sha
        state = checkpoint["student_state_dict"]
        assert isinstance(state, dict) and state
        assert all(torch.isfinite(value).all() for value in state.values())
        temporal = {
            name: value.detach().cpu()
            for name, value in state.items()
            if name.startswith("temporal_encoder.")
        }
        assert temporal
        if reference_temporal is None:
            reference_temporal = {name: value.clone() for name, value in temporal.items()}
        else:
            assert temporal.keys() == reference_temporal.keys()
            for name, value in temporal.items():
                assert torch.equal(value, reference_temporal[name]), name
        head_weight = state["segment_head.weight"].detach().cpu()
        if previous_head_weight is not None and not torch.equal(
            head_weight, previous_head_weight
        ):
            head_changed = True
        previous_head_weight = head_weight.clone()
        state_hash = state_dict_sha256(state)
        state_hashes[step] = state_hash
        receipts[str(step)] = {
            "path": str(path.resolve()),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "epoch": checkpoint["epoch"],
            "global_step": checkpoint["global_step"],
            "student_state_sha256": state_hash,
            "fingerprint_sha256": fingerprint["sha256"],
        }
        del checkpoint, state, temporal
        gc.collect()
    assert head_changed, "active segment head did not change across S7 checkpoints"
    assert reference_temporal is not None
    return (
        {
            "checkpoints": receipts,
            "temporal_encoder_tensor_count": len(reference_temporal),
            "temporal_encoder_unchanged_across_steps": True,
            "active_segment_head_changed_across_steps": True,
            "fingerprint_sha256": fingerprint_sha,
        },
        state_hashes,
    )


def checkpoint_role_receipt(
    path: Path, expected_config: dict[str, Any], trajectory_hashes: Mapping[int, str]
) -> dict[str, Any]:
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    step = int(checkpoint["global_step"])
    assert step in trajectory_hashes
    assert checkpoint["config"] == expected_config
    state_hash = state_dict_sha256(checkpoint["student_state_dict"])
    assert state_hash == trajectory_hashes[step]
    result = {
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "epoch": int(checkpoint["epoch"]),
        "global_step": step,
        "student_state_sha256": state_hash,
        "matches_diagnostic_step": step,
    }
    del checkpoint
    gc.collect()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--git", type=Path, required=True)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--candidate-verification", type=Path, required=True)
    parser.add_argument("--s4-training-audit", type=Path, required=True)
    parser.add_argument("--s4-posthoc-audit", type=Path, required=True)
    args = parser.parse_args()

    assert run_git(args.git, args.repo, "rev-parse", "HEAD") == EXPECTED_COMMIT
    assert (
        run_git(args.git, args.repo, "status", "--porcelain=v1", "--untracked-files=all")
        == ""
    )
    state = read_json(args.control / "worker_state.json")
    assert state["status"] == "completed" and state["exit_code"] == 0
    assert state["git_commit"] == EXPECTED_COMMIT
    assert state["config_sha256"] == EXPECTED_CONFIG_SHA256
    assert state["completed_phases"] == ["s7_training"]

    candidate = read_json(args.candidate_verification)
    assert candidate["status"] == "PASS"
    assert candidate["commit_before"] == candidate["commit_after"] == EXPECTED_COMMIT
    assert candidate["dirty_before"] == candidate["dirty_after"] == 0
    assert candidate["compileall_exit"] == candidate["pytest_exit"] == 0
    s4_training = read_json(args.s4_training_audit)
    s4_posthoc = read_json(args.s4_posthoc_audit)
    assert s4_training["status"] == s4_posthoc["status"] == "PASS"
    assert s4_training["git_commit"] == s4_posthoc["git_commit"] == EXPECTED_S4_COMMIT
    assert s4_training["task_segments"] == s4_posthoc["task_segments"] == 10

    launch = read_json(args.control / "launch.json")
    assert launch["git_head"] == EXPECTED_COMMIT
    assert launch["config_sha256"] == EXPECTED_CONFIG_SHA256
    assert launch["sole_scientific_change_from_s0"] == (
        "student.temporal_path_mode_transformer_to_identity_passthrough"
    )
    assert launch["sequence"] == ["s7_training"]
    assert launch["candidate_verification_sha256"] == sha256(
        args.candidate_verification
    )
    assert launch["s4_training_audit_sha256"] == sha256(args.s4_training_audit)
    assert launch["s4_posthoc_audit_sha256"] == sha256(args.s4_posthoc_audit)

    config_path = (
        args.repo
        / "configs"
        / "diagnostics"
        / "recovery"
        / "ov_orthkd_s7_temporal_identity_seed42.yaml"
    )
    s0_path = (
        args.repo
        / "configs"
        / "diagnostics"
        / "causal"
        / "ov_orthkd_s0_learned_concat_seed42.yaml"
    )
    assert normalized_text_sha256(config_path) == EXPECTED_CONFIG_SHA256
    s7 = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    s0 = yaml.safe_load(s0_path.read_text(encoding="utf-8"))
    assert different_paths(
        normalize_scientific_config(s0), normalize_scientific_config(s7)
    ) == {"student.temporal_path_mode"}
    assert s7["student"]["temporal_path_mode"] == "identity_passthrough"
    assert s7["data"]["num_segments"] == 10
    assert s7["student"]["max_position_segments"] == 16
    assert s7["student"]["pretrained"] is False
    assert s7["data"]["train_augment"] is True
    assert s7["training"]["epochs"] == 3
    assert s7["training"]["max_batches_per_epoch"] == 400
    assert s7["training"]["scheduler"]["T_max"] == 30
    assert s7["evaluation"]["test_views"] == 1
    assert s7["logging"]["training_diagnostics"]["checkpoint_steps"] == [
        400,
        800,
        1200,
    ]
    for key in (
        "alpha_strong_logit",
        "alpha_weak_logit",
        "alpha_strong_feat",
        "alpha_weak_feat",
        "alpha_text_align",
        "alpha_orth",
    ):
        assert float(s7["loss"][key]) == 0.0

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
    source_log_dir = str(s7["logging"]["log_dir"])
    assert resolved_log_dir.replace("\\", "/") == source_log_dir.replace("\\", "/")
    resolved_without_runtime["logging"]["log_dir"] = source_log_dir
    assert resolved_without_runtime == s7
    assert behavior["student"]["path_mode"] == "explicit_projected"
    assert behavior["student"]["fusion_mode"] == "concat_mlp_query_conditioned"
    assert behavior["student"]["gate_mode"] == "learned_softmax"
    assert behavior["student"]["temporal_path_mode"] == "identity_passthrough"

    history = read_jsonl(args.output / "history.jsonl")
    diagnostics = read_jsonl(args.output / "training_diagnostics.jsonl")
    assert len(history) == len(diagnostics) == 3
    assert [record["epoch"] for record in history] == [0, 1, 2]
    assert [record["global_step"] for record in history] == list(CHECKPOINT_STEPS)
    assert [record["global_step_before_update"] for record in diagnostics] == [0, 400, 800]
    assert all(
        float(record["gradient_l2_before_clip"]["student_temporal_encoder"]) == 0.0
        for record in diagnostics
    )
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

    trajectory, trajectory_hashes = audit_checkpoint_trajectory(args.output, resolved)
    checkpoint_roles = {
        role: checkpoint_role_receipt(
            args.output / f"{role}.pt", resolved, trajectory_hashes
        )
        for role in ("best", "last")
    }
    assert checkpoint_roles["last"]["global_step"] == 1200
    artifact_receipts = {
        name: {"bytes": (args.output / name).stat().st_size, "sha256": sha256(args.output / name)}
        for name in REQUIRED_OUTPUTS
        if not name.endswith("_predictions.npz") and not name.endswith(".pt")
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
        "claim_level": "noncanonical_s7_training_artifact_audit",
        "git_commit": EXPECTED_COMMIT,
        "task_segments": 10,
        "max_position_segments": 16,
        "sole_scientific_change_from_s0": (
            "student.temporal_path_mode_transformer_to_identity_passthrough"
        ),
        "worker_state": state,
        "launch": {
            "bytes": (args.control / "launch.json").stat().st_size,
            "sha256": sha256(args.control / "launch.json"),
        },
        "candidate_verification": {
            "bytes": args.candidate_verification.stat().st_size,
            "sha256": sha256(args.candidate_verification),
        },
        "prior_audits": {
            "s4_training_sha256": sha256(args.s4_training_audit),
            "s4_posthoc_sha256": sha256(args.s4_posthoc_audit),
        },
        "history": history,
        "training_diagnostics": diagnostics,
        "final_metrics": {
            "validation_ap": metrics["validation"]["metrics"]["total"]["ap"],
            "test_ap": metrics["test"]["metrics"]["total"]["ap"],
            "test_auroc": metrics["test"]["metrics"]["total"]["auroc"],
            "test_ovavel_segment_f1_at_0_5": metrics["test"]["metrics"]["total"][
                "ovavel_segment_f1_at_0_5"
            ],
        },
        "checkpoint_trajectory": trajectory,
        "checkpoint_roles": checkpoint_roles,
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
