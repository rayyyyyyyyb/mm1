from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Mapping

import torch
import yaml

from scripts.train_ov_orthkd import build_model_and_loss, runtime_implementation_behavior


PROJECT_ROOT = Path(__file__).resolve().parents[1]
S0_PATH = (
    PROJECT_ROOT
    / "configs"
    / "diagnostics"
    / "causal"
    / "ov_orthkd_s0_learned_concat_seed42.yaml"
)
S7_PATH = (
    PROJECT_ROOT
    / "configs"
    / "diagnostics"
    / "recovery"
    / "ov_orthkd_s7_temporal_identity_seed42.yaml"
)


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _normalized_scientific_config(config: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(config)
    result["reproduction"]["variant"] = "NORMALIZED"
    result["logging"]["log_dir"] = "NORMALIZED"
    result["student"].setdefault("temporal_path_mode", "transformer")
    result["logging"]["training_diagnostics"].pop("checkpoint_steps", None)
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


def test_s7_changes_only_temporal_path_after_observation_normalization() -> None:
    s0 = _normalized_scientific_config(_load(S0_PATH))
    s7 = _normalized_scientific_config(_load(S7_PATH))

    assert _different_paths(s0, s7) == {"student.temporal_path_mode"}
    assert s0["student"]["temporal_path_mode"] == "transformer"
    assert s7["student"]["temporal_path_mode"] == "identity_passthrough"


def test_s7_locks_the_approved_short_student_only_protocol() -> None:
    config = _load(S7_PATH)

    assert config["seed"] == 42
    assert config["reproduction"]["claim_level"] == "noncanonical_diagnostic"
    assert config["reproduction"]["diagnostic_only"] is True
    assert config["data"]["num_segments"] == 10
    assert config["student"]["max_position_segments"] == 16
    assert config["student"]["pretrained"] is False
    assert config["data"]["train_augment"] is True
    assert config["training"]["epochs"] == 3
    assert config["training"]["max_batches_per_epoch"] == 400
    assert config["training"]["max_optimizer_steps"] is None
    assert config["training"]["scheduler"] == {
        "type": "CosineAnnealingLR",
        "T_max": 30,
        "interval": "epoch",
    }
    assert config["evaluation"]["test_views"] == 1
    assert config["logging"]["training_diagnostics"]["checkpoint_steps"] == [
        400,
        800,
        1200,
    ]
    assert all(
        config["loss"][name] == 0.0
        for name in (
            "alpha_strong_logit",
            "alpha_weak_logit",
            "alpha_strong_feat",
            "alpha_weak_feat",
            "alpha_text_align",
            "alpha_orth",
        )
    )


def test_s0_s7_preserve_identical_parameter_initialization_and_record_mode() -> None:
    torch.manual_seed(42)
    s0_student, _ = build_model_and_loss(_load(S0_PATH), torch.device("cpu"))
    torch.manual_seed(42)
    s7_student, s7_loss = build_model_and_loss(_load(S7_PATH), torch.device("cpu"))

    s0_state = s0_student.state_dict()
    s7_state = s7_student.state_dict()
    assert s0_state.keys() == s7_state.keys()
    for name in s0_state:
        assert torch.equal(s0_state[name], s7_state[name]), name
    behavior = runtime_implementation_behavior(s7_student, s7_loss)
    assert behavior["student"]["temporal_path_mode"] == "identity_passthrough"
