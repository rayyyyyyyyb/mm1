from __future__ import annotations

from typing import Any

import pytest
import torch

import src.losses.ov_orthkd_loss as camera_ready_loss
from src.models.ov_orthkd import OVOrthKDStudent


def build_tiny_test_student(path_mode: str) -> OVOrthKDStudent:
    return OVOrthKDStudent(
        visual_backbone="mobilenetv3_small_100",
        audio_backbone="mobilenetv3_small_100",
        text_dim=8,
        fusion_dim=32,
        projection_dim=16,
        path_mode=path_mode,
        temporal_layers=1,
        temporal_heads=4,
        temporal_dropout=0.0,
        max_segments=2,
        pretrained=False,
    )


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
