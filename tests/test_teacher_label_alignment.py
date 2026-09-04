from __future__ import annotations

import numpy as np
import pytest

from scripts.audit_teacher_label_alignment import derive_boundaries, evaluate_representations


def test_derive_boundaries_handles_edges_masks_and_empty_or_full_labels() -> None:
    labels = np.asarray([[1, 1, 0, 0], [0, 0, 0, 0], [1, 1, 1, 1]], dtype=np.int64)
    mask = np.asarray([[1, 1, 1, 0], [1, 0, 0, 0], [1, 1, 1, 1]], dtype=bool)

    result = derive_boundaries(labels, mask)

    assert result["onset"].tolist() == [0, -1, 0]
    assert result["offset"].tolist() == [1, -1, 3]
    assert result["positive_count"].tolist() == [2, 0, 4]


def test_representation_alignment_is_deterministic_and_shape_strict() -> None:
    labels = np.zeros((2, 10), dtype=np.int64)
    labels[0, 0] = 1
    labels[1, 1] = 1
    mask = np.ones_like(labels, dtype=bool)
    boundaries = derive_boundaries(labels, mask)
    representation = np.asarray(
        [[[2.0], [0.0], [0.0], [0.0], [0.0], [0.0], [0.0], [0.0], [0.0], [0.0]],
         [[0.0], [2.0], [0.0], [0.0], [0.0], [0.0], [0.0], [0.0], [0.0], [0.0]]],
        dtype=np.float32,
    )
    queries = np.asarray([[1.0], [1.0]], dtype=np.float32)

    result = evaluate_representations(
        {"raw": representation}, labels, boundaries, queries, np.asarray([0, 10, 20])
    )

    assert result["representations"]["raw"]["sample_count"] == 2
    assert result["representations"]["raw"]["ap"] == pytest.approx(1.0)
    assert "raw+query" in result["representations"]
    assert result["task_segments"] == 10

    with pytest.raises(ValueError):
        evaluate_representations({"bad": representation[:, :2]}, labels, boundaries, queries, None)
