"""Condition-based progress and disk monitor for detached MM26 downloads."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.assets.asset_validation import validate_download  # noqa: E402
from scripts.assets.download_mm26_assets import DownloadPaths, _process_is_running  # noqa: E402
from scripts.assets.mm26_asset_catalog import AssetSpec, weight_assets  # noqa: E402


DISK_FLOOR_BYTES = 50 * 1024**3
STALE_AFTER_SECONDS = 120


def _read_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _progress_for(progress: Mapping[str, object], name: str) -> Mapping[str, object]:
    assets = progress.get("assets", {})
    if not isinstance(assets, Mapping):
        return {}
    item = assets.get(name, {})
    return item if isinstance(item, Mapping) else {}


def _int_value(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _normalized_path(path: str | Path) -> str:
    return os.path.normcase(os.path.normpath(str(Path(path).absolute())))


def aria2_entries_to_progress(
    root: str | Path,
    entries: Sequence[Mapping[str, object]],
    *,
    specs: Sequence[AssetSpec] | None = None,
    now: datetime | None = None,
    previous: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Map aria2 RPC task records to catalog assets without trusting sparse file length."""

    paths = DownloadPaths.from_root(root)
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    selected_specs = specs or weight_assets()
    by_path = {_normalized_path(paths.incoming_path(spec)): spec for spec in selected_specs}
    previous_assets = (previous or {}).get("assets", {})
    if not isinstance(previous_assets, Mapping):
        previous_assets = {}
    priorities = {"complete": 4, "active": 3, "waiting": 2, "paused": 1, "error": 0, "removed": 0}
    assets: dict[str, dict[str, object]] = {}
    for entry in entries:
        files = entry.get("files", [])
        if not isinstance(files, Sequence) or not files or not isinstance(files[0], Mapping):
            continue
        spec = by_path.get(_normalized_path(str(files[0].get("path", ""))))
        if spec is None:
            continue
        status = str(entry.get("status", "unknown"))
        completed = _int_value(entry.get("completedLength"))
        existing = assets.get(spec.name)
        if existing is not None:
            existing_rank = (priorities.get(str(existing.get("aria2_status")), -1), _int_value(existing.get("completed_bytes")))
            candidate_rank = (priorities.get(status, -1), completed)
            if candidate_rank <= existing_rank:
                continue
        previous_item = previous_assets.get(spec.name, {})
        if not isinstance(previous_item, Mapping):
            previous_item = {}
        speed = _int_value(entry.get("downloadSpeed"))
        average = _int_value(previous_item.get("average_speed_bps"), speed) or speed
        assets[spec.name] = {
            "gid": str(entry.get("gid", "")),
            "aria2_status": status,
            "expected_bytes": _int_value(entry.get("totalLength")),
            "completed_bytes": completed,
            "current_speed_bps": speed,
            "average_speed_bps": average,
            "retries": _int_value(previous_item.get("retries")),
            "error_code": str(entry.get("errorCode", "0")),
            "error_message": str(entry.get("errorMessage", "")),
            "updated_at": current_time.isoformat(),
        }
    return {"schema_version": 1, "updated_at": current_time.isoformat(), "assets": assets}


def _aria2_rpc(rpc_url: str, method: str, params: list[object]) -> object:
    payload = json.dumps({"jsonrpc": "2.0", "id": method, "method": method, "params": params}).encode(
        "utf-8"
    )
    request = urllib.request.Request(
        rpc_url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        decoded = json.loads(response.read().decode("utf-8"))
    if not isinstance(decoded, dict) or "result" not in decoded:
        raise RuntimeError(f"invalid aria2 RPC response for {method}")
    return decoded["result"]


def refresh_aria2_progress(root: str | Path) -> dict[str, object]:
    paths = DownloadPaths.from_root(root)
    process = _read_json(paths.process_state)
    previous = _read_json(paths.state_dir / "progress.json")
    rpc_url = process.get("rpc_url")
    if not isinstance(rpc_url, str) or not rpc_url:
        return previous
    keys = [
        "gid",
        "status",
        "totalLength",
        "completedLength",
        "downloadSpeed",
        "files",
        "errorCode",
        "errorMessage",
    ]
    entries: list[Mapping[str, object]] = []
    try:
        for method, params in (
            ("aria2.tellActive", [keys]),
            ("aria2.tellWaiting", [0, 100, keys]),
            ("aria2.tellStopped", [0, 100, keys]),
        ):
            result = _aria2_rpc(rpc_url, method, params)
            if isinstance(result, list):
                entries.extend(item for item in result if isinstance(item, Mapping))
        progress = aria2_entries_to_progress(paths.root, entries, previous=previous)
    except (OSError, urllib.error.URLError, json.JSONDecodeError, RuntimeError) as error:
        progress = {**previous, "rpc_error": str(error), "rpc_error_at": datetime.now(timezone.utc).isoformat()}
    _write_atomic(paths.state_dir / "progress.json", json.dumps(progress, indent=2, ensure_ascii=False) + "\n")
    return progress


def collect_download_status(
    root: str | Path,
    *,
    specs: Sequence[AssetSpec] | None = None,
    now: datetime | None = None,
    free_bytes: int | None = None,
    pid_checker: Callable[[int], bool] = _process_is_running,
) -> dict[str, object]:
    """Collect status without mutating downloads or process state."""

    paths = DownloadPaths.from_root(root)
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    process = _read_json(paths.process_state)
    progress = _read_json(paths.state_dir / "progress.json")
    pid = _int_value(process.get("pid"))
    process_running = pid_checker(pid)
    disk_free = free_bytes if free_bytes is not None else shutil.disk_usage(paths.root).free
    items: list[dict[str, object]] = []

    for spec in specs or weight_assets():
        final_path = paths.final_path(spec)
        incoming_path = paths.incoming_path(spec)
        active_path = final_path if final_path.is_file() else incoming_path
        item_progress = _progress_for(progress, spec.name)
        rpc_completed_bytes = _int_value(item_progress.get("completed_bytes"))
        current_bytes = (
            rpc_completed_bytes
            if rpc_completed_bytes > 0
            else (active_path.stat().st_size if active_path.is_file() else 0)
        )
        expected_bytes = _int_value(item_progress.get("expected_bytes"))
        current_speed = _int_value(item_progress.get("current_speed_bps"))
        average_speed = _int_value(item_progress.get("average_speed_bps"))
        retries = _int_value(item_progress.get("retries"))
        updated_at = _parse_time(item_progress.get("updated_at"))
        stale = bool(updated_at and (current_time - updated_at).total_seconds() > STALE_AFTER_SECONDS)

        sha256_verified = False
        status = "missing"
        if final_path.is_file() and spec.expected_sha256 is not None:
            receipt = validate_download(final_path, spec)
            sha256_verified = receipt.status == "passed"
            status = "verified" if sha256_verified else "invalid"
        elif incoming_path.is_file():
            status = "downloading" if process_running else "partial"

        if sha256_verified:
            expected_bytes = current_bytes
        completion_ratio = (
            min(1.0, current_bytes / expected_bytes) if expected_bytes > 0 else (1.0 if sha256_verified else None)
        )
        eta_seconds = None
        if expected_bytes > current_bytes and current_speed > 0:
            eta_seconds = (expected_bytes - current_bytes) // current_speed

        items.append(
            {
                "name": spec.name,
                "target": str(final_path),
                "active_path": str(active_path),
                "status": status,
                "current_bytes": current_bytes,
                "expected_bytes": expected_bytes or None,
                "completion_ratio": completion_ratio,
                "current_speed_bps": current_speed,
                "average_speed_bps": average_speed,
                "eta_seconds": eta_seconds,
                "aria2_process_running": process_running,
                "last_progress_time": updated_at.isoformat() if updated_at else None,
                "stale": stale,
                "retries": retries,
                "disk_free_bytes": disk_free,
                "aria2_control_exists": Path(str(incoming_path) + ".aria2").is_file(),
                "sha256_verified": sha256_verified,
            }
        )

    return {
        "schema_version": 1,
        "generated_at": current_time.isoformat(),
        "process": {**process, "pid": pid or None, "running": process_running},
        "disk_guard": {
            "free_bytes": disk_free,
            "threshold_bytes": DISK_FLOOR_BYTES,
            "action": "pause_requested" if disk_free < DISK_FLOOR_BYTES else "continue",
        },
        "assets": items,
    }


def _format_bytes(value: object) -> str:
    amount = _int_value(value)
    if amount <= 0:
        return "0 B"
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    display = float(amount)
    unit = units[0]
    for candidate in units:
        unit = candidate
        if display < 1024 or candidate == units[-1]:
            break
        display /= 1024
    return f"{display:.2f} {unit}"


def render_markdown(status: Mapping[str, object]) -> str:
    disk = status.get("disk_guard", {})
    disk_map = disk if isinstance(disk, Mapping) else {}
    process = status.get("process", {})
    process_map = process if isinstance(process, Mapping) else {}
    lines = [
        "# MM26 Download Live Status",
        "",
        f"Generated: `{status.get('generated_at')}`",
        f"Disk free: `{_format_bytes(disk_map.get('free_bytes'))}`",
        f"Disk action: `{disk_map.get('action')}`",
        f"aria2 PID: `{process_map.get('pid')}`; running: `{process_map.get('running')}`",
        "",
        "| Asset | Status | Current | Expected | Complete | Speed | ETA | Retries | .aria2 | SHA256 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    assets = status.get("assets", [])
    if isinstance(assets, Sequence):
        for item in assets:
            if not isinstance(item, Mapping):
                continue
            ratio = item.get("completion_ratio")
            ratio_text = f"{float(ratio) * 100:.2f}%" if isinstance(ratio, (int, float)) else "unknown"
            eta = item.get("eta_seconds")
            eta_text = f"{eta}s" if eta is not None else "unknown"
            lines.append(
                "| {name} | {status} | {current} | {expected} | {ratio} | {speed}/s | {eta} | {retries} | {control} | {sha} |".format(
                    name=item.get("name"),
                    status=item.get("status"),
                    current=_format_bytes(item.get("current_bytes")),
                    expected=_format_bytes(item.get("expected_bytes")),
                    ratio=ratio_text,
                    speed=_format_bytes(item.get("current_speed_bps")),
                    eta=eta_text,
                    retries=item.get("retries"),
                    control=item.get("aria2_control_exists"),
                    sha=item.get("sha256_verified"),
                )
            )
    return "\n".join(lines) + "\n"


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def write_status_reports(report_dir: str | Path, status: Mapping[str, object]) -> tuple[Path, Path]:
    directory = Path(report_dir)
    json_path = directory / "live_status.json"
    markdown_path = directory / "live_status.md"
    _write_atomic(json_path, json.dumps(status, indent=2, ensure_ascii=False) + "\n")
    _write_atomic(markdown_path, render_markdown(status))
    return json_path, markdown_path


def request_aria2_pause(rpc_url: str) -> dict[str, object]:
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": "disk-guard", "method": "aria2.pauseAll", "params": []}
    ).encode("utf-8")
    request = urllib.request.Request(
        rpc_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        return {"status": "pause_failed", "error": str(error)}
    return {"status": "pause_requested", "response": decoded}


def monitor_once(root: str | Path) -> dict[str, object]:
    paths = DownloadPaths.from_root(root)
    refresh_aria2_progress(paths.root)
    status = collect_download_status(root)
    if status["disk_guard"]["action"] == "pause_requested":  # type: ignore[index]
        process = status.get("process", {})
        rpc_url = process.get("rpc_url") if isinstance(process, Mapping) else None
        status["pause_result"] = (
            request_aria2_pause(str(rpc_url))
            if rpc_url
            else {"status": "pause_failed", "error": "missing aria2 RPC URL"}
        )
    write_status_reports(paths.root / "reports" / "downloads", status)
    return status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--watch", action="store_true")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--interval", type=int, default=60)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.interval < 1:
        raise SystemExit("--interval must be positive")
    while True:
        status = monitor_once(args.root)
        print(json.dumps(status, indent=2, ensure_ascii=False), flush=True)
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
