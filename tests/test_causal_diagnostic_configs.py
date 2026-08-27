from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Mapping

import pytest
import torch
import yaml

import scripts.train_ov_orthkd as train_module

from scripts.train_ov_orthkd import (
    build_model_and_loss,
    runtime_implementation_behavior,
    validate_repro_config,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = PROJECT_ROOT / "configs" / "diagnostics" / "causal"
BASE_STUDENT_ONLY_CONFIG = (
    PROJECT_ROOT
    / "configs"
    / "diagnostics"
    / "ov_orthkd_mm26_student_only_seed42.yaml"
)
CONFIG_PATHS = {
    "s0": CONFIG_ROOT / "ov_orthkd_s0_learned_concat_seed42.yaml",
    "s1": CONFIG_ROOT / "ov_orthkd_s1_fixed_concat_seed42.yaml",
    "s2": CONFIG_ROOT / "ov_orthkd_s2_learned_additive_seed42.yaml",
}


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _normalized(config: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(config)
    result["reproduction"]["variant"] = "NORMALIZED"
    result["logging"]["log_dir"] = "NORMALIZED"
    return result


def _different_paths(left: Any, right: Any, prefix: str = "") -> set[str]:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        paths: set[str] = set()
        for key in set(left) | set(right):
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in left or key not in right:
                paths.add(path)
            else:
                paths.update(_different_paths(left[key], right[key], path))
        return paths
    return set() if left == right else {prefix}


def test_s0_s1_s2_are_strict_single_variable_diagnostics() -> None:
    configs = {name: _load(path) for name, path in CONFIG_PATHS.items()}
    s0 = _normalized(configs["s0"])

    assert _different_paths(s0, _normalized(configs["s1"])) == {
        "student.gate_mode"
    }
    assert _different_paths(s0, _normalized(configs["s2"])) == {
        "student.fusion_mode"
    }

    for config in configs.values():
        assert config["seed"] == 42
        assert config["reproduction"]["claim_level"] == "noncanonical_diagnostic"
        assert config["reproduction"]["diagnostic_only"] is True
        assert config["data"]["num_segments"] == 10
        assert config["evaluation"]["test_views"] == 1
        assert config["training"]["epochs"] == 3
        assert config["training"]["max_batches_per_epoch"] == 400
        assert config["training"]["max_optimizer_steps"] is None
        assert config["loss"]["alpha_strong_feat"] == 0.0
        assert config["loss"]["alpha_weak_feat"] == 0.0
        assert config["loss"]["alpha_text_align"] == 0.0
        assert config["loss"]["alpha_orth"] == 0.0
        assert config["loss"]["teacher_target_projector_trainable"] is True
        assert config["loss"]["query_anchor_mode"] == "independent_loss_projection"


def test_short_causal_runs_preserve_student_only_optimizer_and_scheduler() -> None:
    base = _load(BASE_STUDENT_ONLY_CONFIG)

    for config_path in CONFIG_PATHS.values():
        config = _load(config_path)
        assert config["training"]["optimizer"] == base["training"]["optimizer"]
        assert config["training"]["scheduler"] == base["training"]["scheduler"]
        assert config["training"]["learning_rate"] == base["training"][
            "learning_rate"
        ]
        assert config["training"]["weight_decay"] == base["training"][
            "weight_decay"
        ]
        assert config["training"]["grad_clip"] == base["training"]["grad_clip"]


def test_noncanonical_diagnostic_claim_requires_literal_marker() -> None:
    config = {
        "reproduction": {
            "claim_level": "noncanonical_diagnostic",
            "diagnostic_only": False,
            "full_run_blocked": False,
        }
    }

    with pytest.raises(RuntimeError, match="diagnostic_only=true"):
        validate_repro_config(config, allow_blocked=False, preflight=False)

    config["reproduction"]["diagnostic_only"] = True
    validate_repro_config(config, allow_blocked=False, preflight=False)


@pytest.mark.parametrize("config_path", CONFIG_PATHS.values(), ids=CONFIG_PATHS.keys())
def test_each_causal_config_constructs_its_declared_behavior(
    config_path: Path,
) -> None:
    config = _load(config_path)

    student, loss_module = build_model_and_loss(config, torch.device("cpu"))
    behavior = runtime_implementation_behavior(student, loss_module)

    assert behavior["student"]["fusion_mode"] == config["student"]["fusion_mode"]
    assert behavior["student"]["gate_mode"] == config["student"]["gate_mode"]
    assert behavior["loss"]["visual_l2_reduction"] == config["loss"][
        "visual_l2_reduction"
    ]
    assert behavior["loss"]["query_anchor_mode"] == config["loss"][
        "query_anchor_mode"
    ]
    assert behavior["loss"]["teacher_target_projector_trainable"] is config[
        "loss"
    ]["teacher_target_projector_trainable"]


def test_noncanonical_diagnostics_still_enforce_official_metric_t10() -> None:
    config = _load(CONFIG_PATHS["s0"])

    assert train_module.expected_metric_task_segments_for_claim(config) == 10


def test_formal_claim_rejects_diagnostic_only_marker_before_readiness() -> None:
    config = {
        "reproduction": {
            "claim_level": "paper_specified_reconstruction",
            "diagnostic_only": True,
            "full_run_blocked": False,
        },
        "training": {"max_batches_per_epoch": 400, "max_optimizer_steps": None},
    }

    with pytest.raises(RuntimeError, match="Formal claims forbid diagnostic_only"):
        validate_repro_config(config, allow_blocked=False, preflight=False)
