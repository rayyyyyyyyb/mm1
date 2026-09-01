from __future__ import annotations

from typing import Any

import pytest
import torch

import src.losses.ov_orthkd_loss as camera_ready_loss
from src.models.ov_orthkd import OVOrthKDStudent


def build_tiny_test_student(path_mode: str, **overrides: Any) -> OVOrthKDStudent:
    kwargs: dict[str, Any] = {
        "visual_backbone": "mobilenetv3_small_100",
        "audio_backbone": "mobilenetv3_small_100",
        "text_dim": 8,
        "fusion_dim": 32,
        "projection_dim": 16,
        "path_mode": path_mode,
        "temporal_layers": 1,
        "temporal_heads": 4,
        "temporal_dropout": 0.0,
        "max_segments": 2,
        "pretrained": False,
    }
    kwargs.update(overrides)
    return OVOrthKDStudent(**kwargs)


def make_tiny_batch() -> dict[str, torch.Tensor]:
    generator = torch.Generator().manual_seed(7)
    return {
        "frame": torch.randn(1, 2, 3, 32, 32, generator=generator),
        "spectrogram": torch.randn(1, 2, 3, 32, 32, generator=generator),
        "text_embedding": torch.randn(1, 8, generator=generator),
        "sequence_mask": torch.ones(1, 2, dtype=torch.float32),
        "frame_valid": torch.ones(1, 2, dtype=torch.float32),
        "audio_valid": torch.ones(1, 2, dtype=torch.float32),
    }


def test_position_capacity_is_not_silently_treated_as_task_segment_count() -> None:
    model = build_tiny_test_student(path_mode="explicit_projected")
    batch = make_tiny_batch()
    batch["frame"] = torch.cat([batch["frame"], batch["frame"][:, :1]], dim=1)
    batch["spectrogram"] = torch.cat(
        [batch["spectrogram"], batch["spectrogram"][:, :1]], dim=1
    )
    for key in ("sequence_mask", "frame_valid", "audio_valid"):
        batch[key] = torch.cat([batch[key], batch[key][:, :1]], dim=1)

    with pytest.raises(ValueError, match="input task segments 3.*position capacity 2"):
        model(**batch)


def make_camera_ready_loss(**overrides: Any) -> torch.nn.Module:
    kwargs: dict[str, Any] = {
        "strong_teacher_dim": 3,
        "weak_teacher_dim": 4,
        "text_dim": 5,
        "projection_dim": 2,
        "alpha_bce": 1.0,
        "alpha_strong_logit": 0.0,
        "alpha_weak_logit": 0.0,
        "alpha_strong_feat": 0.0,
        "alpha_weak_feat": 0.0,
        "alpha_text_align": 0.0,
        "alpha_orth": 0.0,
    }
    kwargs.update(overrides)
    return camera_ready_loss.OVOrthKDLoss(**kwargs)


def make_loss_batch() -> dict[str, torch.Tensor | None]:
    return {
        "student_segment_logits": torch.tensor([[0.2, -0.3]], requires_grad=True),
        "student_decision_features": torch.tensor(
            [[[1.0, 0.0], [0.0, 1.0]]], requires_grad=True
        ),
        "student_audio_aux_features": torch.tensor(
            [[[0.0, 1.0], [1.0, 0.0]]], requires_grad=True
        ),
        "student_query_features": torch.tensor(
            [[[1.0, 0.0], [0.0, 1.0]]], requires_grad=True
        ),
        "segment_labels": torch.tensor([[1.0, 0.0]]),
        "sequence_mask": torch.ones(1, 2),
        "strong_teacher_logits": torch.tensor([[[0.5], [-0.5]]]),
        "strong_teacher_features": torch.ones(1, 2, 3),
        "weak_teacher_logits": torch.tensor([[[0.25], [-0.25]]]),
        "weak_teacher_features": torch.ones(1, 2, 4),
        "text_embeddings": torch.ones(1, 5),
        "strong_teacher_logit_mask": torch.ones(1, 2),
        "strong_teacher_feature_mask": torch.ones(1, 2),
        "weak_teacher_logit_mask": torch.ones(1, 2),
        "weak_teacher_feature_mask": torch.ones(1, 2),
        "text_valid": torch.ones(1),
    }


def test_localization_head_reads_decision_projection() -> None:
    model = build_tiny_test_student(path_mode="explicit_projected")
    model.eval()
    captured: dict[str, torch.Tensor] = {}

    def capture_head_input(_module: torch.nn.Module, inputs: tuple[torch.Tensor, ...]) -> None:
        captured["head_input"] = inputs[0].detach().clone()

    handle = model.segment_head.register_forward_pre_hook(capture_head_input)
    with torch.no_grad():
        outputs = model(**make_tiny_batch())
    handle.remove()

    assert torch.allclose(captured["head_input"], outputs["decision_features"])
    assert captured["head_input"].shape[-1] == model.projection_dim
    assert outputs["shared_features"].shape[-1] == model.fusion_dim


def test_legacy_mode_keeps_shared_head_and_has_no_projection_parameters() -> None:
    model = build_tiny_test_student(path_mode="legacy_shared")
    model.eval()
    captured: dict[str, torch.Tensor] = {}

    def capture_head_input(_module: torch.nn.Module, inputs: tuple[torch.Tensor, ...]) -> None:
        captured["head_input"] = inputs[0].detach().clone()

    handle = model.segment_head.register_forward_pre_hook(capture_head_input)
    with torch.no_grad():
        outputs = model(**make_tiny_batch())
    handle.remove()

    assert outputs["decision_features"] is None
    assert outputs["audio_aux_features"] is None
    assert outputs["query_features"] is None
    assert torch.allclose(captured["head_input"], outputs["shared_features"])
    assert model.segment_head.in_features == model.fusion_dim
    projection_prefixes = ("decision_proj", "audio_aux_proj", "query_proj")
    assert not any(name.startswith(projection_prefixes) for name, _ in model.named_parameters())


def test_student_rejects_unknown_path_mode() -> None:
    with pytest.raises(ValueError, match="Unsupported path_mode: invented"):
        build_tiny_test_student(path_mode="invented")


def test_paper_additive_fusion_is_the_literal_weighted_sum_before_position() -> None:
    model = build_tiny_test_student(
        path_mode="explicit_projected",
        fusion_mode="paper_additive_query_conditioned",
    )
    model.eval()

    with torch.no_grad():
        outputs = model(**make_tiny_batch())

    expected = (
        outputs["gate_weights"][..., 0:1] * outputs["visual_tokens"]
        + outputs["gate_weights"][..., 1:2] * outputs["audio_tokens"]
        + outputs["text_tokens"]
    )
    assert torch.equal(outputs["fused_tokens_before_position"], expected)


def test_fixed_equal_gate_is_literal_and_respects_missing_modalities() -> None:
    model = build_tiny_test_student(
        path_mode="explicit_projected",
        gate_mode="fixed_equal",
    )
    model.eval()
    batch = make_tiny_batch()
    batch["frame_valid"] = torch.tensor([[1.0, 1.0]])
    batch["audio_valid"] = torch.tensor([[1.0, 0.0]])

    with torch.no_grad():
        outputs = model(**batch)

    expected = torch.tensor([[[0.5, 0.5], [1.0, 0.0]]])
    assert torch.equal(outputs["gate_weights"], expected)


@pytest.mark.parametrize(
    ("forced", "expected_both_valid"),
    [
        ((0.0, 1.0), [0.0, 1.0]),
        ((0.25, 0.75), [0.25, 0.75]),
        ((0.5, 0.5), [0.5, 0.5]),
        ((0.75, 0.25), [0.75, 0.25]),
        ((1.0, 0.0), [1.0, 0.0]),
    ],
)
def test_forced_gate_weights_are_literal_and_respect_validity(
    forced: tuple[float, float], expected_both_valid: list[float]
) -> None:
    """Catch approximate gate forcing or an override that revives missing content."""
    model = build_tiny_test_student(
        path_mode="explicit_projected",
        gate_mode="learned_softmax",
    )
    model.eval()
    batch = make_tiny_batch()
    batch["frame_valid"] = torch.tensor([[1.0, 1.0]])
    batch["audio_valid"] = torch.tensor([[1.0, 0.0]])

    with torch.no_grad():
        outputs = model(**batch, forced_gate_weights=forced)

    expected = torch.tensor([[expected_both_valid, [1.0, 0.0]]])
    assert torch.equal(outputs["gate_weights"], expected)


@pytest.mark.parametrize(
    "forced",
    [
        (1.0,),
        (0.2, 0.2),
        (-0.1, 1.1),
        (float("nan"), 0.0),
        (float("inf"), 0.0),
    ],
)
def test_forced_gate_weights_reject_invalid_ratios(forced: tuple[float, ...]) -> None:
    """Catch a diagnostic receipt claiming weights the forward did not apply."""
    model = build_tiny_test_student(path_mode="explicit_projected")

    with pytest.raises(ValueError, match="forced_gate_weights"):
        model(**make_tiny_batch(), forced_gate_weights=forced)


def test_visual_backbone_output_is_the_exact_visual_projection_input() -> None:
    """Catch a timeline audit reading a tensor from a different visual path."""
    model = build_tiny_test_student(path_mode="explicit_projected")
    model.eval()
    captured: dict[str, torch.Tensor] = {}

    def capture_projection_input(
        _module: torch.nn.Module, inputs: tuple[torch.Tensor, ...]
    ) -> None:
        captured["visual_projection_input"] = inputs[0]

    handle = model.visual_proj.register_forward_pre_hook(capture_projection_input)
    with torch.no_grad():
        outputs = model(**make_tiny_batch())
    handle.remove()

    assert torch.equal(
        outputs["visual_backbone_features"],
        captured["visual_projection_input"],
    )


def test_fixed_gate_preserves_counterfactual_initialization_and_ignores_gate() -> None:
    torch.manual_seed(123)
    learned = build_tiny_test_student(
        path_mode="explicit_projected",
        gate_mode="learned_softmax",
    )
    torch.manual_seed(123)
    fixed = build_tiny_test_student(
        path_mode="explicit_projected",
        gate_mode="fixed_equal",
    )

    assert isinstance(fixed.modality_gate, torch.nn.Module)
    learned_state = learned.state_dict()
    fixed_state = fixed.state_dict()
    assert learned_state.keys() == fixed_state.keys()
    for name in learned_state:
        assert torch.equal(learned_state[name], fixed_state[name]), name

    fixed.eval()
    fixed(**make_tiny_batch())["segment_logits"].sum().backward()
    assert all(parameter.grad is None for parameter in fixed.modality_gate.parameters())


def test_additive_fusion_preserves_counterfactual_initialization_and_ignores_mlp() -> None:
    torch.manual_seed(456)
    concat = build_tiny_test_student(
        path_mode="explicit_projected",
        fusion_mode="concat_mlp_query_conditioned",
    )
    torch.manual_seed(456)
    additive = build_tiny_test_student(
        path_mode="explicit_projected",
        fusion_mode="paper_additive_query_conditioned",
    )

    assert isinstance(additive.token_fusion, torch.nn.Module)
    concat_state = concat.state_dict()
    additive_state = additive.state_dict()
    assert concat_state.keys() == additive_state.keys()
    for name in concat_state:
        assert torch.equal(concat_state[name], additive_state[name]), name

    additive.eval()
    additive(**make_tiny_batch())["segment_logits"].sum().backward()
    assert all(
        parameter.grad is None for parameter in additive.token_fusion.parameters()
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"fusion_mode": "invented"}, "Unsupported fusion_mode: invented"),
        ({"gate_mode": "invented"}, "Unsupported gate_mode: invented"),
    ],
)
def test_student_rejects_unknown_fusion_or_gate_mode(
    overrides: dict[str, str],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        build_tiny_test_student(path_mode="explicit_projected", **overrides)


def test_paper_text_alignment_uses_mapped_cosine_probability() -> None:
    assert hasattr(camera_ready_loss, "paper_text_alignment_terms")
    student = torch.tensor([[[0.0, 1.0], [0.0, -1.0]]])
    text = torch.tensor([[1.0, 0.0]])
    labels = torch.tensor([[1.0, 0.0]])

    terms = camera_ready_loss.paper_text_alignment_terms(student, text, labels)

    expected = torch.full_like(terms, torch.log(torch.tensor(2.0)))
    assert torch.allclose(terms, expected, atol=1e-6)


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA is required for AMP coverage")
def test_paper_text_alignment_is_safe_inside_cuda_autocast() -> None:
    student = torch.tensor(
        [[[0.0, 1.0], [0.0, -1.0]]],
        device="cuda",
        dtype=torch.float16,
        requires_grad=True,
    )
    text = torch.tensor([[1.0, 0.0]], device="cuda", dtype=torch.float16)
    labels = torch.tensor([[1.0, 0.0]], device="cuda", dtype=torch.float16)

    with torch.autocast(device_type="cuda", dtype=torch.float16):
        terms = camera_ready_loss.paper_text_alignment_terms(student, text, labels)
    terms.mean().backward()

    assert terms.dtype == torch.float32
    assert torch.isfinite(terms).all()
    assert student.grad is not None
    assert torch.isfinite(student.grad).all()


def test_disabled_logit_kd_does_not_require_teacher_logits() -> None:
    loss_module = make_camera_ready_loss()
    batch = make_loss_batch()
    batch["strong_teacher_logits"] = None
    batch["weak_teacher_logits"] = None
    batch["strong_teacher_logit_mask"] = None
    batch["weak_teacher_logit_mask"] = None

    loss, stats = loss_module(**batch)

    assert torch.isfinite(loss)
    assert stats["strong_logit"] == 0.0
    assert stats["weak_logit"] == 0.0


@pytest.mark.parametrize(
    ("loss_overrides", "missing_field", "message"),
    [
        ({"alpha_strong_feat": 0.4}, "strong_teacher_features", "strong_teacher_features"),
        ({"alpha_strong_feat": 0.4}, "strong_teacher_feature_mask", "strong_teacher_feature_mask"),
        ({"alpha_weak_feat": 0.1}, "weak_teacher_features", "weak_teacher_features"),
        ({"alpha_weak_feat": 0.1}, "weak_teacher_feature_mask", "weak_teacher_feature_mask"),
        ({"alpha_text_align": 0.8}, "text_embeddings", "text_embeddings"),
        ({"alpha_text_align": 0.8}, "text_valid", "text_valid"),
        ({"alpha_weak_logit": 0.2}, "weak_teacher_logits", "weak_teacher_logits"),
        ({"alpha_weak_logit": 0.2}, "weak_teacher_logit_mask", "weak_teacher_logit_mask"),
    ],
)
def test_enabled_loss_term_requires_its_real_artifact_or_mask(
    loss_overrides: dict[str, float],
    missing_field: str,
    message: str,
) -> None:
    loss_module = make_camera_ready_loss(**loss_overrides)
    batch = make_loss_batch()
    batch[missing_field] = None

    with pytest.raises(ValueError, match=message):
        loss_module(**batch)


def test_orthogonality_requires_both_teacher_feature_masks() -> None:
    loss_module = make_camera_ready_loss(alpha_orth=0.5)
    batch = make_loss_batch()
    batch["weak_teacher_feature_mask"] = None

    with pytest.raises(ValueError, match="weak_teacher_feature_mask"):
        loss_module(**batch)


def test_orthogonality_is_squared_cosine_between_explicit_paths() -> None:
    loss_module = make_camera_ready_loss(alpha_bce=0.0, alpha_orth=1.0)
    batch = make_loss_batch()
    batch["student_audio_aux_features"] = batch["student_decision_features"].clone()

    loss, stats = loss_module(**batch)

    assert torch.allclose(loss, torch.tensor(1.0))
    assert stats["orth"] == pytest.approx(1.0)


def test_camera_ready_loss_owns_only_teacher_projectors() -> None:
    loss_module = make_camera_ready_loss()
    parameter_names = {name for name, _ in loss_module.named_parameters()}

    assert any(name.startswith("strong_teacher_proj") for name in parameter_names)
    assert any(name.startswith("weak_teacher_proj") for name in parameter_names)
    assert any(name.startswith("text_teacher_proj") for name in parameter_names)
    assert not any(name.startswith("student_") for name in parameter_names)


def test_visual_l2_reduction_controls_literal_feature_dimension_scaling() -> None:
    batch = make_loss_batch()
    batch["student_decision_features"] = torch.tensor(
        [[[1.0, 2.0], [100.0, 100.0]]], requires_grad=True
    )
    batch["strong_teacher_features"] = torch.zeros(1, 2, 2)
    batch["strong_teacher_feature_mask"] = torch.tensor([[1.0, 0.0]])

    mean_loss_module = make_camera_ready_loss(
        alpha_bce=0.0,
        alpha_strong_feat=1.0,
        visual_l2_reduction="mean_feature_then_masked_mean_segments",
    )
    mean_loss_module.strong_teacher_proj = torch.nn.Identity()
    sum_loss_module = make_camera_ready_loss(
        alpha_bce=0.0,
        alpha_strong_feat=1.0,
        visual_l2_reduction="sum_feature_then_masked_mean_segments",
    )
    sum_loss_module.strong_teacher_proj = torch.nn.Identity()

    mean_loss, mean_stats = mean_loss_module(**batch)
    sum_loss, sum_stats = sum_loss_module(**batch)

    assert mean_loss.item() == pytest.approx(2.5)
    assert mean_stats["strong_feat"] == pytest.approx(2.5)
    assert sum_loss.item() == pytest.approx(5.0)
    assert sum_stats["strong_feat"] == pytest.approx(5.0)


def test_frozen_teacher_target_projectors_require_no_grad() -> None:
    loss_module = make_camera_ready_loss(teacher_target_projector_trainable=False)

    projector_parameters = {
        name: parameter.requires_grad
        for name, parameter in loss_module.named_parameters()
        if name.startswith(
            ("strong_teacher_proj", "weak_teacher_proj", "text_teacher_proj")
        )
    }

    assert projector_parameters
    assert not any(projector_parameters.values())


def test_loss_rejects_unknown_visual_l2_reduction() -> None:
    with pytest.raises(
        ValueError,
        match="Unsupported visual_l2_reduction: invented",
    ):
        make_camera_ready_loss(visual_l2_reduction="invented")


def test_shared_fusion_query_anchor_reuses_exact_fusion_text_projection() -> None:
    model = build_tiny_test_student(
        path_mode="explicit_projected",
        query_anchor_mode="shared_fusion_projection",
    )
    model.eval()

    with torch.no_grad():
        outputs = model(**make_tiny_batch())

    assert outputs["query_features"].shape == (1, 2, model.fusion_dim)
    assert outputs["text_alignment_target"].shape == (1, model.fusion_dim)
    assert torch.equal(
        outputs["text_alignment_target"],
        outputs["text_tokens"][:, 0, :],
    )


def test_shared_query_alignment_uses_student_anchor_without_loss_text_projector() -> None:
    loss_module = make_camera_ready_loss(
        alpha_bce=0.0,
        alpha_text_align=1.0,
        query_anchor_mode="shared_fusion_projection",
    )
    batch = make_loss_batch()
    batch["student_query_features"] = torch.tensor(
        [[[1.0, 0.0], [-1.0, 0.0]]], requires_grad=True
    )
    batch["student_text_anchor"] = torch.tensor(
        [[1.0, 0.0]], requires_grad=True
    )
    batch["text_embeddings"] = None

    loss, stats = loss_module(**batch)
    loss.backward()

    assert torch.isfinite(loss)
    assert stats["text_align"] < 1e-4
    assert batch["student_text_anchor"].grad is not None
    assert not any(
        name.startswith("text_teacher_proj")
        for name, _ in loss_module.named_parameters()
    )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: build_tiny_test_student(
            path_mode="explicit_projected",
            query_anchor_mode="invented",
        ),
        lambda: make_camera_ready_loss(query_anchor_mode="invented"),
    ],
)
def test_student_and_loss_reject_unknown_query_anchor_mode(factory: Any) -> None:
    with pytest.raises(ValueError, match="Unsupported query_anchor_mode: invented"):
        factory()


def test_camera_ready_loss_backward_reaches_each_explicit_student_path() -> None:
    loss_module = make_camera_ready_loss(
        alpha_bce=0.0,
        alpha_strong_feat=0.4,
        alpha_weak_feat=0.3,
        alpha_text_align=0.2,
        alpha_orth=0.1,
    )
    batch = make_loss_batch()

    loss, _ = loss_module(**batch)
    loss.backward()

    for field_name in (
        "student_decision_features",
        "student_audio_aux_features",
        "student_query_features",
    ):
        tensor = batch[field_name]
        assert isinstance(tensor, torch.Tensor)
        assert tensor.grad is not None
        assert torch.isfinite(tensor.grad).all()
