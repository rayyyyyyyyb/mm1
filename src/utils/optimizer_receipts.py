"""Applied optimizer-step, clipping, and AMP accounting utilities."""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Any, Iterable

import torch
from torch import nn


def resolve_clipping_scope_parameters(
    parameters: list[nn.Parameter],
    groups: list[dict[str, Any]],
    config: dict[str, Any] | None,
) -> list[nn.Parameter]:
    """Resolve explicit clipping scope and fail closed on unknown values."""

    training_cfg = config.get("training", {}) if isinstance(config, dict) else {}
    clipping_cfg = training_cfg.get("gradient_clipping", {}) if isinstance(training_cfg, dict) else {}
    scope = str(clipping_cfg.get("scope", "all_parameters")) if isinstance(clipping_cfg, dict) else "all_parameters"
    if scope == "all_parameters":
        return parameters
    if scope != "optimizer_groups_with_positive_lr":
        raise ValueError(f"unsupported gradient clipping scope: {scope}")
    selected = [
        parameter
        for group in groups
        if float(group.get("lr", 0.0)) > 0.0
        for parameter in group["params"]
    ]
    if not selected:
        raise ValueError("positive-LR clipping scope selected no parameters")
    return selected


def _norm(parameters: Iterable[nn.Parameter]) -> float:
    squared = 0.0
    for parameter in parameters:
        if parameter.grad is not None:
            squared += float(parameter.grad.detach().float().square().sum().cpu())
    return math.sqrt(squared)


@dataclass
class OptimizerStepReceipt:
    attempted_step: int
    applied_step: int
    overflow: bool
    pre_clip_global_norm: float
    clip_coefficient: float
    clipped: bool
    amp_scale_before: float | None
    amp_scale_after: float | None
    group_norms: dict[str, float]
    group_contributions: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OptimizerStepTracker:
    """Count actual ``optimizer.step`` calls using optimizer hooks."""

    def __init__(self, optimizer: torch.optim.Optimizer) -> None:
        self.optimizer = optimizer
        self.attempted_steps = 0
        self.applied_steps = 0
        self._pre_handle = optimizer.register_step_pre_hook(self._pre_hook)
        self._post_handle = optimizer.register_step_post_hook(self._post_hook)

    def _pre_hook(self, optimizer: torch.optim.Optimizer, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        del optimizer, args, kwargs

    def _post_hook(self, optimizer: torch.optim.Optimizer, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        del optimizer, args, kwargs
        # GradScaler skips ``optimizer.step`` entirely on overflow, so the
        # post-hook counts only successfully returned optimizer applications.
        self.applied_steps += 1

    def record_attempt(self) -> int:
        self.attempted_steps += 1
        return self.attempted_steps

    def close(self) -> None:
        self._pre_handle.remove()
        self._post_handle.remove()


def clip_gradients_with_receipt(
    parameters: list[nn.Parameter],
    groups: list[dict[str, Any]],
    max_norm: float,
    clip_parameters: list[nn.Parameter] | None = None,
) -> tuple[float, float, dict[str, float], dict[str, float], bool]:
    """Clip once and return pre-norm, coefficient, and all-group shares.

    ``clip_parameters`` is an explicit scope override.  Group receipts still
    include every supplied group so a zero-LR projector remains auditable even
    when it is excluded from the clipping norm.
    """
    if max_norm <= 0:
        raise ValueError("max_norm must be positive")
    active_parameters = parameters if clip_parameters is None else clip_parameters
    if not active_parameters:
        raise ValueError("clip_parameters must not be empty")
    pre_norm = _norm(active_parameters)
    coefficient = min(1.0, max_norm / max(pre_norm, 1e-12))
    group_norms = {
        str(group["group_name"]): _norm(group["params"])
        for group in groups
    }
    denominator = max(pre_norm * pre_norm, 1e-24)
    group_contributions = {
        name: float(value * value / denominator)
        for name, value in group_norms.items()
    }
    torch.nn.utils.clip_grad_norm_(active_parameters, max_norm)
    return pre_norm, coefficient, group_norms, group_contributions, pre_norm > max_norm
