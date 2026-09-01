#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping


EXPECTED_COMMIT = "a7f0dc06d6a98493c0d03f1caa2059e31c50b648"
CHECKPOINT_STEPS = (400, 800, 1200)
ABLATION_MODES = ("original", "visual_zero", "audio_zero", "both_zero")
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
    assert isinstance(value, dict), path
    return value


def assert_finite(value: Any, path: str = "root") -> None:
    if isinstance(value, float):
        assert math.isfinite(value), f"Non-finite value at {path}"
    elif isinstance(value, Mapping):
        for key, item in value.items():
            assert_finite(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_finite(item, f"{path}[{index}]")


def assert_close(left: Any, right: Any, *, tolerance: float = 1e-12) -> None:
    assert abs(float(left) - float(right)) <= tolerance, (left, right)


def supports_shared_encoder_cause(report: Mapping[str, Any]) -> bool:
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


def recompute_causal_decision(
    checkpoint_reports: Mapping[str, Any], best_step: int
) -> dict[str, Any]:
    step_400 = checkpoint_reports["400"]
    best = checkpoint_reports[str(best_step)]
    support_400 = supports_shared_encoder_cause(step_400)
    support_800 = supports_shared_encoder_cause(checkpoint_reports["800"])
    return {
        "criteria_source": "approved_web_review_S7_plan",
        "step_400_supports_shared_encoder_major_cause": support_400,
        "step_800_supports_shared_encoder_major_cause": support_800,
        "simultaneous_step_400_and_800_support": support_400 and support_800,
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
                step_400["causal_deltas"]["shuffle_ap_drop"] < 0.01
            ),
            "step_400_both_zero_retains_at_least_98_percent": (
                step_400["modes"]["both_zero"]["ap"]
                >= 0.98 * step_400["modes"]["original"]["ap"]
            ),
            "step_400_positive_not_above_negative": (
                step_400["label_conditioned_logits"]["positive_minus_negative"]
                <= 0.0
            ),
        },
    }


def audit_payloads(
    training: Mapping[str, Any],
    trajectory: Mapping[str, Any],
    worker_state: Mapping[str, Any],
    launch: Mapping[str, Any],
) -> dict[str, Any]:
    assert training["status"] == "PASS"
    assert training["claim_level"] == "noncanonical_s7_training_artifact_audit"
    assert training["git_commit"] == EXPECTED_COMMIT
    assert training["task_segments"] == 10
    assert training["max_position_segments"] == 16
    assert training["sole_scientific_change_from_s0"] == (
        "student.temporal_path_mode_transformer_to_identity_passthrough"
    )
    assert trajectory["status"] == "PASS"
    assert trajectory["claim_level"] == (
        "noncanonical_s7_checkpoint_trajectory_diagnostic"
    )
    assert trajectory["git_commit"] == EXPECTED_COMMIT
    assert worker_state["status"] == "completed"
    assert int(worker_state["exit_code"]) == 0
    assert worker_state["git_commit"] == EXPECTED_COMMIT
    assert worker_state["completed_phases"] == [
        "training_audit",
        "checkpoint_trajectory",
    ]
    assert launch["git_commit"] == EXPECTED_COMMIT
    assert launch["phases"] == ["training_audit", "checkpoint_trajectory"]

    protocol = trajectory["protocol"]
    assert protocol == {
        "task_segments": 10,
        "temporal_conversion": "forbidden",
        "checkpoints": list(CHECKPOINT_STEPS),
        "content_ablation_modes": list(ABLATION_MODES),
        "shuffle_repeats": 100,
        "test_views": 1,
    }
    assert trajectory["s0_reference"] == S0_REFERENCE
    best_step = int(trajectory["best_step"])
    assert best_step in CHECKPOINT_STEPS
    assert int(training["checkpoint_roles"]["best"]["global_step"]) == best_step
    checkpoint_reports = trajectory["checkpoint_reports"]
    assert set(checkpoint_reports) == {str(step) for step in CHECKPOINT_STEPS}
    training_checkpoints = training["checkpoint_trajectory"]["checkpoints"]
    assert set(training_checkpoints) == set(checkpoint_reports)

    for step in CHECKPOINT_STEPS:
        report = checkpoint_reports[str(step)]
        assert int(report["checkpoint"]["global_step"]) == step
        assert report["checkpoint"]["sha256"] == training_checkpoints[str(step)][
            "sha256"
        ]
        assert set(report["modes"]) == set(ABLATION_MODES)
        for mode in ABLATION_MODES:
            response = report["modes"][mode]
            assert int(response["sample_count"]) == 5820
            assert int(response["segment_count"]) == 58200
        original = report["modes"]["original"]
        original_ap = float(original["ap"])
        assert int(report["temporal_shuffle"]["repeats"]) == 100
        assert int(report["temporal_shuffle"]["seed"]) == 42
        assert_close(
            report["temporal_shuffle"]["student_original_ap"], original_ap
        )
        assert_close(
            report["mean_centered"]["delta_from_original"],
            float(report["mean_centered"]["ap"]) - original_ap,
        )
        assert_close(
            report["per_query"]["macro_ap"],
            original["metrics"]["per_query_macro_ap"],
        )
        expected_deltas = {
            "shuffle_ap_drop": original_ap
            - float(report["temporal_shuffle"]["ap_distribution"]["mean"]),
            "both_zero_ap_drop": original_ap
            - float(report["modes"]["both_zero"]["ap"]),
            "visual_zero_ap_drop": original_ap
            - float(report["modes"]["visual_zero"]["ap"]),
            "audio_zero_ap_drop": original_ap
            - float(report["modes"]["audio_zero"]["ap"]),
        }
        for name, value in expected_deltas.items():
            assert_close(report["causal_deltas"][name], value)
        paths = report["original_path_scales"]
        shared = float(
            paths["shared_features"]["within_sample_temporal_std_mean"]
        )
        decision = float(
            paths["decision_features"]["within_sample_temporal_std_mean"]
        )
        logits = float(paths["segment_logits"]["within_sample_temporal_std_mean"])
        expected_compression = {
            "temporal_input_shared_std": shared,
            "decision_std": decision,
            "logit_std": logits,
            "shared_to_decision_compression_factor": shared / max(decision, 1e-30),
            "shared_to_logit_compression_factor": shared / max(logits, 1e-30),
        }
        for name, value in expected_compression.items():
            assert_close(report["compression"][name], value)
        conditioned = report["label_conditioned_logits"]
        assert_close(
            conditioned["positive_minus_negative"],
            float(conditioned["positive_mean"])
            - float(conditioned["negative_mean"]),
        )

    best_ap = checkpoint_reports[str(best_step)]["modes"]["original"]["ap"]
    assert_close(best_ap, training["final_metrics"]["test_ap"])
    recomputed = recompute_causal_decision(checkpoint_reports, best_step)
    assert trajectory["causal_decision"] == recomputed
    assert_finite(training, "training")
    assert_finite(trajectory, "trajectory")
    return {
        "schema_version": 1,
        "status": "PASS",
        "claim_level": "noncanonical_s7_posthoc_artifact_audit",
        "git_commit": EXPECTED_COMMIT,
        "task_segments": 10,
        "max_position_segments": 16,
        "best_step": best_step,
        "checkpoint_steps": list(CHECKPOINT_STEPS),
        "causal_decision_recomputed": recomputed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--training-audit", type=Path, required=True)
    parser.add_argument("--trajectory", type=Path, required=True)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    temporary = args.output.with_name(args.output.name + ".tmp")
    if args.output.exists() or temporary.exists():
        raise FileExistsError("S7 posthoc audit refuses existing evidence")
    state_path = args.control / "worker_state.json"
    launch_path = args.control / "launch.json"
    report = audit_payloads(
        read_json(args.training_audit),
        read_json(args.trajectory),
        read_json(state_path),
        read_json(launch_path),
    )
    report["sources"] = {
        "auditor": {
            "bytes": Path(__file__).resolve().stat().st_size,
            "sha256": sha256(Path(__file__).resolve()),
        },
        "training_audit": {
            "bytes": args.training_audit.stat().st_size,
            "sha256": sha256(args.training_audit),
        },
        "trajectory": {
            "bytes": args.trajectory.stat().st_size,
            "sha256": sha256(args.trajectory),
        },
        "worker_state": {
            "bytes": state_path.stat().st_size,
            "sha256": sha256(state_path),
        },
        "launch": {
            "bytes": launch_path.stat().st_size,
            "sha256": sha256(launch_path),
        },
    }
    trajectory = read_json(args.trajectory)
    source = trajectory["sources"]["training_audit"]
    assert source["sha256"] == report["sources"]["training_audit"]["sha256"]
    assert int(source["bytes"]) == report["sources"]["training_audit"]["bytes"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
