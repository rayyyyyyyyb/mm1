from __future__ import annotations

import json
from pathlib import Path

from PIL import Image
import numpy as np

from scripts.check_manifest import load_manifest, summarize_ov_avel


def _write_image(path: Path) -> None:
    array = np.random.randint(0, 255, size=(32, 32, 3), dtype=np.uint8)
    Image.fromarray(array).save(path)


def test_check_manifest_supports_source_manifest_without_teacher_artifacts(tmp_path: Path) -> None:
    frame_0 = tmp_path / "frame_0.jpg"
    frame_1 = tmp_path / "frame_1.jpg"
    spec_0 = tmp_path / "spec_0.jpg"
    spec_1 = tmp_path / "spec_1.jpg"
    audio_0 = tmp_path / "audio_0.wav"
    audio_1 = tmp_path / "audio_1.wav"

    _write_image(frame_0)
    _write_image(frame_1)
    _write_image(spec_0)
    _write_image(spec_1)
    audio_0.write_bytes(b"RIFF")
    audio_1.write_bytes(b"RIFF")

    manifest_path = tmp_path / "source.jsonl"
    record = {
        "id": "clip_0",
        "query": "dog barking",
        "frame_paths": [[str(frame_0)], [str(frame_1)]],
        "spectrogram_paths": [str(spec_0), str(spec_1)],
        "audio_paths": [str(audio_0), str(audio_1)],
        "segment_labels": [1, 0],
        "domain": "unit",
    }
    manifest_path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    summary = summarize_ov_avel(load_manifest(str(manifest_path)))

    assert summary["manifest_stage"] == "source"
    assert summary["missing_frames"] == 0
    assert summary["missing_spectrograms"] == 0
    assert summary["missing_audio_sources"] == 0
    assert summary["missing_strong_teacher_features"] == 0
    assert summary["missing_strong_teacher_logits"] == 0
    assert summary["missing_weak_teacher_features"] == 0
    assert summary["missing_text_embeddings"] == 0
