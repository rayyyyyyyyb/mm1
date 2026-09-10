"""Fail-closed runner for the preregistered 800-step teacher-signal controls."""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

import yaml

from src.utils.teacher_signal_probe import evaluate_direct_visual_logit_gate


_CONTROL_REGISTERED_CHANGES = {
    "D1_centered_visual_800": "loss.visual_feature_centering",
    "D2_visual_pretrained_800": "student.visual_pretrained",
    "D3_visual_logit_800": "loss.alpha_strong_logit",
}
_C2_LOSS_OVERRIDES = {
    "strong_teacher_projector_update_mode": "static_zero_lr_keep_grad",
    "weak_teacher_projector_update_mode": "trainable",
    "text_teacher_projector_update_mode": "trainable",
}

# These fields describe the diagnostic runner/output rather than the
# scientific configuration.  Keep this list deliberately narrow: in
# particular, implementation_mode must remain in the comparison so a control
# cannot silently change the execution semantics while claiming one variable.
_REPRODUCTION_METADATA_KEYS = frozenset(
    {"variant", "claim_level", "diagnostic_only", "full_run_blocked", "project_root"}
)
_LOGGING_METADATA_KEYS = frozenset({"log_dir"})


def validate_control_wrapper(wrapper: Mapping[str, Any]) -> None:
    control = wrapper.get("control")
    if not isinstance(control, Mapping):
        raise ValueError("control metadata is required")
    name = str(control.get("name", ""))
    if name not in {"D1_centered_visual_800", "D2_visual_pretrained_800", "D3_visual_logit_800"}:
        raise ValueError(f"unsupported control name: {name}")
    if int(control.get("applied_optimizer_steps", -1)) != 800:
        raise ValueError("every teacher-signal control requires exactly 800 applied optimizer steps")
    if bool(control.get("evaluate_test", True)):
        raise ValueError("teacher-signal controls must not evaluate test data")
    if control.get("registered_change") != _CONTROL_REGISTERED_CHANGES[name]:
        raise ValueError("control must declare its single registered change")
    if not isinstance(wrapper.get("base_config"), str) or not wrapper["base_config"]:
        raise ValueError("base_config is required")
    overrides = wrapper.get("overrides")
    if not isinstance(overrides, Mapping):
        raise ValueError("overrides are required")
    loss = overrides.get("loss")
    if not isinstance(loss, Mapping):
        raise ValueError("loss overrides are required")
    expected_modes = {
        "strong_teacher_projector_update_mode",
        "weak_teacher_projector_update_mode",
        "text_teacher_projector_update_mode",
    }
    if not expected_modes <= set(loss):
        raise ValueError("all three explicit projector update modes are required")
    if name == "D1_centered_visual_800" and loss.get("visual_feature_centering") != "per_sample_temporal":
        raise ValueError("D1 must change only visual_feature_centering to per_sample_temporal")
    if name == "D2_visual_pretrained_800":
        student = overrides.get("student")
        if not isinstance(student, Mapping) or student.get("visual_pretrained") is not True:
            raise ValueError("D2 must enable only student.visual_pretrained")
    if name == "D3_visual_logit_800":
        student = overrides.get("student")
        if not isinstance(student, Mapping) or student.get("path_mode") != "explicit_projected":
            raise ValueError("D3 must preserve student.path_mode=explicit_projected")
        if loss.get("confidence_weighting") is not False:
            raise ValueError("D3 must preserve confidence_weighting=false")
        try:
            alpha_strong_logit = float(loss.get("alpha_strong_logit"))
        except (TypeError, ValueError) as exc:
            raise ValueError("D3 requires a locked positive alpha_strong_logit") from exc
        if not alpha_strong_logit > 0:
            raise ValueError("D3 requires a locked positive alpha_strong_logit")


def _scientific_view(config: Mapping[str, Any]) -> dict[str, Any]:
    """Remove runner metadata before comparing a control with the C2 baseline."""

    result = copy.deepcopy(dict(config))
    reproduction = result.get("reproduction")
    if isinstance(reproduction, dict):
        for key in _REPRODUCTION_METADATA_KEYS:
            reproduction.pop(key, None)
    logging = result.get("logging")
    if isinstance(logging, dict):
        for key in _LOGGING_METADATA_KEYS:
            logging.pop(key, None)
    training = result.get("training")
    if isinstance(training, dict):
        training.pop("max_optimizer_steps", None)
    evaluation = result.get("evaluation")
    if isinstance(evaluation, dict):
        evaluation.pop("run_test", None)
    student = result.setdefault("student", {})
    if isinstance(student, dict):
        student.setdefault("visual_pretrained", bool(student.get("pretrained", False)))
        student.setdefault("audio_pretrained", bool(student.get("pretrained", False)))
    result.setdefault("loss", {}).setdefault("visual_feature_centering", "none")
    return result


def _flatten(mapping: Mapping[str, Any], prefix: tuple[str, ...] = ()) -> dict[tuple[str, ...], Any]:
    values: dict[tuple[str, ...], Any] = {}
    for key, value in mapping.items():
        path = (*prefix, str(key))
        if isinstance(value, Mapping):
            values.update(_flatten(value, path))
        else:
            values[path] = value
    return values


def _c2_reference_config(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "configs/diagnostics/recovery/ov_orthkd_visual_only_sum_feature_seed42_no_workers.yaml"
    if not path.exists():
        raise ValueError(f"fixed C2 reference config is missing: {path}")
    base = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(base, Mapping):
        raise ValueError("fixed C2 reference config must be a mapping")
    reference = copy.deepcopy(dict(base))
    reference.setdefault("loss", {}).update(_C2_LOSS_OVERRIDES)
    reference.setdefault("training", {})["gradient_clipping"] = {"scope": "optimizer_groups_with_positive_lr"}
    return _scientific_view(reference)


def _assert_single_registered_change(config: Mapping[str, Any], name: str, repo_root: Path) -> None:
    baseline = _flatten(_c2_reference_config(repo_root))
    candidate = _flatten(_scientific_view(config))
    changed = sorted(path for path in set(baseline) | set(candidate) if baseline.get(path) != candidate.get(path))
    allowed = tuple(_CONTROL_REGISTERED_CHANGES[name].split("."))
    if changed != [allowed]:
        raise ValueError(f"{name} must differ from fixed C2 baseline only at {'.'.join(allowed)}; changed={changed}")


def _direct_visual_logit_gate(phase_a: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute the D3 gate from Phase A direct-logit evidence."""
    result = evaluate_direct_visual_logit_gate(
        mixed_concordance=phase_a.get("direct_mixed_video_macro_concordance"),
        best_temporal_shift=phase_a.get("direct_best_temporal_shift"),
        shuffle_ap_drop=phase_a.get("direct_shuffle_ap_drop"),
        shuffle_auroc_drop=phase_a.get("direct_shuffle_auroc_drop"),
    )
    declared = phase_a.get("visual_logit_gate_pass")
    if declared is not None and bool(declared) != result["pass"]:
        raise ValueError(
            "phase_a.visual_logit_gate_pass disagrees with the direct-logit evidence"
        )
    return result


def authorize_control(name: str, evidence: Mapping[str, Any]) -> dict[str, Any]:
    phase_a = evidence.get("phase_a", {})
    phase_c = evidence.get("phase_c", {})
    phase_d = evidence.get("phase_d", {})
    teacher = phase_a.get("teacher_gate_pass") is True
    mean_dominance = (
        phase_c.get("scientific_status")
        == "VISUAL_MEAN_COMPONENT_DOMINANCE_CONFIRMED"
    )
    visual_logit_gate = _direct_visual_logit_gate(phase_a)
    if name == "D1_centered_visual_800":
        authorized = teacher and mean_dominance
        reason = "Phase A teacher gate and Phase C visual-mean-dominance gate"
    elif name == "D2_visual_pretrained_800":
        authorized = teacher and phase_d.get("scientific_status") == "D2_ZERO_TRAINING_DECODABILITY_GATE_PASS"
        reason = "Phase A teacher gate and frozen pretrained-visual superiority gate"
    elif name == "D3_visual_logit_800":
        authorized = visual_logit_gate["pass"]
        reason = "Phase A direct-logit concordance, shift, and shuffle gate"
    else:
        raise ValueError(f"unsupported control name: {name}")
    return {
        "authorized": bool(authorized),
        "reason": reason,
        "teacher_gate": teacher,
        "visual_mean_dominance_gate": mean_dominance,
        "visual_logit_gate": visual_logit_gate,
    }


def _overlay(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(base))
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = _overlay(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def materialize_config(wrapper_path: str | Path, repo_root: str | Path, output_dir: str | Path) -> Path:
    wrapper_file = Path(wrapper_path).resolve()
    wrapper = yaml.safe_load(wrapper_file.read_text(encoding="utf-8"))
    if not isinstance(wrapper, Mapping):
        raise ValueError("control wrapper must be a mapping")
    validate_control_wrapper(wrapper)
    base_path = Path(repo_root).resolve() / str(wrapper["base_config"])
    config = yaml.safe_load(base_path.read_text(encoding="utf-8"))
    config = _overlay(config, wrapper["overrides"])
    name = str(wrapper["control"]["name"])
    _assert_single_registered_change(config, name, Path(repo_root).resolve())
    reproduction = config.setdefault("reproduction", {})
    reproduction.update({"variant": name, "claim_level": "noncanonical_diagnostic", "diagnostic_only": True, "full_run_blocked": True})
    config.setdefault("training", {})["max_optimizer_steps"] = 800
    config.setdefault("evaluation", {})["run_test"] = False
    output_path = Path(output_dir).resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    config.setdefault("logging", {})["log_dir"] = str(output_path)
    resolved = output_path / "resolved_config.yaml"
    resolved.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return resolved


def run_control(wrapper_path: str | Path, evidence_path: str | Path, repo_root: str | Path, output_root: str | Path) -> dict[str, Any]:
    wrapper = yaml.safe_load(Path(wrapper_path).read_text(encoding="utf-8"))
    validate_control_wrapper(wrapper)
    evidence = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
    name = str(wrapper["control"]["name"])
    authorization = authorize_control(name, evidence)
    output_dir = Path(output_root).resolve() / name
    output_dir.mkdir(parents=True, exist_ok=True)
    if not authorization["authorized"]:
        result = {"name": name, "status": "BLOCKED_BY_CONTROL_GATE", "authorization": authorization, "applied_optimizer_steps": 0, "test_evaluation": False}
        (output_dir / "control_command_result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
    config_path = materialize_config(wrapper_path, repo_root, output_dir)
    command = [sys.executable, str(Path(repo_root) / "scripts" / "train_ov_orthkd.py"), "--config", str(config_path), "--allow-blocked-reproduction", "--max-optimizer-steps", "800"]
    completed = subprocess.run(command, cwd=Path(repo_root), capture_output=True, text=True)
    step_summary_path = output_dir / "optimizer_step_summary.json"
    step_summary: dict[str, Any] = {}
    if step_summary_path.exists():
        try:
            loaded = json.loads(step_summary_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                step_summary = loaded
        except (OSError, json.JSONDecodeError):
            step_summary = {}
    applied_steps = step_summary.get("applied_steps")
    try:
        applied_steps_int = int(applied_steps)
    except (TypeError, ValueError):
        applied_steps_int = None
    try:
        attempted_steps_int = int(step_summary.get("attempted_steps", 0))
    except (TypeError, ValueError):
        attempted_steps_int = 0
    receipt_ok = (
        completed.returncode == 0
        and applied_steps_int == 800
        and attempted_steps_int >= 800
        and not (output_dir / "test_predictions.npz").exists()
    )
    result = {
        "name": name,
        "status": "PASS" if receipt_ok else "CONTROL_RECEIPT_MISMATCH" if completed.returncode == 0 else "CONTROL_RUN_FAILED",
        "authorization": authorization,
        "command": command,
        "exit_code": int(completed.returncode),
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
        "output_dir": str(output_dir),
        "applied_optimizer_steps": applied_steps_int,
        "optimizer_step_summary": step_summary,
        "receipt_ok": receipt_ok,
        "test_evaluation": False,
    }
    (output_dir / "control_command_result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wrapper", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_control(args.wrapper, args.evidence, args.repo_root, args.output_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status") in {"PASS", "BLOCKED_BY_CONTROL_GATE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
