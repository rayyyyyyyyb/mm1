#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any


EXPECTED_COMMIT = "74d211d34ace74ce3b74ea082a7dfd0379b251fb"
MODES = {"original", "visual_zero", "audio_zero", "both_zero"}
PATHS = {
    "query_features",
    "visual_tokens",
    "audio_tokens",
    "fused_tokens_before_position",
    "shared_features",
    "decision_features",
    "segment_logits",
}
EXPECTED_SPLITS = {
    "validation": (5798, 57980),
    "test": (5820, 58200),
}


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prediction", type=Path, required=True)
    parser.add_argument("--modality", type=Path, required=True)
    parser.add_argument("--training-audit", type=Path, required=True)
    parser.add_argument("--launch-receipt", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--git", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    prediction = read_json(args.prediction)
    modality = read_json(args.modality)
    training = read_json(args.training_audit)
    launch = read_json(args.launch_receipt)
    assert_finite(prediction, "prediction")
    assert_finite(modality, "modality")
    assert_finite(training, "training_audit")

    assert training["status"] == "PASS"
    assert training["git_commit"] == EXPECTED_COMMIT
    assert training["task_segments"] == 10
    assert training["sole_scientific_change_from_s0"] == (
        "data.train_augment_true_to_false"
    )
    assert launch["git_head"] == EXPECTED_COMMIT
    assert launch["s4_training_audit_sha256"] == sha256(args.training_audit)
    assert launch["sequence"] == ["prediction", "modality"]
    assert run_git(args.git, args.repo, "rev-parse", "HEAD") == EXPECTED_COMMIT
    assert run_git(
        args.git, args.repo, "status", "--porcelain=v1", "--untracked-files=all"
    ) == ""

    assert prediction["status"] == "PASS"
    assert prediction["metric_claim"] == "diagnostic_global_segment_micro_ap"
    assert prediction["protocol"] == {
        "task_segments": 10,
        "temporal_conversion": "forbidden",
        "prior_estimator": "empirical_training_segment_frequency",
        "prior_smoothing": "none",
        "shuffle_repeats": 100,
        "shuffle_seed": 42,
    }
    for split in EXPECTED_SPLITS:
        assert prediction["sources"][split]["sha256"] == training["predictions"][
            split
        ]["sha256"]

    assert modality["status"] == "PASS"
    assert modality["claim_level"] == "noncanonical_posthoc_checkpoint_diagnostic"
    assert modality["protocol"]["task_segments"] == 10
    assert modality["protocol"]["temporal_conversion"] == "forbidden"
    assert set(modality["protocol"]["ablation_modes"]) == MODES
    assert modality["sources"]["checkpoint"]["sha256"] == training["artifacts"][
        "best.pt"
    ]["sha256"]
    assert modality["sources"]["resolved_config"]["sha256"] == training[
        "artifacts"
    ]["resolved_config.yaml"]["sha256"]
    assert modality["state_loading"]["strict"] is True
    assert modality["state_loading"]["missing_keys"] == []
    assert modality["state_loading"]["unexpected_keys"] == []
    assert modality["state_loading"]["resolved_config_canonical_sha256"] == modality[
        "state_loading"
    ]["checkpoint_config_canonical_sha256"]
    assert modality["git"]["head"]["stdout"] == EXPECTED_COMMIT
    assert modality["git"]["status"]["stdout"] == ""

    for split, (samples, segments) in EXPECTED_SPLITS.items():
        assert prediction[split]["sample_count"] == samples
        assert prediction[split]["segment_count"] == segments
        assert prediction[split]["temporal_shuffle"]["repeats"] == 100
        assert prediction[split]["temporal_shuffle"]["seed"] == 42
        assert prediction[split]["mean_centered_student"][
            "within_sample_logit_mean_max_abs"
        ] < 1e-10
        assert set(modality["splits"][split]["modes"]) == MODES
        assert set(modality["splits"][split]["original_path_scales"]) == PATHS
        for mode in MODES:
            response = modality["splits"][split]["modes"][mode]
            assert response["sample_count"] == samples
            assert response["segment_count"] == segments
        for receipt in modality["splits"][split]["original_path_scales"].values():
            assert receipt["valid_rows"] == segments
            assert receipt["temporal_sample_count"] == samples

        training_ap = training["final_metrics"][f"{split}_ap"]
        prediction_ap = prediction[split]["student_original_ap"]
        modality_ap = modality["splits"][split]["modes"]["original"]["ap"]
        assert abs(training_ap - prediction_ap) < 1e-12
        assert abs(training_ap - modality_ap) < 1e-12

    report = {
        "schema_version": 1,
        "status": "PASS",
        "claim_level": "noncanonical_s4_posthoc_artifact_audit",
        "git_commit": EXPECTED_COMMIT,
        "task_segments": 10,
        "training_audit": {
            "bytes": args.training_audit.stat().st_size,
            "sha256": sha256(args.training_audit),
        },
        "launch": {
            "bytes": args.launch_receipt.stat().st_size,
            "sha256": sha256(args.launch_receipt),
        },
        "prediction": {
            "bytes": args.prediction.stat().st_size,
            "sha256": sha256(args.prediction),
        },
        "modality": {
            "bytes": args.modality.stat().st_size,
            "sha256": sha256(args.modality),
        },
        "test": {
            "original_ap": prediction["test"]["student_original_ap"],
            "query_only_prior_ap": prediction["test"]["query_only_prior"]["ap"],
            "query_position_prior_ap": prediction["test"]["query_position_prior"][
                "ap"
            ],
            "mean_centered_ap": prediction["test"]["mean_centered_student"]["ap"],
            "shuffle_mean_ap": prediction["test"]["temporal_shuffle"][
                "ap_distribution"
            ]["mean"],
            "original_within_sample_std": modality["splits"]["test"]["modes"][
                "original"
            ]["within_sample_logit_std"]["mean"],
            "visual_zero_ap": modality["splits"]["test"]["modes"]["visual_zero"][
                "ap"
            ],
            "audio_zero_ap": modality["splits"]["test"]["modes"]["audio_zero"][
                "ap"
            ],
            "both_zero_ap": modality["splits"]["test"]["modes"]["both_zero"][
                "ap"
            ],
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
