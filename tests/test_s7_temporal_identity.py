from __future__ import annotations

from typing import Any

import pytest
import torch

from src.models.ov_orthkd import OVOrthKDStudent


def _student(**overrides: Any) -> OVOrthKDStudent:
    kwargs: dict[str, Any] = {
        "visual_backbone": "mobilenetv3_small_100",
        "audio_backbone": "mobilenetv3_small_100",
        "text_dim": 8,
        "fusion_dim": 32,
        "projection_dim": 16,
        "path_mode": "explicit_projected",
        "temporal_layers": 1,
        "temporal_heads": 4,
        "temporal_dropout": 0.0,
        "max_segments": 3,
        "pretrained": False,
    }
    kwargs.update(overrides)
    return OVOrthKDStudent(**kwargs)


def _batch() -> dict[str, torch.Tensor]:
    generator = torch.Generator().manual_seed(19)
    return {
        "frame": torch.randn(1, 3, 3, 32, 32, generator=generator),
        "spectrogram": torch.randn(1, 3, 3, 32, 32, generator=generator),
        "text_embedding": torch.randn(1, 8, generator=generator),
        "sequence_mask": torch.tensor([[1.0, 1.0, 0.0]]),
        "frame_valid": torch.ones(1, 3),
        "audio_valid": torch.ones(1, 3),
    }


def test_temporal_modes_preserve_identical_initial_state_and_parameter_count() -> None:
    """Catch mode-specific construction that changes RNG use or state keys."""
    torch.manual_seed(2718)
    transformer = _student(temporal_path_mode="transformer")
    torch.manual_seed(2718)
    identity = _student(temporal_path_mode="identity_passthrough")

    transformer_state = transformer.state_dict()
    identity_state = identity.state_dict()
    assert transformer_state.keys() == identity_state.keys()
    assert sum(parameter.numel() for parameter in transformer.parameters()) == sum(
        parameter.numel() for parameter in identity.parameters()
    )
    for name, value in transformer_state.items():
        assert torch.equal(value, identity_state[name]), name


def test_identity_passthrough_exposes_exact_temporal_input_and_ignores_encoder() -> None:
    """Catch accidental Transformer execution or a second transform in identity mode."""
    model = _student(temporal_path_mode="identity_passthrough")
    model.eval()

    outputs = model(**_batch())
    valid = _batch()["sequence_mask"].bool()
    assert torch.equal(outputs["shared_features"][valid], outputs["temporal_input"][valid])

    outputs["segment_logits"].sum().backward()
    assert all(parameter.grad is None for parameter in model.temporal_encoder.parameters())


def test_default_temporal_mode_is_explicit_transformer_compatible() -> None:
    """Catch a default-mode change that alters existing S0 tensor outputs."""
    torch.manual_seed(3141)
    default = _student()
    torch.manual_seed(3141)
    explicit = _student(temporal_path_mode="transformer")
    default.eval()
    explicit.eval()
    batch = _batch()

    with torch.no_grad():
        default_outputs = default(**batch)
        explicit_outputs = explicit(**batch)

    assert default.temporal_path_mode == "transformer"
    assert default_outputs.keys() == explicit_outputs.keys()
    for name in default_outputs:
        left = default_outputs[name]
        right = explicit_outputs[name]
        if left is None:
            assert right is None
        else:
            assert torch.equal(left, right), name


def test_student_rejects_unknown_temporal_path_mode() -> None:
    """Catch silent fallback of a misspelled causal-control value."""
    with pytest.raises(
        ValueError,
        match="Unsupported temporal_path_mode: invented",
    ):
        _student(temporal_path_mode="invented")
