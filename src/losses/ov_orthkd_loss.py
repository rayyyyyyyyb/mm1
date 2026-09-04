from __future__ import annotations

from typing import Dict, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F

from src.models.ov_orthkd import ProjectionHead
from src.utils.projector_update_modes import (
    apply_projector_update_modes,
    resolve_projector_update_modes,
)


def _masked_mean(values: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    if values.shape != mask.shape:
        raise ValueError(f"values/mask shape mismatch: {values.shape} vs {mask.shape}")
    mask = mask.to(dtype=values.dtype)
    denom = mask.sum().clamp_min(1.0)
    return (values * mask).sum() / denom


def _zero(reference: torch.Tensor) -> torch.Tensor:
    return reference.new_zeros(())


def _require_tensor(value: torch.Tensor | None, name: str) -> torch.Tensor:
    if value is None:
        raise ValueError(f"Required tensor is missing while its loss is enabled: {name}")
    return value


def paper_text_alignment_terms(
    student_query_features: torch.Tensor,
    projected_text_target: torch.Tensor,
    segment_labels: torch.Tensor,
    eps: float = 1e-6,
) -> torch.Tensor:
    """Compute the paper's mapped-cosine probability BCE terms."""
    if projected_text_target.ndim != 2:
        raise ValueError(
            f"projected_text_target must be [B, D], got {projected_text_target.shape}"
        )
    # CUDA autocast intentionally rejects probability-space BCE.  Keep the
    # paper's mapped-cosine probability formulation, but evaluate this
    # numerically sensitive term in FP32 outside autocast.
    with torch.autocast(device_type=student_query_features.device.type, enabled=False):
        query_fp32 = student_query_features.float()
        target_fp32 = projected_text_target.float()[:, None, :].expand_as(query_fp32)
        labels_fp32 = segment_labels.float()
        cosine = F.cosine_similarity(query_fp32, target_fp32, dim=-1)
        probability = ((cosine + 1.0) * 0.5).clamp(min=eps, max=1.0 - eps)
        return F.binary_cross_entropy(probability, labels_fp32, reduction="none")


class OVOrthKDLoss(nn.Module):
    def __init__(
        self,
        strong_teacher_dim: int,
        weak_teacher_dim: int,
        text_dim: int,
        projection_dim: int = 256,
        temperature: float = 2.0,
        alpha_bce: float = 1.0,
        alpha_strong_logit: float = 0.0,
        alpha_weak_logit: float = 0.0,
        alpha_strong_feat: float = 0.4,
        alpha_weak_feat: float = 0.1,
        alpha_text_align: float = 0.8,
        alpha_orth: float = 0.5,
        text_alignment_mode: str = "paper_probability",
        confidence_weighting: bool = True,
        confidence_scale: float = 2.0,
        visual_l2_reduction: str = "mean_feature_then_masked_mean_segments",
        teacher_target_projector_trainable: bool | None = None,
        strong_teacher_projector_update_mode: str | None = None,
        weak_teacher_projector_update_mode: str | None = None,
        text_teacher_projector_update_mode: str | None = None,
        query_anchor_mode: str = "independent_loss_projection",
    ) -> None:
        super().__init__()
        self.temperature = float(temperature)
        self.alpha_bce = float(alpha_bce)
        self.alpha_strong_logit = float(alpha_strong_logit)
        self.alpha_weak_logit = float(alpha_weak_logit)
        self.alpha_strong_feat = float(alpha_strong_feat)
        self.alpha_weak_feat = float(alpha_weak_feat)
        self.alpha_text_align = float(alpha_text_align)
        self.alpha_orth = float(alpha_orth)
        if text_alignment_mode not in {"paper_probability", "legacy_logit_temperature"}:
            raise ValueError(f"Unsupported text_alignment_mode: {text_alignment_mode}")
        self.text_alignment_mode = text_alignment_mode
        self.confidence_weighting = bool(confidence_weighting)
        self.confidence_scale = float(confidence_scale)
        if visual_l2_reduction not in {
            "mean_feature_then_masked_mean_segments",
            "sum_feature_then_masked_mean_segments",
        }:
            raise ValueError(
                f"Unsupported visual_l2_reduction: {visual_l2_reduction}"
            )
        self.visual_l2_reduction = visual_l2_reduction
        mode_config = {
            "teacher_target_projector_trainable": teacher_target_projector_trainable,
            "strong_teacher_projector_update_mode": strong_teacher_projector_update_mode,
            "weak_teacher_projector_update_mode": weak_teacher_projector_update_mode,
            "text_teacher_projector_update_mode": text_teacher_projector_update_mode,
        }
        mode_config = {key: value for key, value in mode_config.items() if value is not None}
        self.projector_update_modes = resolve_projector_update_modes(mode_config)
        self.teacher_target_projector_trainable = all(
            mode == "trainable" for mode in self.projector_update_modes.values()
        )
        if query_anchor_mode not in {
            "independent_loss_projection",
            "shared_fusion_projection",
        }:
            raise ValueError(f"Unsupported query_anchor_mode: {query_anchor_mode}")
        self.query_anchor_mode = query_anchor_mode

        self.strong_teacher_proj = ProjectionHead(strong_teacher_dim, projection_dim)
        self.weak_teacher_proj = ProjectionHead(weak_teacher_dim, projection_dim)
        self.text_teacher_proj: nn.Module | None
        if query_anchor_mode == "independent_loss_projection":
            self.text_teacher_proj = ProjectionHead(text_dim, projection_dim)
        else:
            self.text_teacher_proj = None
        apply_projector_update_modes(self, self.projector_update_modes)

    def forward(
        self,
        *,
        student_segment_logits: torch.Tensor,
        student_decision_features: torch.Tensor,
        student_audio_aux_features: torch.Tensor,
        student_query_features: torch.Tensor,
        segment_labels: torch.Tensor,
        sequence_mask: torch.Tensor,
        strong_teacher_logits: torch.Tensor | None = None,
        strong_teacher_features: torch.Tensor | None = None,
        weak_teacher_logits: torch.Tensor | None = None,
        weak_teacher_features: torch.Tensor | None = None,
        text_embeddings: torch.Tensor | None = None,
        student_text_anchor: torch.Tensor | None = None,
        strong_teacher_logit_mask: torch.Tensor | None = None,
        strong_teacher_feature_mask: torch.Tensor | None = None,
        weak_teacher_logit_mask: torch.Tensor | None = None,
        weak_teacher_feature_mask: torch.Tensor | None = None,
        text_valid: torch.Tensor | None = None,
    ) -> Tuple[torch.Tensor, Dict[str, float]]:
        sequence_mask = sequence_mask.to(dtype=student_segment_logits.dtype)
        segment_labels = segment_labels.to(dtype=student_segment_logits.dtype)

        bce_terms = F.binary_cross_entropy_with_logits(
            student_segment_logits,
            segment_labels,
            reduction="none",
        )
        bce_loss = _masked_mean(bce_terms, sequence_mask)

        strong_logit_loss = _zero(student_segment_logits)
        if self.alpha_strong_logit > 0:
            teacher_logits = _require_tensor(strong_teacher_logits, "strong_teacher_logits")
            logit_mask = _require_tensor(
                strong_teacher_logit_mask, "strong_teacher_logit_mask"
            ).to(dtype=student_segment_logits.dtype)
            teacher_logits = teacher_logits.squeeze(-1)
            teacher_probs = torch.sigmoid(teacher_logits / self.temperature)
            student_logits_t = student_segment_logits / self.temperature
            terms = F.binary_cross_entropy_with_logits(
                student_logits_t, teacher_probs, reduction="none"
            ) * (self.temperature**2)
            if self.confidence_weighting:
                confidence = torch.sigmoid(teacher_logits.abs() * self.confidence_scale)
                logit_mask = logit_mask * confidence
            strong_logit_loss = _masked_mean(terms, sequence_mask * logit_mask)

        weak_logit_loss = _zero(student_segment_logits)
        if self.alpha_weak_logit > 0:
            teacher_logits = _require_tensor(weak_teacher_logits, "weak_teacher_logits")
            logit_mask = _require_tensor(
                weak_teacher_logit_mask, "weak_teacher_logit_mask"
            ).to(dtype=student_segment_logits.dtype)
            teacher_logits = teacher_logits.squeeze(-1)
            teacher_probs = torch.sigmoid(teacher_logits / self.temperature)
            student_logits_t = student_segment_logits / self.temperature
            terms = F.binary_cross_entropy_with_logits(
                student_logits_t, teacher_probs, reduction="none"
            ) * (self.temperature**2)
            weak_logit_loss = _masked_mean(terms, sequence_mask * logit_mask)

        strong_feat_loss = _zero(student_segment_logits)
        strong_mask_for_orth: torch.Tensor | None = None
        if self.alpha_strong_feat > 0 or self.alpha_orth > 0:
            strong_features = _require_tensor(strong_teacher_features, "strong_teacher_features")
            strong_mask_for_orth = _require_tensor(
                strong_teacher_feature_mask, "strong_teacher_feature_mask"
            ).to(dtype=student_segment_logits.dtype)
            strong_target = self.strong_teacher_proj(strong_features.detach())
            if self.alpha_strong_feat > 0:
                squared_error = (student_decision_features - strong_target).pow(2)
                if (
                    self.visual_l2_reduction
                    == "mean_feature_then_masked_mean_segments"
                ):
                    strong_terms = squared_error.mean(dim=-1)
                else:
                    strong_terms = squared_error.sum(dim=-1)
                strong_feat_loss = _masked_mean(
                    strong_terms, sequence_mask * strong_mask_for_orth
                )

        weak_feat_loss = _zero(student_segment_logits)
        weak_mask_for_orth: torch.Tensor | None = None
        if self.alpha_weak_feat > 0 or self.alpha_orth > 0:
            weak_features = _require_tensor(weak_teacher_features, "weak_teacher_features")
            weak_mask_for_orth = _require_tensor(
                weak_teacher_feature_mask, "weak_teacher_feature_mask"
            ).to(dtype=student_segment_logits.dtype)
            weak_target = self.weak_teacher_proj(weak_features.detach())
            if self.alpha_weak_feat > 0:
                weak_terms = 1.0 - F.cosine_similarity(
                    student_audio_aux_features, weak_target, dim=-1
                )
                weak_feat_loss = _masked_mean(
                    weak_terms, sequence_mask * weak_mask_for_orth
                )

        text_align_loss = _zero(student_segment_logits)
        if self.alpha_text_align > 0:
            text_valid = _require_tensor(text_valid, "text_valid").to(
                dtype=student_segment_logits.dtype
            )
            if self.query_anchor_mode == "shared_fusion_projection":
                text_target = _require_tensor(
                    student_text_anchor,
                    "student_text_anchor",
                )
            else:
                text_embeddings = _require_tensor(text_embeddings, "text_embeddings")
                if self.text_teacher_proj is None:
                    raise RuntimeError("independent text teacher projector is missing")
                text_target = self.text_teacher_proj(text_embeddings.detach())
            if (
                text_target.shape[0] != student_query_features.shape[0]
                or text_target.shape[-1] != student_query_features.shape[-1]
            ):
                raise ValueError(
                    "student query/text anchor shape mismatch: "
                    f"{student_query_features.shape} vs {text_target.shape}"
                )
            if self.text_alignment_mode == "paper_probability":
                text_terms = paper_text_alignment_terms(
                    student_query_features=student_query_features,
                    projected_text_target=text_target,
                    segment_labels=segment_labels,
                )
            else:
                expanded = text_target[:, None, :].expand_as(student_query_features)
                text_logits = F.cosine_similarity(
                    student_query_features, expanded, dim=-1
                ) / 0.07
                text_terms = F.binary_cross_entropy_with_logits(
                    text_logits, segment_labels, reduction="none"
                )
            text_align_loss = _masked_mean(
                text_terms,
                sequence_mask * text_valid[:, None],
            )

        orth_loss = _zero(student_segment_logits)
        if self.alpha_orth > 0:
            if strong_mask_for_orth is None or weak_mask_for_orth is None:
                raise RuntimeError("Orthogonality requires both teacher feature masks")
            orth_terms = F.cosine_similarity(
                student_decision_features,
                student_audio_aux_features,
                dim=-1,
            ).pow(2)
            orth_loss = _masked_mean(
                orth_terms,
                sequence_mask * strong_mask_for_orth * weak_mask_for_orth,
            )

        total_loss = (
            self.alpha_bce * bce_loss
            + self.alpha_strong_logit * strong_logit_loss
            + self.alpha_weak_logit * weak_logit_loss
            + self.alpha_strong_feat * strong_feat_loss
            + self.alpha_weak_feat * weak_feat_loss
            + self.alpha_text_align * text_align_loss
            + self.alpha_orth * orth_loss
        )

        stats = {
            "bce": float(bce_loss.detach().cpu()),
            "strong_logit": float(strong_logit_loss.detach().cpu()),
            "weak_logit": float(weak_logit_loss.detach().cpu()),
            "strong_feat": float(strong_feat_loss.detach().cpu()),
            "weak_feat": float(weak_feat_loss.detach().cpu()),
            "text_align": float(text_align_loss.detach().cpu()),
            "orth": float(orth_loss.detach().cpu()),
            "total": float(total_loss.detach().cpu()),
        }
        return total_loss, stats
