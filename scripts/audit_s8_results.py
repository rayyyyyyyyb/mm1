#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import gc
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import torch
import yaml


TASK_SEGMENTS = 10
CHECKPOINT_STEPS = (400, 800, 1200)
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
    "diagnostic_checkpoints/step_000400.pt",
    "diagnostic_checkpoints/step_000800.pt",
    "diagnostic_checkpoints/step_001200.pt",
)


def sha256_file(path: str | Path) -> str:
    source = Path(path)
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_text_sha256(path: str | Path) -> str:
    text = Path(path).read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        Path(path).read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        if not line.strip():
            raise ValueError(f"Blank JSONL line {line_number}: {path}")
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"Expected object at JSONL line {line_number}: {path}")
        records.append(value)
    return records


def assert_finite(value: Any, location: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            assert_finite(item, f"{location}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_finite(item, f"{location}[{index}]")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"Non-finite value at {location}")


def run_git(git: Path, repo: Path, *args: str) -> str:
    completed = subprocess.run(
        [str(git), "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip())
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


def normalize_scientific_config(config: Mapping[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(dict(config))
    normalized["reproduction"]["variant"] = "NORMALIZED"
    normalized["logging"]["log_dir"] = "NORMALIZED"
    return normalized


def state_dict_sha256(state: Mapping[str, torch.Tensor]) -> str:
    digest = hashlib.sha256()
    for name, tensor in sorted(state.items()):
        value = tensor.detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(value.dtype).encode("ascii"))
        digest.update(json.dumps(list(value.shape)).encode("ascii"))
        digest.update(value.numpy().tobytes(order="C"))
    return digest.hexdigest()


def _prefix_state(
    state: Mapping[str, torch.Tensor], prefix: str
) -> dict[str, torch.Tensor]:
    selected = {
        name: value.detach().cpu()
        for name, value in state.items()
        if name.startswith(prefix)
    }
    if not selected:
        raise ValueError(f"State has no tensors under {prefix}")
    return selected


def _require_equal_state(
    observed: Mapping[str, torch.Tensor],
    expected: Mapping[str, torch.Tensor],
    *,
    label: str,
) -> None:
    if observed.keys() != expected.keys():
        raise ValueError(f"{label} tensor names changed")
    for name in observed:
        if not torch.equal(observed[name], expected[name]):
            raise ValueError(f"{label} tensor changed: {name}")


def audit_inactive_checkpoint_states(
    checkpoints: Mapping[int, Mapping[str, torch.Tensor]],
    reconstructed_initial: Mapping[str, torch.Tensor],
) -> dict[str, Any]:
    if tuple(sorted(checkpoints)) != CHECKPOINT_STEPS:
        raise ValueError("S8 checkpoints must be exactly 400, 800, 1200")
    initial_temporal = _prefix_state(reconstructed_initial, "temporal_encoder.")
    initial_gate = _prefix_state(reconstructed_initial, "modality_gate.")
    previous_head: torch.Tensor | None = None
    head_changed = False
    for step in CHECKPOINT_STEPS:
        state = checkpoints[step]
        _require_equal_state(
            _prefix_state(state, "temporal_encoder."),
            initial_temporal,
            label=f"step {step} temporal_encoder",
        )
        _require_equal_state(
            _prefix_state(state, "modality_gate."),
            initial_gate,
            label=f"step {step} modality_gate",
        )
        head = state.get("segment_head.weight")
        if not isinstance(head, torch.Tensor):
            raise ValueError(f"step {step} is missing segment_head.weight")
        head = head.detach().cpu()
        if previous_head is not None and not torch.equal(head, previous_head):
            head_changed = True
        previous_head = head.clone()
    if not head_changed:
        raise ValueError("Active segment_head did not change across S8 checkpoints")
    return {
        "checkpoint_steps": list(CHECKPOINT_STEPS),
        "temporal_encoder_tensor_count": len(initial_temporal),
        "modality_gate_tensor_count": len(initial_gate),
        "temporal_encoder_unchanged_from_initial": True,
        "modality_gate_unchanged_from_initial": True,
        "active_segment_head_changed_across_steps": True,
    }


def validate_s8_training_diagnostics(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if [int(record.get("global_step_before_update", -1)) for record in records] != [
        0,
        400,
        800,
    ]:
        raise ValueError("S8 diagnostics must be the first batch at steps 0, 400, 800")
    visual_gradients: list[float] = []
    for index, record in enumerate(records):
        gradients = record.get("gradient_l2_before_clip")
        if not isinstance(gradients, Mapping):
            raise ValueError(f"S8 diagnostic {index} is missing gradient receipt")
        for key in ("student_temporal_encoder", "student_modality_gate"):
            value = float(gradients.get(key, float("nan")))
            if not math.isfinite(value) or value != 0.0:
                raise ValueError(f"Inactive {key} gradient is not exactly zero")
        visual = float(gradients.get("student_visual_encoder", float("nan")))
        if not math.isfinite(visual) or visual < 0.0:
            raise ValueError("student_visual_encoder gradient is invalid")
        visual_gradients.append(visual)
    return {
        "global_step_before_update": [0, 400, 800],
        "temporal_encoder_gradient_exact_zero": True,
        "modality_gate_gradient_exact_zero": True,
        "visual_encoder_gradient_l2": visual_gradients,
    }


def extract_s8_primary_metrics(
    ae_report: Mapping[str, Any],
    training_diagnostics: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    protocol = ae_report.get("protocol")
    if not isinstance(protocol, Mapping) or int(
        protocol.get("task_segments", -1)
    ) != TASK_SEGMENTS:
        raise ValueError("S8 evidence is not official T=10")
    if protocol.get("expected_gate_mode") != "fixed_equal":
        raise ValueError("S8 evidence must explicitly bind fixed_equal gate mode")
    metrics = ae_report.get("intervention_metrics")
    timeline = ae_report.get("timeline")
    if not isinstance(metrics, Mapping) or not isinstance(timeline, Mapping):
        raise ValueError("S8 evidence is missing intervention metrics or timeline")
    mixed = metrics["strata"]["mixed"]
    modes = mixed["modes"]
    original = modes["content_original"]
    visual_zero = modes["content_visual_zero"]
    shuffle = metrics["mixed_only_shuffle"]["content_original"]
    concordance = metrics["mixed_pairwise_concordance"]["content_original"]
    sources = ae_report.get("sources")
    if not isinstance(sources, Mapping) or not isinstance(
        sources.get("best_checkpoint"), Mapping
    ):
        raise ValueError("S8 evidence is missing best-checkpoint provenance")
    best_step = int(sources["best_checkpoint"].get("global_step", -1))
    if best_step not in CHECKPOINT_STEPS:
        raise ValueError("S8 best checkpoint is not one of 400, 800, 1200")
    best_label = f"step_{best_step:06d}"

    def summarize_timeline_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
        paths = entry["visual_timeline"]["paths"]
        blocks = entry["fusion_input_blocks"]
        jacobian = entry["first_test_batch_input_jacobians"]["l2"]
        return {
            "visual_path": {
                "backbone_temporal_std": float(
                    paths["visual_backbone_features"][
                        "within_sample_temporal_std_mean"
                    ]
                ),
                "projected_temporal_std": float(
                    paths["visual_projected_tokens"][
                        "within_sample_temporal_std_mean"
                    ]
                ),
            },
            "fusion_input_block_frobenius_l2": {
                name: float(blocks[name]["frobenius_l2"])
                for name in ("visual", "audio", "query")
            },
            "fusion_input_jacobian_l2": {
                name: float(jacobian[name]) for name in ("visual", "audio", "query")
            },
        }

    timeline_summary = {
        label: summarize_timeline_entry(entry)
        for label, entry in timeline.items()
        if isinstance(entry, Mapping)
    }
    if best_label not in timeline_summary:
        raise ValueError("S8 timeline does not contain its best checkpoint")
    best_summary = timeline_summary[best_label]
    diagnostics = validate_s8_training_diagnostics(training_diagnostics)
    result = {
        "mixed_sample_count": int(mixed["sample_count"]),
        "mixed_original": {
            "ap": float(original["ap"]),
            "auroc": float(original["auroc"]),
        },
        "mixed_visual_zero": {
            "ap": float(visual_zero["ap"]),
            "auroc": float(visual_zero["auroc"]),
            "ap_drop": float(original["ap"]) - float(visual_zero["ap"]),
            "auroc_drop": float(original["auroc"])
            - float(visual_zero["auroc"]),
        },
        "mixed_temporal_shuffle": {
            "ap_mean_drop": float(shuffle["ap"]["mean_drop"]),
            "auroc_mean_drop": float(shuffle["auroc"]["mean_drop"]),
        },
        "mixed_pairwise_concordance": {
            "pairs": int(concordance["pairs"]),
            "pair_weighted": float(concordance["pair_weighted"]),
            "video_macro_mean": float(concordance["video_macro_mean"]),
        },
        "best_checkpoint_step": best_step,
        "timeline": timeline_summary,
        "visual_path": best_summary["visual_path"],
        "fusion_input_block_frobenius_l2": best_summary[
            "fusion_input_block_frobenius_l2"
        ],
        "fusion_input_jacobian_l2": best_summary["fusion_input_jacobian_l2"],
        "training_visual_encoder_gradient_l2": diagnostics[
            "visual_encoder_gradient_l2"
        ],
        "scientific_outcome_threshold_preregistered": False,
        "automatic_scientific_success_claimed": False,
        "interpretation_policy": (
            "Report exact S8 values against the three approved evidence patterns; "
            "do not invent a post-hoc numeric success threshold."
        ),
    }
    assert_finite(result, "s8_primary_metrics")
    return result


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
        if set(payload.files) != required:
            raise ValueError(f"Unexpected prediction fields: {payload.files}")
        arrays = {name: np.asarray(payload[name]) for name in required}
    offsets = arrays["sample_offsets"].astype(np.int64, copy=False).reshape(-1)
    indices = arrays["segment_indices"].astype(np.int64, copy=False).reshape(-1)
    labels = arrays["labels"].astype(np.float64, copy=False).reshape(-1)
    logits = arrays["logits"].astype(np.float64, copy=False).reshape(-1)
    probabilities = arrays["probabilities"].astype(np.float64, copy=False).reshape(-1)
    if arrays["ids"].reshape(-1).size != samples or offsets.size != samples + 1:
        raise ValueError("Prediction sample count is invalid")
    if offsets[0] != 0 or offsets[-1] != segments or not np.all(np.diff(offsets) == 10):
        raise ValueError("Prediction offsets do not preserve T=10")
    if not np.array_equal(indices.reshape(samples, 10), np.tile(np.arange(10), (samples, 1))):
        raise ValueError("Prediction segment indices do not preserve T=10")
    if labels.size != segments or logits.size != segments or probabilities.size != segments:
        raise ValueError("Prediction segment count is invalid")
    if not np.isin(labels, (0.0, 1.0)).all() or not np.isfinite(logits).all():
        raise ValueError("Prediction labels/logits are invalid")
    expected = 1.0 / (1.0 + np.exp(-logits))
    if not np.isfinite(probabilities).all() or not np.allclose(
        probabilities, expected, rtol=1e-7, atol=1e-8
    ):
        raise ValueError("Prediction probabilities do not equal sigmoid(logits)")
    return {
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "sample_count": samples,
        "segment_count": segments,
        "positive_rate": float(labels.mean()),
    }


def _checkpoint_role(
    path: Path, config: Mapping[str, Any], state_hashes: Mapping[int, str]
) -> dict[str, Any]:
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    step = int(checkpoint.get("global_step", -1))
    if step not in state_hashes or checkpoint.get("config") != config:
        raise ValueError(f"Checkpoint role does not bind an audited step: {path}")
    state_hash = state_dict_sha256(checkpoint["student_state_dict"])
    if state_hash != state_hashes[step]:
        raise ValueError(f"Checkpoint role state differs from diagnostic step: {path}")
    result = {
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "epoch": int(checkpoint["epoch"]),
        "global_step": step,
        "student_state_sha256": state_hash,
        "matches_diagnostic_step": step,
    }
    del checkpoint
    gc.collect()
    return result


def audit_s8_training_artifacts(
    *,
    repo: Path,
    git: Path,
    output: Path,
    source_config_path: Path,
    s7_config_path: Path,
    worker_state_path: Path,
    candidate_verification_path: Path,
    expected_commit: str,
    expected_config_sha256: str,
) -> dict[str, Any]:
    if len(expected_commit) != 40:
        raise ValueError("Expected commit must be a full 40-character SHA")
    head = run_git(git, repo, "rev-parse", "HEAD")
    status = run_git(git, repo, "status", "--porcelain=v1", "--untracked-files=all")
    if head != expected_commit or status:
        raise ValueError("S8 audit requires the exact clean implementation commit")
    if normalized_text_sha256(source_config_path) != expected_config_sha256:
        raise ValueError("S8 source config SHA256 mismatch")
    s8 = yaml.safe_load(source_config_path.read_text(encoding="utf-8"))
    s7 = yaml.safe_load(s7_config_path.read_text(encoding="utf-8"))
    if not isinstance(s8, dict) or not isinstance(s7, dict):
        raise ValueError("S7/S8 source configs must be mappings")
    if different_paths(
        normalize_scientific_config(s7), normalize_scientific_config(s8)
    ) != {"student.gate_mode"}:
        raise ValueError("S8 does not differ from S7 only at student.gate_mode")
    if (
        s7["student"]["gate_mode"] != "learned_softmax"
        or s8["student"]["gate_mode"] != "fixed_equal"
        or s8["student"]["temporal_path_mode"] != "identity_passthrough"
        or int(s8["data"]["num_segments"]) != TASK_SEGMENTS
    ):
        raise ValueError("S8 source config does not bind identity + fixed_equal + T=10")
    if (
        int(s8["training"]["epochs"]) != 3
        or int(s8["training"]["max_batches_per_epoch"]) != 400
        or s8["logging"]["training_diagnostics"]["checkpoint_steps"]
        != list(CHECKPOINT_STEPS)
    ):
        raise ValueError("S8 exposure/checkpoint schedule changed")
    if any(
        float(s8["loss"][key]) != 0.0
        for key in (
            "alpha_strong_logit",
            "alpha_weak_logit",
            "alpha_strong_feat",
            "alpha_weak_feat",
            "alpha_text_align",
            "alpha_orth",
        )
    ):
        raise ValueError("S8 is not Student-only BCE")

    worker = read_json(worker_state_path)
    candidate = read_json(candidate_verification_path)
    if (
        worker.get("status") != "completed"
        or int(worker.get("exit_code", -1)) != 0
        or worker.get("git_commit") != expected_commit
        or worker.get("config_sha256") != expected_config_sha256
        or worker.get("completed_phases") != ["s8_training"]
    ):
        raise ValueError("S8 worker did not complete the exact locked training phase")
    if (
        candidate.get("status") != "PASS"
        or candidate.get("commit_before") != expected_commit
        or candidate.get("commit_after") != expected_commit
        or int(candidate.get("dirty_before", -1)) != 0
        or int(candidate.get("dirty_after", -1)) != 0
        or int(candidate.get("compileall_exit", -1)) != 0
        or int(candidate.get("pytest_exit", -1)) != 0
    ):
        raise ValueError("S8 exact-candidate verification is not PASS")
    for name in REQUIRED_OUTPUTS:
        path = output / name
        if not path.is_file() or path.stat().st_size <= 0:
            raise FileNotFoundError(f"Missing S8 output: {name}")

    resolved = yaml.safe_load((output / "resolved_config.yaml").read_text(encoding="utf-8"))
    duplicate = yaml.safe_load((output / "config_resolved.yaml").read_text(encoding="utf-8"))
    behavior = read_json(output / "implementation_behavior.json")
    if resolved != duplicate or resolved.get("runtime_implementation") != behavior:
        raise ValueError("Resolved config/runtime behavior receipts disagree")
    without_runtime = copy.deepcopy(resolved)
    del without_runtime["runtime_implementation"]
    observed_log_dir = str(without_runtime["logging"]["log_dir"]).replace("\\", "/")
    source_log_dir = str(s8["logging"]["log_dir"]).replace("\\", "/")
    if observed_log_dir != source_log_dir:
        raise ValueError("S8 output directory does not match the locked config")
    without_runtime["logging"]["log_dir"] = s8["logging"]["log_dir"]
    if without_runtime != s8:
        raise ValueError("Resolved S8 config differs from the locked source config")
    if (
        behavior["student"]["path_mode"] != "explicit_projected"
        or behavior["student"]["fusion_mode"] != "concat_mlp_query_conditioned"
        or behavior["student"]["gate_mode"] != "fixed_equal"
        or behavior["student"]["temporal_path_mode"] != "identity_passthrough"
    ):
        raise ValueError("S8 runtime behavior is not the approved causal cell")

    history = read_jsonl(output / "history.jsonl")
    diagnostics = read_jsonl(output / "training_diagnostics.jsonl")
    if len(history) != 3 or [int(row["global_step"]) for row in history] != list(CHECKPOINT_STEPS):
        raise ValueError("S8 history does not contain exact 3x400 exposure")
    diagnostic_receipt = validate_s8_training_diagnostics(diagnostics)
    assert_finite(history, "history")
    assert_finite(diagnostics, "training_diagnostics")
    metrics = read_json(output / "final_metrics.json")
    assert_finite(metrics, "final_metrics")
    for split, (samples, segments) in EXPECTED_SPLITS.items():
        total = metrics[split]["metrics"]["total"]
        if int(total["sample_count"]) != samples or int(total["segment_count"]) != segments:
            raise ValueError(f"S8 {split} metrics do not preserve official sample/T=10 counts")

    sys.path.insert(0, str(repo))
    from scripts.train_ov_orthkd import build_model_and_loss, set_seed  # noqa: PLC0415

    device = torch.device("cpu")
    set_seed(int(s8.get("seed", 42)), deterministic=True)
    initial_student, initial_loss = build_model_and_loss(s8, device)
    del initial_loss
    initial_state = {
        name: value.detach().cpu().clone()
        for name, value in initial_student.state_dict().items()
    }
    del initial_student
    gc.collect()
    checkpoint_states: dict[int, dict[str, torch.Tensor]] = {}
    checkpoint_receipts: dict[str, Any] = {}
    state_hashes: dict[int, str] = {}
    fingerprint_sha: str | None = None
    for step in CHECKPOINT_STEPS:
        path = output / "diagnostic_checkpoints" / f"step_{step:06d}.pt"
        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
        if (
            int(checkpoint.get("global_step", -1)) != step
            or int(checkpoint.get("epoch", -1)) != step // 400 - 1
            or checkpoint.get("config") != resolved
            or checkpoint["runtime_implementation"]["student"]["gate_mode"]
            != "fixed_equal"
        ):
            raise ValueError(f"S8 checkpoint metadata mismatch at step {step}")
        fingerprint = checkpoint.get("reproduction_fingerprint")
        if not isinstance(fingerprint, Mapping) or not isinstance(fingerprint.get("sha256"), str):
            raise ValueError(f"S8 checkpoint fingerprint missing at step {step}")
        if fingerprint_sha is None:
            fingerprint_sha = str(fingerprint["sha256"])
        if fingerprint["sha256"] != fingerprint_sha:
            raise ValueError("S8 reproduction fingerprint changed across checkpoints")
        state = checkpoint.get("student_state_dict")
        if not isinstance(state, dict) or not all(torch.isfinite(value).all() for value in state.values()):
            raise ValueError(f"S8 checkpoint state is invalid at step {step}")
        checkpoint_states[step] = {
            name: value.detach().cpu().clone() for name, value in state.items()
        }
        state_hash = state_dict_sha256(state)
        state_hashes[step] = state_hash
        checkpoint_receipts[str(step)] = {
            "path": str(path.resolve()),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "epoch": int(checkpoint["epoch"]),
            "global_step": step,
            "student_state_sha256": state_hash,
            "fingerprint_sha256": fingerprint_sha,
        }
        del checkpoint, state
        gc.collect()
    inactive_receipt = audit_inactive_checkpoint_states(
        checkpoint_states, initial_state
    )
    checkpoint_roles = {
        role: _checkpoint_role(output / f"{role}.pt", resolved, state_hashes)
        for role in ("best", "last")
    }
    if checkpoint_roles["last"]["global_step"] != 1200:
        raise ValueError("S8 last checkpoint is not step 1200")
    prediction_receipts = {
        split: audit_prediction_npz(
            output / f"{split}_predictions.npz", samples, segments
        )
        for split, (samples, segments) in EXPECTED_SPLITS.items()
    }
    artifact_receipts = {
        name: {
            "bytes": (output / name).stat().st_size,
            "sha256": sha256_file(output / name),
        }
        for name in REQUIRED_OUTPUTS
        if not name.endswith("_predictions.npz") and not name.endswith(".pt")
    }
    return {
        "schema_version": 1,
        "status": "PASS",
        "claim_level": "noncanonical_s8_training_artifact_integrity",
        "git_commit": expected_commit,
        "task_segments": TASK_SEGMENTS,
        "max_position_segments": 16,
        "sole_scientific_change_from_s7": "student.gate_mode_learned_to_fixed_equal",
        "worker_state": worker,
        "candidate_verification": {
            "bytes": candidate_verification_path.stat().st_size,
            "sha256": sha256_file(candidate_verification_path),
        },
        "source_config": {
            "bytes": source_config_path.stat().st_size,
            "sha256": sha256_file(source_config_path),
            "normalized_text_sha256": expected_config_sha256,
        },
        "history": history,
        "training_diagnostics": diagnostics,
        "inactive_path_audit": inactive_receipt,
        "diagnostic_gradient_audit": diagnostic_receipt,
        "checkpoint_trajectory": {
            "checkpoints": checkpoint_receipts,
            "fingerprint_sha256": fingerprint_sha,
        },
        "checkpoint_roles": checkpoint_roles,
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Independent S8 training artifact audit")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--git", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-config", type=Path, required=True)
    parser.add_argument("--s7-config", type=Path, required=True)
    parser.add_argument("--worker-state", type=Path, required=True)
    parser.add_argument("--candidate-verification", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-config-sha256", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    audit_output = args.audit_output.resolve()
    temporary = audit_output.with_name(audit_output.name + ".tmp")
    if audit_output.exists() or temporary.exists():
        raise FileExistsError(f"Refusing to overwrite S8 audit output: {audit_output}")
    report = audit_s8_training_artifacts(
        repo=args.repo.resolve(),
        git=args.git.resolve(),
        output=args.output.resolve(),
        source_config_path=args.source_config.resolve(),
        s7_config_path=args.s7_config.resolve(),
        worker_state_path=args.worker_state.resolve(),
        candidate_verification_path=args.candidate_verification.resolve(),
        expected_commit=args.expected_commit,
        expected_config_sha256=args.expected_config_sha256,
    )
    assert_finite(report, "report")
    audit_output.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(audit_output)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
