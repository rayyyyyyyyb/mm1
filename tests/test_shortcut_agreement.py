from __future__ import annotations

import copy

import numpy as np
import pytest
import torch

from scripts.audit_shortcut_agreement import (
    mean_centered_decomposition,
    stratified_batches,
    tie_aware_mixed_concordance,
    virtual_adamw_delta,
)


def _records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for index in range(44):
        count = index % 11
        records.append({"id": f"r{index:02d}", "segment_labels": [1] * count + [0] * (10 - count)})
    return records


def test_stratified_batches_are_disjoint_and_cover_requested_strata() -> None:
    records = _records()
    batches = stratified_batches(records, ("k0", "kmid", "k10", "mixed_only"), 2, 2, 7)
    assert set(batches) == {"k0", "kmid", "k10", "mixed_only"}
    ids = [record["id"] for rows in batches.values() for batch in rows for record in batch]
    assert len(ids) == len(set(ids))
    assert all(len(batch) == 2 for rows in batches.values() for batch in rows)


def test_kmid_and_mixed_only_use_exactly_two_disjoint_pool_slices() -> None:
    records = []
    for index in range(8):
        labels = [0] * 10
        labels[index % 9] = 1
        records.append({"id": f"mixed-{index}", "segment_labels": labels})

    batches = stratified_batches(
        records,
        ("kmid", "mixed_only"),
        batches_per_stratum=2,
        batch_size=2,
        seed=42,
    )

    kmid_ids = {record["id"] for batch in batches["kmid"] for record in batch}
    mixed_only_ids = {
        record["id"] for batch in batches["mixed_only"] for record in batch
    }
    assert len(kmid_ids) == 4
    assert len(mixed_only_ids) == 4
    assert kmid_ids.isdisjoint(mixed_only_ids)


def test_mean_plus_centered_identity_is_exact() -> None:
    student = torch.tensor([[[1.0, 4.0], [3.0, 2.0], [5.0, 6.0]]])
    target = torch.tensor([[[0.0, 1.0], [1.0, 1.0], [3.0, 4.0]]])
    mask = torch.tensor([[True, True, False]])
    result = mean_centered_decomposition(student, target, mask)
    assert result["identity_abs_error"] == pytest.approx(0.0)
    assert result["total"] == pytest.approx(result["mean"] + result["centered"])


def test_virtual_adamw_delta_does_not_mutate_inputs() -> None:
    parameters = {"p": torch.tensor([1.0, -2.0])}
    gradients = {"p": torch.tensor([3.0, 4.0])}
    before_parameters = copy.deepcopy(parameters)
    before_gradients = copy.deepcopy(gradients)
    result = virtual_adamw_delta(parameters, gradients, learning_rate=0.1, weight_decay=0.01, max_norm=1.0)
    assert torch.equal(parameters["p"], before_parameters["p"])
    assert torch.equal(gradients["p"], before_gradients["p"])
    assert result["clip_coefficient"] == pytest.approx(0.2)


def test_ties_receive_half_credit_in_mixed_aggregation() -> None:
    labels = np.asarray([[1, 0, 1, 0]])
    scores = np.asarray([[0.5, 0.5, 0.5, 0.0]])
    result = tie_aware_mixed_concordance(labels, scores)
    assert result["pair_weighted_concordance"] == pytest.approx(0.75)
