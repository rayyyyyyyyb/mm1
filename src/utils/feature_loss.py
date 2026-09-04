"""Pure tensor diagnostics for temporal visual feature losses."""
from __future__ import annotations

from typing import Dict

import torch


def decompose_temporal_squared_error(
    student: torch.Tensor,
    target: torch.Tensor,
    mask: torch.Tensor,
    group_labels: torch.Tensor | None = None,
) -> Dict[str, torch.Tensor | Dict[str, Dict[str, float | int]]]:
    """Decompose masked temporal squared error into mean and centered terms.

    For each sample, with ``n`` valid task segments, this computes
    ``n*||mean(s)-mean(y)||²`` and the centered residual sum.  The identity is
    exact for arbitrary masks; the official protocol supplies ``n=10``.
    When labels are supplied, aggregate rows by the number of positive labels.
    """
    if student.ndim != 3 or target.shape != student.shape:
        raise ValueError("student and target must have identical [B, T, D] shapes")
    if mask.shape != student.shape[:2]:
        raise ValueError("mask must have shape [B, T]")
    if group_labels is not None and group_labels.shape != mask.shape:
        raise ValueError("group_labels must have shape [B, T]")
    work_student = student.float()
    work_target = target.float()
    valid = mask.to(dtype=torch.bool)
    sample_mean_terms: list[torch.Tensor] = []
    sample_temporal_terms: list[torch.Tensor] = []
    sample_total_terms: list[torch.Tensor] = []
    groups: dict[str, dict[str, float | int]] = {}
    for index in range(student.shape[0]):
        row_valid = valid[index]
        count = int(row_valid.sum().item())
        if count == 0:
            mean_term = work_student.new_zeros(())
            temporal_term = work_student.new_zeros(())
            total_term = work_student.new_zeros(())
        else:
            s = work_student[index, row_valid]
            y = work_target[index, row_valid]
            difference = s - y
            mean_difference = difference.mean(dim=0)
            mean_term = count * mean_difference.square().sum()
            centered_difference = difference - mean_difference
            temporal_term = centered_difference.square().sum()
            total_term = difference.square().sum()
            if not torch.allclose(total_term, mean_term + temporal_term, rtol=2e-5, atol=2e-6):
                raise RuntimeError("temporal squared-error decomposition identity failed")
        sample_mean_terms.append(mean_term)
        sample_temporal_terms.append(temporal_term)
        sample_total_terms.append(total_term)
        if group_labels is not None:
            k = int(group_labels[index][row_valid].float().sum().item()) if count else 0
            key = f"k={k}"
            bucket = groups.setdefault(key, {"samples": 0, "mean_term": 0.0, "temporal_term": 0.0, "total": 0.0})
            bucket["samples"] = int(bucket["samples"]) + 1
            bucket["mean_term"] = float(bucket["mean_term"]) + float(mean_term.detach().cpu())
            bucket["temporal_term"] = float(bucket["temporal_term"]) + float(temporal_term.detach().cpu())
            bucket["total"] = float(bucket["total"]) + float(total_term.detach().cpu())
    mean_terms = torch.stack(sample_mean_terms)
    temporal_terms = torch.stack(sample_temporal_terms)
    total_terms = torch.stack(sample_total_terms)
    if group_labels is not None:
        groups["overall"] = {
            "samples": int(student.shape[0]),
            "mean_term": float(mean_terms.sum().detach().cpu()),
            "temporal_term": float(temporal_terms.sum().detach().cpu()),
            "total": float(total_terms.sum().detach().cpu()),
        }
    return {
        "mean_term": mean_terms.sum(),
        "temporal_term": temporal_terms.sum(),
        "total": total_terms.sum(),
        "sample_mean_term": mean_terms,
        "sample_temporal_term": temporal_terms,
        "sample_total": total_terms,
        "groups": groups,
    }
