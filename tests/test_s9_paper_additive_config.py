from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Mapping

import torch
import torch.nn as nn
import yaml

from scripts.train_ov_orthkd import build_model_and_loss, runtime_implementation_behavior


PROJECT_ROOT = Path(__file__).resolve().parents[1]
S8_PATH = (
    PROJECT_ROOT
    / "configs"
    / "diagnostics"
    / "recovery"
    / "ov_orthkd_s8_identity_fixed_gate_seed42.yaml"
)
S9_PATH = (
    PROJECT_ROOT
    / "configs"
    / "diagnostics"
    / "recovery"
    / "ov_orthkd_s9_paper_additive_seed42.yaml"
)
EXPECTED_STUDENT_PARAMETERS = 46_278_129


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


def test_s9_changes_only_fusion_mode_relative_to_s8() -> None:
    s8 = _normalized_scientific_config(_load(S8_PATH))
    s9 = _normalized_scientific_config(_load(S9_PATH))

    assert _different_paths(s8, s9) == {"student.fusion_mode"}
    assert s8["student"]["fusion_mode"] == "concat_mlp_query_conditioned"
    assert s9["student"]["fusion_mode"] == "paper_additive_query_conditioned"


def test_s9_preserves_every_preregistered_protocol_lock() -> None:
    config = _load(S9_PATH)

    assert config["seed"] == 42
    assert config["training"]["deterministic"] is True
    assert config["data"]["num_segments"] == 10
    assert config["student"]["max_position_segments"] == 16
    assert config["data"]["train_augment"] is True
    assert config["student"]["pretrained"] is False
    assert config["student"]["gate_mode"] == "fixed_equal"
    assert config["student"]["temporal_path_mode"] == "identity_passthrough"
    assert config["student"]["path_mode"] == "explicit_projected"
    assert config["student"]["fusion_dim"] == 384
    assert config["student"]["projection_dim"] == 256
    assert config["loss"]["alpha_bce"] == 1.0
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
    assert config["training"]["epochs"] == 3
    assert config["training"]["max_batches_per_epoch"] == 400
    assert config["training"]["max_optimizer_steps"] is None
    assert config["training"]["learning_rate"] == 2e-4
    assert config["training"]["weight_decay"] == 1e-4
    assert config["training"]["grad_clip"] == 1.0
    assert config["training"]["mixed_precision"] is True
    assert config["training"]["scheduler"] == {
        "type": "CosineAnnealingLR",
        "T_max": 30,
        "interval": "epoch",
    }
    assert config["logging"]["training_diagnostics"]["checkpoint_steps"] == [
        400,
        800,
        1200,
    ]
    assert config["evaluation"]["test_views"] == 1
    assert config["evaluation"]["view_aggregation"] == "none"


def test_s8_s9_initial_states_keys_and_parameter_count_are_exactly_identical() -> None:
    torch.manual_seed(42)
    s8_student, _ = build_model_and_loss(_load(S8_PATH), torch.device("cpu"))
    torch.manual_seed(42)
    s9_student, s9_loss = build_model_and_loss(_load(S9_PATH), torch.device("cpu"))

    s8_state = s8_student.state_dict()
    s9_state = s9_student.state_dict()
    assert s8_state.keys() == s9_state.keys()
    for name in s8_state:
        assert torch.equal(s8_state[name], s9_state[name]), name
    assert sum(parameter.numel() for parameter in s8_student.parameters()) == (
        EXPECTED_STUDENT_PARAMETERS
    )
    assert sum(parameter.numel() for parameter in s9_student.parameters()) == (
        EXPECTED_STUDENT_PARAMETERS
    )
    behavior = runtime_implementation_behavior(s9_student, s9_loss)
    assert behavior["student"]["fusion_mode"] == "paper_additive_query_conditioned"
    assert behavior["student"]["token_fusion_present"] is True


def test_s9_forward_is_literal_addition_and_token_fusion_stays_inactive() -> None:
    torch.manual_seed(42)
    student, _ = build_model_and_loss(_load(S9_PATH), torch.device("cpu"))
    student.visual_encoder = nn.Identity()
    student.audio_encoder = nn.Identity()
    student.visual_proj = nn.Identity()
    student.audio_proj = nn.Identity()
    student.text_proj = nn.Identity()
    student.eval()
    initial_token_fusion = {
        name: value.detach().clone()
        for name, value in student.token_fusion.state_dict().items()
    }
    frame = torch.linspace(-1.0, 1.0, steps=10 * 384).reshape(1, 10, 384)
    spectrogram = torch.linspace(1.0, -1.0, steps=10 * 384).reshape(1, 10, 384)
    text = torch.linspace(-0.5, 0.5, steps=384).reshape(1, 384)

    outputs = student(
        frame=frame,
        spectrogram=spectrogram,
        text_embedding=text,
        sequence_mask=torch.ones(1, 10, dtype=torch.bool),
    )
    expected = (
        outputs["visual_tokens"] * outputs["gate_weights"][..., 0:1]
        + outputs["audio_tokens"] * outputs["gate_weights"][..., 1:2]
        + outputs["text_tokens"]
    )
    max_abs_error = (
        outputs["fused_tokens_before_position"] - expected
    ).abs().max().item()
    assert max_abs_error <= 1e-7
    assert outputs["segment_logits"].shape == (1, 10)
    assert torch.equal(outputs["shared_features"], outputs["temporal_input"])
    assert torch.equal(
        outputs["gate_weights"], torch.full((1, 10, 2), 0.5)
    )

    outputs["segment_logits"].sum().backward()
    assert all(parameter.grad is None for parameter in student.token_fusion.parameters())
    for name, value in student.token_fusion.state_dict().items():
        assert torch.equal(value, initial_token_fusion[name]), name
