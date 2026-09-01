#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.diagnose_s7_zero_training import (  # noqa: E402
    GATE_GRID,
    TIMELINE_STATE_LABELS,
    intervention_mode_names,
)
from src.utils.zero_training_diagnostics import (  # noqa: E402
    build_audio_donor_maps,
    summarize_label_strata,
    validate_t10_predictions,
)


TASK_SEGMENTS = 10
EXPECTED_AUDIO_MODES = {
    "original": "content_original",
    "same_query_donor": "audio_same_query_donor",
    "different_query_donor": "audio_different_query_donor",
    "temporal_shuffle": "audio_temporal_shuffle",
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_receipt(path: Path) -> dict[str, Any]:
    source = path.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    return {
        "path": str(source),
        "bytes": source.stat().st_size,
        "sha256": _sha256_file(source),
    }


def _assert_finite_json(value: Any, location: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            _assert_finite_json(child, f"{location}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_finite_json(child, f"{location}[{index}]")
    elif isinstance(value, (float, np.floating)) and not math.isfinite(float(value)):
        raise ValueError(f"Non-finite JSON number at {location}")


def _verify_source_receipts(value: Any, location: str = "sources") -> int:
    if not isinstance(value, Mapping):
        return 0
    if {"path", "bytes", "sha256"}.issubset(value):
        path = Path(str(value["path"])).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Receipt source is missing at {location}: {path}")
        if int(value["bytes"]) != path.stat().st_size:
            raise ValueError(f"Receipt byte count mismatch at {location}")
        actual = _sha256_file(path)
        expected = str(value["sha256"])
        if len(expected) != 64 or actual != expected:
            raise ValueError(f"Receipt SHA256 mismatch at {location}")
        return 1
    return sum(
        _verify_source_receipts(child, f"{location}.{key}")
        for key, child in value.items()
        if isinstance(child, Mapping)
    )


def _load_prediction_archive(path: Path) -> dict[str, Any]:
    with np.load(path, allow_pickle=False) as archive:
        required = {
            "mode_names",
            "ids",
            "queries",
            "split_types",
            "sample_offsets",
            "segment_indices",
            "labels",
            "logits",
            "probabilities",
        }
        if set(archive.files) != required:
            raise ValueError(
                f"Prediction archive fields differ: {sorted(archive.files)}"
            )
        arrays = {name: np.asarray(archive[name]) for name in archive.files}
    modes = arrays["mode_names"].astype(str).reshape(-1).tolist()
    expected_modes = list(intervention_mode_names())
    if modes != expected_modes or len(set(modes)) != len(modes):
        raise ValueError("Prediction archive mode set/order is not exact")
    logits = np.asarray(arrays["logits"], dtype=np.float64)
    probabilities = np.asarray(arrays["probabilities"], dtype=np.float64)
    total_segments = int(np.asarray(arrays["labels"]).size)
    expected_shape = (len(modes), total_segments)
    if logits.shape != expected_shape or probabilities.shape != expected_shape:
        raise ValueError("Prediction archive mode score matrices have invalid shape")
    predictions: dict[str, dict[str, np.ndarray]] = {}
    common = {
        name: arrays[name]
        for name in (
            "ids",
            "queries",
            "split_types",
            "sample_offsets",
            "segment_indices",
            "labels",
        )
    }
    for index, mode in enumerate(modes):
        payload = {
            **common,
            "logits": logits[index],
            "probabilities": probabilities[index],
        }
        validate_t10_predictions(payload)
        predictions[mode] = payload
    return {
        "modes": modes,
        "arrays": arrays,
        "predictions": predictions,
    }


def _assert_equal(
    expected: Any,
    actual: Any,
    *,
    location: str,
    tolerance: float = 1e-12,
) -> None:
    if isinstance(expected, Mapping) and isinstance(actual, Mapping):
        if set(expected) != set(actual):
            raise ValueError(f"Mapping keys differ at {location}")
        for key in expected:
            _assert_equal(
                expected[key],
                actual[key],
                location=f"{location}.{key}",
                tolerance=tolerance,
            )
        return
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            raise ValueError(f"List length differs at {location}")
        for index, (left, right) in enumerate(zip(expected, actual)):
            _assert_equal(
                left,
                right,
                location=f"{location}[{index}]",
                tolerance=tolerance,
            )
        return
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if not isinstance(actual, (int, float)) or isinstance(actual, bool):
            raise ValueError(f"Numeric type differs at {location}")
        if not math.isclose(
            float(expected), float(actual), rel_tol=tolerance, abs_tol=tolerance
        ):
            raise ValueError(f"Numeric value differs at {location}")
        return
    if expected != actual:
        raise ValueError(f"Value differs at {location}")


def _donor_mapping_sha256(ids: Sequence[str], queries: Sequence[str]) -> str:
    donor_maps = build_audio_donor_maps(ids, queries)
    return hashlib.sha256(
        np.stack(
            [donor_maps["same_query"], donor_maps["different_query"]], axis=0
        )
        .astype("<i8")
        .tobytes()
    ).hexdigest()


def _validate_ae_structure(
    ae_report: Mapping[str, Any], archive: Mapping[str, Any]
) -> None:
    if ae_report.get("status") != "PASS":
        raise ValueError("A-E report is not PASS")
    protocol = ae_report.get("protocol")
    if not isinstance(protocol, Mapping):
        raise ValueError("A-E protocol is missing")
    if int(protocol.get("task_segments", -1)) != TASK_SEGMENTS:
        raise ValueError("A-E protocol is not official T=10")
    if protocol.get("timeline_states") != list(TIMELINE_STATE_LABELS):
        raise ValueError("A-E timeline state labels/order changed")
    if protocol.get("zero_step_identity") != "reconstructed_not_saved_checkpoint":
        raise ValueError("A-E protocol misstates zero-step identity")
    if protocol.get("gate_grid") != [list(value) for value in GATE_GRID]:
        raise ValueError("A-E forced gate grid changed")
    if protocol.get("gate_content_modes") != ["original", "visual_zero"]:
        raise ValueError("A-E gate content mode set changed")
    if protocol.get("audio_modes") != EXPECTED_AUDIO_MODES:
        raise ValueError("A-E audio intervention mode mapping changed")
    if ae_report.get("intervention_mode_names") != list(intervention_mode_names()):
        raise ValueError("A-E report intervention mode list changed")
    zero_step = ae_report.get("reconstructed_zero_step")
    if (
        not isinstance(zero_step, Mapping)
        or zero_step.get("identity") != "reconstructed_zero_step"
        or zero_step.get("saved_checkpoint_claim") is not False
        or int(zero_step.get("stored_global_step_before_update", -1)) != 0
    ):
        raise ValueError("A-E zero-step provenance is invalid")
    guards = ae_report.get("mutation_guards")
    if not isinstance(guards, Mapping) or guards.get(
        "matches_best_checkpoint_loaded_state"
    ) is not True:
        raise ValueError("A-E student mutation guard failed")
    if any(
        guards.get(name) is not False
        for name in (
            "optimizer_constructed",
            "optimizer_step_executed",
            "checkpoint_written",
        )
    ):
        raise ValueError("A-E report claims a forbidden mutation")
    visual = ae_report.get("test_visual_content_audit")
    if not isinstance(visual, Mapping):
        raise ValueError("A-E full visual content audit is missing")
    video_count = int(visual.get("video_count", -1))
    if (
        int(visual.get("task_segments", -1)) != TASK_SEGMENTS
        or int(visual.get("frame_count", -1)) != video_count * TASK_SEGMENTS
        or len(str(visual.get("full_canonical_sha256", ""))) != 64
    ):
        raise ValueError("A-E full visual content audit is malformed")

    arrays = archive["arrays"]
    ids = arrays["ids"].astype(str).reshape(-1).tolist()
    queries = arrays["queries"].astype(str).reshape(-1).tolist()
    donor = ae_report.get("audio_donor_maps")
    if not isinstance(donor, Mapping) or int(donor.get("sample_count", -1)) != len(ids):
        raise ValueError("A-E donor receipt sample count changed")
    for name in ("same_query", "different_query"):
        relation = donor.get(name)
        if not isinstance(relation, Mapping) or any(
            relation.get(field) is not True
            for field in ("is_bijection", "query_relation_verified")
        ):
            raise ValueError(f"A-E donor relation failed: {name}")
    if donor.get("mapping_sha256") != _donor_mapping_sha256(ids, queries):
        raise ValueError("A-E donor map/query receipt disagrees with prediction archive")


def _validate_f_structure(f_report: Mapping[str, Any]) -> None:
    if f_report.get("status") != "PASS":
        raise ValueError("F report is not PASS")
    protocol = f_report.get("protocol")
    if not isinstance(protocol, Mapping) or int(
        protocol.get("task_segments", -1)
    ) != TASK_SEGMENTS:
        raise ValueError("F protocol is not official T=10")
    if (
        int(protocol.get("optimizer_steps_on_source", -1)) != 0
        or int(protocol.get("optimizer_steps_on_disposable_clone", -1)) != 1
        or protocol.get("updated_checkpoint_written") is not False
    ):
        raise ValueError("F protocol violates disposable-clone boundary")
    probe = f_report.get("probe")
    if not isinstance(probe, Mapping):
        raise ValueError("F probe payload is missing")
    feature_dimension = int(probe.get("feature_dimension", -1))
    expected_factor = float(probe.get("mean_to_sum_expected_factor", float("nan")))
    ratios = probe.get("mean_to_sum_observed_ratios")
    if feature_dimension < 1 or not math.isclose(
        expected_factor, float(feature_dimension), rel_tol=0.0, abs_tol=0.0
    ):
        raise ValueError("F mean/sum expected factor is invalid")
    if not isinstance(ratios, Mapping) or any(
        not math.isclose(
            float(ratios.get(name, float("nan"))),
            float(feature_dimension),
            rel_tol=1e-9,
            abs_tol=1e-10,
        )
        for name in ("loss", "projector_gradient", "student_decision_gradient")
    ):
        raise ValueError("F mean/sum observed ratios are invalid")
    source = probe.get("source_projector")
    if (
        not isinstance(source, Mapping)
        or source.get("state_sha256_before") != source.get("state_sha256_after")
        or source.get("gradients_remained_none") is not True
    ):
        raise ValueError("F source projector was mutated")
    disposable = probe.get("disposable_adamw_step")
    if (
        not isinstance(disposable, Mapping)
        or disposable.get("clone_state_changed") is not True
        or disposable.get("decision_changed") is not True
        or disposable.get("source_state_unchanged") is not True
        or disposable.get("persisted") is not False
    ):
        raise ValueError("F disposable clone receipt is invalid")


def audit_zero_training_evidence(
    *,
    ae_report: Mapping[str, Any],
    prediction_archive: str | Path,
    f_report: Mapping[str, Any],
    training_audit: Mapping[str, Any],
    trajectory: Mapping[str, Any],
    expected_commit: str,
    git_head: str,
    git_status: str,
) -> dict[str, Any]:
    for name, value in (
        ("ae_report", ae_report),
        ("f_report", f_report),
        ("training_audit", training_audit),
        ("trajectory", trajectory),
    ):
        _assert_finite_json(value, name)
    if len(expected_commit) != 40 or git_head != expected_commit or git_status != "":
        raise ValueError("Evidence repository commit/status is not exact and clean")
    for report_name, report in (("A-E", ae_report), ("F", f_report)):
        git = report.get("git")
        if (
            not isinstance(git, Mapping)
            or git.get("implementation_commit") != expected_commit
            or git.get("status") != "clean"
        ):
            raise ValueError(f"{report_name} implementation commit/status mismatch")
    if training_audit.get("status") != "PASS" or int(
        training_audit.get("task_segments", -1)
    ) != TASK_SEGMENTS:
        raise ValueError("S7 training audit is not PASS T=10")
    trajectory_protocol = trajectory.get("protocol")
    if (
        trajectory.get("status") != "PASS"
        or not isinstance(trajectory_protocol, Mapping)
        or int(trajectory_protocol.get("task_segments", -1)) != TASK_SEGMENTS
    ):
        raise ValueError("S7 trajectory is not PASS T=10")

    prediction_path = Path(prediction_archive).resolve()
    archive = _load_prediction_archive(prediction_path)
    _validate_ae_structure(ae_report, archive)
    _validate_f_structure(f_report)
    source_count = _verify_source_receipts(ae_report.get("sources", {}), "ae.sources")
    source_count += _verify_source_receipts(f_report.get("sources", {}), "f.sources")
    prediction_receipt = ae_report["sources"].get("prediction_archive")
    if not isinstance(prediction_receipt, Mapping) or Path(
        str(prediction_receipt.get("path", ""))
    ).resolve() != prediction_path:
        raise ValueError("A-E prediction receipt does not bind supplied archive")

    protocol = ae_report["protocol"]
    repeats = int(protocol.get("shuffle_repeats", 0))
    seed = int(protocol.get("seed", -1))
    if repeats < 1 or seed < 0:
        raise ValueError("A-E metric recomputation seed/repeats are invalid")
    independent = summarize_label_strata(
        archive["predictions"],
        shuffle_repeats=repeats,
        seed=seed,
        threshold=0.5,
    )
    _assert_equal(
        independent,
        ae_report.get("intervention_metrics"),
        location="intervention_metrics",
    )
    metrics_payload = json.dumps(
        independent, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return {
        "schema_version": 1,
        "status": "PASS",
        "claim_level": "artifact_integrity_only",
        "task_segments": TASK_SEGMENTS,
        "git": {"head": git_head, "status": "clean"},
        "verified_source_receipt_count": source_count,
        "prediction_archive": {
            **_source_receipt(prediction_path),
            "mode_count": len(archive["modes"]),
            "sample_count": int(archive["arrays"]["ids"].size),
            "segment_count": int(archive["arrays"]["labels"].size),
        },
        "independent_metrics": independent,
        "independent_metrics_canonical_sha256": hashlib.sha256(
            metrics_payload
        ).hexdigest(),
        "scientific_success_claimed": False,
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _run_git(git: Path, repo: Path, *args: str) -> str:
    completed = subprocess.run(
        [str(git), "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip())
    return completed.stdout.strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Independent A-F zero-training artifact-integrity audit"
    )
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--git", type=Path, required=True)
    parser.add_argument("--ae-report", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--f-report", type=Path, required=True)
    parser.add_argument("--training-audit", type=Path, required=True)
    parser.add_argument("--trajectory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    temporary = output.with_name(output.name + ".tmp")
    if output.exists() or temporary.exists():
        raise FileExistsError(f"Refusing to overwrite audit output: {output}")
    repo = args.repo.resolve()
    head = _run_git(args.git, repo, "rev-parse", "HEAD")
    status = _run_git(
        args.git, repo, "status", "--porcelain=v1", "--untracked-files=all"
    )
    result = audit_zero_training_evidence(
        ae_report=_read_json(args.ae_report),
        prediction_archive=args.predictions,
        f_report=_read_json(args.f_report),
        training_audit=_read_json(args.training_audit),
        trajectory=_read_json(args.trajectory),
        expected_commit=args.expected_commit,
        git_head=head,
        git_status=status,
    )
    result["input_sources"] = {
        "ae_report": _source_receipt(args.ae_report),
        "predictions": _source_receipt(args.predictions),
        "f_report": _source_receipt(args.f_report),
        "training_audit": _source_receipt(args.training_audit),
        "trajectory": _source_receipt(args.trajectory),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
