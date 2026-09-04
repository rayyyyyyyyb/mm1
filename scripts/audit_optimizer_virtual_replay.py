"""Pure in-memory AdamW replay for diagnosing global clipping coupling."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import torch


def _group_meta(name: str, optimizer_state: Mapping[str, Any]) -> Mapping[str, Any]:
    groups = optimizer_state.get("groups", {})
    if isinstance(groups, Mapping) and isinstance(groups.get(name), Mapping):
        return groups[name]
    return optimizer_state.get("hyperparameters", {}) if isinstance(optimizer_state.get("hyperparameters", {}), Mapping) else {}


def _state_for(name: str, optimizer_state: Mapping[str, Any], parameter: torch.Tensor) -> Mapping[str, Any]:
    state = optimizer_state.get("state", {})
    value = state.get(name, {}) if isinstance(state, Mapping) else {}
    if not isinstance(value, Mapping):
        value = {}
    return value


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def replay_virtual_update(
    parameters: Mapping[str, torch.Tensor],
    optimizer_state: Mapping[str, Any],
    gradients: Mapping[str, torch.Tensor],
    *,
    clip_scope: str,
) -> dict[str, Any]:
    """Replay one AdamW step on clones; input tensors and state are untouched.

    The state schema is intentionally small and JSON/checkpoint friendly:
    ``groups[name]`` supplies ``lr``/``weight_decay`` and ``hyperparameters``
    supplies AdamW ``betas``, ``eps`` and ``max_norm``.  Missing moments are
    initialized as AdamW does for a fresh parameter.
    """

    if clip_scope not in {"current_global_all_grad_clip", "updating_parameters_only_clip"}:
        raise ValueError(f"unsupported clip_scope: {clip_scope}")
    names = list(parameters)
    if set(gradients) != set(names):
        raise ValueError("parameters and gradients must have identical names")
    hyper = optimizer_state.get("hyperparameters", {})
    if not isinstance(hyper, Mapping):
        hyper = {}
    max_norm = _float(hyper.get("max_norm", 1.0), 1.0)
    beta_values = hyper.get("betas", (0.9, 0.999))
    if not isinstance(beta_values, (tuple, list)) or len(beta_values) != 2:
        raise ValueError("betas must be a pair")
    beta1, beta2 = float(beta_values[0]), float(beta_values[1])
    eps = _float(hyper.get("eps", 1e-8), 1e-8)
    included = [
        name
        for name in names
        if clip_scope == "current_global_all_grad_clip" or _float(_group_meta(name, optimizer_state).get("lr", 0.0), 0.0) > 0.0
    ]
    squared_norm = sum(float(gradients[name].detach().float().square().sum().cpu()) for name in included)
    global_norm = float(np.sqrt(max(squared_norm, 0.0)))
    coefficient = 1.0 if max_norm <= 0.0 or global_norm <= max_norm else max_norm / max(global_norm, 1e-12)
    clipped_gradients = {name: gradients[name].detach().clone() * coefficient for name in names}
    state_after: dict[str, dict[str, Any]] = {}
    output_parameters: dict[str, torch.Tensor] = {}
    deltas: dict[str, torch.Tensor] = {}
    for name, parameter in parameters.items():
        parameter_clone = parameter.detach().clone()
        meta = _group_meta(name, optimizer_state)
        lr = _float(meta.get("lr", 0.0), 0.0)
        weight_decay = _float(meta.get("weight_decay", 0.0), 0.0)
        old = _state_for(name, optimizer_state, parameter)
        step = int(old.get("step", 0)) + 1
        exp_avg = old.get("exp_avg", torch.zeros_like(parameter_clone)).detach().clone()
        exp_avg_sq = old.get("exp_avg_sq", torch.zeros_like(parameter_clone)).detach().clone()
        grad = clipped_gradients[name].to(dtype=parameter_clone.dtype, device=parameter_clone.device)
        exp_avg = exp_avg * beta1 + grad * (1.0 - beta1)
        exp_avg_sq = exp_avg_sq * beta2 + grad.square() * (1.0 - beta2)
        bias_correction1 = 1.0 - beta1**step
        bias_correction2 = 1.0 - beta2**step
        step_size = lr * (bias_correction2**0.5) / max(bias_correction1, 1e-30)
        updated = parameter_clone * (1.0 - lr * weight_decay)
        updated = updated - step_size * exp_avg / (exp_avg_sq.sqrt() + eps)
        output_parameters[name] = updated
        deltas[name] = updated - parameter_clone
        state_after[name] = {"step": step, "exp_avg": exp_avg, "exp_avg_sq": exp_avg_sq}
    return {
        "clip_scope": clip_scope,
        "included_parameters": included,
        "global_norm": global_norm,
        "clip_coefficient": coefficient,
        "parameters": output_parameters,
        "deltas": deltas,
        "clipped_gradients": clipped_gradients,
        "state_after": state_after,
    }


def _cosine(left: torch.Tensor, right: torch.Tensor) -> float | None:
    left_value, right_value = left.detach().float().reshape(-1), right.detach().float().reshape(-1)
    denominator = float(torch.linalg.vector_norm(left_value) * torch.linalg.vector_norm(right_value))
    if denominator <= 1e-12:
        return None
    return float(torch.dot(left_value, right_value) / denominator)


def summarize_virtual_deltas(replays: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    names = list(replays)
    if not names:
        return {"scopes": [], "parameters": {}}
    parameter_names = sorted(set().union(*(set(replay.get("deltas", {})) for replay in replays.values())))
    parameters: dict[str, Any] = {}
    for parameter_name in parameter_names:
        per_scope = {}
        for scope, replay in replays.items():
            gradient = replay.get("clipped_gradients", {}).get(parameter_name, torch.zeros(0))
            delta = replay.get("deltas", {}).get(parameter_name, torch.zeros(0))
            per_scope[scope] = {
                "gradient_norm": float(torch.linalg.vector_norm(gradient).cpu()),
                "delta_norm": float(torch.linalg.vector_norm(delta).cpu()),
            }
        if len(names) >= 2:
            first, second = names[0], names[1]
            delta_first = replays[first].get("deltas", {}).get(parameter_name, torch.zeros(0))
            delta_second = replays[second].get("deltas", {}).get(parameter_name, torch.zeros(0))
            per_scope["pairwise_delta_cosine"] = _cosine(delta_first, delta_second)
            norm_first = per_scope[first]["delta_norm"]
            norm_second = per_scope[second]["delta_norm"]
            per_scope["delta_norm_ratio_second_over_first"] = None if norm_first <= 1e-12 else norm_second / norm_first
        parameters[parameter_name] = per_scope
    return {"scopes": names, "parameters": parameters}


def audit_model_checkpoint(
    config_path: str | Path,
    checkpoint_path: str | Path,
    *,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Replay one real C1 batch with both clipping scopes, without stepping."""

    from scripts.train_ov_orthkd import (
        build_model_and_loss,
        build_named_optimizer_groups,
        build_runtime_reproduction_fingerprint,
        compute_loss_for_batch,
        create_ov_avel_data_loaders,
        load_config,
        load_evaluation_checkpoint,
        set_seed,
    )
    from src.utils.projector_update_modes import resolve_projector_update_modes

    config = load_config(str(config_path))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    set_seed(int(config.get("seed", 42)), deterministic=bool(config.get("training", {}).get("deterministic", True)))
    student, loss_module = build_model_and_loss(config, device)
    load_evaluation_checkpoint(
        student=student,
        resume_path=str(checkpoint_path),
        expected_fingerprint=build_runtime_reproduction_fingerprint(config),
        allow_incompatible=True,
        incompatible_marker_path=Path(output_dir) / "INCOMPATIBLE_RESUME.txt",
    )
    modes = resolve_projector_update_modes(config.get("loss", {}))
    groups = build_named_optimizer_groups(
        student,
        loss_module,
        learning_rate=float(config.get("training", {}).get("learning_rate", 2e-4)),
        weight_decay=float(config.get("training", {}).get("weight_decay", 1e-4)),
        modes=modes,
    )
    optimizer = torch.optim.AdamW(groups, lr=2e-4, weight_decay=1e-4)
    checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=True)
    optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
    train_loader, _, _ = create_ov_avel_data_loaders(config)
    batch = next(iter(train_loader))
    student.eval()
    loss_module.eval()
    outputs = student(
        frame=batch["frame"].to(device),
        spectrogram=batch["spectrogram"].to(device),
        text_embedding=batch["text_embedding"].to(device),
        sequence_mask=batch["sequence_mask"].to(device),
        frame_valid=batch["frame_valid"].to(device),
        audio_valid=batch["audio_valid"].to(device),
    )
    total_loss, stats = compute_loss_for_batch(loss_module, outputs, batch, device)
    named_parameters: list[tuple[str, torch.nn.Parameter, Mapping[str, Any]]] = []
    for group in groups:
        for name, parameter in zip(group["param_names"], group["params"]):
            named_parameters.append((name, parameter, group))
    gradients_raw = torch.autograd.grad(
        total_loss,
        [parameter for _, parameter, _ in named_parameters],
        allow_unused=True,
        retain_graph=False,
        create_graph=False,
    )
    parameters = {name: parameter.detach() for name, parameter, _ in named_parameters}
    gradients = {
        name: (gradient.detach() if gradient is not None else torch.zeros_like(parameter))
        for (name, parameter, _), gradient in zip(named_parameters, gradients_raw)
    }
    optimizer_state: dict[str, Any] = {
        "groups": {
            name: {"lr": float(group["lr"]), "weight_decay": float(group["weight_decay"])}
            for name, _, group in named_parameters
        },
        "hyperparameters": {
            "betas": tuple(optimizer.defaults.get("betas", (0.9, 0.999))),
            "eps": float(optimizer.defaults.get("eps", 1e-8)),
            "max_norm": float(config.get("training", {}).get("grad_clip", 1.0)),
        },
        "state": {
            name: {
                key: value.detach().clone()
                for key, value in optimizer.state.get(parameter, {}).items()
                if key in {"step", "exp_avg", "exp_avg_sq"}
            }
            for name, parameter, _ in named_parameters
        },
    }
    replays = {
        scope: replay_virtual_update(parameters, optimizer_state, gradients, clip_scope=scope)
        for scope in ("current_global_all_grad_clip", "updating_parameters_only_clip")
    }
    compact: dict[str, Any] = {}
    for scope, replay in replays.items():
        module_receipts: dict[str, dict[str, float]] = {}
        for name, gradient in replay["clipped_gradients"].items():
            if not name.startswith("student."):
                continue
            module = name.split(".", 2)[1]
            receipt = module_receipts.setdefault(module, {"gradient_norm_sq": 0.0, "delta_norm_sq": 0.0})
            receipt["gradient_norm_sq"] += float(gradient.detach().float().square().sum().cpu())
            receipt["delta_norm_sq"] += float(replay["deltas"][name].detach().float().square().sum().cpu())
        for receipt in module_receipts.values():
            receipt["gradient_norm"] = float(np.sqrt(receipt.pop("gradient_norm_sq")))
            receipt["delta_norm"] = float(np.sqrt(receipt.pop("delta_norm_sq")))
        compact[scope] = {
            "global_norm": replay["global_norm"],
            "clip_coefficient": replay["clip_coefficient"],
            "included_parameter_count": len(replay["included_parameters"]),
            "student_modules": module_receipts,
        }
    compact["student_delta_cosines"] = {}
    for module in sorted({name.split(".", 2)[1] for name in parameters if name.startswith("student.") and "." in name[8:]}):
        first_values = [
            replays["current_global_all_grad_clip"]["deltas"][name].reshape(-1)
            for name in parameters
            if name.startswith(f"student.{module}.")
        ]
        second_values = [
            replays["updating_parameters_only_clip"]["deltas"][name].reshape(-1)
            for name in parameters
            if name.startswith(f"student.{module}.")
        ]
        if first_values and second_values:
            compact["student_delta_cosines"][module] = _cosine(
                torch.cat(first_values), torch.cat(second_values)
            )
    import hashlib

    return {
        "schema_version": 1,
        "device": str(device),
        "checkpoint_sha256": hashlib.sha256(Path(checkpoint_path).read_bytes()).hexdigest(),
        "batch_ids": [str(value) for value in batch.get("id", [])],
        "loss_stats": stats,
        "scopes": compact,
        "input_state_unchanged": True,
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, torch.Tensor):
        return value.detach().cpu().tolist()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="JSON virtual-replay receipt")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.config is not None:
        if args.input is not None or args.checkpoint is None:
            raise ValueError("--config requires --checkpoint and cannot be combined with --input")
        payload = audit_model_checkpoint(args.config, args.checkpoint, output_dir=args.output.parent)
    else:
        if args.input is None or args.checkpoint is not None:
            raise ValueError("--input is required when --config is not supplied")
        payload = json.loads(args.input.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(_jsonable(payload), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(_jsonable(payload), ensure_ascii=False))


if __name__ == "__main__":
    main()
