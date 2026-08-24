from __future__ import annotations

from pathlib import Path
import json

from scripts.audit_mm26_reproduction import audit_reproduction
from scripts.discover_ovave_raw_video_layout import discover_raw_video_layout


def _metadata(path: Path) -> Path:
    path.write_text(
        "split,cls_name,cls_type,vid_name\n"
        "train,cat,close,train_clip\n"
        "val,cat,close,val_clip\n"
        "test,cat,open,test_clip\n",
        encoding="utf-8",
    )
    return path


def _probe(path: Path) -> dict[str, object]:
    return {"codec": "h264", "fps": 25.0, "duration_seconds": 10.0}


def test_raw_video_layout_requires_metadata_bijection_and_media_probe(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    root.mkdir()
    for clip_id in ("train_clip", "val_clip", "test_clip"):
        (root / f"{clip_id}.mp4").write_bytes(b"video")

    report = discover_raw_video_layout(
        root,
        meta_csv=_metadata(tmp_path / "meta.csv"),
        enforce_official_counts=False,
        probe_fn=_probe,
        max_workers=2,
    )

    assert report["status"] == "passed"
    assert report["split_counts"] == {"test": 1, "train": 1, "val": 1}
    assert report["metadata_bijection_verified"] is True
    assert report["id_match_rate"] == 1.0
    assert report["extension_counts"] == {".mp4": 3}
    assert report["codec_counts"] == {"h264": 3}
    assert report["video_count"] == 3
    assert all(record["fps"] == 25.0 for record in report["video_records"])


def test_raw_video_layout_ignores_only_macos_appledouble_video_sidecars(
    tmp_path: Path,
) -> None:
    root = tmp_path / "raw"
    root.mkdir()
    for clip_id in ("train_clip", "val_clip", "test_clip"):
        (root / f"{clip_id}.mp4").write_bytes(b"video")
    (root / "._train_clip.mp4").write_bytes(b"AppleDouble-sidecar")

    report = discover_raw_video_layout(
        root,
        meta_csv=_metadata(tmp_path / "meta.csv"),
        enforce_official_counts=False,
        probe_fn=_probe,
    )

    assert report["status"] == "passed"
    assert report["video_count"] == 3
    assert report["ignored_appledouble_sidecars"] == ["._train_clip.mp4"]

    (root / "ordinary_extra.mp4").write_bytes(b"not-a-sidecar")
    report_with_real_extra = discover_raw_video_layout(
        root,
        meta_csv=tmp_path / "meta.csv",
        enforce_official_counts=False,
        probe_fn=_probe,
    )
    assert report_with_real_extra["status"] == "failed"
    assert report_with_real_extra["extra_clip_ids"] == ["ordinary_extra"]


def test_raw_video_layout_fails_on_duplicate_id_missing_id_and_short_video(
    tmp_path: Path,
) -> None:
    root = tmp_path / "raw"
    root.mkdir()
    (root / "train_clip.mp4").write_bytes(b"video")
    (root / "train_clip.avi").write_bytes(b"duplicate")
    (root / "val_clip.mp4").write_bytes(b"video")

    def short_probe(path: Path) -> dict[str, object]:
        value = _probe(path)
        if path.stem == "val_clip":
            value["duration_seconds"] = 9.0
        return value

    report = discover_raw_video_layout(
        root,
        meta_csv=_metadata(tmp_path / "meta.csv"),
        enforce_official_counts=False,
        probe_fn=short_probe,
    )

    assert report["status"] == "failed"
    assert report["duplicate_video_ids"] == ["train_clip"]
    assert report["missing_clip_ids"] == ["test_clip"]
    assert report["short_video_count"] == 1
    assert report["short_video_files"] == [
        {"path": "val_clip.mp4", "duration_seconds": 9.0}
    ]
    assert any("shorter than 10 seconds" in item["error"] for item in report["errors"])


def test_source_audit_requires_existing_wav_and_raw_video_for_every_record(
    tmp_path: Path,
) -> None:
    manifests = {}
    raw_video = tmp_path / "clip.mp4"
    raw_video.write_bytes(b"video")
    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"wav")
    frame = tmp_path / "frame.png"
    frame.write_bytes(b"png")
    for split, split_type in (("train", "seen"), ("val", "seen"), ("test", "unseen")):
        record = {
            "id": f"{split}-clip",
            "query": split,
            "split_type": split_type,
            "segment_labels": [0] * 10,
            "frame_paths": [[str(frame)] for _ in range(10)],
            "spectrogram_paths": [],
            "audio_path": str(wav),
            "raw_video_path": str(raw_video),
        }
        manifests[split] = tmp_path / f"{split}.jsonl"
        manifests[split].write_text(json.dumps(record) + "\n", encoding="utf-8")

    passed = audit_reproduction(
        train_manifest=manifests["train"],
        val_manifest=manifests["val"],
        test_manifest=manifests["test"],
        path_root=tmp_path,
        stage="source",
        artifact_scan="none",
        sample_count=0,
        expected_segments="10",
    )
    raw_video.unlink()
    failed = audit_reproduction(
        train_manifest=manifests["train"],
        val_manifest=manifests["val"],
        test_manifest=manifests["test"],
        path_root=tmp_path,
        stage="source",
        artifact_scan="none",
        sample_count=0,
        expected_segments="10",
    )

    assert passed["errors"] == []
    assert len([item for item in failed["errors"] if item["code"] == "missing_path"]) == 3
