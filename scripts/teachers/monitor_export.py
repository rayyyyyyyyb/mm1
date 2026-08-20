#!/usr/bin/env python3

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import time
from typing import Callable, Mapping


SPLITS = ("train", "val", "test")


def _record_count(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def _json(path: Path) -> dict:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def query_nvidia_smi() -> dict[str, int | None]:
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            raise ValueError(completed.stderr.strip() or "no nvidia-smi output")
        utilization, used_mib, total_mib = [
            int(value.strip()) for value in completed.stdout.splitlines()[0].split(",")
        ]
        return {
            "utilization_percent": utilization,
            "memory_used_bytes": used_mib * 1024 * 1024,
            "memory_total_bytes": total_mib * 1024 * 1024,
        }
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        return {
            "utilization_percent": None,
            "memory_used_bytes": None,
            "memory_total_bytes": None,
            "error": str(error),
        }


def query_disk(path: Path) -> dict[str, int]:
    usage = shutil.disk_usage(path)
    return {"free_bytes": usage.free, "total_bytes": usage.total}


def collect_export_status(
    *,
    cache_root: str | Path,
    manifests: Mapping[str, str | Path],
    progress_root: str | Path | None = None,
    now: datetime | None = None,
    gpu_query: Callable[[], dict] = query_nvidia_smi,
    disk_query: Callable[[Path], dict] = query_disk,
) -> dict:
    cache = Path(cache_root).expanduser().resolve()
    progress = (
        Path(progress_root).expanduser().resolve()
        if progress_root is not None
        else cache / "progress"
    )
    generated = now or datetime.now(timezone.utc)
    rows: dict[str, dict] = {}
    start_times: list[datetime] = []
    current_sample_id = None
    completed = 0
    failed = 0
    total = 0
    for split in SPLITS:
        manifest = Path(manifests[split]).expanduser().resolve()
        split_total = _record_count(manifest)
        split_completed = len(list((cache / "receipts" / split).glob("*.json")))
        split_failed = len(list((cache / "errors" / split).glob("*.json")))
        state = _json(progress / f"{split}.json")
        started_at = state.get("started_at")
        if isinstance(started_at, str):
            try:
                start_times.append(datetime.fromisoformat(started_at))
            except ValueError:
                pass
        if state.get("status") == "running" and current_sample_id is None:
            current_sample_id = state.get("current_record_id")
        rows[split] = {
            "completed": split_completed,
            "total": split_total,
            "failed": split_failed,
            "current_sample_id": state.get("current_record_id"),
            "progress_status": state.get("status", "pending"),
        }
        completed += split_completed
        failed += split_failed
        total += split_total

    elapsed_seconds = 0.0
    if start_times:
        earliest = min(start_times)
        if earliest.tzinfo is None:
            earliest = earliest.replace(tzinfo=timezone.utc)
        elapsed_seconds = max(0.0, (generated - earliest).total_seconds())
    rate = completed / elapsed_seconds if elapsed_seconds > 0 else 0.0
    remaining = max(0, total - completed)
    eta = remaining / rate if rate > 0 else None
    if failed:
        status = "failed"
    elif total > 0 and completed == total:
        status = "completed"
    elif current_sample_id is not None or completed:
        status = "running"
    else:
        status = "pending"
    return {
        "schema_version": 1,
        "generated_at": generated.astimezone(timezone.utc).isoformat(),
        "status": status,
        "completed": completed,
        "total": total,
        "failed": failed,
        "samples_per_second": round(rate, 6),
        "eta_seconds": round(eta, 3) if eta is not None else None,
        "current_sample_id": current_sample_id,
        "splits": rows,
        "gpu": gpu_query(),
        "disk": disk_query(cache),
    }


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _markdown(status: Mapping[str, object]) -> str:
    lines = [
        "# MM26 Teacher Export Live Status",
        "",
        f"- Status: `{status['status']}`",
        f"- Completed: {status['completed']} / {status['total']}",
        f"- Failed: {status['failed']}",
        f"- Samples/second: {status['samples_per_second']}",
        f"- ETA seconds: {status['eta_seconds']}",
        f"- Current sample ID: `{status['current_sample_id']}`",
        "",
        "## Splits",
        "",
    ]
    for split, row in status.get("splits", {}).items():
        lines.append(
            f"- {split}: {row['completed']} / {row['total']}, "
            f"failed={row['failed']}, current=`{row['current_sample_id']}`"
        )
    return "\n".join(lines) + "\n"


def publish_status(status: Mapping[str, object], *, output_json: Path, output_md: Path) -> None:
    _atomic_text(output_json, json.dumps(status, indent=2, ensure_ascii=False) + "\n")
    _atomic_text(output_md, _markdown(status))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor resumable MM26 teacher-cache export")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--watch", action="store_true")
    parser.add_argument("--cache-root", default="data/teacher_cache/mm26")
    parser.add_argument("--progress-root", default="reports/teachers/progress")
    parser.add_argument("--train-manifest", required=True)
    parser.add_argument("--val-manifest", required=True)
    parser.add_argument("--test-manifest", required=True)
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--output-json", default="reports/teachers/export_live_status.json")
    parser.add_argument("--output-md", default="reports/teachers/export_live_status.md")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifests = {
        "train": args.train_manifest,
        "val": args.val_manifest,
        "test": args.test_manifest,
    }
    while True:
        status = collect_export_status(
            cache_root=args.cache_root,
            manifests=manifests,
            progress_root=args.progress_root,
        )
        publish_status(
            status,
            output_json=Path(args.output_json),
            output_md=Path(args.output_md),
        )
        print(json.dumps(status, indent=2, ensure_ascii=False), flush=True)
        if args.once:
            break
        time.sleep(max(1, int(args.interval)))


if __name__ == "__main__":
    main()
