from __future__ import annotations

import pytest
import torch


def _canonical_tensors(batch_size: int = 2):
    return {
        "visual_input": torch.zeros(batch_size, 10, 3, 224, 224),
        "audio_input": torch.zeros(batch_size, 10, 3, 224, 224),
        "visual_teacher_features": torch.zeros(batch_size, 10, 512),
        "audio_teacher_features": torch.zeros(batch_size, 10, 768),
        "labels": torch.zeros(batch_size, 10),
        "student_logits": torch.zeros(batch_size, 10),
        "sequence_mask": torch.tensor(
            [[True] * 10, [True] * 8 + [False] * 2], dtype=torch.bool
        ),
    }


def test_canonical_temporal_shape_receipt_records_every_t10_boundary() -> None:
    from src.utils.temporal_protocol import build_temporal_shape_receipt

    receipt = build_temporal_shape_receipt(**_canonical_tensors())

    assert receipt == {
        "schema_version": 1,
        "protocol": "official_ov_avebench_t10",
        "task_segments": 10,
        "shapes": {
            "visual_input": [2, 10, 3, 224, 224],
            "audio_input": [2, 10, 3, 224, 224],
            "visual_teacher_features": [2, 10, 512],
            "audio_teacher_features": [2, 10, 768],
            "label": [2, 10],
            "student_logits": [2, 10],
            "sequence_mask": [2, 10],
            "metric_labels": [18],
            "metric_probabilities": [18],
        },
        "alignment_valid": True,
        "temporal_resampling_performed": False,
    }


def test_canonical_temporal_shape_receipt_rejects_any_t16_label_or_logit_path() -> None:
    from src.utils.temporal_protocol import build_temporal_shape_receipt

    tensors = _canonical_tensors()
    tensors["student_logits"] = torch.zeros(2, 16)

    with pytest.raises(ValueError, match=r"student_logits.*\[2, 16\].*label=\[2, 10\]"):
        build_temporal_shape_receipt(**tensors)


def test_canonical_temporal_shape_receipt_rejects_teacher_time_axis_mismatch() -> None:
    from src.utils.temporal_protocol import build_temporal_shape_receipt

    tensors = _canonical_tensors()
    tensors["visual_teacher_features"] = torch.zeros(2, 16, 512)

    with pytest.raises(ValueError, match="visual_teacher_features.*task time axis 10"):
        build_temporal_shape_receipt(**tensors)


def test_metric_flattening_contract_rejects_silent_extra_student_logits() -> None:
    from src.utils.temporal_protocol import validate_temporal_alignment

    with pytest.raises(
        ValueError,
        match=r"student_logits.*label.*sequence_mask.*\[2, 16\].*\[2, 10\]",
    ):
        validate_temporal_alignment(
            student_logits=torch.zeros(2, 16),
            labels=torch.zeros(2, 10),
            sequence_mask=torch.ones(2, 10, dtype=torch.bool),
        )


def test_formal_metric_contract_rejects_matching_t16_tensors() -> None:
    from src.utils.temporal_protocol import validate_temporal_alignment

    with pytest.raises(ValueError, match=r"official task time axis 10.*\[2, 16\]"):
        validate_temporal_alignment(
            student_logits=torch.zeros(2, 16),
            labels=torch.zeros(2, 16),
            sequence_mask=torch.ones(2, 16, dtype=torch.bool),
            task_segments=10,
        )


def test_formal_config_resolves_task_segments_separately_from_position_capacity() -> None:
    from src.utils.temporal_protocol import (
        task_segments_from_config,
        max_position_segments_from_config,
    )

    config = {
        "reproduction": {"claim_level": "paper_specified_reconstruction"},
        "data": {"num_segments": 10, "temporal_resampling": False},
        "student": {"max_position_segments": 16},
    }

    assert task_segments_from_config(config) == 10
    assert max_position_segments_from_config(config) == 16

    with pytest.raises(ValueError, match="data.num_segments=10"):
        task_segments_from_config(
            {
                "reproduction": {"claim_level": "paper_specified_reconstruction"},
                "data": {"max_segments": 16},
                "student": {"max_position_segments": 16},
            }
        )
