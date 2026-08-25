from __future__ import annotations

from collections.abc import Mapping
from typing import Any


OFFICIAL_TASK_SEGMENTS = 10
OFFICIAL_TEMPORAL_PROTOCOL = "official_ov_avebench_t10"
STUDENT_MAX_POSITION_SEGMENTS = 16
STUDENT_FRAMES_PER_SEGMENT = 1
TEACHER_FRAMES_PER_SEGMENT = 8
TEACHER_FRAME_SAMPLING = "repeat_segment_keyframe"
TEACHER_FRAME_EXPANSION = "repeat_last_to_num_frames"
TEST_VIEWS = 1
TEST_VIEW_AGGREGATION = "none"
BEATS_SAMPLE_RATE = 16_000
BEATS_SEGMENT_SECONDS = 1
BEATS_CLIP_DURATION_SECONDS = 10
BEATS_SHORT_WAVEFORM_POLICY = "zero_pad_to_task_duration"
BEATS_LONG_WAVEFORM_POLICY = "truncate_to_task_duration"


def _is_formal_reconstruction(config: Mapping[str, Any]) -> bool:
    reproduction = config.get("reproduction", {})
    if not isinstance(reproduction, Mapping):
        return False
    return reproduction.get("claim_level") in {
        "paper_specified_reconstruction",
        "archival_exact",
    }


def _mapping_at(config: Mapping[str, Any], path: str) -> Mapping[str, Any]:
    current: Any = config
    for component in path.split("."):
        if not isinstance(current, Mapping) or component not in current:
            raise ValueError(f"Formal OV-AVEBench config requires {path}")
        current = current[component]
    if not isinstance(current, Mapping):
        raise ValueError(f"Formal OV-AVEBench config requires {path} to be a mapping")
    return current


def _require_exact(
    config: Mapping[str, Any], dotted_path: str, expected: Any
) -> Any:
    components = dotted_path.split(".")
    current: Any = config
    for component in components:
        if not isinstance(current, Mapping) or component not in current:
            expected_text = str(expected).lower() if isinstance(expected, bool) else expected
            raise ValueError(
                f"Formal OV-AVEBench config requires {dotted_path}={expected_text}"
            )
        current = current[component]
    if current != expected or type(current) is not type(expected):
        expected_text = str(expected).lower() if isinstance(expected, bool) else expected
        raise ValueError(
            f"Formal OV-AVEBench config requires {dotted_path}={expected_text}"
        )
    return current


def validate_final_runtime_protocol(config: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed on the approved formal runtime protocol.

    The five numeric values describe different axes/operations.  This validator
    intentionally rejects defaults so an omitted field cannot silently change a
    formal run.
    """

    _mapping_at(config, "data")
    _mapping_at(config, "data.visual_preprocessing")
    _mapping_at(config, "data.audio_preprocessing")
    _mapping_at(config, "student")
    _mapping_at(config, "teacher_export.internvideo2")
    _mapping_at(config, "teacher_export.beats")
    _mapping_at(config, "evaluation")
    _require_exact(
        config,
        "teacher_export.internvideo2.task_segments",
        OFFICIAL_TASK_SEGMENTS,
    )
    _require_exact(
        config,
        "teacher_export.internvideo2.raw_video_diagnostic.enabled",
        False,
    )
    _require_exact(
        config,
        "teacher_export.internvideo2.raw_video_diagnostic.executed",
        False,
    )
    for path, expected in (
        ("data.audio_preprocessing.beats_task_window_seconds", BEATS_CLIP_DURATION_SECONDS),
        (
            "data.audio_preprocessing.beats_short_waveform_policy",
            BEATS_SHORT_WAVEFORM_POLICY,
        ),
        (
            "data.audio_preprocessing.beats_long_waveform_policy",
            BEATS_LONG_WAVEFORM_POLICY,
        ),
        ("teacher_export.beats.sample_rate", BEATS_SAMPLE_RATE),
        ("teacher_export.beats.task_segments", OFFICIAL_TASK_SEGMENTS),
        ("teacher_export.beats.segment_seconds", BEATS_SEGMENT_SECONDS),
        (
            "teacher_export.beats.clip_duration_seconds",
            BEATS_CLIP_DURATION_SECONDS,
        ),
        (
            "teacher_export.beats.short_waveform_policy",
            BEATS_SHORT_WAVEFORM_POLICY,
        ),
        (
            "teacher_export.beats.long_waveform_policy",
            BEATS_LONG_WAVEFORM_POLICY,
        ),
    ):
        _require_exact(config, path, expected)
    return {
        "task_segments": _require_exact(
            config, "data.num_segments", OFFICIAL_TASK_SEGMENTS
        ),
        "max_position_segments": _require_exact(
            config,
            "student.max_position_segments",
            STUDENT_MAX_POSITION_SEGMENTS,
        ),
        "student_frames_per_segment": _require_exact(
            config,
            "data.visual_preprocessing.jpgs_per_segment",
            STUDENT_FRAMES_PER_SEGMENT,
        ),
        "teacher_frames_per_segment": _require_exact(
            config,
            "teacher_export.internvideo2.num_frames",
            TEACHER_FRAMES_PER_SEGMENT,
        ),
        "teacher_frame_sampling": _require_exact(
            config,
            "teacher_export.internvideo2.frame_sampling",
            TEACHER_FRAME_SAMPLING,
        ),
        "teacher_frame_expansion": _require_exact(
            config,
            "teacher_export.internvideo2.frame_expansion",
            TEACHER_FRAME_EXPANSION,
        ),
        "test_views": _require_exact(config, "evaluation.test_views", TEST_VIEWS),
        "test_view_aggregation": _require_exact(
            config, "evaluation.view_aggregation", TEST_VIEW_AGGREGATION
        ),
        "temporal_resampling": _require_exact(
            config, "data.temporal_resampling", False
        ),
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
