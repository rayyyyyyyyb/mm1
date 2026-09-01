from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Mapping

import torch
import yaml

from scripts.train_ov_orthkd import build_model_and_loss, runtime_implementation_behavior


PROJECT_ROOT = Path(__file__).resolve().parents[1]
S7_PATH = (
    PROJECT_ROOT
    / "configs"
    / "diagnostics"
    / "recovery"
    / "ov_orthkd_s7_temporal_identity_seed42.yaml"
)
S8_PATH = (
    PROJECT_ROOT
    / "configs"
    / "diagnostics"
    / "recovery"
    / "ov_orthkd_s8_identity_fixed_gate_seed42.yaml"
)


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _normalized_scientific_config(config: dict[str, Any]) -> dict[str, Any]:
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


def test_s8_changes_only_gate_mode_relative_to_s7() -> None:
    s7 = _normalized_scientific_config(_load(S7_PATH))
    s8 = _normalized_scientific_config(_load(S8_PATH))

    assert _different_paths(s7, s8) == {"student.gate_mode"}
    assert s7["student"]["gate_mode"] == "learned_softmax"
    assert s8["student"]["gate_mode"] == "fixed_equal"


def test_s8_preserves_the_approved_short_student_only_protocol() -> None:
    s7 = _load(S7_PATH)
    s8 = _load(S8_PATH)

    assert s8["seed"] == 42
    assert s8["reproduction"]["claim_level"] == "noncanonical_diagnostic"
    assert s8["reproduction"]["diagnostic_only"] is True
    assert s8["data"]["num_segments"] == 10
    assert s8["student"]["max_position_segments"] == 16
    assert s8["student"]["pretrained"] is False
    assert s8["student"]["temporal_path_mode"] == "identity_passthrough"
    assert s8["data"]["train_augment"] is True
    assert s8["student"]["fusion_mode"] == "concat_mlp_query_conditioned"
    assert s8["training"]["epochs"] == 3
    assert s8["training"]["max_batches_per_epoch"] == 400
    assert s8["training"]["max_optimizer_steps"] is None
    assert s8["logging"]["training_diagnostics"]["checkpoint_steps"] == [
        400,
        800,
        1200,
    ]
    assert all(
        s8["loss"][name] == 0.0
        for name in (
            "alpha_strong_logit",
            "alpha_weak_logit",
            "alpha_strong_feat",
            "alpha_weak_feat",
            "alpha_text_align",
            "alpha_orth",
        )
    )
    assert _different_paths(
        _normalized_scientific_config(s7),
        _normalized_scientific_config(s8),
    ) == {"student.gate_mode"}


def test_s7_s8_preserve_identical_initial_state_and_record_fixed_gate() -> None:
    torch.manual_seed(42)
    s7_student, _ = build_model_and_loss(_load(S7_PATH), torch.device("cpu"))
    torch.manual_seed(42)
    s8_student, s8_loss = build_model_and_loss(_load(S8_PATH), torch.device("cpu"))

    s7_state = s7_student.state_dict()
    s8_state = s8_student.state_dict()
    assert s7_state.keys() == s8_state.keys()
    for name in s7_state:
        assert torch.equal(s7_state[name], s8_state[name]), name
    behavior = runtime_implementation_behavior(s8_student, s8_loss)
    assert behavior["student"]["temporal_path_mode"] == "identity_passthrough"
    assert behavior["student"]["gate_mode"] == "fixed_equal"
