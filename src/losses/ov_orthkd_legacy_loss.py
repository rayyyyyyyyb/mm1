from __future__ import annotations

from typing import Dict, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F

from src.models.ov_orthkd import ProjectionHead


def _masked_mean(values: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    mask = mask.float()
    denom = mask.sum().clamp_min(1.0)
    return (values * mask).sum() / denom


class OVOrthKDLegacyLoss(nn.Module):
    """Frozen collaboration-base loss kept for controlled legacy comparisons."""

    def __init__(
        self,
        student_dim: int,
        strong_teacher_dim: int,
        weak_teacher_dim: int,
        text_dim: int,
        projection_dim: int = 256,
        temperature: float = 2.0,
        text_temperature: float = 0.07,
        alpha_bce: float = 1.0,
        alpha_strong_logit: float = 0.8,
        alpha_weak_logit: float = 0.0,
        alpha_strong_feat: float = 0.4,
        alpha_weak_feat: float = 0.25,
        alpha_text_align: float = 0.3,
        alpha_orth: float = 0.15,
        confidence_weighting: bool = True,
        confidence_scale: float = 2.0,
    ) -> None:
        super().__init__()
        self.temperature = temperature
        self.text_temperature = text_temperature
        self.alpha_bce = alpha_bce
        self.alpha_strong_logit = alpha_strong_logit
        self.alpha_weak_logit = alpha_weak_logit
        self.alpha_strong_feat = alpha_strong_feat
        self.alpha_weak_feat = alpha_weak_feat
        self.alpha_text_align = alpha_text_align
        self.alpha_orth = alpha_orth
        self.confidence_weighting = confidence_weighting
        self.confidence_scale = confidence_scale

        self.student_strong_proj = ProjectionHead(student_dim, projection_dim)
        self.student_weak_proj = ProjectionHead(student_dim, projection_dim)
        self.student_text_proj = ProjectionHead(student_dim, projection_dim)
        self.strong_teacher_proj = ProjectionHead(strong_teacher_dim, projection_dim)
        self.weak_teacher_proj = ProjectionHead(weak_teacher_dim, projection_dim)
        self.text_teacher_proj = ProjectionHead(text_dim, projection_dim)

    def forward(
        self,
        student_segment_logits: torch.Tensor,
        student_segment_features: torch.Tensor,
        strong_teacher_logits: torch.Tensor,
        strong_teacher_features: torch.Tensor,
        weak_teacher_logits: torch.Tensor | None = None,
        weak_teacher_features: torch.Tensor | None = None,
        text_embeddings: torch.Tensor | None = None,
        segment_labels: torch.Tensor | None = None,
        sequence_mask: torch.Tensor | None = None,
        strong_teacher_logit_mask: torch.Tensor | None = None,
        strong_teacher_feature_mask: torch.Tensor | None = None,
        weak_teacher_mask: torch.Tensor | None = None,
        text_valid: torch.Tensor | None = None,
    ) -> Tuple[torch.Tensor, Dict[str, float]]:
        bce_terms = F.binary_cross_entropy_with_logits(
            student_segment_logits,
            segment_labels,
            reduction="none",
        )
        bce_loss = _masked_mean(bce_terms, sequence_mask)

        teacher_logits = strong_teacher_logits.squeeze(-1)
        teacher_probs = torch.sigmoid(teacher_logits / self.temperature)
        student_logits = student_segment_logits / self.temperature
        logit_terms = F.binary_cross_entropy_with_logits(student_logits, teacher_probs, reduction="none")
        if self.confidence_weighting:
            confidence = torch.sigmoid(teacher_logits.abs() * self.confidence_scale)
            strong_logit_mask = strong_teacher_logit_mask * confidence
        else:
            strong_logit_mask = strong_teacher_logit_mask
        strong_logit_loss = _masked_mean(logit_terms * (self.temperature**2), strong_logit_mask)

        weak_logit_loss = torch.tensor(0.0, device=student_segment_logits.device)
        if self.alpha_weak_logit > 0 and weak_teacher_logits is not None:
            w_teacher_logits = weak_teacher_logits.squeeze(-1)
            w_teacher_probs = torch.sigmoid(w_teacher_logits / self.temperature)
            w_logit_terms = F.binary_cross_entropy_with_logits(student_logits, w_teacher_probs, reduction="none")
            weak_logit_loss = _masked_mean(w_logit_terms * (self.temperature**2), weak_teacher_mask)

        student_strong = self.student_strong_proj(student_segment_features)
        student_weak = self.student_weak_proj(student_segment_features)
        student_text = self.student_text_proj(student_segment_features)
        strong_target = self.strong_teacher_proj(strong_teacher_features.detach())
        weak_target = self.weak_teacher_proj(weak_teacher_features.detach())
        text_target = self.text_teacher_proj(text_embeddings.detach())[:, None, :]

        strong_feat_terms = (student_strong - strong_target).pow(2).mean(dim=-1)
        strong_feat_loss = _masked_mean(strong_feat_terms, strong_teacher_feature_mask)

        weak_cosine = 1.0 - F.cosine_similarity(student_weak, weak_target, dim=-1)
        weak_feat_loss = _masked_mean(weak_cosine, weak_teacher_mask)

        text_sim = F.cosine_similarity(
            F.normalize(student_text, dim=-1),
            F.normalize(text_target.expand_as(student_text), dim=-1),
            dim=-1,
        ) / self.text_temperature
        text_mask = sequence_mask * text_valid[:, None]
        text_align_terms = F.binary_cross_entropy_with_logits(text_sim, segment_labels, reduction="none")
        text_align_loss = _masked_mean(text_align_terms, text_mask)

        orth_terms = (
            F.normalize(student_strong, dim=-1) * F.normalize(student_weak, dim=-1)
        ).sum(dim=-1).pow(2)
        orth_loss = _masked_mean(orth_terms, strong_teacher_feature_mask * weak_teacher_mask)

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
            "bce": float(bce_loss.detach()),
            "strong_logit": float(strong_logit_loss.detach()),
            "weak_logit": float(weak_logit_loss.detach()),
            "strong_feat": float(strong_feat_loss.detach()),
            "weak_feat": float(weak_feat_loss.detach()),
            "text_align": float(text_align_loss.detach()),
            "orth": float(orth_loss.detach()),
            "total": float(total_loss.detach()),
        }
        return total_loss, stats
