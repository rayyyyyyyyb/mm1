from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from audit_s7_posthoc import audit_payloads, main


COMMIT = "a7f0dc06d6a98493c0d03f1caa2059e31c50b648"


def _step_report(step: int, original_ap: float) -> dict:
    modes = {}
    for mode, ap in {
        "original": original_ap,
        "visual_zero": original_ap - 0.01,
        "audio_zero": original_ap - 0.02,
        "both_zero": original_ap - 0.04,
    }.items():
        modes[mode] = {
            "sample_count": 5820,
            "segment_count": 58200,
            "ap": ap,
            "predicted_positive_rate": 0.9,
            "within_sample_logit_std": {"mean": 0.02},
            "metrics": {"per_query_macro_ap": 0.66},
        }
    return {
        "checkpoint": {
            "global_step": step,
            "sha256": f"checkpoint-{step}",
        },
        "modes": modes,
        "original_path_scales": {
            "shared_features": {"within_sample_temporal_std_mean": 0.2},
            "decision_features": {"within_sample_temporal_std_mean": 0.1},
            "segment_logits": {"within_sample_temporal_std_mean": 0.02},
        },
        "label_conditioned_logits": {
            "positive_mean": 0.4,
            "negative_mean": 0.1,
            "positive_minus_negative": 0.3,
        },
        "mean_centered": {
            "ap": 0.65,
            "delta_from_original": 0.65 - original_ap,
        },
        "per_query": {"macro_ap": 0.66},
        "temporal_shuffle": {
            "repeats": 100,
            "seed": 42,
            "student_original_ap": original_ap,
            "ap_distribution": {"mean": original_ap - 0.03},
        },
        "causal_deltas": {
            "shuffle_ap_drop": 0.03,
            "both_zero_ap_drop": 0.04,
            "visual_zero_ap_drop": 0.01,
            "audio_zero_ap_drop": 0.02,
        },
        "compression": {
            "temporal_input_shared_std": 0.2,
            "decision_std": 0.1,
            "logit_std": 0.02,
            "shared_to_decision_compression_factor": 2.0,
            "shared_to_logit_compression_factor": 10.0,
        },
    }


def _payloads() -> tuple[dict, dict, dict, dict]:
    reports = {str(step): _step_report(step, 0.75) for step in (400, 800, 1200)}
    training = {
        "status": "PASS",
        "claim_level": "noncanonical_s7_training_artifact_audit",
        "git_commit": COMMIT,
        "task_segments": 10,
        "max_position_segments": 16,
        "sole_scientific_change_from_s0": (
            "student.temporal_path_mode_transformer_to_identity_passthrough"
        ),
        "final_metrics": {"test_ap": 0.75},
        "checkpoint_trajectory": {
            "checkpoints": {
                str(step): {"sha256": f"checkpoint-{step}"}
                for step in (400, 800, 1200)
            }
        },
        "checkpoint_roles": {"best": {"global_step": 800}},
    }
    trajectory = {
        "status": "PASS",
        "claim_level": "noncanonical_s7_checkpoint_trajectory_diagnostic",
        "git_commit": COMMIT,
        "protocol": {
            "task_segments": 10,
            "temporal_conversion": "forbidden",
            "checkpoints": [400, 800, 1200],
            "content_ablation_modes": [
                "original",
                "visual_zero",
                "audio_zero",
                "both_zero",
            ],
            "shuffle_repeats": 100,
            "test_views": 1,
        },
        "s0_reference": {
            "global_test_ap": 0.7487446823980081,
            "mean_centered_test_ap": 0.6376356327985894,
            "per_query_macro_test_ap": 0.6243702016586737,
        },
        "best_step": 800,
        "checkpoint_reports": reports,
        "causal_decision": {
            "criteria_source": "approved_web_review_S7_plan",
            "step_400_supports_shared_encoder_major_cause": True,
            "step_800_supports_shared_encoder_major_cause": True,
            "simultaneous_step_400_and_800_support": True,
            "stronger_recovery_at_best": {
                "predicted_positive_rate_below_0_98": True,
                "centered_ap_above_s0": True,
                "per_query_macro_ap_above_s0": True,
            },
            "failure_signals": {
                "step_400_shuffle_drop_below_0_01": False,
                "step_400_both_zero_retains_at_least_98_percent": False,
                "step_400_positive_not_above_negative": False,
            },
        },
    }
    state = {
        "status": "completed",
        "exit_code": 0,
        "git_commit": COMMIT,
        "completed_phases": ["training_audit", "checkpoint_trajectory"],
    }
    launch = {
        "status": "running",
        "git_commit": COMMIT,
        "phases": ["training_audit", "checkpoint_trajectory"],
    }
    return training, trajectory, state, launch


class S7PosthocAuditTests(unittest.TestCase):
    def test_accepts_internally_consistent_payloads(self) -> None:
        report = audit_payloads(*_payloads())
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(
            report["causal_decision_recomputed"][
                "simultaneous_step_400_and_800_support"
            ]
        )

    def test_rejects_tampered_causal_delta(self) -> None:
        training, trajectory, state, launch = _payloads()
        altered = copy.deepcopy(trajectory)
        altered["checkpoint_reports"]["400"]["causal_deltas"][
            "both_zero_ap_drop"
        ] = 0.5
        with self.assertRaises(AssertionError):
            audit_payloads(training, altered, state, launch)

    def test_rejects_tampered_scientific_decision(self) -> None:
        training, trajectory, state, launch = _payloads()
        altered = copy.deepcopy(trajectory)
        altered["causal_decision"][
            "step_400_supports_shared_encoder_major_cause"
        ] = False
        with self.assertRaises(AssertionError):
            audit_payloads(training, altered, state, launch)

    def test_rejects_wrong_task_timeline(self) -> None:
        training, trajectory, state, launch = _payloads()
        altered = copy.deepcopy(trajectory)
        altered["protocol"]["task_segments"] = 16
        with self.assertRaises(AssertionError):
            audit_payloads(training, altered, state, launch)

    def test_cli_refuses_to_overwrite_existing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "audit.json"
            output.write_text("existing evidence\n", encoding="utf-8")
            arguments = [
                "audit_s7_posthoc.py",
                "--training-audit",
                str(Path(directory) / "missing-training.json"),
                "--trajectory",
                str(Path(directory) / "missing-trajectory.json"),
                "--control",
                directory,
                "--output",
                str(output),
            ]
            with mock.patch.object(sys, "argv", arguments):
                with self.assertRaisesRegex(
                    FileExistsError, "refuses existing evidence"
                ):
                    main()
            self.assertEqual(output.read_text(encoding="utf-8"), "existing evidence\n")


if __name__ == "__main__":
    unittest.main()
