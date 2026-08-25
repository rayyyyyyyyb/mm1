from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_EXPERIMENT_CONFIGS = (
    "ov_orthkd.yaml",
    "ov_orthkd_student_only.yaml",
    "ov_orthkd_weak_feat_only.yaml",
    "ov_orthkd_strong_feat_only.yaml",
    "ov_orthkd_dual_feat_orth_sweep_a.yaml",
    "ov_orthkd_text_align.yaml",
    "ov_orthkd_paper_setting.yaml",
    "ov_orthkd_mm26_repro.yaml",
)


def _formal_config() -> dict:
    return {
        "reproduction": {"claim_level": "paper_specified_reconstruction"},
        "data": {
            "num_segments": 10,
            "temporal_resampling": False,
            "visual_preprocessing": {"jpgs_per_segment": 1},
            "audio_preprocessing": {
                "beats_task_window_seconds": 10,
                "beats_short_waveform_policy": "zero_pad_to_task_duration",
                "beats_long_waveform_policy": "truncate_to_task_duration",
            },
        },
        "student": {"max_position_segments": 16},
        "teacher_export": {
            "internvideo2": {
                "task_segments": 10,
                "num_frames": 8,
                "frame_sampling": "repeat_segment_keyframe",
                "frame_expansion": "repeat_last_to_num_frames",
                "raw_video_diagnostic": {"enabled": False, "executed": False},
            },
            "beats": {
                "sample_rate": 16_000,
                "task_segments": 10,
                "segment_seconds": 1,
                "clip_duration_seconds": 10,
                "short_waveform_policy": "zero_pad_to_task_duration",
                "long_waveform_policy": "truncate_to_task_duration",
            },
        },
        "evaluation": {
            "test_views": 1,
            "view_aggregation": "none",
        },
    }


def _set_path(document: dict, dotted_path: str, value: object) -> None:
    current = document
    components = dotted_path.split(".")
    for component in components[:-1]:
        current = current[component]
    current[components[-1]] = value


def test_formal_runtime_protocol_returns_the_five_independent_quantities() -> None:
    from src.utils.temporal_protocol import validate_final_runtime_protocol

    assert validate_final_runtime_protocol(_formal_config()) == {
        "task_segments": 10,
        "max_position_segments": 16,
        "student_frames_per_segment": 1,
        "teacher_frames_per_segment": 8,
        "teacher_frame_sampling": "repeat_segment_keyframe",
        "teacher_frame_expansion": "repeat_last_to_num_frames",
        "test_views": 1,
        "test_view_aggregation": "none",
        "temporal_resampling": False,
    }


@pytest.mark.parametrize("config_name", PUBLIC_EXPERIMENT_CONFIGS)
def test_every_public_real_experiment_config_states_the_final_protocol_explicitly(
    config_name: str,
) -> None:
    config = yaml.safe_load(
        (PROJECT_ROOT / "configs" / config_name).read_text(encoding="utf-8")
    )

    assert config["data"]["num_segments"] == 10
    assert config["data"]["temporal_resampling"] is False
    assert config["data"]["visual_preprocessing"]["jpgs_per_segment"] == 1
    assert config["student"]["max_position_segments"] == 16
    internvideo = config["teacher_export"]["internvideo2"]
    assert internvideo["task_segments"] == 10
    assert internvideo["num_frames"] == 8
    assert internvideo["frame_sampling"] == "repeat_segment_keyframe"
    assert internvideo["frame_expansion"] == "repeat_last_to_num_frames"
    assert internvideo["raw_video_diagnostic"]["enabled"] is False
    assert internvideo["raw_video_diagnostic"]["executed"] is False
    assert config["evaluation"]["test_views"] == 1
    assert config["evaluation"]["view_aggregation"] == "none"


@pytest.mark.parametrize(
    ("path", "bad_value", "message"),
    [
        ("data.num_segments", 16, "data.num_segments=10"),
        ("student.max_position_segments", 10, "student.max_position_segments=16"),
        (
            "data.visual_preprocessing.jpgs_per_segment",
            16,
            "data.visual_preprocessing.jpgs_per_segment=1",
        ),
        ("teacher_export.internvideo2.task_segments", 16, "task_segments=10"),
        ("teacher_export.internvideo2.num_frames", 16, "num_frames=8"),
        (
            "teacher_export.internvideo2.frame_sampling",
            "uniform_within_segment",
            "frame_sampling=repeat_segment_keyframe",
        ),
        (
            "teacher_export.internvideo2.frame_expansion",
            "linspace",
            "frame_expansion=repeat_last_to_num_frames",
        ),
        (
            "teacher_export.internvideo2.raw_video_diagnostic.enabled",
            True,
            "raw_video_diagnostic.enabled=false",
        ),
        (
            "teacher_export.internvideo2.raw_video_diagnostic.executed",
            True,
            "raw_video_diagnostic.executed=false",
        ),
        ("evaluation.test_views", 3, "evaluation.test_views=1"),
        ("evaluation.view_aggregation", "mean", "evaluation.view_aggregation=none"),
        ("data.temporal_resampling", True, "data.temporal_resampling=false"),
        (
            "data.audio_preprocessing.beats_short_waveform_policy",
            "repeat_last_sample",
            "beats_short_waveform_policy=zero_pad_to_task_duration",
        ),
        (
            "teacher_export.beats.short_waveform_policy",
            "reject",
            "short_waveform_policy=zero_pad_to_task_duration",
        ),
        (
            "teacher_export.beats.clip_duration_seconds",
            9,
            "clip_duration_seconds=10",
        ),
    ],
)
def test_formal_runtime_protocol_rejects_each_conflated_or_multiview_setting(
    path: str,
    bad_value: object,
    message: str,
) -> None:
    from src.utils.temporal_protocol import validate_final_runtime_protocol

    config = deepcopy(_formal_config())
    _set_path(config, path, bad_value)

    with pytest.raises(ValueError, match=message):
        validate_final_runtime_protocol(config)


@pytest.mark.parametrize(
    "path",
    [
        "data.visual_preprocessing.jpgs_per_segment",
        "teacher_export.internvideo2.num_frames",
        "evaluation.test_views",
    ],
)
def test_formal_runtime_protocol_rejects_missing_required_dimensions(path: str) -> None:
    from src.utils.temporal_protocol import validate_final_runtime_protocol

    config = deepcopy(_formal_config())
    current = config
    components = path.split(".")
    for component in components[:-1]:
        current = current[component]
    del current[components[-1]]

    with pytest.raises(ValueError, match=path.replace(".", r"\.")):
        validate_final_runtime_protocol(config)


def test_evaluator_lock_single_view_protocol_is_cross_bound_to_runtime() -> None:
    from src.utils.canonical_readiness import validate_evaluator_test_protocol

    lock = {
        "test_protocol": {
            "status": "resolved",
            "views": 1,
            "aggregation": "none",
            "deterministic_single_forward": True,
            "config_bindings": [
                {"path": "evaluation.test_views", "value": 1},
                {"path": "evaluation.view_aggregation", "value": "none"},
            ],
        }
    }
    config = _formal_config()

    assert validate_evaluator_test_protocol(lock, config) == []
    lock["test_protocol"]["views"] = 3
    assert validate_evaluator_test_protocol(lock, config) == [
        "evaluator_lock: test protocol must be one deterministic unaggregated view"
    ]


def test_real_preflight_protocol_receipt_must_equal_the_validated_runtime() -> None:
    from src.utils.canonical_readiness import validate_real_preflight_protocol
    from src.utils.temporal_protocol import validate_final_runtime_protocol

    config = _formal_config()
    preflight = {"runtime_protocol": validate_final_runtime_protocol(config)}

    assert validate_real_preflight_protocol(preflight, config) == []
    preflight["runtime_protocol"]["test_views"] = 3
    assert validate_real_preflight_protocol(preflight, config) == [
        "real_preflight: runtime protocol receipt does not match canonical config"
    ]
