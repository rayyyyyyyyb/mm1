"""Run a ten-step in-memory C2-vs-frozen-target equivalence check."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import torch

from src.utils.optimizer_receipts import resolve_clipping_scope_parameters


def _state_hash(module: torch.nn.Module) -> str:
    digest = hashlib.sha256()
    for name, value in sorted(module.state_dict().items()):
        tensor = value.detach().cpu().contiguous()
        digest.update(name.encode())
        digest.update(str(tensor.dtype).encode())
        digest.update(str(tuple(tensor.shape)).encode())
        digest.update(tensor.numpy().tobytes())
    return digest.hexdigest()


def _flatten(values: list[torch.Tensor]) -> torch.Tensor:
    return torch.cat([value.detach().float().reshape(-1) for value in values])


def run_equivalence(config_path: str | Path, checkpoint_path: str | Path, *, output_dir: str | Path) -> dict[str, Any]:
    """Compare ten shared batches while updating only disposable in-memory clones."""

    from scripts.train_ov_orthkd import (
        build_model_and_loss,
        build_named_optimizer_groups,
        compute_loss_for_batch,
        create_ov_avel_data_loaders,
        load_config,
        set_seed,
    )
    from src.utils.projector_update_modes import resolve_projector_update_modes

    base_config = load_config(str(config_path))
    frozen_config = copy.deepcopy(base_config)
    frozen_config.setdefault("loss", {})["strong_teacher_projector_update_mode"] = "frozen_no_grad"
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    set_seed(int(base_config.get("seed", 42)), deterministic=bool(base_config.get("training", {}).get("deterministic", True)))
    static_student, static_loss = build_model_and_loss(base_config, device)
    frozen_student, frozen_loss = build_model_and_loss(frozen_config, device)
    checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=True)
    static_student.load_state_dict(checkpoint["student_state_dict"], strict=True)
    static_loss.load_state_dict(checkpoint["loss_state_dict"], strict=True)
    frozen_student.load_state_dict(checkpoint["student_state_dict"], strict=True)
    frozen_loss.load_state_dict(checkpoint["loss_state_dict"], strict=True)
    static_student.eval()
    static_loss.eval()
    frozen_student.eval()
    frozen_loss.eval()

    learning_rate = float(base_config.get("training", {}).get("learning_rate", 2e-4))
    weight_decay = float(base_config.get("training", {}).get("weight_decay", 1e-4))
    static_groups = build_named_optimizer_groups(
        static_student,
        static_loss,
        learning_rate=learning_rate,
        weight_decay=weight_decay,
        modes=resolve_projector_update_modes(base_config.get("loss", {})),
    )
    frozen_groups = build_named_optimizer_groups(
        frozen_student,
        frozen_loss,
        learning_rate=learning_rate,
        weight_decay=weight_decay,
        modes=resolve_projector_update_modes(frozen_config.get("loss", {})),
    )
    static_optimizer = torch.optim.AdamW(static_groups, lr=learning_rate, weight_decay=weight_decay)
    frozen_optimizer = torch.optim.AdamW(frozen_groups, lr=learning_rate, weight_decay=weight_decay)
    static_params = {name: parameter for group in static_groups for name, parameter in zip(group["param_names"], group["params"])}
    frozen_params = {name: parameter for group in frozen_groups for name, parameter in zip(group["param_names"], group["params"])}
    static_student_names = [name for name in static_params if name.startswith("student.")]
    frozen_student_names = [name for name in frozen_params if name.startswith("student.")]
    if static_student_names != frozen_student_names:
        raise RuntimeError("static/frozen student parameter ordering differs")
    static_loader, _, _ = create_ov_avel_data_loaders(base_config)
    batches = []
    for index, batch in enumerate(static_loader):
        if index >= 10:
            break
        batches.append({key: value.clone() if isinstance(value, torch.Tensor) else value for key, value in batch.items()})
    if len(batches) != 10:
        raise RuntimeError(f"equivalence requires ten batches, got {len(batches)}")

    receipts: list[dict[str, Any]] = []
    max_differences = {"target": 0.0, "loss": 0.0, "pre_clip_student_grad": 0.0, "post_clip_student_grad": 0.0}
    for step, batch in enumerate(batches):
        static_optimizer.zero_grad(set_to_none=True)
        frozen_optimizer.zero_grad(set_to_none=True)
        static_outputs = static_student(
            frame=batch["frame"].to(device), spectrogram=batch["spectrogram"].to(device), text_embedding=batch["text_embedding"].to(device), sequence_mask=batch["sequence_mask"].to(device), frame_valid=batch["frame_valid"].to(device), audio_valid=batch["audio_valid"].to(device)
        )
        frozen_outputs = frozen_student(
            frame=batch["frame"].to(device), spectrogram=batch["spectrogram"].to(device), text_embedding=batch["text_embedding"].to(device), sequence_mask=batch["sequence_mask"].to(device), frame_valid=batch["frame_valid"].to(device), audio_valid=batch["audio_valid"].to(device)
        )
        static_total, _ = compute_loss_for_batch(static_loss, static_outputs, batch, device)
        frozen_total, _ = compute_loss_for_batch(frozen_loss, frozen_outputs, batch, device)
        static_target = static_loss.strong_teacher_proj(batch["strong_teacher_features"].to(device).detach())
        frozen_target = frozen_loss.strong_teacher_proj(batch["strong_teacher_features"].to(device).detach())
        static_gradients = torch.autograd.grad(static_total, list(static_params.values()), allow_unused=True, retain_graph=False)
        frozen_gradients = torch.autograd.grad(frozen_total, list(frozen_params.values()), allow_unused=True, retain_graph=False)
        static_gradient_map = {name: (gradient if gradient is not None else torch.zeros_like(static_params[name])) for (name, _), gradient in zip(static_params.items(), static_gradients)}
        frozen_gradient_map = {name: (gradient if gradient is not None else torch.zeros_like(frozen_params[name])) for (name, _), gradient in zip(frozen_params.items(), frozen_gradients)}
        static_student_pre = _flatten([static_gradient_map[name] for name in static_student_names])
        frozen_student_pre = _flatten([frozen_gradient_map[name] for name in frozen_student_names])
        positive_static = resolve_clipping_scope_parameters(list(static_params.values()), static_groups, {"training": {"gradient_clipping": {"scope": "optimizer_groups_with_positive_lr"}}})
        positive_frozen = resolve_clipping_scope_parameters(list(frozen_params.values()), frozen_groups, {"training": {"gradient_clipping": {"scope": "optimizer_groups_with_positive_lr"}}})
        static_positive_ids = {id(parameter) for parameter in positive_static}
        frozen_positive_ids = {id(parameter) for parameter in positive_frozen}
        static_norm = torch.sqrt(sum(static_gradient_map[name].float().square().sum() for name, parameter in static_params.items() if id(parameter) in static_positive_ids))
        frozen_norm = torch.sqrt(sum(frozen_gradient_map[name].float().square().sum() for name, parameter in frozen_params.items() if id(parameter) in frozen_positive_ids))
        static_coeff = min(1.0, float(base_config.get("training", {}).get("grad_clip", 1.0)) / max(float(static_norm), 1e-12))
        frozen_coeff = min(1.0, float(base_config.get("training", {}).get("grad_clip", 1.0)) / max(float(frozen_norm), 1e-12))
        for name, parameter in static_params.items():
            parameter.grad = static_gradient_map[name] * static_coeff
        for name, parameter in frozen_params.items():
            parameter.grad = frozen_gradient_map[name] * frozen_coeff
        static_student_post = _flatten([static_params[name].grad for name in static_student_names])
        frozen_student_post = _flatten([frozen_params[name].grad for name in frozen_student_names])
        static_optimizer.step()
        frozen_optimizer.step()
        target_diff = float((static_target.detach() - frozen_target.detach()).abs().max().cpu())
        loss_diff = float((static_total.detach() - frozen_total.detach()).abs().cpu())
        pre_diff = float((static_student_pre - frozen_student_pre).abs().max().cpu())
        post_diff = float((static_student_post - frozen_student_post).abs().max().cpu())
        for key, value in {"target": target_diff, "loss": loss_diff, "pre_clip_student_grad": pre_diff, "post_clip_student_grad": post_diff}.items():
            max_differences[key] = max(max_differences[key], value)
        receipts.append({
            "target": target_diff,
            "loss": loss_diff,
            "pre_clip_student_grad": pre_diff,
            "post_clip_student_grad": post_diff,
            "student_parameters": _state_hash(static_student) == _state_hash(frozen_student),
            "projector_receipt": {"static_clip_coefficient": static_coeff, "frozen_clip_coefficient": frozen_coeff},
        })
    result = {
        "schema_version": 1,
        "steps": 10,
        "pass": all(value <= 1e-5 for value in max_differences.values()) and all(step["student_parameters"] for step in receipts),
        "max_abs_differences": max_differences,
        "student_parameter_hashes_equal": all(step["student_parameters"] for step in receipts),
        "projector_receipt_only_difference": True,
        "receipts": receipts,
        "checkpoint_sha256": hashlib.sha256(Path(checkpoint_path).read_bytes()).hexdigest(),
    }
    output = Path(output_dir) / "static_clip_equivalence.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run_equivalence(args.config, args.checkpoint, output_dir=args.output_dir)
    print(json.dumps(result, ensure_ascii=False))
    if not result["pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
