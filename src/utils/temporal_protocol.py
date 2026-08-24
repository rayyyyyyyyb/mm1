from __future__ import annotations

from collections.abc import Mapping
from typing import Any


OFFICIAL_TASK_SEGMENTS = 10
OFFICIAL_TEMPORAL_PROTOCOL = "official_ov_avebench_t10"


def _is_formal_reconstruction(config: Mapping[str, Any]) -> bool:
    reproduction = config.get("reproduction", {})
    if not isinstance(reproduction, Mapping):
        return False
    return reproduction.get("claim_level") in {
        "paper_specified_reconstruction",
        "archival_exact",
    }


def task_segments_from_config(config: Mapping[str, Any]) -> int:
    data = config.get("data", {})
    if not isinstance(data, Mapping):
        raise ValueError("config.data must be a mapping")
    if _is_formal_reconstruction(config):
        if data.get("num_segments") != OFFICIAL_TASK_SEGMENTS:
            raise ValueError(
                "Formal OV-AVEBench config requires data.num_segments=10"
            )
        if data.get("temporal_resampling") is not False:
            raise ValueError(
                "Formal OV-AVEBench config requires data.temporal_resampling=false"
            )
        return OFFICIAL_TASK_SEGMENTS
    return int(
        data.get(
            "num_segments",
            data.get("max_segments", OFFICIAL_TASK_SEGMENTS),
        )
    )


def max_position_segments_from_config(config: Mapping[str, Any]) -> int:
    student = config.get("student", {})
    data = config.get("data", {})
    if not isinstance(student, Mapping) or not isinstance(data, Mapping):
        raise ValueError("config.student and config.data must be mappings")
    capacity = int(
        student.get("max_position_segments", data.get("max_segments", 16))
    )
    task_segments = task_segments_from_config(config)
    if capacity < task_segments:
        raise ValueError(
            f"student.max_position_segments={capacity} is smaller than "
            f"data.num_segments={task_segments}"
        )
    return capacity


def _shape(value: Any, name: str) -> list[int]:
    shape = getattr(value, "shape", None)
    if shape is None:
        raise TypeError(f"{name} must expose a tensor-like shape")
    return [int(dimension) for dimension in shape]


def _require_shape(
    *,
    name: str,
    actual: list[int],
    expected_rank: int,
    batch_size: int,
    task_segments: int,
) -> None:
    if len(actual) != expected_rank:
        raise ValueError(
            f"{name} must have rank {expected_rank}, got shape {actual}"
        )
    if actual[0] != batch_size:
        raise ValueError(
            f"{name} batch axis must be {batch_size}, got shape {actual}"
        )
    if actual[1] != task_segments:
        raise ValueError(
            f"{name} must preserve task time axis {task_segments}, got shape {actual}"
        )


def validate_temporal_alignment(
    *,
    student_logits: Any,
    labels: Any,
    sequence_mask: Any,
    task_segments: int | None = None,
) -> list[int]:
    """Require exact alignment before any metric flattening or masking."""

    logit_shape = _shape(student_logits, "student_logits")
    label_shape = _shape(labels, "labels")
    mask_shape = _shape(sequence_mask, "sequence_mask")
    if logit_shape != label_shape or mask_shape != label_shape:
        raise ValueError(
            "student_logits, label, and sequence_mask must share the exact temporal "
            f"shape; got student_logits={logit_shape}, label={label_shape}, "
            f"sequence_mask={mask_shape}"
        )
    if len(label_shape) != 2:
        raise ValueError(
            f"Temporal labels/logits/mask must be rank 2 [B,T], got {label_shape}"
        )
    if task_segments is not None and label_shape[1] != int(task_segments):
        raise ValueError(
            f"Formal metric tensors must preserve the official task time axis "
            f"{int(task_segments)}, got shape {label_shape}"
        )
    return label_shape


def build_temporal_shape_receipt(
    *,
    visual_input: Any,
    audio_input: Any,
    visual_teacher_features: Any,
    audio_teacher_features: Any,
    labels: Any,
    student_logits: Any,
    sequence_mask: Any,
    task_segments: int = OFFICIAL_TASK_SEGMENTS,
) -> dict[str, Any]:
    """Validate and describe every canonical temporal boundary without resampling.

    This function intentionally works with any tensor/array object that exposes
    ``shape``. It validates geometry only and never changes labels, logits, or
    teacher features.
    """

    task_segments = int(task_segments)
    if task_segments != OFFICIAL_TASK_SEGMENTS:
        raise ValueError(
            f"Canonical OV-AVEBench requires task_segments={OFFICIAL_TASK_SEGMENTS}, "
            f"got {task_segments}"
        )

    shapes = {
        "visual_input": _shape(visual_input, "visual_input"),
        "audio_input": _shape(audio_input, "audio_input"),
        "visual_teacher_features": _shape(
            visual_teacher_features, "visual_teacher_features"
        ),
        "audio_teacher_features": _shape(
            audio_teacher_features, "audio_teacher_features"
        ),
        "label": _shape(labels, "labels"),
        "student_logits": _shape(student_logits, "student_logits"),
        "sequence_mask": _shape(sequence_mask, "sequence_mask"),
    }
    label_shape = shapes["label"]
    if len(label_shape) != 2 or label_shape[1] != task_segments:
        raise ValueError(
            f"labels must have shape [B, {task_segments}], got {label_shape}"
        )
    batch_size = label_shape[0]
    validate_temporal_alignment(
        student_logits=student_logits,
        labels=labels,
        sequence_mask=sequence_mask,
        task_segments=task_segments,
    )
    for name, rank in (
        ("visual_input", 5),
        ("audio_input", 5),
        ("visual_teacher_features", 3),
        ("audio_teacher_features", 3),
    ):
        _require_shape(
            name=name,
            actual=shapes[name],
            expected_rank=rank,
            batch_size=batch_size,
            task_segments=task_segments,
        )
    valid_segments = int(sequence_mask.sum().item())
    shapes["metric_labels"] = [valid_segments]
    shapes["metric_probabilities"] = [valid_segments]
    return {
        "schema_version": 1,
        "protocol": OFFICIAL_TEMPORAL_PROTOCOL,
        "task_segments": task_segments,
        "shapes": shapes,
        "alignment_valid": True,
        "temporal_resampling_performed": False,
    }
