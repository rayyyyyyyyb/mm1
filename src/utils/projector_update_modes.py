"""Explicit teacher-projector update semantics and optimizer receipts."""
from __future__ import annotations

import hashlib
from typing import Any, Mapping

from torch import nn


MODES = {"trainable", "frozen_no_grad", "static_zero_lr_keep_grad"}
MODE_KEYS = {
    "strong_teacher": "strong_teacher_projector_update_mode",
    "weak_teacher": "weak_teacher_projector_update_mode",
    "text_teacher": "text_teacher_projector_update_mode",
}
PROJECTOR_ATTRIBUTES = {
    "strong_teacher": "strong_teacher_proj",
    "weak_teacher": "weak_teacher_proj",
    "text_teacher": "text_teacher_proj",
}


def resolve_projector_update_modes(loss_cfg: Mapping[str, Any]) -> dict[str, str]:
    """Resolve explicit modes, failing closed on partial or old/new configs."""
    present = [key for key in MODE_KEYS.values() if key in loss_cfg]
    legacy_present = "teacher_target_projector_trainable" in loss_cfg
    if present and len(present) != len(MODE_KEYS):
        raise ValueError("all three projector update mode fields must be provided together")
    if present and legacy_present:
        raise ValueError("legacy teacher_target_projector_trainable conflicts with explicit projector modes")
    if present:
        modes = {name: str(loss_cfg[key]) for name, key in MODE_KEYS.items()}
        invalid = {name: mode for name, mode in modes.items() if mode not in MODES}
        if invalid:
            raise ValueError(f"unsupported projector update mode(s): {invalid}")
        return modes
    trainable = bool(loss_cfg.get("teacher_target_projector_trainable", True))
    mode = "trainable" if trainable else "frozen_no_grad"
    return {name: mode for name in MODE_KEYS}


def apply_projector_update_modes(loss_module: nn.Module, modes: Mapping[str, str]) -> None:
    expected = set(MODE_KEYS)
    if set(modes) != expected:
        raise ValueError(f"projector modes must contain exactly {sorted(expected)}")
    for name, mode in modes.items():
        if mode not in MODES:
            raise ValueError(f"unsupported projector update mode: {mode}")
        projector = getattr(loss_module, PROJECTOR_ATTRIBUTES[name], None)
        if not isinstance(projector, nn.Module):
            continue
        projector.requires_grad_(mode != "frozen_no_grad")
    setattr(loss_module, "projector_update_modes", dict(modes))


def tensor_state_sha256(module: nn.Module) -> str:
    digest = hashlib.sha256()
    for name, parameter in module.named_parameters():
        digest.update(name.encode("utf-8"))
        digest.update(str(tuple(parameter.shape)).encode("ascii"))
        digest.update(parameter.detach().cpu().contiguous().numpy().tobytes())
    for name, buffer in module.named_buffers():
        digest.update(name.encode("utf-8"))
        digest.update(str(tuple(buffer.shape)).encode("ascii"))
        digest.update(buffer.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def parameter_list_sha256(parameters: list[tuple[str, nn.Parameter]]) -> str:
    digest = hashlib.sha256()
    for name, parameter in parameters:
        digest.update(name.encode("utf-8"))
        digest.update(str(tuple(parameter.shape)).encode("ascii"))
        digest.update(parameter.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def _group(
    name: str,
    parameters: list[tuple[str, nn.Parameter]],
    *,
    learning_rate: float,
    weight_decay: float,
    update_mode: str,
) -> dict[str, Any]:
    if not parameters:
        raise ValueError(f"cannot create empty optimizer group: {name}")
    values = [parameter for _, parameter in parameters]
    names = [parameter_name for parameter_name, _ in parameters]
    return {
        "group_name": name,
        "params": values,
        "param_names": names,
        "parameter_count": int(sum(parameter.numel() for parameter in values)),
        "parameter_hash": parameter_list_sha256(parameters),
        "lr": float(learning_rate),
        "weight_decay": float(weight_decay),
        "update_mode": update_mode,
    }


def build_named_optimizer_groups(
    student: nn.Module,
    loss_module: nn.Module,
    *,
    learning_rate: float,
    weight_decay: float,
    modes: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Build deterministic student/projector groups with explicit receipts."""
    groups: list[dict[str, Any]] = []
    student_parameters = [(f"student.{name}", parameter) for name, parameter in student.named_parameters() if parameter.requires_grad]
    if student_parameters:
        groups.append(_group("student", student_parameters, learning_rate=learning_rate, weight_decay=weight_decay, update_mode="trainable"))
    for name, attribute in PROJECTOR_ATTRIBUTES.items():
        projector = getattr(loss_module, attribute, None)
        if not isinstance(projector, nn.Module) or modes[name] == "frozen_no_grad":
            continue
        parameters = [(f"loss.{attribute}.{parameter_name}", parameter) for parameter_name, parameter in projector.named_parameters() if parameter.requires_grad]
        if parameters:
            lr = 0.0 if modes[name] == "static_zero_lr_keep_grad" else learning_rate
            wd = 0.0 if modes[name] == "static_zero_lr_keep_grad" else weight_decay
            groups.append(_group(f"loss.{attribute}", parameters, learning_rate=lr, weight_decay=wd, update_mode=modes[name]))
    if not groups:
        raise ValueError("optimizer would contain no trainable parameters")
    return groups


def optimizer_group_receipts(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return JSON-safe metadata without serializing parameter tensors."""
    return [
        {
            "group_name": group["group_name"],
            "param_names": list(group["param_names"]),
            "parameter_count": int(group["parameter_count"]),
            "parameter_hash": group["parameter_hash"],
            "lr": float(group["lr"]),
            "weight_decay": float(group["weight_decay"]),
            "update_mode": group["update_mode"],
        }
        for group in groups
    ]
