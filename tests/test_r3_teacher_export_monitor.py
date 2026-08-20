from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from scripts.teachers.monitor_export import collect_export_status, publish_status


def _manifest(path: Path, count: int) -> Path:
    path.write_text(
        "".join(json.dumps({"id": f"{path.stem}-{index}"}) + "\n" for index in range(count)),
        encoding="utf-8",
    )
    return path


def _json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_export_monitor_counts_receipts_errors_current_id_gpu_and_eta(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    manifests = {
        "train": _manifest(tmp_path / "train.jsonl", 3),
        "val": _manifest(tmp_path / "val.jsonl", 2),
        "test": _manifest(tmp_path / "test.jsonl", 1),
    }
    for index in range(2):
        _json(cache / "receipts/train" / f"train-{index}.json", {"record_id": f"train-{index}"})
    _json(cache / "receipts/val/val-0.json", {"record_id": "val-0"})
    _json(cache / "errors/test/test-0.json", {"record_id": "test-0"})
    started = "2026-08-20T12:00:00+00:00"
    _json(
        cache / "progress/train.json",
        {
            "status": "running",
            "started_at": started,
            "current_record_id": "train-2",
            "current_index": 2,
            "total": 3,
        },
    )

    status = collect_export_status(
        cache_root=cache,
        manifests=manifests,
        now=datetime(2026, 8, 20, 12, 1, 40, tzinfo=timezone.utc),
        gpu_query=lambda: {
            "utilization_percent": 73,
            "memory_used_bytes": 12,
            "memory_total_bytes": 24,
        },
        disk_query=lambda _path: {"free_bytes": 1000, "total_bytes": 2000},
    )

    assert status["completed"] == 3
    assert status["total"] == 6
    assert status["failed"] == 1
    assert status["current_sample_id"] == "train-2"
    assert status["samples_per_second"] == 0.03
    assert status["eta_seconds"] == 100.0
    assert status["gpu"]["utilization_percent"] == 73
    assert status["disk"]["free_bytes"] == 1000


def test_export_monitor_publishes_json_and_markdown_atomically(tmp_path: Path) -> None:
    status = {
        "schema_version": 1,
        "generated_at": "2026-08-20T12:00:00+00:00",
        "status": "running",
        "completed": 1,
        "total": 2,
        "failed": 0,
        "samples_per_second": 0.5,
        "eta_seconds": 2.0,
        "current_sample_id": "clip-2",
        "splits": {},
        "gpu": {},
        "disk": {},
    }
    output_json = tmp_path / "reports/status.json"
    output_md = tmp_path / "reports/status.md"

    publish_status(status, output_json=output_json, output_md=output_md)

    assert json.loads(output_json.read_text(encoding="utf-8"))["completed"] == 1
    assert "clip-2" in output_md.read_text(encoding="utf-8")
    assert not output_json.with_suffix(".json.tmp").exists()
    assert not output_md.with_suffix(".md.tmp").exists()
