from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from scripts.audit_zero_training_evidence import (
    audit_identity_ae_evidence,
    audit_zero_training_evidence,
)
from scripts.diagnose_s7_zero_training import (
    GATE_GRID,
    TIMELINE_STATE_LABELS,
    intervention_mode_names,
)
from src.utils.zero_training_diagnostics import (
    build_audio_donor_maps,
    summarize_label_strata,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _receipt(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _mapping_sha(ids: list[str], queries: list[str]) -> str:
    maps = build_audio_donor_maps(ids, queries)
    return hashlib.sha256(
        np.stack([maps["same_query"], maps["different_query"]], axis=0)
        .astype("<i8")
        .tobytes()
    ).hexdigest()


def _write_npz(path: Path, arrays: dict[str, np.ndarray]) -> None:
    with path.open("wb") as handle:
        np.savez_compressed(handle, **arrays)


def _fixture(tmp_path: Path) -> dict[str, Any]:
    ids = ["q0_a", "q0_b", "q1_a", "q1_b"]
    queries = ["q0", "q0", "q1", "q1"]
    modes = list(intervention_mode_names())
    labels = np.asarray(
        [0] * 10
        + [0, 1] * 5
        + [1] * 10
        + [1, 1, 0, 0, 1, 0, 1, 0, 1, 0],
        dtype=np.float64,
    )
    base_logits = np.linspace(-2.0, 2.0, labels.size, dtype=np.float64)
    logits = np.stack(
        [base_logits + 0.01 * index for index in range(len(modes))], axis=0
    )
    probabilities = 1.0 / (1.0 + np.exp(-logits))
    arrays = {
        "mode_names": np.asarray(modes, dtype=str),
        "ids": np.asarray(ids, dtype=str),
        "queries": np.asarray(queries, dtype=str),
        "split_types": np.asarray(["seen"] * 4, dtype=str),
        "sample_offsets": np.asarray([0, 10, 20, 30, 40], dtype=np.int64),
        "segment_indices": np.tile(np.arange(10, dtype=np.int64), 4),
        "labels": labels,
        "logits": logits,
        "probabilities": probabilities,
    }
    predictions = {
        mode: {
            "ids": arrays["ids"],
            "queries": arrays["queries"],
            "split_types": arrays["split_types"],
            "sample_offsets": arrays["sample_offsets"],
            "segment_indices": arrays["segment_indices"],
            "labels": arrays["labels"],
            "logits": arrays["logits"][index],
            "probabilities": arrays["probabilities"][index],
        }
        for index, mode in enumerate(modes)
    }
    prediction_path = tmp_path / "predictions.npz"
    _write_npz(prediction_path, arrays)
    training_path = tmp_path / "training_audit.json"
    training_path.write_text('{"status":"PASS"}\n', encoding="utf-8")
    trajectory_path = tmp_path / "trajectory.json"
    trajectory_path.write_text('{"status":"PASS"}\n', encoding="utf-8")
    config_path = tmp_path / "full.yaml"
    config_path.write_text("data:\n  num_segments: 10\n", encoding="utf-8")
    checkpoint_path = tmp_path / "full.pt"
    checkpoint_path.write_bytes(b"checkpoint-receipt-only")
    commit = "a" * 40
    ae_report = {
        "schema_version": 1,
        "status": "PASS",
        "protocol": {
            "task_segments": 10,
            "timeline_states": list(TIMELINE_STATE_LABELS),
            "zero_step_identity": "reconstructed_not_saved_checkpoint",
            "gate_grid": [list(value) for value in GATE_GRID],
            "gate_content_modes": ["original", "visual_zero"],
            "audio_modes": {
                "original": "content_original",
                "same_query_donor": "audio_same_query_donor",
                "different_query_donor": "audio_different_query_donor",
                "temporal_shuffle": "audio_temporal_shuffle",
            },
            "seed": 42,
            "shuffle_repeats": 3,
        },
        "git": {"implementation_commit": commit, "status": "clean"},
        "sources": {
            "training_audit": _receipt(training_path),
            "prediction_archive": _receipt(prediction_path),
        },
        "reconstructed_zero_step": {
            "identity": "reconstructed_zero_step",
            "saved_checkpoint_claim": False,
            "stored_global_step_before_update": 0,
        },
        "audio_donor_maps": {
            "sample_count": 4,
            "same_query": {
                "is_bijection": True,
                "query_relation_verified": True,
            },
            "different_query": {
                "is_bijection": True,
                "query_relation_verified": True,
            },
            "mapping_sha256": _mapping_sha(ids, queries),
        },
        "test_visual_content_audit": {
            "video_count": 4,
            "frame_count": 40,
            "task_segments": 10,
            "full_canonical_sha256": "c" * 64,
        },
        "intervention_mode_names": modes,
        "intervention_metrics": summarize_label_strata(
            predictions, shuffle_repeats=3, seed=42, threshold=0.5
        ),
        "mutation_guards": {
            "optimizer_constructed": False,
            "optimizer_step_executed": False,
            "checkpoint_written": False,
            "matches_best_checkpoint_loaded_state": True,
        },
    }
    source_hash = "b" * 64
    f_report = {
        "schema_version": 1,
        "status": "PASS",
        "protocol": {
            "task_segments": 10,
            "optimizer_steps_on_source": 0,
            "optimizer_steps_on_disposable_clone": 1,
            "updated_checkpoint_written": False,
        },
        "git": {"implementation_commit": commit, "status": "clean"},
        "sources": {
            "config": _receipt(config_path),
            "checkpoint": _receipt(checkpoint_path),
        },
        "probe": {
            "feature_dimension": 2,
            "mean_to_sum_expected_factor": 2.0,
            "mean_to_sum_observed_ratios": {
                "loss": 2.0,
                "projector_gradient": 2.0,
                "student_decision_gradient": 2.0,
            },
            "source_projector": {
                "state_sha256_before": source_hash,
                "state_sha256_after": source_hash,
                "gradients_remained_none": True,
            },
            "disposable_adamw_step": {
                "clone_state_changed": True,
                "decision_changed": True,
                "source_state_unchanged": True,
                "persisted": False,
                "target_variance_before": 0.1,
                "target_variance_after": 0.2,
            },
        },
    }
    training_audit = {
        "status": "PASS",
        "task_segments": 10,
    }
    trajectory = {
        "status": "PASS",
        "protocol": {"task_segments": 10},
    }
    return {
        "ae_report": ae_report,
        "prediction_path": prediction_path,
        "prediction_arrays": arrays,
        "f_report": f_report,
        "training_audit": training_audit,
        "trajectory": trajectory,
        "expected_commit": commit,
    }


def _audit(fixture: dict[str, Any]) -> dict[str, Any]:
    return audit_zero_training_evidence(
        ae_report=fixture["ae_report"],
        prediction_archive=fixture["prediction_path"],
        f_report=fixture["f_report"],
        training_audit=fixture["training_audit"],
        trajectory=fixture["trajectory"],
        expected_commit=fixture["expected_commit"],
        git_head=fixture["expected_commit"],
        git_status="",
    )


def test_valid_compact_evidence_is_independently_recomputed(tmp_path: Path) -> None:
    result = _audit(_fixture(tmp_path))

    assert result["status"] == "PASS"
    assert result["task_segments"] == 10
    assert result["prediction_archive"]["mode_count"] == 17
    assert result["independent_metrics"]["sample_count"] == 4
    assert result["claim_level"] == "artifact_integrity_only"


def test_fixed_equal_identity_ae_can_be_audited_without_reusing_full_probe(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    fixture["ae_report"]["protocol"]["expected_gate_mode"] = "fixed_equal"
    fixture["ae_report"]["claim_level"] = (
        "read_only_identity_fixed_equal_zero_near_zero_training_diagnostics"
    )

    result = audit_identity_ae_evidence(
        ae_report=fixture["ae_report"],
        prediction_archive=fixture["prediction_path"],
        training_audit=fixture["training_audit"],
        expected_commit=fixture["expected_commit"],
        expected_gate_mode="fixed_equal",
        git_head=fixture["expected_commit"],
        git_status="",
    )

    assert result["status"] == "PASS"
    assert result["expected_gate_mode"] == "fixed_equal"
    assert result["scientific_success_claimed"] is False


def test_fixed_equal_additive_ae_must_bind_the_expected_fusion_mode(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    fixture["ae_report"]["protocol"].update(
        {
            "expected_gate_mode": "fixed_equal",
            "expected_fusion_mode": "paper_additive_query_conditioned",
        }
    )
    fixture["ae_report"]["claim_level"] = (
        "read_only_identity_fixed_equal_additive_zero_near_zero_training_diagnostics"
    )

    result = audit_identity_ae_evidence(
        ae_report=fixture["ae_report"],
        prediction_archive=fixture["prediction_path"],
        training_audit=fixture["training_audit"],
        expected_commit=fixture["expected_commit"],
        expected_gate_mode="fixed_equal",
        expected_fusion_mode="paper_additive_query_conditioned",
        git_head=fixture["expected_commit"],
        git_status="",
    )

    assert result["expected_fusion_mode"] == "paper_additive_query_conditioned"
    fixture["ae_report"]["protocol"]["expected_fusion_mode"] = (
        "concat_mlp_query_conditioned"
    )
    with pytest.raises(ValueError, match="fusion mode"):
        audit_identity_ae_evidence(
            ae_report=fixture["ae_report"],
            prediction_archive=fixture["prediction_path"],
            training_audit=fixture["training_audit"],
            expected_commit=fixture["expected_commit"],
            expected_gate_mode="fixed_equal",
            expected_fusion_mode="paper_additive_query_conditioned",
            git_head=fixture["expected_commit"],
            git_status="",
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "task_segments",
        "donor_query",
        "gate_ratio",
        "concordance",
        "saved_step_zero",
        "source_sha",
        "nan",
        "persistent_clone",
    ],
)
def test_each_evidence_tamper_fails_closed(tmp_path: Path, mutation: str) -> None:
    fixture = _fixture(tmp_path)
    if mutation == "task_segments":
        fixture["ae_report"]["protocol"]["task_segments"] = 16
    elif mutation == "donor_query":
        arrays = copy.deepcopy(fixture["prediction_arrays"])
        arrays["queries"][0] = "q1"
        _write_npz(fixture["prediction_path"], arrays)
        fixture["ae_report"]["sources"]["prediction_archive"] = _receipt(
            fixture["prediction_path"]
        )
    elif mutation == "gate_ratio":
        fixture["ae_report"]["protocol"]["gate_grid"][1] = [0.2, 0.8]
    elif mutation == "concordance":
        fixture["ae_report"]["intervention_metrics"][
            "mixed_pairwise_concordance"
        ]["content_original"]["pair_weighted"] += 0.1
    elif mutation == "saved_step_zero":
        fixture["ae_report"]["reconstructed_zero_step"][
            "saved_checkpoint_claim"
        ] = True
    elif mutation == "source_sha":
        fixture["ae_report"]["sources"]["prediction_archive"]["sha256"] = "0" * 64
    elif mutation == "nan":
        arrays = copy.deepcopy(fixture["prediction_arrays"])
        arrays["logits"][0, 0] = float("nan")
        arrays["probabilities"][0, 0] = float("nan")
        _write_npz(fixture["prediction_path"], arrays)
        fixture["ae_report"]["sources"]["prediction_archive"] = _receipt(
            fixture["prediction_path"]
        )
    else:
        fixture["f_report"]["probe"]["disposable_adamw_step"]["persisted"] = True

    with pytest.raises((AssertionError, ValueError, RuntimeError)):
        _audit(fixture)
