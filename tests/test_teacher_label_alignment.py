from __future__ import annotations

import numpy as np
import pytest

import scripts.audit_teacher_label_alignment as alignment
from scripts.audit_teacher_label_alignment import audit_train_fit, derive_boundaries, evaluate_representations


def test_zero_metric_is_not_treated_as_missing() -> None:
    assert alignment._metric_or_missing(0.0) == 0.0
    assert alignment._metric_or_missing(None) == -1.0


def test_train_fit_rejects_train_validation_sample_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"ids": np.asarray(["shared-id"])}
    monkeypatch.setattr(alignment, "_load_manifest_arrays", lambda *args, **kwargs: payload)
    with pytest.raises(ValueError, match="overlap"):
        audit_train_fit("train.jsonl", "val.jsonl", initial_projector_checkpoint="unused.pt")


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


def test_train_fit_audit_uses_separate_query_ids_and_emits_json_safe_summary(tmp_path) -> None:
    pytest.importorskip("timm")
    import torch
    from src.models.ov_orthkd import ProjectionHead

    root = tmp_path
    projector = ProjectionHead(512, 256)
    checkpoint = root / "initial.pt"
    torch.save({"loss_state_dict": {f"strong_teacher_proj.{key}": value for key, value in projector.state_dict().items()}}, checkpoint)
    train_lines = []
    val_lines = []
    for split, target in (("train", train_lines), ("val", val_lines)):
        for index in range(4):
            features_path = root / f"{split}_{index}_features.npy"
            logits_path = root / f"{split}_{index}_logits.npy"
            query_path = root / f"{split}_{index}_query.npy"
            np.save(features_path, np.full((10, 512), index + 1, dtype=np.float32))
            np.save(logits_path, np.linspace(-1.0, 1.0, 10, dtype=np.float32) + index)
            np.save(query_path, np.full((1024,), index + 1, dtype=np.float32))
            target.append(
                {
                    "id": f"{split}-{index}",
                    "query": f"query-{index % 2}",
                    "segment_labels": [0, 1] * 5,
                    "strong_teacher_features_path": str(features_path),
                    "strong_teacher_logits_path": str(logits_path),
                    "text_embedding_path": str(query_path),
                }
            )
    import json

    train_manifest = root / "train.jsonl"
    val_manifest = root / "val.jsonl"
    train_manifest.write_text("\n".join(json.dumps(row) for row in train_lines) + "\n", encoding="utf-8")
    val_manifest.write_text("\n".join(json.dumps(row) for row in val_lines) + "\n", encoding="utf-8")

    result = audit_train_fit(
        train_manifest,
        val_manifest,
        initial_projector_checkpoint=checkpoint,
        workers=1,
        shuffle_repeats=2,
        common_dim=4,
    )

    assert result["protocol"]["query_conditioning"] == "[v,q,v*q,position] with fixed label-independent maps"
    assert result["query_fields"]["validation_unique_query_ids"] == 2
    assert result["transitions"]["validation"]["total_transitions"] == 36
    assert result["probes"]["raw_teacher"]["metrics"]["shuffle"]["repeats"] == 2
