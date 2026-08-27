from __future__ import annotations

import copy
import json
import os
import random
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import torch
from torch.optim import AdamW
from torch.optim.lr_scheduler import CosineAnnealingLR, StepLR

import scripts.train_ov_orthkd as train_module

from scripts.train_ov_orthkd import (
    build_model_and_loss,
    build_scheduler,
    require_real_weak_logits,
    resolve_early_stopping,
    resolve_training_limits,
    set_seed,
    validate_repro_config,
)
from src.losses import OVOrthKDLoss, OVOrthKDLegacyLoss
from src.utils.training_diagnostics import diagnostic_parameter_snapshots


def test_epoch_evaluation_returns_predictions_with_its_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    predictions = {
        "labels": np.asarray([0.0, 1.0], dtype=np.float32),
        "probabilities": np.asarray([0.25, 0.75], dtype=np.float32),
    }
    expected_metrics = {"accuracy": 1.0, "ap": 1.0}
    monkeypatch.setattr(train_module, "collect_predictions", lambda *args, **kwargs: predictions)
    monkeypatch.setattr(
        train_module,
        "compute_grouped_metrics",
        lambda values, threshold: {"total": expected_metrics},
    )

    returned_predictions, returned_metrics = train_module.evaluate_with_predictions(
        object(), object(), torch.device("cpu"), max_batches=2
    )

    assert returned_predictions is predictions
    assert returned_metrics is expected_metrics


def tiny_config(implementation_mode: str, path_mode: str) -> dict[str, Any]:
    return {
        "seed": 41,
        "reproduction": {
            "paper": "ACM MM 2026 OV-OrthKD",
            "implementation_mode": implementation_mode,
            "full_run_blocked": False,
            "blocked_archival_facts": [],
        },
        "data": {
            "text_dim": 5,
            "strong_teacher_dim": 3,
            "weak_teacher_dim": 4,
            "max_segments": 2,
        },
        "student": {
            "visual_backbone": "mobilenetv3_small_100",
            "audio_backbone": "mobilenetv3_small_100",
            "fusion_dim": 16,
            "projection_dim": 8,
            "path_mode": path_mode,
            "temporal_layers": 1,
            "temporal_heads": 4,
            "temporal_dropout": 0.0,
            "pretrained": False,
        },
        "loss": {
            "projection_dim": 8,
            "text_alignment_mode": "paper_probability",
            "alpha_bce": 1.0,
            "alpha_strong_logit": 0.0,
            "alpha_weak_logit": 0.0,
            "alpha_strong_feat": 0.0,
            "alpha_weak_feat": 0.0,
            "alpha_text_align": 0.0,
            "alpha_orth": 0.0,
        },
        "training": {
            "epochs": 2,
            "scheduler": {"type": "cosine"},
        },
    }


def test_camera_ready_mode_maps_only_to_explicit_student_and_camera_loss() -> None:
    config = tiny_config("camera_ready_explicit_paths", "explicit_projected")

    student, loss_module = build_model_and_loss(config, torch.device("cpu"))

    assert student.path_mode == "explicit_projected"
    assert isinstance(loss_module, OVOrthKDLoss)
    assert not isinstance(loss_module, OVOrthKDLegacyLoss)


def test_builder_plumbs_nondefault_runtime_modes_into_actual_modules() -> None:
    config = tiny_config("camera_ready_explicit_paths", "explicit_projected")
    config["student"].update(
        {
            "fusion_mode": "paper_additive_query_conditioned",
            "gate_mode": "fixed_equal",
        }
    )
    config["loss"].update(
        {
            "visual_l2_reduction": "sum_feature_then_masked_mean_segments",
            "teacher_target_projector_trainable": False,
            "query_anchor_mode": "shared_fusion_projection",
        }
    )

    student, loss_module = build_model_and_loss(config, torch.device("cpu"))

    assert student.fusion_mode == "paper_additive_query_conditioned"
    assert student.gate_mode == "fixed_equal"
    assert student.query_anchor_mode == "shared_fusion_projection"
    assert loss_module.visual_l2_reduction == "sum_feature_then_masked_mean_segments"
    assert loss_module.query_anchor_mode == "shared_fusion_projection"
    assert loss_module.teacher_target_projector_trainable is False
    assert all(
        not parameter.requires_grad
        for name, parameter in loss_module.named_parameters()
        if name.startswith(("strong_teacher_proj", "weak_teacher_proj"))
    )


def test_runtime_behavior_receipt_is_derived_from_modules_and_written(
    tmp_path: Path,
) -> None:
    config = tiny_config("camera_ready_explicit_paths", "explicit_projected")
    config["student"]["gate_mode"] = "fixed_equal"
    config["loss"]["teacher_target_projector_trainable"] = False
    student, loss_module = build_model_and_loss(config, torch.device("cpu"))

    behavior = train_module.attach_runtime_implementation_behavior(
        config=config,
        student=student,
        loss_module=loss_module,
        output_dir=tmp_path,
    )

    assert behavior["schema_version"] == 1
    assert behavior["student"]["fusion_mode"] == "concat_mlp_query_conditioned"
    assert behavior["student"]["gate_mode"] == "fixed_equal"
    assert behavior["loss"]["visual_l2_reduction"] == (
        "mean_feature_then_masked_mean_segments"
    )
    assert behavior["loss"]["teacher_target_projector_trainable"] is False
    assert behavior["loss"]["target_projectors"]["strong_teacher_proj"][
        "trainable_parameters"
    ] == 0
    assert config["runtime_implementation"] == behavior
    assert json.loads(
        (tmp_path / "implementation_behavior.json").read_text(encoding="utf-8")
    ) == behavior


def test_optimizer_parameter_filter_excludes_frozen_target_projectors() -> None:
    config = tiny_config("camera_ready_explicit_paths", "explicit_projected")
    config["loss"]["teacher_target_projector_trainable"] = False
    student, loss_module = build_model_and_loss(config, torch.device("cpu"))
    frozen_ids = {
        id(parameter)
        for name, parameter in loss_module.named_parameters()
        if name.startswith(("strong_teacher_proj", "weak_teacher_proj", "text_teacher_proj"))
    }

    optimizer_parameters = train_module.trainable_model_and_loss_parameters(
        student,
        loss_module,
    )

    assert optimizer_parameters
    assert not frozen_ids.intersection(map(id, optimizer_parameters))
    assert all(parameter.requires_grad for parameter in optimizer_parameters)


def test_checkpoint_payload_carries_the_actual_behavior_receipt() -> None:
    config = tiny_config("camera_ready_explicit_paths", "explicit_projected")
    student, loss_module = build_model_and_loss(config, torch.device("cpu"))
    behavior = train_module.runtime_implementation_behavior(student, loss_module)
    config["runtime_implementation"] = behavior
    optimizer = AdamW(
        train_module.trainable_model_and_loss_parameters(student, loss_module),
        lr=1e-3,
    )
    scheduler = StepLR(optimizer, step_size=1)

    payload = train_module.checkpoint_payload(
        epoch=1,
        global_step=2,
        best_metric=0.3,
        student=student,
        loss_module=loss_module,
        optimizer=optimizer,
        scheduler=scheduler,
        scaler=None,
        config=config,
        reproduction_fingerprint={"sha256": "test"},
        loader_generators={"train": torch.Generator().manual_seed(1)},
    )

    assert payload["runtime_implementation"] == behavior


def test_checkpoint_rejects_a_stale_config_behavior_receipt() -> None:
    config = tiny_config("camera_ready_explicit_paths", "explicit_projected")
    student, loss_module = build_model_and_loss(config, torch.device("cpu"))
    config["runtime_implementation"] = {"schema_version": 1, "stale": True}
    optimizer = AdamW(
        train_module.trainable_model_and_loss_parameters(student, loss_module),
        lr=1e-3,
    )
    scheduler = StepLR(optimizer, step_size=1)

    with pytest.raises(RuntimeError, match="runtime implementation behavior changed"):
        train_module.checkpoint_payload(
            epoch=1,
            global_step=2,
            best_metric=0.3,
            student=student,
            loss_module=loss_module,
            optimizer=optimizer,
            scheduler=scheduler,
            scaler=None,
            config=config,
            reproduction_fingerprint={"sha256": "test"},
            loader_generators={},
        )


def test_diagnostics_ignore_modules_absent_in_selected_runtime_modes() -> None:
    config = tiny_config("camera_ready_explicit_paths", "explicit_projected")
    student, loss_module = build_model_and_loss(config, torch.device("cpu"))
    student.modality_gate = None
    student.token_fusion = None
    loss_module.text_teacher_proj = None

    snapshots = diagnostic_parameter_snapshots(student, loss_module)

    assert "loss_text_teacher_proj" not in snapshots
    assert "student_segment_head" in snapshots


def test_legacy_mode_maps_only_to_shared_student_and_legacy_loss() -> None:
    config = tiny_config("legacy_collaboration", "legacy_shared")

    student, loss_module = build_model_and_loss(config, torch.device("cpu"))

    assert student.path_mode == "legacy_shared"
    assert isinstance(loss_module, OVOrthKDLegacyLoss)


def test_mode_mismatch_fails_before_model_construction() -> None:
    config = tiny_config("camera_ready_explicit_paths", "legacy_shared")

    with pytest.raises(
        ValueError,
        match=r"camera_ready_explicit_paths.*explicit_projected",
    ):
        build_model_and_loss(config, torch.device("cpu"))


def test_unknown_implementation_mode_is_rejected() -> None:
    config = tiny_config("invented", "explicit_projected")

    with pytest.raises(ValueError, match="Unsupported implementation_mode: invented"):
        build_model_and_loss(config, torch.device("cpu"))


def blocked_config() -> dict[str, Any]:
    config = tiny_config("camera_ready_explicit_paths", "explicit_projected")
    config["reproduction"].update(
        {
            "full_run_blocked": True,
            "blocked_archival_facts": ["scheduler unknown", "checkpoint identities unknown"],
        }
    )
    config["training"]["scheduler"] = {"type": "UNRESOLVED"}
    return config


def test_blocked_full_run_fails_before_data_loading() -> None:
    with pytest.raises(RuntimeError, match="full run is blocked"):
        validate_repro_config(
            blocked_config(),
            allow_blocked=False,
            preflight=False,
        )


def test_explicit_block_override_writes_noncanonical_marker(tmp_path: Path) -> None:
    output_dir = tmp_path / "diagnostic"
    validate_repro_config(
        blocked_config(),
        allow_blocked=True,
        preflight=False,
        output_dir=output_dir,
    )

    marker = output_dir / "NON_CANONICAL_UNRESOLVED_RUN.txt"
    contents = marker.read_text(encoding="utf-8")
    assert "NON-CANONICAL" in contents
    assert "scheduler unknown" in contents
    assert "checkpoint identities unknown" in contents


def test_preflight_is_allowed_without_overriding_or_marking_full_run(tmp_path: Path) -> None:
    validate_repro_config(
        blocked_config(),
        allow_blocked=False,
        preflight=True,
        output_dir=tmp_path,
    )

    assert not (tmp_path / "NON_CANONICAL_UNRESOLVED_RUN.txt").exists()


def test_set_seed_repeats_all_host_rngs_and_sets_deterministic_flags() -> None:
    set_seed(77, deterministic=True)
    first = (random.random(), float(np.random.rand()), float(torch.rand(())))

    set_seed(77, deterministic=True)
    second = (random.random(), float(np.random.rand()), float(torch.rand(())))

    assert first == second
    assert torch.backends.cudnn.deterministic is True
    assert torch.backends.cudnn.benchmark is False
    assert torch.are_deterministic_algorithms_enabled() is True
    assert torch.is_deterministic_algorithms_warn_only_enabled() is False
    assert torch.backends.cuda.flash_sdp_enabled() is False
    assert torch.backends.cuda.mem_efficient_sdp_enabled() is False
    assert torch.backends.cuda.math_sdp_enabled() is True
    assert os.environ["CUBLAS_WORKSPACE_CONFIG"] == ":4096:8"


def test_set_seed_restores_non_deterministic_runtime_mode() -> None:
    set_seed(77, deterministic=True)
    set_seed(77, deterministic=False)

    assert torch.backends.cudnn.deterministic is False
    assert torch.backends.cudnn.benchmark is True
    assert torch.are_deterministic_algorithms_enabled() is False
    assert torch.backends.cuda.flash_sdp_enabled() is True
    assert torch.backends.cuda.mem_efficient_sdp_enabled() is True
    assert torch.backends.cuda.math_sdp_enabled() is True


def test_build_scheduler_supports_cosine_and_step_intervals() -> None:
    parameter = torch.nn.Parameter(torch.tensor(1.0))
    optimizer = AdamW([parameter], lr=1e-3)

    cosine, cosine_interval = build_scheduler(
        optimizer,
        {"scheduler": {"type": "cosine"}},
        epochs=3,
        steps_per_epoch=4,
    )
    step, step_interval = build_scheduler(
        optimizer,
        {
            "scheduler": {
                "type": "step",
                "step_size": 4,
                "gamma": 0.5,
                "interval": "optimizer_step",
            }
        },
        epochs=3,
        steps_per_epoch=4,
    )

    assert isinstance(cosine, CosineAnnealingLR)
    assert cosine_interval == "epoch"
    assert isinstance(step, StepLR)
    assert step_interval == "optimizer_step"


def test_build_scheduler_rejects_unresolved_paper_schedule() -> None:
    parameter = torch.nn.Parameter(torch.tensor(1.0))
    optimizer = AdamW([parameter], lr=1e-3)

    with pytest.raises(RuntimeError, match="scheduler is unresolved"):
        build_scheduler(
            optimizer,
            {"scheduler": {"type": "UNRESOLVED"}},
            epochs=30,
            steps_per_epoch=100,
        )


def test_training_limits_keep_epoch_batches_and_global_steps_distinct() -> None:
    max_batches, max_steps = resolve_training_limits(
        {
            "max_batches_per_epoch": 3,
            "max_optimizer_steps": 7,
        },
        deprecated_max_train_steps=None,
    )

    assert max_batches == 3
    assert max_steps == 7


def test_deprecated_max_train_steps_only_overrides_per_epoch_batches() -> None:
    with pytest.warns(DeprecationWarning, match="max-train-steps"):
        max_batches, max_steps = resolve_training_limits(
            {
                "max_batches_per_epoch": 3,
                "max_optimizer_steps": 7,
            },
            deprecated_max_train_steps=2,
        )

    assert max_batches == 2
    assert max_steps == 7


def test_early_stop_uses_yaml_unless_cli_overrides() -> None:
    train_cfg = {"early_stop_patience": 5, "early_stop_min_delta": 0.02}

    assert resolve_early_stopping(train_cfg, None, None) == (5, 0.02)
    assert resolve_early_stopping(train_cfg, 2, 0.5) == (2, 0.5)


def test_weak_logit_kd_requires_real_nonempty_mask() -> None:
    with pytest.raises(RuntimeError, match="Synthetic logits are forbidden"):
        require_real_weak_logits(0.2, torch.zeros(2, 3))

    require_real_weak_logits(0.0, torch.zeros(2, 3))
    require_real_weak_logits(0.2, torch.tensor([[1.0]]))


def test_validation_does_not_mutate_the_input_config(tmp_path: Path) -> None:
    config = blocked_config()
    original = copy.deepcopy(config)

    validate_repro_config(
        config,
        allow_blocked=True,
        preflight=False,
        output_dir=tmp_path / "diagnostic",
    )

    assert config == original
