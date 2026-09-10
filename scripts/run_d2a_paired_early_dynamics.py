#!/usr/bin/env python3
"""Run the preregistered, validation-only D2A paired early-dynamics control."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import torch
from torch.optim import AdamW
from torch.utils.data import DataLoader, Sampler

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.diagnose_checkpoint_modalities import (  # noqa: E402
    collect_early_dynamics_matrix,
)
from scripts.train_ov_orthkd import (  # noqa: E402
    autocast_context,
    build_model_and_loss,
    build_scheduler,
    compute_loss_for_batch,
    make_grad_scaler,
    set_seed,
    trainable_model_and_loss_parameters,
)
from src.data import create_ov_avel_data_loaders  # noqa: E402
from src.data.ov_avel_dataset import ov_avel_collate_fn  # noqa: E402
from src.utils.atomic_artifacts import atomic_write_text  # noqa: E402
from src.utils.d2a_early_dynamics import (  # noqa: E402
    D2A_CHECKPOINTS,
    D2A_INPUT_HASH_STEPS,
    D2A_NAME,
    batch_input_receipt,
    build_fixed_batch_plan,
    canonical_sha256,
    json_safe,
    materialize_d2a_configs,
    recompute_d2a_gate,
    summarize_receipt_range,
    summarize_d2a_evaluation,
)
from src.utils.locked_pretrained import (  # noqa: E402
    compare_nonvisual_initialization,
    load_locked_timm_state_into_encoder,
)
from src.utils.optimizer_receipts import (  # noqa: E402
    OptimizerStepTracker,
    clip_gradients_with_receipt,
    resolve_clipping_scope_parameters,
)
from src.utils.projector_update_modes import (  # noqa: E402
    build_named_optimizer_groups,
    optimizer_group_receipts,
    resolve_projector_update_modes,
)
from src.utils.reproduction_fingerprint import (  # noqa: E402
    capture_rng_state,
    restore_rng_state,
)


ROLES = ("random", "pretrained")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default="configs/diagnostics/recovery/ov_orthkd_d2a_paired_pretrained_early_dynamics_400.yaml",
    )
    parser.add_argument("--asset-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--smoke-attempted-batches",
        type=int,
        default=None,
        help="Diagnostic wiring smoke only; never emits a D2A scientific verdict.",
    )
    parser.add_argument("--max-eval-batches", type=int, default=None)
    return parser.parse_args()


def _atomic_json(path: Path, value: Any) -> None:
    atomic_write_text(
        path,
        json.dumps(
            json_safe(value),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
    )


def _atomic_torch_save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.partial")
    torch.save(value, temporary)
    os.replace(temporary, path)


def _atomic_npz(path: Path, values: Mapping[str, np.ndarray]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.partial.npz")
    np.savez_compressed(temporary, **values)
    os.replace(temporary, path)


def _sha256_tensor_state(state: Mapping[str, Any]) -> str:
    digest = hashlib.sha256()
    for key in sorted(state):
        value = state[key]
        if not isinstance(value, torch.Tensor):
            raise TypeError(f"state entry is not a tensor: {key}")
        tensor = value.detach().cpu().contiguous()
        digest.update(str(key).encode("utf-8"))
        digest.update(str(tensor.dtype).encode("ascii"))
        digest.update(json.dumps(list(tensor.shape), separators=(",", ":")).encode("ascii"))
        digest.update(tensor.reshape(-1).view(torch.uint8).numpy().tobytes())
    return digest.hexdigest()


def _assert_equal_tensor_states(
    reference: Mapping[str, Any], candidate: Mapping[str, Any], name: str
) -> dict[str, Any]:
    if set(reference) != set(candidate):
        raise RuntimeError(f"{name} state keys differ")
    differing = [
        key
        for key in sorted(reference)
        if not torch.equal(reference[key].detach().cpu(), candidate[key].detach().cpu())
    ]
    if differing:
        raise RuntimeError(f"{name} initialization differs at {differing}")
    return {
        "pass": True,
        "key_count": len(reference),
        "reference_sha256": _sha256_tensor_state(reference),
        "candidate_sha256": _sha256_tensor_state(candidate),
    }


def _rng_hash(state: Mapping[str, Any]) -> str:
    digest = hashlib.sha256()
    digest.update(repr(state["python"]).encode("utf-8"))
    digest.update(json.dumps(state["numpy"], sort_keys=True).encode("utf-8"))
    digest.update(state["torch_cpu"].cpu().numpy().tobytes())
    for value in state.get("torch_cuda", []):
        digest.update(value.cpu().numpy().tobytes())
    return digest.hexdigest()


def _parameter_grad_norm(module: torch.nn.Module) -> float:
    squared = 0.0
    for parameter in module.parameters():
        if parameter.grad is not None:
            squared += float(parameter.grad.detach().float().square().sum().cpu())
    return float(squared**0.5)


class FixedBatchSampler(Sampler[list[int]]):
    """Replay a preregistered list of sample-index batches from an offset."""

    def __init__(self, batches: list[list[int]], start: int = 0) -> None:
        self.batches = [list(map(int, batch)) for batch in batches]
        self.start = int(start)
        if not 0 <= self.start <= len(self.batches):
            raise ValueError("fixed batch sampler start is out of range")

    def __iter__(self) -> Iterable[list[int]]:
        return iter(self.batches[self.start :])

    def __len__(self) -> int:
        return len(self.batches) - self.start


def _fixed_train_loader(
    template: DataLoader[Any], batches: list[list[int]], start: int, seed: int
) -> DataLoader[Any]:
    return DataLoader(
        template.dataset,
        batch_sampler=FixedBatchSampler(batches, start=start),
        num_workers=0,
        pin_memory=bool(template.pin_memory),
        collate_fn=ov_avel_collate_fn,
        generator=torch.Generator().manual_seed(int(seed) + 1000),
    )


def _validation_loader(template: DataLoader[Any], batch_size: int, seed: int) -> DataLoader[Any]:
    return DataLoader(
        template.dataset,
        batch_size=int(batch_size),
        shuffle=False,
        num_workers=0,
        pin_memory=bool(template.pin_memory),
        collate_fn=ov_avel_collate_fn,
        generator=torch.Generator().manual_seed(int(seed) + 1),
    )


@dataclass
class Arm:
    role: str
    config: dict[str, Any]
    student: torch.nn.Module
    loss: torch.nn.Module
    optimizer: torch.optim.Optimizer
    scheduler: torch.optim.lr_scheduler.LRScheduler
    scheduler_interval: str
    scaler: Any
    tracker: OptimizerStepTracker
    groups: list[dict[str, Any]]
    parameters: list[torch.nn.Parameter]
    clip_parameters: list[torch.nn.Parameter]


def _build_arm(role: str, config: Mapping[str, Any], device: torch.device) -> Arm:
    # Both branches travel through the identical random constructor. The locked
    # visual bytes are injected into P only after both full models exist.
    construction = copy.deepcopy(dict(config))
    construction["student"]["visual_pretrained"] = False
    set_seed(int(construction["seed"]), deterministic=True)
    student, loss = build_model_and_loss(construction, device)
    student.visual_pretrained = role == "pretrained"
    modes = resolve_projector_update_modes(config["loss"])
    training = config["training"]
    groups = build_named_optimizer_groups(
        student,
        loss,
        learning_rate=float(training["learning_rate"]),
        weight_decay=float(training["weight_decay"]),
        modes=modes,
    )
    parameters = trainable_model_and_loss_parameters(student, loss)
    optimizer = AdamW(
        groups,
        lr=float(training["learning_rate"]),
        weight_decay=float(training["weight_decay"]),
    )
    scheduler, interval = build_scheduler(
        optimizer,
        training,
        epochs=int(training["epochs"]),
        steps_per_epoch=400,
    )
    use_amp = bool(training["mixed_precision"]) and device.type == "cuda"
    return Arm(
        role=role,
        config=copy.deepcopy(dict(config)),
        student=student,
        loss=loss,
        optimizer=optimizer,
        scheduler=scheduler,
        scheduler_interval=interval,
        scaler=make_grad_scaler(device.type, use_amp),
        tracker=OptimizerStepTracker(optimizer),
        groups=groups,
        parameters=parameters,
        clip_parameters=resolve_clipping_scope_parameters(parameters, groups, dict(config)),
    )


def _train_one(
    arm: Arm, batch: Mapping[str, Any], device: torch.device, attempted_step: int
) -> dict[str, Any]:
    arm.student.train()
    arm.loss.train()
    arm.optimizer.zero_grad(set_to_none=True)
    use_amp = bool(arm.config["training"]["mixed_precision"]) and device.type == "cuda"
    with autocast_context(device.type, use_amp):
        outputs = arm.student(
            frame=batch["frame"].to(device),
            spectrogram=batch["spectrogram"].to(device),
            text_embedding=batch["text_embedding"].to(device),
            sequence_mask=batch["sequence_mask"].to(device),
            frame_valid=batch["frame_valid"].to(device),
            audio_valid=batch["audio_valid"].to(device),
        )
        loss, stats = compute_loss_for_batch(arm.loss, outputs, dict(batch), device)
    arm.scaler.scale(loss).backward()
    arm.scaler.unscale_(arm.optimizer)
    visual_grad_norm = _parameter_grad_norm(arm.student.visual_encoder)
    audio_grad_norm = _parameter_grad_norm(arm.student.audio_encoder)
    pre_norm, coefficient, group_norms, contributions, clipped = (
        clip_gradients_with_receipt(
            arm.parameters,
            arm.groups,
            float(arm.config["training"]["grad_clip"]),
            clip_parameters=arm.clip_parameters,
        )
    )
    scale_before = float(arm.scaler.get_scale())
    tracker_attempt = arm.tracker.record_attempt()
    if tracker_attempt != attempted_step:
        raise RuntimeError("optimizer attempted-step tracker diverged")
    applied_before = arm.tracker.applied_steps
    arm.scaler.step(arm.optimizer)
    arm.scaler.update()
    applied = arm.tracker.applied_steps > applied_before
    scale_after = float(arm.scaler.get_scale())
    if applied and arm.scheduler_interval == "optimizer_step":
        arm.scheduler.step()
    return {
        "attempted_step": attempted_step,
        "applied_step": arm.tracker.applied_steps,
        "applied": applied,
        "overflow": not applied,
        "loss": {key: float(value) for key, value in stats.items()},
        "visual_encoder_grad_norm": visual_grad_norm,
        "audio_encoder_grad_norm": audio_grad_norm,
        "pre_clip_global_norm": pre_norm,
        "clip_coefficient": coefficient,
        "clipped": clipped,
        "amp_scale_before": scale_before,
        "amp_scale_after": scale_after,
        "group_norms": group_norms,
        "group_contributions": contributions,
        "clipping_scope": "optimizer_groups_with_positive_lr",
    }


def _write_jsonl(path: Path, rows: list[Mapping[str, Any]]) -> None:
    atomic_write_text(
        path,
        "".join(
            json.dumps(
                json_safe(dict(row)),
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
            for row in rows
        ),
    )


def _evaluate_arm(
    arm: Arm,
    validation_template: DataLoader[Any],
    output: Path,
    attempted_step: int,
    eval_batch_size: int,
    shuffle_repeats: int,
    max_eval_batches: int | None,
) -> tuple[dict[str, Any], dict[str, dict[str, np.ndarray]]]:
    loader = _validation_loader(validation_template, eval_batch_size, int(arm.config["seed"]))
    predictions, paths = collect_early_dynamics_matrix(
        arm.student,
        loader,
        next(arm.student.parameters()).device,
        expected_task_segments=10,
        max_batches=max_eval_batches,
    )
    summary = summarize_d2a_evaluation(
        predictions,
        paths,
        shuffle_repeats=shuffle_repeats,
        shuffle_seed=int(arm.config["seed"]) + attempted_step,
    )
    target = output / "evaluations" / f"step_{attempted_step:03d}" / arm.role
    for mode, payload in predictions.items():
        _atomic_npz(target / f"{mode}.npz", payload)
    _atomic_json(target / "summary.json", summary)
    return summary, predictions


def _checkpoint_payload(
    arms: Mapping[str, Arm],
    attempted_step: int,
    batch_plan: list[list[int]],
    receipts: Mapping[str, list[Mapping[str, Any]]],
    input_receipts: list[Mapping[str, Any]],
    trajectory: Mapping[str, Any],
    materialization: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "control": D2A_NAME,
        "attempted_step": attempted_step,
        "batch_plan": batch_plan,
        "batch_plan_sha256": canonical_sha256(batch_plan),
        "rng_state": capture_rng_state(),
        "receipts": {key: list(value) for key, value in receipts.items()},
        "input_receipts": list(input_receipts),
        "trajectory": copy.deepcopy(dict(trajectory)),
        "materialization_hashes": dict(materialization["config_canonical_sha256"]),
        "arms": {
            role: {
                "student": arm.student.state_dict(),
                "loss": arm.loss.state_dict(),
                "optimizer": arm.optimizer.state_dict(),
                "scheduler": arm.scheduler.state_dict(),
                "scaler": arm.scaler.state_dict(),
                "attempted_steps": arm.tracker.attempted_steps,
                "applied_steps": arm.tracker.applied_steps,
            }
            for role, arm in arms.items()
        },
    }


def _restore_checkpoint(
    path: Path,
    arms: Mapping[str, Arm],
    materialization: Mapping[str, Any],
) -> dict[str, Any]:
    payload = torch.load(path, map_location="cpu", weights_only=False)
    if payload.get("control") != D2A_NAME:
        raise RuntimeError("resume checkpoint belongs to another control")
    if payload.get("materialization_hashes") != materialization["config_canonical_sha256"]:
        raise RuntimeError("resume checkpoint resolved-config hashes differ")
    for role, arm in arms.items():
        state = payload["arms"][role]
        arm.student.load_state_dict(state["student"], strict=True)
        arm.loss.load_state_dict(state["loss"], strict=True)
        arm.optimizer.load_state_dict(state["optimizer"])
        arm.scheduler.load_state_dict(state["scheduler"])
        arm.scaler.load_state_dict(state["scaler"])
        arm.tracker.attempted_steps = int(state["attempted_steps"])
        arm.tracker.applied_steps = int(state["applied_steps"])
    restore_rng_state(payload["rng_state"])
    return payload


def main() -> None:
    args = parse_args()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")
    materialization = materialize_d2a_configs(
        args.config, PROJECT_ROOT, output, args.asset_root
    )
    wrapper = materialization["wrapper"]
    requested_attempts = int(wrapper["control"]["attempted_batches"])
    smoke = args.smoke_attempted_batches is not None
    if smoke:
        requested_attempts = int(args.smoke_attempted_batches)
        if not 1 <= requested_attempts < 400:
            raise ValueError("smoke attempted batches must be in [1,399]")
    elif args.max_eval_batches is not None:
        raise ValueError("formal D2A forbids partial validation")

    arms = {
        role: _build_arm(role, materialization["configs"][role], device)
        for role in ROLES
    }
    parity = compare_nonvisual_initialization(
        arms["random"].student.state_dict(),
        arms["pretrained"].student.state_dict(),
    )
    loss_parity = _assert_equal_tensor_states(
        arms["random"].loss.state_dict(), arms["pretrained"].loss.state_dict(), "loss"
    )
    rng_before_asset = capture_rng_state()
    asset_receipt = load_locked_timm_state_into_encoder(
        arms["pretrained"].student.visual_encoder,
        str(materialization["configs"]["pretrained"]["student"]["visual_backbone"]),
        str(wrapper["pretrained_asset"]["lock"]),
        asset_root=args.asset_root,
    )
    rng_after_asset = capture_rng_state()
    if _rng_hash(rng_before_asset) != _rng_hash(rng_after_asset):
        raise RuntimeError("locked visual state loading consumed global RNG")
    parity_after = compare_nonvisual_initialization(
        arms["random"].student.state_dict(),
        arms["pretrained"].student.state_dict(),
    )
    if (
        asset_receipt["loaded_backbone_tensor_sha256"]
        == _sha256_tensor_state(arms["random"].student.visual_encoder.backbone.state_dict())
    ):
        raise RuntimeError("pretrained and random visual backbones unexpectedly match")

    config = materialization["configs"]["random"]
    set_seed(int(config["seed"]), deterministic=True)
    train_template, validation_template, test_loader = create_ov_avel_data_loaders(config)
    if test_loader is not None or "test_manifest" in config["data"]:
        raise RuntimeError("D2A must not construct or retain a test loader")
    batch_plan = build_fixed_batch_plan(
        len(train_template.dataset), int(config["data"]["batch_size"]), int(config["seed"])
    )
    init_receipt = {
        "schema_version": 1,
        "control": D2A_NAME,
        "smoke_only": smoke,
        "nonvisual_student_parity_before_locked_load": parity,
        "nonvisual_student_parity_after_locked_load": parity_after,
        "loss_parity": loss_parity,
        "asset": asset_receipt,
        "asset_load_rng_unchanged": True,
        "optimizer_groups": {
            role: optimizer_group_receipts(arm.groups) for role, arm in arms.items()
        },
        "batch_plan_sha256": canonical_sha256(batch_plan),
        "batch_plan_count": len(batch_plan),
        "loader_rng_independent_of_model_initialization": True,
        "shared_batch_tensor_object_per_attempt": True,
        "preprocessing_provenance_gap": wrapper["preprocessing_provenance_gap"],
    }
    _atomic_json(output / "initialization_receipt.json", init_receipt)
    _atomic_json(output / "batch_plan.json", {"batches": batch_plan})

    receipts: dict[str, list[Mapping[str, Any]]] = {role: [] for role in ROLES}
    input_receipts: list[Mapping[str, Any]] = []
    trajectory: dict[str, Any] = {
        "schema_version": 1,
        "control": D2A_NAME,
        "smoke_only": smoke,
        "primary_budget_semantics": "attempted_batches",
        "checkpoints": [],
    }
    start = 0
    resume_path = output / str(wrapper["control"]["resume_checkpoint"])
    if args.resume:
        if not resume_path.is_file():
            raise FileNotFoundError(resume_path)
        saved = _restore_checkpoint(resume_path, arms, materialization)
        start = int(saved["attempted_step"])
        if saved["batch_plan"] != batch_plan:
            raise RuntimeError("resume batch plan differs")
        receipts = {key: list(value) for key, value in saved["receipts"].items()}
        input_receipts = list(saved["input_receipts"])
        trajectory = dict(saved["trajectory"])

    checkpoints = (
        tuple(step for step in D2A_CHECKPOINTS if step <= requested_attempts)
        if not smoke
        else (0, requested_attempts)
    )
    if start == 0 and not trajectory["checkpoints"]:
        rng = capture_rng_state()
        summaries: dict[str, Any] = {}
        predictions: dict[str, Any] = {}
        for role in ROLES:
            summaries[role], predictions[role] = _evaluate_arm(
                arms[role],
                validation_template,
                output,
                0,
                int(wrapper["control"]["evaluation_batch_size"]),
                int(wrapper["control"]["temporal_shuffle_repeats"]),
                args.max_eval_batches,
            )
        from src.utils.d2a_early_dynamics import assert_prediction_identity

        assert_prediction_identity(predictions["random"]["original"], predictions["pretrained"]["original"])
        restore_rng_state(rng)
        trajectory["checkpoints"].append(
            {"attempted_step": 0, "arms": summaries, "training_interval": {}}
        )
        _atomic_json(output / "trajectory.json", trajectory)

    train_loader = _fixed_train_loader(train_template, batch_plan, start, int(config["seed"]))
    prior_checkpoint = max(
        [int(row["attempted_step"]) for row in trajectory["checkpoints"]], default=0
    )
    for local_index, batch in enumerate(train_loader, start=start + 1):
        if local_index > requested_attempts:
            break
        if local_index in D2A_INPUT_HASH_STEPS:
            input_receipts.append(
                {"attempted_step": local_index, **batch_input_receipt(batch)}
            )
        before = capture_rng_state()
        role_rng: dict[str, str] = {}
        for role in ROLES:
            restore_rng_state(before)
            receipt = _train_one(arms[role], batch, device, local_index)
            receipts[role].append(receipt)
            role_rng[role] = _rng_hash(capture_rng_state())
        if role_rng["random"] != role_rng["pretrained"]:
            raise RuntimeError(f"paired RNG consumption differs at attempted step {local_index}")
        after = capture_rng_state()
        restore_rng_state(after)
        for role in ROLES:
            _write_jsonl(output / role / "optimizer_receipts.jsonl", receipts[role])
        _write_jsonl(output / "input_receipts.jsonl", input_receipts)

        if local_index in checkpoints:
            if local_index == requested_attempts:
                for arm in arms.values():
                    if arm.scheduler_interval == "epoch" and arm.tracker.applied_steps > 0:
                        arm.scheduler.step()
            evaluation_rng = capture_rng_state()
            summaries = {}
            predictions = {}
            for role in ROLES:
                summaries[role], predictions[role] = _evaluate_arm(
                    arms[role],
                    validation_template,
                    output,
                    local_index,
                    int(wrapper["control"]["evaluation_batch_size"]),
                    int(wrapper["control"]["temporal_shuffle_repeats"]),
                    args.max_eval_batches,
                )
            from src.utils.d2a_early_dynamics import assert_prediction_identity

            assert_prediction_identity(
                predictions["random"]["original"], predictions["pretrained"]["original"]
            )
            restore_rng_state(evaluation_rng)
            trajectory["checkpoints"].append(
                {
                    "attempted_step": local_index,
                    "arms": summaries,
                    "training_interval": {
                        role: summarize_receipt_range(
                            receipts[role], prior_checkpoint, local_index
                        )
                        for role in ROLES
                    },
                }
            )
            prior_checkpoint = local_index
            _atomic_json(output / "trajectory.json", trajectory)
            _atomic_torch_save(
                resume_path,
                _checkpoint_payload(
                    arms,
                    local_index,
                    batch_plan,
                    receipts,
                    input_receipts,
                    trajectory,
                    materialization,
                ),
            )

    final_step = int(trajectory["checkpoints"][-1]["attempted_step"])
    completed = final_step == requested_attempts
    result: dict[str, Any] = {
        "schema_version": 1,
        "control": D2A_NAME,
        "artifact_status": "D2A_ARTIFACT_PENDING_AUDIT",
        "smoke_only": smoke,
        "completed": completed,
        "attempted_batches": final_step,
        "requested_attempted_batches": requested_attempts,
        "applied_updates": {role: arm.tracker.applied_steps for role, arm in arms.items()},
        "scientific_status": "D2A_SMOKE_NO_SCIENTIFIC_VERDICT" if smoke else "D2A_INCOMPLETE",
        "authorization": {
            "automatic_extension": False,
            "test_evaluation": False,
            "d3": False,
            "formal_full": False,
        },
    }
    if not smoke and completed and final_step == 400:
        final = trajectory["checkpoints"][-1]["arms"]
        result["gate"] = recompute_d2a_gate(
            final["random"], final["pretrained"], wrapper["gate"]
        )
        result["scientific_status"] = result["gate"]["scientific_status"]
        result["authorization"] = result["gate"]["authorization"]
    _atomic_json(output / "result.json", result)
    for arm in arms.values():
        arm.tracker.close()
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
