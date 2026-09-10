#!/usr/bin/env python3
"""Independently audit D2A pairing, raw validation predictions, and fixed gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml
from sklearn.metrics import average_precision_score, roc_auc_score

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.atomic_artifacts import atomic_write_text  # noqa: E402


ROLES = ("random", "pretrained")
MODES = ("original", "visual_zero", "audio_zero")
CHECKPOINTS = (0, 25, 50, 100, 200, 400)
INPUT_STEPS = (1, 10, 50, 100, 200, 400)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument(
        "--config",
        default="configs/diagnostics/recovery/ov_orthkd_d2a_paired_pretrained_early_dynamics_400.yaml",
    )
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    return parser.parse_args()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_predictions(path: Path) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as archive:
        return {name: archive[name] for name in archive.files}


def _validate_predictions(payload: Mapping[str, np.ndarray]) -> None:
    expected = {
        "ids",
        "queries",
        "split_types",
        "sample_offsets",
        "segment_indices",
        "labels",
        "logits",
        "probabilities",
    }
    if set(payload) != expected:
        raise ValueError(f"prediction schema differs: {sorted(set(payload) ^ expected)}")
    ids = np.asarray(payload["ids"])
    offsets = np.asarray(payload["sample_offsets"], dtype=np.int64)
    labels = np.asarray(payload["labels"], dtype=np.float64)
    logits = np.asarray(payload["logits"], dtype=np.float64)
    probabilities = np.asarray(payload["probabilities"], dtype=np.float64)
    if (
        offsets.ndim != 1
        or offsets.size != ids.size + 1
        or offsets[0] != 0
        or offsets[-1] != labels.size
        or np.any(np.diff(offsets) != 10)
        or labels.shape != logits.shape
        or labels.shape != probabilities.shape
    ):
        raise ValueError("prediction payload violates aligned official T=10")
    expected_indices = np.arange(10, dtype=np.int64)
    indices = np.asarray(payload["segment_indices"], dtype=np.int64)
    for start, end in zip(offsets[:-1], offsets[1:]):
        if not np.array_equal(indices[int(start) : int(end)], expected_indices):
            raise ValueError("prediction segment order is not 0..9")
    expected_probabilities = 1.0 / (1.0 + np.exp(-logits))
    if not np.allclose(probabilities, expected_probabilities, rtol=0.0, atol=1e-12):
        raise ValueError("stored probabilities do not equal sigmoid(logits)")
    if not np.isin(labels, (0.0, 1.0)).all():
        raise ValueError("labels are not binary")
    if not np.isfinite(logits).all():
        raise ValueError("logits contain NaN/Inf")


def _assert_identity(left: Mapping[str, np.ndarray], right: Mapping[str, np.ndarray]) -> None:
    for name in (
        "ids",
        "queries",
        "split_types",
        "sample_offsets",
        "segment_indices",
        "labels",
    ):
        if not np.array_equal(left[name], right[name]):
            raise ValueError(f"paired validation identity differs at {name}")


def _concordance(payload: Mapping[str, np.ndarray]) -> float:
    offsets = np.asarray(payload["sample_offsets"], dtype=np.int64)
    labels = np.asarray(payload["labels"], dtype=np.int64)
    logits = np.asarray(payload["logits"], dtype=np.float64)
    wins = 0.0
    pairs = 0
    for start, end in zip(offsets[:-1], offsets[1:]):
        row_y = labels[int(start) : int(end)]
        if row_y.sum() in (0, row_y.size):
            continue
        positive = logits[int(start) : int(end)][row_y == 1]
        negative = logits[int(start) : int(end)][row_y == 0]
        differences = positive[:, None] - negative[None, :]
        wins += float((differences > 0).sum()) + 0.5 * float((differences == 0).sum())
        pairs += int(differences.size)
    if pairs == 0:
        raise ValueError("no mixed-label comparison pairs")
    return wins / pairs


def _shuffle(payload: Mapping[str, np.ndarray], repeats: int, seed: int) -> dict[str, float]:
    offsets = np.asarray(payload["sample_offsets"], dtype=np.int64)
    labels = np.asarray(payload["labels"], dtype=np.int64)
    logits = np.asarray(payload["logits"], dtype=np.float64)
    rows = [
        (int(start), int(end))
        for start, end in zip(offsets[:-1], offsets[1:])
        if 0 < labels[int(start) : int(end)].sum() < int(end) - int(start)
    ]
    if not rows:
        raise ValueError("no mixed-label samples")
    y = np.concatenate([labels[start:end] for start, end in rows])
    original = np.concatenate([logits[start:end] for start, end in rows])
    rng = np.random.default_rng(int(seed))
    shuffled_ap: list[float] = []
    shuffled_auroc: list[float] = []
    for _ in range(int(repeats)):
        shuffled = np.concatenate(
            [logits[start:end][rng.permutation(end - start)] for start, end in rows]
        )
        shuffled_ap.append(float(average_precision_score(y, shuffled)))
        shuffled_auroc.append(float(roc_auc_score(y, shuffled)))
    return {
        "ap_drop": float(average_precision_score(y, original) - np.mean(shuffled_ap)),
        "auroc_drop": float(roc_auc_score(y, original) - np.mean(shuffled_auroc)),
    }


def _raw_metrics(
    payloads: Mapping[str, Mapping[str, np.ndarray]], repeats: int, seed: int
) -> dict[str, Any]:
    original = payloads["original"]
    for mode in MODES:
        _validate_predictions(payloads[mode])
        _assert_identity(original, payloads[mode])
    labels = np.asarray(original["labels"], dtype=np.int64)
    logits = np.asarray(original["logits"], dtype=np.float64)
    probabilities = np.asarray(original["probabilities"], dtype=np.float64)
    concordances = {mode: _concordance(payloads[mode]) for mode in MODES}
    return {
        "validation_ap": float(average_precision_score(labels, logits)),
        "validation_auroc": float(roc_auc_score(labels, logits)),
        "predicted_positive_rate": float(np.mean(probabilities >= 0.5)),
        "mixed_pair_weighted_concordance": concordances["original"],
        "visual_zero_mixed_concordance_drop": (
            concordances["original"] - concordances["visual_zero"]
        ),
        "audio_zero_mixed_concordance_drop": (
            concordances["original"] - concordances["audio_zero"]
        ),
        "shuffle": _shuffle(original, repeats, seed),
    }


def _close(left: float, right: float) -> bool:
    return bool(np.isclose(float(left), float(right), rtol=0.0, atol=1e-12))


def _audit_snapshot(
    run_dir: Path, checkpoint: int, repeats: int, seed: int
) -> tuple[dict[str, Any], dict[str, Mapping[str, np.ndarray]]]:
    metrics: dict[str, Any] = {}
    originals: dict[str, Mapping[str, np.ndarray]] = {}
    for role in ROLES:
        root = run_dir / "evaluations" / f"step_{checkpoint:03d}" / role
        payloads = {mode: _load_predictions(root / f"{mode}.npz") for mode in MODES}
        metrics[role] = _raw_metrics(payloads, repeats, seed + checkpoint)
        originals[role] = payloads["original"]
        stored = _read_json(root / "summary.json")
        observed = metrics[role]
        stored_original = stored["modes"]["original"]
        checks = (
            (observed["validation_ap"], stored_original["validation_ap"]),
            (observed["validation_auroc"], stored_original["validation_auroc"]),
            (
                observed["predicted_positive_rate"],
                stored_original["predicted_positive_rate"],
            ),
            (
                observed["mixed_pair_weighted_concordance"],
                stored_original["mixed_pair_weighted_concordance"],
            ),
            (
                observed["visual_zero_mixed_concordance_drop"],
                stored["causal_deltas"]["visual_zero_mixed_concordance_drop"],
            ),
            (observed["shuffle"]["ap_drop"], stored["mixed_temporal_shuffle"]["ap_drop"]),
            (
                observed["shuffle"]["auroc_drop"],
                stored["mixed_temporal_shuffle"]["auroc_drop"],
            ),
        )
        if not all(_close(left, right) for left, right in checks):
            raise ValueError(f"stored summary differs from raw predictions for {role} step {checkpoint}")
    _assert_identity(originals["random"], originals["pretrained"])
    return metrics, originals


def _independent_gate(
    raw: Mapping[str, Any], trajectory_snapshot: Mapping[str, Any], gate: Mapping[str, Any]
) -> dict[str, Any]:
    random = raw["random"]
    pretrained = raw["pretrained"]
    decision_std = float(
        trajectory_snapshot["arms"]["pretrained"]["paths"]["decision_features"][
            "within_sample_temporal_std_mean"
        ]
    )
    concordance_delta = float(pretrained["mixed_pair_weighted_concordance"]) - float(
        random["mixed_pair_weighted_concordance"]
    )
    shuffle_signal = max(
        float(pretrained["shuffle"]["ap_drop"]),
        float(pretrained["shuffle"]["auroc_drop"]),
    )
    support = {
        "decision_temporal_std": decision_std
        >= float(gate["pretrained_decision_temporal_std_min"]),
        "shuffle_drop": shuffle_signal
        >= float(gate["pretrained_temporal_shuffle_ap_or_auroc_drop_min"]),
        "visual_zero_drop": float(pretrained["visual_zero_mixed_concordance_drop"])
        >= float(gate["pretrained_visual_zero_mixed_concordance_drop_min"]),
    }
    requirements = {
        "concordance_delta": concordance_delta
        >= float(gate["pretrained_minus_random_mixed_concordance_min"]),
        "support_count": sum(support.values()) >= int(gate["supporting_required_count"]),
        "validation_ap_floor": float(pretrained["validation_ap"])
        - float(random["validation_ap"])
        >= float(gate["pretrained_validation_ap_floor_relative_to_random"]),
        "predicted_positive_rate": float(pretrained["predicted_positive_rate"])
        < float(gate["pretrained_predicted_positive_rate_max_exclusive"]),
    }
    passed = all(requirements.values())
    return {
        "pass": passed,
        "support": support,
        "requirements": requirements,
        "observed": {
            "pretrained_minus_random_mixed_concordance": concordance_delta,
            "pretrained_decision_temporal_std": decision_std,
            "pretrained_shuffle_ap_drop": float(pretrained["shuffle"]["ap_drop"]),
            "pretrained_shuffle_auroc_drop": float(pretrained["shuffle"]["auroc_drop"]),
            "pretrained_visual_zero_mixed_concordance_drop": float(
                pretrained["visual_zero_mixed_concordance_drop"]
            ),
            "pretrained_minus_random_validation_ap": float(pretrained["validation_ap"])
            - float(random["validation_ap"]),
            "pretrained_predicted_positive_rate": float(
                pretrained["predicted_positive_rate"]
            ),
        },
        "scientific_status": (
            "D2A_PRETRAINED_EARLY_DYNAMICS_PASS"
            if passed
            else "D2A_PRETRAINED_EARLY_DYNAMICS_FAIL"
        ),
    }


def _check(condition: bool, name: str, failures: list[str]) -> None:
    if not condition:
        failures.append(name)


def _render(report: Mapping[str, Any]) -> str:
    gate = report.get("independent_gate", {})
    lines = [
        "# D2A paired early-dynamics independent audit",
        "",
        f"- Artifact status: `{report['artifact_status']}`",
        f"- Scientific status: `{report['scientific_status']}`",
        f"- Attempted batches: `{report.get('attempted_batches')}`",
        f"- Applied updates: `{report.get('applied_updates')}`",
        "- Test accessed: `false`",
        "- Automatic extension: `false`",
        "",
        "## Independent step-400 gate",
        "",
        f"- Pass: `{gate.get('pass')}`",
        f"- Observed: `{json.dumps(gate.get('observed', {}), ensure_ascii=False, sort_keys=True)}`",
        f"- Requirements: `{json.dumps(gate.get('requirements', {}), ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Audit failures",
        "",
    ]
    failures = report.get("failures", [])
    lines.extend([f"- {failure}" for failure in failures] or ["- None"])
    lines.extend(
        [
            "",
            "This result is validation-only and diagnostic. It does not authorize test evaluation, D3, Full, a second seed, or automatic schedule extension.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    run_dir = Path(args.run_dir).resolve()
    wrapper = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    result = _read_json(run_dir / "result.json")
    initialization = _read_json(run_dir / "initialization_receipt.json")
    trajectory = _read_json(run_dir / "trajectory.json")
    batch_plan = _read_json(run_dir / "batch_plan.json")["batches"]
    failures: list[str] = []

    _check(result.get("control") == "D2A_PAIRED_PRETRAINED_EARLY_DYNAMICS_400", "control identity", failures)
    _check(result.get("completed") is True, "run incomplete", failures)
    _check(result.get("smoke_only") is False, "smoke result cannot be audited as D2A", failures)
    _check(int(result.get("attempted_batches", -1)) == 400, "attempted budget", failures)
    _check(initialization.get("nonvisual_student_parity_after_locked_load", {}).get("pass") is True, "nonvisual parity", failures)
    _check(initialization.get("loss_parity", {}).get("pass") is True, "loss parity", failures)
    _check(initialization.get("asset_load_rng_unchanged") is True, "asset load RNG", failures)
    _check(initialization.get("batch_plan_sha256") == _canonical_hash(batch_plan), "batch plan hash", failures)
    _check(len(batch_plan) == 400 and all(len(row) == 4 for row in batch_plan), "batch plan dimensions", failures)
    asset = initialization.get("asset", {})
    lock_path = PROJECT_ROOT / str(wrapper["pretrained_asset"]["lock"])
    asset_lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    locked_model = asset_lock["model"]
    _check(asset.get("model_id") == locked_model["id"], "locked model identity", failures)
    _check(asset.get("revision") == locked_model["revision"], "locked model revision", failures)
    _check(
        asset.get("weights_sha256")
        == locked_model["files"]["model.safetensors"]["sha256"],
        "locked weights SHA256",
        failures,
    )
    _check(
        asset.get("config_sha256") == locked_model["files"]["config.json"]["sha256"],
        "locked config SHA256",
        failures,
    )

    checkpoint_rows = trajectory.get("checkpoints", [])
    observed_checkpoints = tuple(int(row["attempted_step"]) for row in checkpoint_rows)
    _check(observed_checkpoints == CHECKPOINTS, "checkpoint schedule", failures)
    snapshot_by_step = {int(row["attempted_step"]): row for row in checkpoint_rows}

    input_rows = _read_jsonl(run_dir / "input_receipts.jsonl")
    _check(tuple(int(row["attempted_step"]) for row in input_rows) == INPUT_STEPS, "input hash schedule", failures)
    _check(all(len(str(row.get("composite_sha256", ""))) == 64 for row in input_rows), "input hashes", failures)

    receipt_rows: dict[str, list[dict[str, Any]]] = {}
    for role in ROLES:
        rows = _read_jsonl(run_dir / role / "optimizer_receipts.jsonl")
        receipt_rows[role] = rows
        _check(len(rows) == 400, f"{role} receipt count", failures)
        _check([int(row["attempted_step"]) for row in rows] == list(range(1, 401)), f"{role} attempted sequence", failures)
        _check(all(bool(row["applied"]) != bool(row["overflow"]) for row in rows), f"{role} AMP receipt consistency", failures)
    masks = {
        role: [bool(row["applied"]) for row in receipt_rows[role]] for role in ROLES
    }
    applied_updates = {role: sum(masks[role]) for role in ROLES}
    _check(result.get("applied_updates") == applied_updates, "applied-update totals", failures)

    raw_by_step: dict[int, Any] = {}
    try:
        for checkpoint in CHECKPOINTS:
            raw_by_step[checkpoint], _ = _audit_snapshot(
                run_dir,
                checkpoint,
                int(wrapper["control"]["temporal_shuffle_repeats"]),
                42,
            )
    except (FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        failures.append(f"raw validation audit: {exc}")

    independent_gate: dict[str, Any] = {}
    if 400 in raw_by_step and 400 in snapshot_by_step:
        independent_gate = _independent_gate(
            raw_by_step[400], snapshot_by_step[400], wrapper["gate"]
        )
        producer_gate = result.get("gate", {})
        _check(
            producer_gate.get("scientific_status") == independent_gate["scientific_status"]
            and producer_gate.get("pass") == independent_gate["pass"],
            "producer gate differs from independent gate",
            failures,
        )
    else:
        failures.append("step-400 raw gate unavailable")

    forbidden = [
        str(path.relative_to(run_dir))
        for path in run_dir.rglob("*")
        if path.is_file() and "test" in path.name.lower()
    ]
    _check(not forbidden, f"forbidden test-named artifacts: {forbidden}", failures)
    authorization = result.get("authorization", {})
    _check(authorization.get("automatic_extension") is False, "automatic extension guard", failures)
    _check(authorization.get("test_evaluation") is False, "test guard", failures)
    _check(authorization.get("d3") is False, "D3 guard", failures)
    _check(authorization.get("formal_full") is False, "Full guard", failures)

    artifact_status = "D2A_ARTIFACT_AUDIT_PASS" if not failures else "D2A_ARTIFACT_AUDIT_FAIL"
    scientific_status = (
        independent_gate.get("scientific_status", "D2A_SCIENTIFIC_VERDICT_UNAVAILABLE")
        if not failures
        else "D2A_SCIENTIFIC_VERDICT_WITHHELD"
    )
    report = {
        "schema_version": 1,
        "artifact_status": artifact_status,
        "scientific_status": scientific_status,
        "attempted_batches": result.get("attempted_batches"),
        "applied_updates": applied_updates,
        "amp_applied_masks_identical": masks["random"] == masks["pretrained"],
        "independent_gate": independent_gate,
        "raw_metrics_by_checkpoint": raw_by_step,
        "forbidden_test_artifacts": forbidden,
        "failures": failures,
        "authorization": {
            "automatic_extension": False,
            "test_evaluation": False,
            "d3": False,
            "formal_full": False,
        },
    }
    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    atomic_write_text(
        output_json,
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
    )
    atomic_write_text(output_md, _render(report))
    print(json.dumps({"artifact_status": artifact_status, "scientific_status": scientific_status, "failures": failures}, indent=2))
    raise SystemExit(0 if not failures else 1)


if __name__ == "__main__":
    main()
