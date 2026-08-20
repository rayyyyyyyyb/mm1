from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.assets.mm26_asset_catalog import AssetSpec
from scripts.assets.monitor_downloads import (
    aria2_entries_to_progress,
    collect_download_status,
    render_markdown,
    write_status_reports,
)


def _spec(payload: bytes = b"x" * 50) -> AssetSpec:
    return AssetSpec(
        name="fixture_weight",
        kind="weight",
        target=Path("weights/fixture/model.pth"),
        sources=("https://example.invalid/model.pth",),
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        checkpoint_format=None,
        min_bytes=1,
    )


def _write_progress(root: Path, now: datetime) -> None:
    state = root / "data" / "downloads" / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "progress.json").write_text(
        json.dumps(
            {
                "assets": {
                    "fixture_weight": {
                        "expected_bytes": 100,
                        "current_speed_bps": 10,
                        "average_speed_bps": 8,
                        "retries": 2,
                        "updated_at": now.isoformat(),
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (state / "aria2_process.json").write_text(
        json.dumps({"pid": 1234, "status": "running"}),
        encoding="utf-8",
    )


def test_collect_status_reports_per_asset_progress_and_process_state(tmp_path: Path) -> None:
    now = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
    spec = _spec()
    incoming = (
        tmp_path
        / "data"
        / "downloads"
        / "incoming"
        / "weights"
        / spec.name
        / spec.target.name
    )
    incoming.parent.mkdir(parents=True)
    incoming.write_bytes(b"x" * 50)
    Path(str(incoming) + ".aria2").write_bytes(b"control")
    _write_progress(tmp_path, now)

    status = collect_download_status(
        tmp_path,
        specs=(spec,),
        now=now,
        free_bytes=100 * 1024**3,
        pid_checker=lambda pid: pid == 1234,
    )

    asset = status["assets"][0]
    assert asset["name"] == "fixture_weight"
    assert asset["current_bytes"] == 50
    assert asset["expected_bytes"] == 100
    assert asset["completion_ratio"] == 0.5
    assert asset["current_speed_bps"] == 10
    assert asset["average_speed_bps"] == 8
    assert asset["eta_seconds"] == 5
    assert asset["retries"] == 2
    assert asset["aria2_control_exists"] is True
    assert asset["sha256_verified"] is False
    assert asset["stale"] is False
    assert status["process"]["running"] is True


def test_completed_exact_file_is_sha_verified(tmp_path: Path) -> None:
    payload = b"x" * 50
    spec = _spec(payload)
    final_path = tmp_path / spec.target
    final_path.parent.mkdir(parents=True)
    final_path.write_bytes(payload)

    status = collect_download_status(
        tmp_path,
        specs=(spec,),
        now=datetime.now(timezone.utc),
        free_bytes=100 * 1024**3,
        pid_checker=lambda pid: False,
    )

    asset = status["assets"][0]
    assert asset["current_bytes"] == len(payload)
    assert asset["completion_ratio"] == 1.0
    assert asset["sha256_verified"] is True
    assert asset["status"] == "verified"


def test_low_disk_requests_pause_without_deleting_partial(tmp_path: Path) -> None:
    spec = _spec()
    incoming = (
        tmp_path
        / "data"
        / "downloads"
        / "incoming"
        / "weights"
        / spec.name
        / spec.target.name
    )
    incoming.parent.mkdir(parents=True)
    incoming.write_bytes(b"partial")

    status = collect_download_status(
        tmp_path,
        specs=(spec,),
        free_bytes=49 * 1024**3,
        pid_checker=lambda pid: False,
    )

    assert status["disk_guard"]["action"] == "pause_requested"
    assert status["disk_guard"]["threshold_bytes"] == 50 * 1024**3
    assert incoming.read_bytes() == b"partial"


def test_old_progress_is_marked_stale(tmp_path: Path) -> None:
    now = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
    _write_progress(tmp_path, now - timedelta(minutes=3))

    status = collect_download_status(
        tmp_path,
        specs=(_spec(),),
        now=now,
        free_bytes=100 * 1024**3,
        pid_checker=lambda pid: True,
    )

    assert status["assets"][0]["stale"] is True


def test_status_reports_are_atomic_json_and_markdown(tmp_path: Path) -> None:
    status = collect_download_status(
        tmp_path,
        specs=(_spec(),),
        free_bytes=100 * 1024**3,
        pid_checker=lambda pid: False,
    )
    report_dir = tmp_path / "reports" / "downloads"

    json_path, markdown_path = write_status_reports(report_dir, status)

    assert json.loads(json_path.read_text(encoding="utf-8"))["schema_version"] == 1
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "fixture_weight" in markdown
    assert "Disk free" in markdown
    assert not list(report_dir.glob("*.tmp"))
    assert render_markdown(status) == markdown


def test_rpc_entries_are_mapped_to_exact_asset_progress(tmp_path: Path) -> None:
    spec = _spec()
    now = datetime(2026, 8, 20, 13, 0, tzinfo=timezone.utc)
    paths = (
        tmp_path
        / "data"
        / "downloads"
        / "incoming"
        / "weights"
        / spec.name
        / spec.target.name
    )
    entries = [
        {
            "gid": "abc123",
            "status": "active",
            "totalLength": "100",
            "completedLength": "55",
            "downloadSpeed": "11",
            "errorCode": "0",
            "files": [{"path": str(paths)}],
        }
    ]

    progress = aria2_entries_to_progress(
        tmp_path, entries, specs=(spec,), now=now, previous={}
    )

    item = progress["assets"][spec.name]
    assert item["gid"] == "abc123"
    assert item["aria2_status"] == "active"
    assert item["expected_bytes"] == 100
    assert item["completed_bytes"] == 55
    assert item["current_speed_bps"] == 11
    assert item["average_speed_bps"] == 11
    assert item["updated_at"] == now.isoformat()
