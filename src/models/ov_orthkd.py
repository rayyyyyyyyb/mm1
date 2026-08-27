from __future__ import annotations

from typing import Dict, Optional

import timm
import torch
import torch.nn as nn


class SequenceImageEncoder(nn.Module):
    def __init__(self, model_name: str, pretrained: bool = False) -> None:
        super().__init__()
        self.backbone = timm.create_model(model_name, pretrained=pretrained, num_classes=0, global_pool="avg")
        self.feature_dim = self._infer_feature_dim()

    def _infer_feature_dim(self) -> int:
        declared = getattr(self.backbone, "head_hidden_size", None)
        if declared is None:
            declared = getattr(self.backbone, "num_features", None)
        if declared is not None:
            return int(declared)
        was_training = self.backbone.training
        try:
            self.backbone.eval()
            with torch.inference_mode():
                probe = torch.zeros(1, 3, 224, 224)
                features = self.backbone(probe)
            return int(features.shape[-1])
        finally:
            self.backbone.train(was_training)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        batch_size, seq_len = x.shape[:2]
        flattened = x.reshape(batch_size * seq_len, *x.shape[2:])
        encoded = self.backbone(flattened)
        return encoded.reshape(batch_size, seq_len, -1)


class ProjectionHead(nn.Module):
    def __init__(self, in_dim: int, out_dim: int, hidden_dim: int | None = None) -> None:
        super().__init__()
        hidden_dim = hidden_dim or out_dim
        self.net = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
            nn.Linear(hidden_dim, out_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class OVOrthKDStudent(nn.Module):
    def __init__(
        self,
        visual_backbone: str,
        audio_backbone: str,
        text_dim: int,
        fusion_dim: int = 384,
        projection_dim: int = 256,
        path_mode: str = "explicit_projected",
        temporal_layers: int = 4,
        temporal_heads: int = 8,
        temporal_dropout: float = 0.1,
        max_position_segments: int = 16,
        max_segments: int | None = None,
        pretrained: bool = False,
        fusion_mode: str = "concat_mlp_query_conditioned",
        gate_mode: str = "learned_softmax",
        query_anchor_mode: str = "independent_loss_projection",
    ) -> None:
        super().__init__()
        if path_mode not in {"explicit_projected", "legacy_shared"}:
            raise ValueError(f"Unsupported path_mode: {path_mode}")
        if fusion_mode not in {
            "concat_mlp_query_conditioned",
            "paper_additive_query_conditioned",
        }:
            raise ValueError(f"Unsupported fusion_mode: {fusion_mode}")
        if gate_mode not in {"learned_softmax", "fixed_equal"}:
            raise ValueError(f"Unsupported gate_mode: {gate_mode}")
        if query_anchor_mode not in {
            "independent_loss_projection",
            "shared_fusion_projection",
        }:
            raise ValueError(f"Unsupported query_anchor_mode: {query_anchor_mode}")
        if (
            query_anchor_mode == "shared_fusion_projection"
            and path_mode != "explicit_projected"
        ):
            raise ValueError(
                "shared_fusion_projection query anchor requires "
                "path_mode explicit_projected"
            )

        self.visual_encoder = SequenceImageEncoder(visual_backbone, pretrained=pretrained)
        self.audio_encoder = SequenceImageEncoder(audio_backbone, pretrained=pretrained)
        self.visual_dim = self.visual_encoder.feature_dim
        self.audio_dim = self.audio_encoder.feature_dim
        self.text_dim = text_dim
        self.fusion_dim = fusion_dim
        self.projection_dim = projection_dim
        self.path_mode = path_mode
        self.fusion_mode = fusion_mode
        self.gate_mode = gate_mode
        self.query_anchor_mode = query_anchor_mode
        if max_segments is not None:
            max_position_segments = int(max_segments)
        self.max_position_segments = int(max_position_segments)
        if self.max_position_segments < 1:
            raise ValueError("max_position_segments must be positive")

        self.visual_proj = nn.Sequential(
            nn.LayerNorm(self.visual_dim),
            nn.Linear(self.visual_dim, fusion_dim),
            nn.GELU(),
            nn.Dropout(temporal_dropout),
        )
        self.audio_proj = nn.Sequential(
            nn.LayerNorm(self.audio_dim),
            nn.Linear(self.audio_dim, fusion_dim),
            nn.GELU(),
            nn.Dropout(temporal_dropout),
        )
        self.text_proj = nn.Sequential(
            nn.LayerNorm(text_dim),
            nn.Linear(text_dim, fusion_dim),
            nn.GELU(),
            nn.Dropout(temporal_dropout),
        )

        # Keep the learned gate instantiated in fixed-gate diagnostics so the
        # intervention does not alter RNG consumption or downstream parameter
        # initialization. The fixed forward branch deliberately ignores it.
        self.modality_gate: nn.Module = nn.Sequential(
            nn.Linear(fusion_dim * 3 + 2, fusion_dim),
            nn.GELU(),
            nn.Linear(fusion_dim, 2),
        )

        self.token_fusion: nn.Module | None
        if fusion_mode == "concat_mlp_query_conditioned":
            self.token_fusion = nn.Sequential(
                nn.LayerNorm(fusion_dim * 3),
                nn.Linear(fusion_dim * 3, fusion_dim),
                nn.GELU(),
                nn.Dropout(temporal_dropout),
            )
        else:
            self.token_fusion = None
        self.position_embedding = nn.Parameter(
            torch.zeros(1, self.max_position_segments, fusion_dim)
        )

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=fusion_dim,
            nhead=temporal_heads,
            dim_feedforward=fusion_dim * 4,
            dropout=temporal_dropout,
            activation="gelu",
            batch_first=True,
            norm_first=False,
        )
        self.temporal_encoder = nn.TransformerEncoder(
            encoder_layer,
            num_layers=temporal_layers,
            enable_nested_tensor=False,
        )
        if path_mode == "explicit_projected":
            self.decision_proj = ProjectionHead(fusion_dim, projection_dim)
            self.audio_aux_proj = ProjectionHead(fusion_dim, projection_dim)
            query_dim = (
                fusion_dim
                if query_anchor_mode == "shared_fusion_projection"
                else projection_dim
            )
            self.query_proj = ProjectionHead(fusion_dim, query_dim)
            self.segment_head = nn.Linear(projection_dim, 1)
        else:
            self.segment_head = nn.Linear(fusion_dim, 1)

    def forward(
        self,
        frame: torch.Tensor,
        spectrogram: torch.Tensor,
        text_embedding: torch.Tensor,
        sequence_mask: torch.Tensor,
        frame_valid: Optional[torch.Tensor] = None,
        audio_valid: Optional[torch.Tensor] = None,
    ) -> Dict[str, torch.Tensor | None]:
        input_segments = int(frame.shape[1])
        if input_segments > self.max_position_segments:
            raise ValueError(
                f"input task segments {input_segments} exceed student position capacity "
                f"{self.max_position_segments}"
            )
        visual_tokens = self.visual_proj(self.visual_encoder(frame))
        audio_tokens = self.audio_proj(self.audio_encoder(spectrogram))
        projected_text = self.text_proj(text_embedding)
        text_token = projected_text.unsqueeze(1).expand(
            -1, visual_tokens.size(1), -1
        )

        if frame_valid is None:
            frame_valid = torch.ones(frame.size(0), frame.size(1), device=frame.device)
        if audio_valid is None:
            audio_valid = torch.ones(frame.size(0), frame.size(1), device=frame.device)

        validity = torch.stack([frame_valid, audio_valid], dim=-1)
        gate_input = torch.cat(
            [
                visual_tokens,
                audio_tokens,
                text_token,
                frame_valid.unsqueeze(-1),
                audio_valid.unsqueeze(-1),
            ],
            dim=-1,
        )
        both_missing = validity.sum(dim=-1, keepdim=True) == 0
        if self.gate_mode == "learned_softmax":
            if self.modality_gate is None:
                raise RuntimeError("learned_softmax gate module is missing")
            gate_logits = self.modality_gate(gate_input)
            gate_logits = gate_logits.masked_fill(validity <= 0, -1e4)
            gate_logits = torch.where(both_missing, torch.zeros_like(gate_logits), gate_logits)
            gate_weights = torch.softmax(gate_logits, dim=-1)
        else:
            fixed_validity = validity.to(dtype=visual_tokens.dtype)
            denominator = fixed_validity.sum(dim=-1, keepdim=True).clamp_min(1.0)
            gate_weights = fixed_validity / denominator
            gate_weights = torch.where(
                both_missing,
                torch.full_like(gate_weights, 0.5),
                gate_weights,
            )
            gate_logits = torch.log(gate_weights.clamp_min(1e-12))

        weighted_visual = visual_tokens * gate_weights[..., 0:1]
        weighted_audio = audio_tokens * gate_weights[..., 1:2]
        if self.fusion_mode == "concat_mlp_query_conditioned":
            if self.token_fusion is None:
                raise RuntimeError("concat fusion module is missing")
            fused_tokens = self.token_fusion(
                torch.cat([weighted_visual, weighted_audio, text_token], dim=-1)
            )
        else:
            fused_tokens = weighted_visual + weighted_audio + text_token
        fused_tokens_before_position = fused_tokens

        seq_len = fused_tokens.size(1)
        fused_tokens = fused_tokens + self.position_embedding[:, :seq_len, :]
        shared_features = self.temporal_encoder(
            fused_tokens,
            src_key_padding_mask=~sequence_mask.bool(),
        )

        decision_features: torch.Tensor | None = None
        audio_aux_features: torch.Tensor | None = None
        query_features: torch.Tensor | None = None
        if self.path_mode == "explicit_projected":
            decision_features = self.decision_proj(shared_features)
            audio_aux_features = self.audio_aux_proj(shared_features)
            query_features = self.query_proj(shared_features)
            segment_logits = self.segment_head(decision_features).squeeze(-1)
        else:
            segment_logits = self.segment_head(shared_features).squeeze(-1)

        return {
            "segment_logits": segment_logits,
            "shared_features": shared_features,
            "decision_features": decision_features,
            "audio_aux_features": audio_aux_features,
            "query_features": query_features,
            "segment_features": shared_features,
            "visual_tokens": visual_tokens,
            "audio_tokens": audio_tokens,
            "text_tokens": text_token,
            "gate_logits": gate_logits,
            "gate_weights": gate_weights,
            "fused_tokens_before_position": fused_tokens_before_position,
            "text_alignment_target": (
                projected_text
                if self.query_anchor_mode == "shared_fusion_projection"
                else None
            ),
        }
