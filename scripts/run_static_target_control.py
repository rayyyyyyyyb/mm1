"""Run the preregistered C0/C1 bounded static-target control.

This wrapper materializes noncanonical configs and refuses test evaluation.
It is intentionally explicit: no implicit extension to 3200 steps is allowed.
"""
from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

import yaml


def apply_overlay(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(base))
    for key, value in overlay.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = apply_overlay(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def validate_control_config(wrapper: Mapping[str, Any]) -> None:
    control = wrapper.get("control")
    if not isinstance(control, Mapping):
        raise ValueError("control metadata is required")
    if bool(control.get("evaluate_test", True)):
        raise ValueError("static-target control must not evaluate test data")
    if int(control.get("applied_optimizer_steps", -1)) != 800:
        raise ValueError("static-target control requires exactly 800 applied optimizer steps")
    overrides = wrapper.get("overrides")
    if not isinstance(overrides, Mapping):
        raise ValueError("overrides are required")
    loss = overrides.get("loss")
    if not isinstance(loss, Mapping):
        raise ValueError("loss projector modes are required")
    expected = {
        "strong_teacher_projector_update_mode",
        "weak_teacher_projector_update_mode",
        "text_teacher_projector_update_mode",
    }
    if set(loss) != expected:
        raise ValueError("control must specify all three explicit projector mode fields")


def evaluate_800_gates(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate the exact preregistered Phase-C gates; missing values fail."""
    c0_ap = metrics.get("validation_ap_c0")
    c1_ap = metrics.get("validation_ap_c1")
    gates = {
        "strong_projector_hash_unchanged": {
            "value": metrics.get("strong_projector_hash_unchanged"),
            "passed": metrics.get("strong_projector_hash_unchanged") is True,
        },
        "projected_target_temporal_std": {
            "value": metrics.get("projected_target_temporal_std"),
            "threshold": ">=0.15",
            "passed": metrics.get("projected_target_temporal_std") is not None and float(metrics["projected_target_temporal_std"]) >= 0.15,
        },
        "decision_temporal_std": {
            "value": metrics.get("decision_temporal_std"),
            "threshold": ">=0.003",
            "passed": metrics.get("decision_temporal_std") is not None and float(metrics["decision_temporal_std"]) >= 0.003,
        },
        "projected_to_decision_distance_correlation": {
            "value": metrics.get("projected_to_decision_distance_correlation"),
            "threshold": ">=0.20",
            "passed": metrics.get("projected_to_decision_distance_correlation") is not None and float(metrics["projected_to_decision_distance_correlation"]) >= 0.20,
        },
        "decision_centered_to_total_l2_ratio": {
            "value": metrics.get("decision_centered_to_total_l2_ratio"),
            "threshold": ">=0.005",
            "passed": metrics.get("decision_centered_to_total_l2_ratio") is not None and float(metrics["decision_centered_to_total_l2_ratio"]) >= 0.005,
        },
        "mixed_validation_concordance_gain_over_c0": {
            "value": metrics.get("mixed_validation_concordance_gain_over_c0"),
            "threshold": ">=0.02",
            "passed": metrics.get("mixed_validation_concordance_gain_over_c0") is not None and float(metrics["mixed_validation_concordance_gain_over_c0"]) >= 0.02,
        },
        "validation_ap_not_more_than_0.02_below_c0": {
            "value": None if c0_ap is None or c1_ap is None else float(c1_ap) - float(c0_ap),
            "threshold": ">=-0.02",
            "passed": c0_ap is not None and c1_ap is not None and float(c1_ap) >= float(c0_ap) - 0.02,
        },
        "unexplained_amp_skips": {
            "value": metrics.get("unexplained_amp_skips"),
            "threshold": "==0",
            "passed": metrics.get("unexplained_amp_skips") == 0,
        },
        "clip_receipts_complete": {
            "value": metrics.get("clip_receipts_complete"),
            "passed": metrics.get("clip_receipts_complete") is True,
        },
    }
    return {"gates": gates, "all_passed": all(row["passed"] for row in gates.values())}


def materialize_config(wrapper_path: Path, repo_root: Path, output_dir: Path) -> Path:
    wrapper = yaml.safe_load(wrapper_path.read_text(encoding="utf-8"))
    validate_control_config(wrapper)
    base_path = repo_root / str(wrapper["base_config"])
    config = yaml.safe_load(base_path.read_text(encoding="utf-8"))
    config = apply_overlay(config, wrapper["overrides"])
    config.setdefault("reproduction", {})["variant"] = str(wrapper["control"]["name"])
    config["reproduction"]["claim_level"] = "noncanonical_diagnostic"
    config["reproduction"]["diagnostic_only"] = True
    config["reproduction"]["full_run_blocked"] = True
    config.setdefault("training", {})["max_optimizer_steps"] = 800
    config.setdefault("evaluation", {})["run_test"] = False
    config.setdefault("logging", {})["log_dir"] = str(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "resolved_config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def run_one(wrapper_path: Path, repo_root: Path, output_root: Path) -> dict[str, Any]:
    wrapper = yaml.safe_load(wrapper_path.read_text(encoding="utf-8"))
    validate_control_config(wrapper)
    name = str(wrapper["control"]["name"])
    output_dir = output_root / name
    config_path = materialize_config(wrapper_path, repo_root, output_dir)
    command = [
        sys.executable,
        str(repo_root / "scripts" / "train_ov_orthkd.py"),
        "--config",
        str(config_path),
        "--allow-blocked-reproduction",
        "--max-optimizer-steps",
        "800",
    ]
    completed = subprocess.run(command, cwd=repo_root, capture_output=True, text=True)
    result = {
        "name": name,
        "command": command,
        "exit_code": int(completed.returncode),
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
        "output_dir": str(output_dir),
        "test_evaluation": False,
    }
    (output_dir / "control_command_result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return result


def run_paired_control(c0_config: Path, c1_config: Path, output_root: Path, repo_root: Path | None = None) -> dict[str, Any]:
    root = (repo_root or Path(__file__).resolve().parents[1]).resolve()
    output_root = output_root.resolve()
    results = [run_one(c0_config.resolve(), root, output_root), run_one(c1_config.resolve(), root, output_root)]
    return {"schema_version": 1, "steps": 800, "test_evaluation": False, "runs": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--c0", type=Path, required=True)
    parser.add_argument("--c1", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_paired_control(args.c0, args.c1, args.output_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"exit_codes": [row["exit_code"] for row in result["runs"]]}, ensure_ascii=False))
    if any(row["exit_code"] != 0 for row in result["runs"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
