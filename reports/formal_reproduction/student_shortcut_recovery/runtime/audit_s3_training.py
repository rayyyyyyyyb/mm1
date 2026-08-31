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


EXPECTED_COMMIT = "a0aa4d7ad4b98455e26a2fe6ff2537a321293233"
EXPECTED_CONFIG_SHA256 = "96b98047f0ae8404a1e1fb99d0cc4934e1ed87c858766d05a2d502eb362b39e5"
EXPECTED_MODELS = {
    "visual": "convnextv2_tiny.fcmae_ft_in22k_in1k",
    "audio": "tf_efficientnetv2_b2.in1k",
}
EXPECTED_CACHE_ASSETS = {
    "visual": {
        "model": "convnextv2_tiny.fcmae_ft_in22k_in1k",
        "url": "https://dl.fbaipublicfiles.com/convnext/convnextv2/im22k/convnextv2_tiny_22k_224_ema.pt",
        "bytes": 114_604_362,
        "sha256": "853d431aa9363f1b058e3c343d4bf2fca5fe2a4196621c381ddbcd4828290a96",
    },
    "audio": {
        "model": "tf_efficientnetv2_b2.in1k",
        "url": "https://github.com/rwightman/pytorch-image-models/releases/download/v0.1-effv2-weights/tf_efficientnetv2_b2-847de54e.pth",
        "bytes": 40_795_861,
        "sha256": "847de54eb133fad3ab1230ff637ed242aefe9fd2da197d041e6753d9ec5a80bd",
    },
}
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


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise AssertionError(f"Expected JSON object: {path}")
    return payload


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
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
    assert np.array_equal(indices.reshape(samples, 10), np.tile(np.arange(10), (samples, 1)))
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


def audit_pretrained_receipt(path: Path) -> dict[str, Any]:
    receipt = read_json(path)
    assert receipt["status"] == "PASS"
    assert receipt["config"]["sha256"] == EXPECTED_CONFIG_SHA256
    assert receipt["fallback_policy"] == "construction_or_download_failure_propagates_and_blocks"
    assert set(receipt["backbones"]) == set(EXPECTED_MODELS)
    for role, model_name in EXPECTED_MODELS.items():
        backbone = receipt["backbones"][role]
        assert backbone["status"] == "PASS"
        assert backbone["model_name"] == model_name
        assert backbone["pretrained_requested"] is True
        assert backbone["random_reference_requested"] is False
        assert backbone["state_hashes_differ"] is True
        assert backbone["pretrained_state_sha256"] != backbone["random_state_sha256"]
        assert len(backbone["pretrained_state_sha256"]) == 64
        assert len(backbone["random_state_sha256"]) == 64
        assert backbone["parameter_count"] > 0 and backbone["feature_dim"] > 0
    return {
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "backbones": receipt["backbones"],
    }


def audit_official_cache_receipt(path: Path) -> dict[str, Any]:
    receipt = read_json(path)
    assert receipt["status"] == "PASS"
    assert (
        receipt["claim_level"]
        == "official_timm_1.0.28_pretrained_cfg_direct_url_cache_lock"
    )
    assert receipt["source_policy"] == "exact_url_from_locked_timm_1.0.28_pretrained_cfg"
    assert set(receipt["assets"]) == set(EXPECTED_CACHE_ASSETS)
    for role, expected in EXPECTED_CACHE_ASSETS.items():
        asset = receipt["assets"][role]
        assert asset["status"] == "PASS"
        assert asset["model"] == expected["model"]
        assert asset["url"] == expected["url"]
        assert asset["bytes"] == expected["bytes"]
        assert asset["sha256"] == expected["sha256"]
        target = Path(asset["target"])
        assert target.is_file() and target.stat().st_size == expected["bytes"]
        assert sha256(target) == expected["sha256"]
    range_receipt = Path(receipt["audio_range_receipt"]["path"])
    assert range_receipt.is_file()
    assert sha256(range_receipt) == receipt["audio_range_receipt"]["sha256"]
    return {
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "assets": receipt["assets"],
        "audio_range_receipt": receipt["audio_range_receipt"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--git", type=Path, required=True)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--official-cache-receipt", type=Path, required=True)
    args = parser.parse_args()

    assert run_git(args.git, args.repo, "rev-parse", "HEAD") == EXPECTED_COMMIT
    assert run_git(
        args.git, args.repo, "status", "--porcelain=v1", "--untracked-files=all"
    ) == ""
    state = read_json(args.control / "worker_state.json")
    assert state["status"] == "completed" and state["exit_code"] == 0
    assert state["git_commit"] == EXPECTED_COMMIT
    assert state["config_sha256"] == EXPECTED_CONFIG_SHA256
    assert state["completed_phases"] == ["pretrained_receipt", "s3_training"]

    config_path = (
        args.repo
        / "configs"
        / "diagnostics"
        / "recovery"
        / "ov_orthkd_s3_pretrained_seed42.yaml"
    )
    s0_path = (
        args.repo
        / "configs"
        / "diagnostics"
        / "causal"
        / "ov_orthkd_s0_learned_concat_seed42.yaml"
    )
    assert sha256(config_path) == EXPECTED_CONFIG_SHA256
    s3 = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    s0 = yaml.safe_load(s0_path.read_text(encoding="utf-8"))
    assert different_paths(
        normalize_control_identity(s0), normalize_control_identity(s3)
    ) == {"student.pretrained"}
    assert s0["student"]["pretrained"] is False
    assert s3["student"]["pretrained"] is True
    assert s3["data"]["num_segments"] == 10
    assert s3["student"]["max_position_segments"] == 16
    assert s3["training"]["epochs"] == 3
    assert s3["training"]["max_batches_per_epoch"] == 400
    assert s3["training"]["scheduler"]["T_max"] == 30

    for name in REQUIRED_OUTPUTS:
        path = args.output / name
        assert path.is_file() and path.stat().st_size > 0, name
    resolved = yaml.safe_load((args.output / "resolved_config.yaml").read_text(encoding="utf-8"))
    config_resolved = yaml.safe_load((args.output / "config_resolved.yaml").read_text(encoding="utf-8"))
    assert resolved == config_resolved
    assert resolved["student"]["pretrained"] is True
    assert resolved["data"]["num_segments"] == 10
    assert resolved["student"]["max_position_segments"] == 16
    assert resolved["training"]["epochs"] == 3
    assert resolved["training"]["max_batches_per_epoch"] == 400

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
    behavior = read_json(args.output / "implementation_behavior.json")
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
        "claim_level": "noncanonical_s3_training_artifact_audit",
        "git_commit": EXPECTED_COMMIT,
        "task_segments": 10,
        "max_position_segments": 16,
        "sole_scientific_change_from_s0": "student.pretrained_false_to_true",
        "worker_state": state,
        "pretrained_receipt": audit_pretrained_receipt(
            args.control / "pretrained_backbone_receipt.json"
        ),
        "official_cache_receipt": audit_official_cache_receipt(
            args.official_cache_receipt
        ),
        "history": history,
        "final_metrics": {
            "validation_ap": metrics["validation"]["metrics"]["total"]["ap"],
            "test_ap": metrics["test"]["metrics"]["total"]["ap"],
            "test_auroc": metrics["test"]["metrics"]["total"]["auroc"],
            "test_ovavel_segment_f1_at_0_5": metrics["test"]["metrics"]["total"]["ovavel_segment_f1_at_0_5"],
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
