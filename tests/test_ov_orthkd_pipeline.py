from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from src.data import QueryConditionedOVAvelDataset, create_ov_avel_data_loaders
from src.losses import OVOrthKDLegacyLoss
from src.models import OVOrthKDStudent
from scripts.train_ov_orthkd import evaluate


def _write_image(path: Path) -> None:
    array = np.random.randint(0, 255, size=(64, 64, 3), dtype=np.uint8)
    Image.fromarray(array).save(path)


def _write_features(path: Path, shape: tuple[int, ...]) -> None:
    np.save(path, np.random.randn(*shape).astype(np.float32))


def _write_manifest(path: Path, frame_paths: list[str], spec_paths: list[str], assets_dir: Path) -> None:
    records = []
    queries = ["dog barking", "glass breaking"]
    label_sets = [[1, 0, 1, 0], [0, 1, 0]]
    for idx, query in enumerate(queries):
        segment_labels = label_sets[idx]
        frame_subset = frame_paths[: len(segment_labels)]
        spec_subset = spec_paths[: len(segment_labels)]
        strong_feat = assets_dir / f"strong_feat_{idx}.npy"
        strong_logit = assets_dir / f"strong_logit_{idx}.npy"
        weak_feat = assets_dir / f"weak_feat_{idx}.npy"
        text_embed = assets_dir / f"text_{idx}.npy"
        _write_features(strong_feat, (len(segment_labels), 32))
        np.save(strong_logit, np.random.randn(len(segment_labels)).astype(np.float32))
        _write_features(weak_feat, (len(segment_labels), 24))
        _write_features(text_embed, (16,))

        records.append(
            {
                "id": f"sample_{idx}",
                "query": query,
                "frame_paths": frame_subset,
                "spectrogram_paths": spec_subset,
                "segment_labels": segment_labels,
                "strong_teacher_features_path": str(strong_feat),
                "strong_teacher_logits_path": str(strong_logit),
                "weak_teacher_features_path": str(weak_feat),
                "text_embedding_path": str(text_embed),
                "domain": "unit",
            }
        )
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def test_ov_orthkd_vertical_slice(tmp_path: Path) -> None:
    frame_paths = []
    spec_paths = []
    for idx in range(4):
        frame_path = tmp_path / f"frame_{idx}.jpg"
        spec_path = tmp_path / f"spec_{idx}.jpg"
        _write_image(frame_path)
        _write_image(spec_path)
        frame_paths.append(str(frame_path))
        spec_paths.append(str(spec_path))

    manifest_path = tmp_path / "train.jsonl"
    _write_manifest(manifest_path, frame_paths, spec_paths, tmp_path)

    dataset = QueryConditionedOVAvelDataset(
        manifest_path=str(manifest_path),
        image_size=64,
        max_segments=4,
        augment=False,
        strong_teacher_dim=32,
        weak_teacher_dim=24,
        strong_teacher_logit_dim=1,
        text_dim=16,
    )
    sample = dataset[0]
    assert sample["frame"].shape == (4, 3, 64, 64)
    assert sample["strong_teacher_features"].shape == (4, 32)
    assert sample["weak_teacher_features"].shape == (4, 24)

    config = {
        "data": {
            "train_manifest": str(manifest_path),
            "val_manifest": str(manifest_path),
            "image_size": 64,
            "batch_size": 2,
            "num_workers": 0,
            "pin_memory": False,
            "max_segments": 4,
            "allow_missing_modalities": True,
            "strong_teacher_dim": 32,
            "weak_teacher_dim": 24,
            "strong_teacher_logit_dim": 1,
            "text_dim": 16,
            "train_augment": False,
        }
    }
    train_loader, val_loader, _ = create_ov_avel_data_loaders(config)
    batch = next(iter(train_loader))

    student = OVOrthKDStudent(
        visual_backbone="mobilenetv3_small_100",
        audio_backbone="mobilenetv3_small_100",
        text_dim=16,
        fusion_dim=64,
        path_mode="legacy_shared",
        temporal_layers=2,
        temporal_heads=4,
        temporal_dropout=0.1,
        max_segments=4,
        pretrained=False,
    )
    outputs = student(
        frame=batch["frame"],
        spectrogram=batch["spectrogram"],
        text_embedding=batch["text_embedding"],
        sequence_mask=batch["sequence_mask"],
        frame_valid=batch["frame_valid"],
        audio_valid=batch["audio_valid"],
    )

    loss_module = OVOrthKDLegacyLoss(
        student_dim=64,
        strong_teacher_dim=32,
        weak_teacher_dim=24,
        text_dim=16,
        projection_dim=32,
    )
    loss, stats = loss_module(
        student_segment_logits=outputs["segment_logits"],
        student_segment_features=outputs["segment_features"],
        strong_teacher_logits=batch["strong_teacher_logits"],
        strong_teacher_features=batch["strong_teacher_features"],
        weak_teacher_features=batch["weak_teacher_features"],
        text_embeddings=batch["text_embedding"],
        segment_labels=batch["segment_label"],
        sequence_mask=batch["sequence_mask"],
        strong_teacher_logit_mask=batch["strong_teacher_logit_mask"],
        strong_teacher_feature_mask=batch["strong_teacher_feature_mask"],
        weak_teacher_mask=batch["weak_teacher_mask"] * batch["audio_valid"],
        text_valid=batch["text_valid"],
    )

    loss.backward()

    metrics = evaluate(student, val_loader, device=torch.device("cpu"), max_batches=2)

    assert outputs["segment_logits"].shape == (2, 4)
    assert outputs["segment_features"].shape == (2, 4, 64)
    assert torch.isfinite(loss)
    assert stats["total"] > 0.0
    assert "ap" in metrics
