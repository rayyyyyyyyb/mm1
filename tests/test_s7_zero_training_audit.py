from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset

from scripts.diagnose_s7_zero_training import (
    GATE_GRID,
    TIMELINE_STATE_LABELS,
    apply_audio_intervention,
    audit_frame_sequence,
    collect_intervention_predictions,
    fusion_input_block_norms,
    input_jacobian_norms,
    intervention_mode_names,
    reserve_output_paths,
    validate_identity_gate_config,
    verify_reconstructed_zero_step,
)
from src.data.ov_avel_dataset import ov_avel_collate_fn
from src.utils.zero_training_diagnostics import build_audio_donor_maps
from tests.test_paper_faithfulness import build_tiny_test_student, make_tiny_batch


def _write_rgb(path: Path, value: int) -> None:
    Image.new("RGB", (5, 4), (value, value, value)).save(path, format="PNG")


def test_frame_sequence_audit_binds_all_hashes_and_retains_duplicate(tmp_path: Path) -> None:
    paths = []
    for index in range(10):
        path = tmp_path / f"frame_{index:02d}.png"
        _write_rgb(path, 30 if index in {3, 7} else index)
        paths.append(path)

    report = audit_frame_sequence(paths)

    assert report["frame_count"] == 10
    assert len(report["frame_sha256"]) == 10
    assert len(report["canonical_sha256"]) == 64
    assert report["exact_duplicate_file_count"] == 1
    assert report["exact_duplicate_groups"] == [[3, 7]]
    assert len(report["adjacent_pixel_mean_absolute_difference"]) == 9
    assert all(
        value >= 0.0
        for value in report["adjacent_pixel_mean_absolute_difference"]
    )


def test_frame_sequence_audit_requires_exact_official_ten(tmp_path: Path) -> None:
    paths = []
    for index in range(9):
        path = tmp_path / f"frame_{index:02d}.png"
        _write_rgb(path, index)
        paths.append(path)

    with pytest.raises(ValueError, match="exactly 10"):
        audit_frame_sequence(paths)


def test_reconstructed_zero_step_must_match_stored_head_receipt() -> None:
    model = build_tiny_test_student(path_mode="explicit_projected")
    expected = {
        "global_step_before_update": 0,
        "segment_head": {
            "weight_l2": float(
                model.segment_head.weight.detach().double().norm()
            ),
            "bias": [
                float(value)
                for value in model.segment_head.bias.detach().tolist()
            ],
        },
    }

    receipt = verify_reconstructed_zero_step(expected, model)

    assert receipt["identity"] == "reconstructed_zero_step"
    assert receipt["stored_global_step_before_update"] == 0
    changed = copy.deepcopy(expected)
    changed["segment_head"]["bias"][0] += 1e-3
    with pytest.raises(ValueError, match="segment-head bias"):
        verify_reconstructed_zero_step(changed, model)


def test_timeline_and_gate_grid_are_literal_and_ordered() -> None:
    assert TIMELINE_STATE_LABELS == (
        "reconstructed_zero_step",
        "step_000400",
        "step_000800",
        "step_001200",
    )
    assert GATE_GRID == (
        (0.0, 1.0),
        (0.25, 0.75),
        (0.5, 0.5),
        (0.75, 0.25),
        (1.0, 0.0),
    )


def test_concat_fusion_blocks_are_visual_audio_query_in_exact_order() -> None:
    model = build_tiny_test_student(
        path_mode="explicit_projected",
        fusion_mode="concat_mlp_query_conditioned",
    )

    report = fusion_input_block_norms(model)

    assert report["block_order"] == ["visual", "audio", "query"]
    assert report["first_linear_shape"] == [model.fusion_dim, 3 * model.fusion_dim]
    assert [report["blocks"][name]["column_count"] for name in report["block_order"]] == [
        model.fusion_dim,
        model.fusion_dim,
        model.fusion_dim,
    ]
    squared = sum(report["blocks"][name]["frobenius_l2"] ** 2 for name in report["block_order"])
    assert squared == pytest.approx(report["first_linear_frobenius_l2"] ** 2)


def test_input_jacobians_are_finite_without_parameter_or_gradient_mutation() -> None:
    model = build_tiny_test_student(path_mode="explicit_projected")
    model.eval()
    before = {name: value.detach().clone() for name, value in model.state_dict().items()}
    assert all(parameter.grad is None for parameter in model.parameters())

    report = input_jacobian_norms(
        model,
        make_tiny_batch(),
        forced_gate_weights=(0.5, 0.5),
    )

    assert report["input_order"] == ["visual", "audio", "query"]
    assert all(np.isfinite(report["l2"][name]) for name in report["input_order"])
    assert all(report["l2"][name] >= 0.0 for name in report["input_order"])
    assert all(parameter.grad is None for parameter in model.parameters())
    after = model.state_dict()
    assert before.keys() == after.keys()
    assert all(torch.equal(before[name], after[name]) for name in before)


def _audio_batch() -> dict[str, Any]:
    batch = make_tiny_batch()
    batch.update(
        {
            "id": ["a"],
            "query": ["q"],
            "split_type": ["seen"],
            "selected_segment_indices": [[0, 1]],
            "segment_label": torch.tensor([[1.0, 0.0]]),
        }
    )
    return batch


@pytest.mark.parametrize(
    "mode",
    ["same_query_donor", "different_query_donor", "temporal_shuffle"],
)
def test_audio_interventions_only_change_paired_audio_fields(mode: str) -> None:
    batch = _audio_batch()
    donor = _audio_batch()
    donor["spectrogram"] = torch.full_like(batch["spectrogram"], 17.0)
    donor["audio_valid"] = torch.tensor([[0.0, 1.0]])

    result = apply_audio_intervention(
        batch,
        mode=mode,
        donor_batch=donor if mode != "temporal_shuffle" else None,
        seed=4,
    )

    for name in (
        "id",
        "query",
        "split_type",
        "selected_segment_indices",
        "segment_label",
        "frame",
        "frame_valid",
        "sequence_mask",
        "text_embedding",
    ):
        if isinstance(batch[name], torch.Tensor):
            assert torch.equal(result[name], batch[name]), name
        else:
            assert result[name] == batch[name], name
    if mode != "temporal_shuffle":
        assert torch.equal(result["spectrogram"], donor["spectrogram"])
        assert torch.equal(result["audio_valid"], donor["audio_valid"])
    else:
        source_pairs = sorted(
            zip(batch["spectrogram"][0, :, 0, 0, 0].tolist(), batch["audio_valid"][0].tolist())
        )
        result_pairs = sorted(
            zip(result["spectrogram"][0, :, 0, 0, 0].tolist(), result["audio_valid"][0].tolist())
        )
        assert result_pairs == source_pairs


def test_audio_donor_intervention_rejects_mismatched_batch() -> None:
    donor = _audio_batch()
    donor["spectrogram"] = donor["spectrogram"].repeat(2, 1, 1, 1, 1)
    donor["audio_valid"] = donor["audio_valid"].repeat(2, 1)

    with pytest.raises(ValueError, match="shape"):
        apply_audio_intervention(
            _audio_batch(),
            mode="same_query_donor",
            donor_batch=donor,
        )


def test_output_reservation_refuses_collisions_and_existing_files(tmp_path: Path) -> None:
    output = tmp_path / "audit.json"
    predictions = tmp_path / "predictions.npz"
    reserve_output_paths(output, predictions)
    output.write_text("occupied", encoding="utf-8")
    with pytest.raises(FileExistsError):
        reserve_output_paths(output, predictions)
    with pytest.raises(ValueError, match="distinct"):
        reserve_output_paths(predictions, predictions)


class _TinyT10Dataset(Dataset[dict[str, Any]]):
    def __init__(self) -> None:
        self.records = [
            {"id": "q0_a", "query": "q0"},
            {"id": "q0_b", "query": "q0"},
            {"id": "q1_a", "query": "q1"},
            {"id": "q1_b", "query": "q1"},
        ]

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, index: int) -> dict[str, Any]:
        record = self.records[index]
        timeline = torch.arange(10, dtype=torch.float32).view(10, 1, 1, 1)
        scalar_sequence = torch.arange(10, dtype=torch.float32).view(10, 1)
        labels = torch.tensor([0.0, 1.0] * 5)
        return {
            "id": record["id"],
            "query": record["query"],
            "domain": "seen",
            "split_type": "seen",
            "selected_segment_indices": list(range(10)),
            "temporal_sampling_policy": "error",
            "noncanonical_temporal_sampling": False,
            "meta": {},
            "frame": timeline + 100.0 * index,
            "spectrogram": timeline + 10.0 * index,
            "segment_label": labels,
            "sequence_mask": torch.ones(10),
            "frame_valid": torch.ones(10),
            "audio_valid": torch.ones(10),
            "strong_teacher_logits": scalar_sequence,
            "strong_teacher_logit_mask": torch.ones(10),
            "strong_teacher_feature_mask": torch.ones(10),
            "strong_teacher_features": scalar_sequence,
            "weak_teacher_features": scalar_sequence,
            "weak_teacher_feature_mask": torch.ones(10),
            "weak_teacher_mask": torch.ones(10),
            "weak_teacher_logits": scalar_sequence,
            "weak_teacher_logit_mask": torch.ones(10),
            "text_embedding": torch.tensor([float(index), 1.0]),
            "text_valid": torch.tensor(1.0),
        }


class _TinyInterventionStudent(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.scale = torch.nn.Parameter(torch.tensor(0.1))

    def forward(
        self,
        *,
        frame: torch.Tensor,
        spectrogram: torch.Tensor,
        text_embedding: torch.Tensor,
        sequence_mask: torch.Tensor,
        frame_valid: torch.Tensor,
        audio_valid: torch.Tensor,
        forced_gate_weights: tuple[float, float] | None = None,
    ) -> dict[str, torch.Tensor]:
        del sequence_mask
        visual = frame.reshape(frame.shape[0], frame.shape[1], -1).mean(dim=-1, keepdim=True)
        audio = spectrogram.reshape(
            spectrogram.shape[0], spectrogram.shape[1], -1
        ).mean(dim=-1, keepdim=True)
        query = text_embedding[:, None, :1].expand(-1, frame.shape[1], -1)
        validity = torch.stack([frame_valid, audio_valid], dim=-1)
        if forced_gate_weights is None:
            weights = validity / validity.sum(dim=-1, keepdim=True)
        else:
            requested = frame.new_tensor(forced_gate_weights).view(1, 1, 2)
            weighted = requested * validity
            weights = weighted / weighted.sum(dim=-1, keepdim=True)
        logits = self.scale * (
            weights[..., 0] * visual.squeeze(-1)
            + weights[..., 1] * audio.squeeze(-1)
            + query.squeeze(-1)
        )
        return {
            "segment_logits": logits,
            "gate_weights": weights,
            "visual_tokens": visual,
            "audio_tokens": audio,
            "text_tokens": query,
        }


def test_full_intervention_matrix_is_aligned_t10_and_read_only() -> None:
    dataset = _TinyT10Dataset()
    loader = DataLoader(
        dataset,
        batch_size=2,
        shuffle=False,
        num_workers=0,
        collate_fn=ov_avel_collate_fn,
    )
    ids = [record["id"] for record in dataset.records]
    queries = [record["query"] for record in dataset.records]
    donor_maps = build_audio_donor_maps(ids, queries)
    student = _TinyInterventionStudent()
    before = {name: value.detach().clone() for name, value in student.state_dict().items()}

    predictions = collect_intervention_predictions(
        student,
        loader,
        torch.device("cpu"),
        donor_maps=donor_maps,
        seed=42,
    )

    assert tuple(predictions) == intervention_mode_names()
    assert len(predictions) == 17
    for payload in predictions.values():
        assert payload["ids"].tolist() == ids
        assert payload["sample_offsets"].tolist() == [0, 10, 20, 30, 40]
        assert payload["segment_indices"].tolist() == list(range(10)) * 4
        assert payload["labels"].tolist() == [0.0, 1.0] * 20
    assert not np.array_equal(
        predictions["content_original"]["logits"],
        predictions["audio_same_query_donor"]["logits"],
    )
    after = student.state_dict()
    assert all(torch.equal(before[name], after[name]) for name in before)
    assert all(parameter.grad is None for parameter in student.parameters())


@pytest.mark.parametrize("gate_mode", ["learned_softmax", "fixed_equal"])
def test_identity_gate_config_accepts_only_the_explicit_expected_mode(
    gate_mode: str,
) -> None:
    config = {
        "data": {"num_segments": 10},
        "student": {
            "temporal_path_mode": "identity_passthrough",
            "gate_mode": gate_mode,
        },
    }

    validate_identity_gate_config(config, expected_gate_mode=gate_mode)
    other = "fixed_equal" if gate_mode == "learned_softmax" else "learned_softmax"
    with pytest.raises(ValueError, match="gate_mode"):
        validate_identity_gate_config(config, expected_gate_mode=other)


def test_identity_gate_config_rejects_nonofficial_timeline_or_transformer() -> None:
    with pytest.raises(ValueError, match="T=10"):
        validate_identity_gate_config(
            {
                "data": {"num_segments": 16},
                "student": {
                    "temporal_path_mode": "identity_passthrough",
                    "gate_mode": "fixed_equal",
                },
            },
            expected_gate_mode="fixed_equal",
        )
    with pytest.raises(ValueError, match="identity_passthrough"):
        validate_identity_gate_config(
            {
                "data": {"num_segments": 10},
                "student": {
                    "temporal_path_mode": "transformer",
                    "gate_mode": "fixed_equal",
                },
            },
            expected_gate_mode="fixed_equal",
        )


def test_identity_gate_config_binds_the_explicit_additive_fusion_mode() -> None:
    config = {
        "data": {"num_segments": 10},
        "student": {
            "temporal_path_mode": "identity_passthrough",
            "gate_mode": "fixed_equal",
            "fusion_mode": "paper_additive_query_conditioned",
        },
    }

    validate_identity_gate_config(
        config,
        expected_gate_mode="fixed_equal",
        expected_fusion_mode="paper_additive_query_conditioned",
    )
    with pytest.raises(ValueError, match="fusion_mode"):
        validate_identity_gate_config(
            config,
            expected_gate_mode="fixed_equal",
            expected_fusion_mode="concat_mlp_query_conditioned",
        )
