from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from scripts.preflight_ov_orthkd import run_preflight
from src.teachers import TeacherExportBundle, export_manifest_file
from src.teachers.common import load_records
from src.teachers.mock import MockStrongVisualTeacher, MockTextTeacher, MockWeakAudioTeacher


def _write_image(path: Path) -> None:
    array = np.random.randint(0, 255, size=(64, 64, 3), dtype=np.uint8)
    Image.fromarray(array).save(path)


def _write_source_manifest(path: Path, frame_paths: list[str], spec_paths: list[str]) -> None:
    records = [
        {
            "id": "clip_0",
            "query": "dog barking",
            "frame_paths": frame_paths[:3],
            "spectrogram_paths": spec_paths[:3],
            "audio_paths": ["audio_seg_0.wav", "audio_seg_1.wav", "audio_seg_2.wav"],
            "segment_labels": [1, 0, 1],
            "domain": "unit",
        },
        {
            "id": "clip_1",
            "query": "glass breaking",
            "frame_paths": frame_paths[:2],
            "spectrogram_paths": spec_paths[:2],
            "audio_paths": ["audio_seg_3.wav", "audio_seg_4.wav"],
            "segment_labels": [0, 1],
            "domain": "unit",
        },
    ]
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def test_export_and_preflight_pipeline(tmp_path: Path) -> None:
    frame_paths = []
    spec_paths = []
    for idx in range(3):
        frame_path = tmp_path / f"frame_{idx}.jpg"
        spec_path = tmp_path / f"spec_{idx}.jpg"
        _write_image(frame_path)
        _write_image(spec_path)
        frame_paths.append(str(frame_path))
        spec_paths.append(str(spec_path))

    source_manifest = tmp_path / "train_source.jsonl"
    exported_manifest = tmp_path / "train.jsonl"
    _write_source_manifest(source_manifest, frame_paths, spec_paths)

    export_summary = export_manifest_file(
        source_manifest=source_manifest,
        artifact_dir=tmp_path / "teacher_cache",
        output_manifest=exported_manifest,
        teachers=TeacherExportBundle(
            strong_visual=MockStrongVisualTeacher(feature_dim=32),
            weak_audio=MockWeakAudioTeacher(feature_dim=24),
            text_teacher=MockTextTeacher(feature_dim=16),
        ),
        overwrite=True,
    )

    assert export_summary["records_exported"] == 2

    records = load_records(exported_manifest)
    assert len(records) == 2
    assert np.load(records[0]["strong_teacher_features_path"]).shape == (3, 32)
    assert np.load(records[0]["strong_teacher_logits_path"]).shape == (3,)
    assert np.load(records[0]["weak_teacher_features_path"]).shape == (3, 24)
    assert np.load(records[0]["text_embedding_path"]).shape == (16,)

    config = {
        "seed": 42,
        "data": {
            "train_manifest": str(exported_manifest),
            "val_manifest": str(exported_manifest),
            "test_manifest": str(exported_manifest),
            "image_size": 64,
            "batch_size": 2,
            "num_workers": 0,
            "pin_memory": False,
            "max_segments": 4,
            "allow_missing_modalities": True,
            "strict_alignment": True,
            "strong_teacher_dim": 32,
            "weak_teacher_dim": 24,
            "strong_teacher_logit_dim": 1,
            "text_dim": 16,
            "train_augment": False,
        },
        "student": {
            "visual_backbone": "mobilenetv3_small_100",
            "audio_backbone": "mobilenetv3_small_100",
            "fusion_dim": 64,
            "temporal_layers": 2,
            "temporal_heads": 4,
            "temporal_dropout": 0.1,
            "pretrained": False,
        },
        "loss": {
            "projection_dim": 32,
        },
        "training": {
            "epochs": 2,
            "learning_rate": 2e-4,
            "weight_decay": 1e-4,
            "grad_clip": 1.0,
            "mixed_precision": False,
        },
        "logging": {
            "log_dir": str(tmp_path / "outputs"),
        },
    }

    preflight_summary = run_preflight(
        config=config,
        device_name="cpu",
        output_dir=tmp_path / "preflight",
        probe_samples=2,
        max_eval_batches=2,
    )

    assert preflight_summary["dataset_probe"]["train"]["samples_probed"] == 2
    assert preflight_summary["train_probe"]["batch_size"] == 2
    assert preflight_summary["resume_probe"]["resume_epoch"] == 1
    assert "ap" in preflight_summary["val_metrics"]
