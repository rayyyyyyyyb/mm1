from __future__ import annotations

import json
from pathlib import Path


def _record(record_id: str, audio_path: str) -> dict:
    return {
        "id": record_id,
        "audio_path": audio_path,
        "segment_labels": [0] * 10,
        "segment_timestamps": [[float(index), float(index + 1)] for index in range(10)],
    }


def test_audio_task_window_audit_accounts_for_padding_truncation_and_exact_t10(
    tmp_path: Path,
) -> None:
    from scripts.audit_ovave_audio_task_windows import audit_audio_task_windows

    records = [
        _record("short", "short.wav"),
        _record("exact", "exact.wav"),
        _record("long", "long.wav"),
    ]
    manifest = tmp_path / "train.jsonl"
    manifest.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )
    for name in ("short.wav", "exact.wav", "long.wav"):
        (tmp_path / name).write_bytes(b"RIFF")
    frames = {
        "short.wav": 9 * 16_000,
        "exact.wav": 10 * 16_000,
        "long.wav": 11 * 16_000,
    }

    report = audit_audio_task_windows(
        manifests={"train": manifest},
        path_root=tmp_path,
        expected_counts={"train": 3},
        info_reader=lambda path: (frames[path.name], 16_000),
    )

    assert report["status"] == "passed"
    assert report["record_count"] == 3
    assert report["waveform_fit_counts"] == {
        "zero_pad_to_task_duration": 1,
        "unchanged": 1,
        "truncate_to_task_duration": 1,
    }
    assert report["zero_padding_samples"] == 16_000
    assert report["truncated_samples"] == 16_000
    assert report["task_segments"] == 10
    assert report["temporal_resampling_performed"] is False
    assert report["errors"] == []


def test_audio_task_window_audit_rejects_noncanonical_timestamps(tmp_path: Path) -> None:
    from scripts.audit_ovave_audio_task_windows import audit_audio_task_windows

    record = _record("bad", "bad.wav")
    record["segment_timestamps"][-1] = [8.5, 10.0]
    manifest = tmp_path / "train.jsonl"
    manifest.write_text(json.dumps(record) + "\n", encoding="utf-8")
    (tmp_path / "bad.wav").write_bytes(b"RIFF")

    report = audit_audio_task_windows(
        manifests={"train": manifest},
        path_root=tmp_path,
        expected_counts={"train": 1},
        info_reader=lambda path: (10 * 16_000, 16_000),
    )

    assert report["status"] == "failed"
    assert report["errors"][0]["code"] == "temporal_protocol"


def test_canonical_audio_audit_binding_rejects_a_relocked_bad_policy() -> None:
    from src.utils.canonical_readiness import validate_audio_task_window_audit

    report = {
        "schema_version": 1,
        "status": "passed",
        "record_count": 24800,
        "split_counts": {"train": 13182, "val": 5798, "test": 5820},
        "task_segments": 10,
        "task_duration_seconds": 10,
        "required_sample_rate": 16000,
        "short_waveform_policy": "zero_pad_to_task_duration",
        "long_waveform_policy": "truncate_to_task_duration",
        "temporal_resampling_performed": False,
        "waveform_fit_counts": {
            "zero_pad_to_task_duration": 954,
            "unchanged": 23844,
            "truncate_to_task_duration": 2,
        },
        "errors": [],
    }
    config = {
        "data": {
            "audio_preprocessing": {
                "beats_task_window_seconds": 10,
                "beats_short_waveform_policy": "zero_pad_to_task_duration",
                "beats_long_waveform_policy": "truncate_to_task_duration",
            }
        },
        "teacher_export": {
            "beats": {
                "sample_rate": 16000,
                "task_segments": 10,
                "segment_seconds": 1,
                "clip_duration_seconds": 10,
                "short_waveform_policy": "zero_pad_to_task_duration",
                "long_waveform_policy": "truncate_to_task_duration",
            }
        },
    }

    assert validate_audio_task_window_audit(report, config) == []
    report["short_waveform_policy"] = "repeat_last_sample"
    assert validate_audio_task_window_audit(report, config) == [
        "audio_task_window_audit: report does not prove the locked 16 kHz/T=10 task-window policy"
    ]
