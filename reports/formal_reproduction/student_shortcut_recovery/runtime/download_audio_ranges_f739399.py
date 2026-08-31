#!/usr/bin/env python3

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.request


URL = "https://github.com/rwightman/pytorch-image-models/releases/download/v0.1-effv2-weights/tf_efficientnetv2_b2-847de54e.pth"
EXPECTED_BYTES = 40_795_861
EXPECTED_SHA256_PREFIX = "847de54e"
CONTENT_RANGE = re.compile(r"^bytes (\d+)-(\d+)/(\d+)$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def chunk_ranges(total: int, count: int) -> list[tuple[int, int]]:
    base, remainder = divmod(total, count)
    ranges = []
    start = 0
    for index in range(count):
        length = base + (1 if index < remainder else 0)
        end = start + length - 1
        ranges.append((start, end))
        start = end + 1
    assert start == total
    return ranges


def download_range(
    index: int,
    start: int,
    end: int,
    root: Path,
    retries: int,
) -> dict[str, object]:
    expected = end - start + 1
    path = root / f"range_{index:02d}_{start}_{end}.part"
    if path.exists() and path.stat().st_size > expected:
        raise RuntimeError(f"range file exceeds expected size: {path}")
    for attempt in range(retries + 1):
        present = path.stat().st_size if path.exists() else 0
        if present == expected:
            return {
                "index": index,
                "start": start,
                "end": end,
                "bytes": present,
                "path": str(path),
                "attempts": attempt,
            }
        absolute_start = start + present
        request = urllib.request.Request(
            URL,
            headers={
                "Range": f"bytes={absolute_start}-{end}",
                "User-Agent": "OV-OrthKD-reproduction-range-downloader/1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                if response.status != 206:
                    raise RuntimeError(
                        f"range {index} expected HTTP 206, got {response.status}"
                    )
                header = response.headers.get("Content-Range", "")
                match = CONTENT_RANGE.fullmatch(header)
                if match is None:
                    raise RuntimeError(
                        f"range {index} missing/invalid Content-Range: {header!r}"
                    )
                received_start, received_end, received_total = map(int, match.groups())
                if (
                    received_start != absolute_start
                    or received_end != end
                    or received_total != EXPECTED_BYTES
                ):
                    raise RuntimeError(
                        f"range {index} Content-Range mismatch: {header!r}"
                    )
                with path.open("ab") as handle:
                    while True:
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        handle.write(block)
            if path.stat().st_size == expected:
                continue
            raise RuntimeError(
                f"range {index} response ended at {path.stat().st_size}/{expected}"
            )
        except Exception:
            if attempt >= retries:
                raise
            time.sleep(min(3 * (attempt + 1), 15))
    raise AssertionError("unreachable")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--connections", type=int, default=8)
    parser.add_argument("--retries", type=int, default=20)
    args = parser.parse_args()
    if args.connections < 1 or args.connections > 16:
        raise ValueError("connections must be in [1,16]")
    args.control.mkdir(parents=True, exist_ok=True)
    args.target.parent.mkdir(parents=True, exist_ok=True)
    state_path = args.control / "worker_state.json"
    receipt_path = args.control / "download_receipt.json"
    ranges = chunk_ranges(EXPECTED_BYTES, args.connections)
    stop_event = threading.Event()
    state_lock = threading.Lock()

    def state(status: str, message: str, exit_code: int | None) -> None:
        parts = []
        for index, (start, end) in enumerate(ranges):
            path = args.control / f"range_{index:02d}_{start}_{end}.part"
            parts.append(
                {
                    "index": index,
                    "start": start,
                    "end": end,
                    "expected_bytes": end - start + 1,
                    "bytes": path.stat().st_size if path.exists() else 0,
                }
            )
        with state_lock:
            atomic_json(
                state_path,
                {
                    "schema_version": 1,
                    "status": status,
                    "process_id": os.getpid(),
                    "updated_at_utc_epoch": time.time(),
                    "exit_code": exit_code,
                    "message": message,
                    "url": URL,
                    "expected_bytes": EXPECTED_BYTES,
                    "parts": parts,
                },
            )

    def monitor() -> None:
        while not stop_event.wait(5):
            state("running", "validated parallel HTTP range download", None)

    try:
        if args.target.exists():
            if args.target.stat().st_size != EXPECTED_BYTES:
                raise RuntimeError("existing final target has unexpected byte count")
            digest = sha256(args.target)
            if not digest.startswith(EXPECTED_SHA256_PREFIX):
                raise RuntimeError("existing final target fails SHA256 prefix")
            atomic_json(
                receipt_path,
                {
                    "schema_version": 1,
                    "status": "PASS",
                    "source": "preexisting_verified_target",
                    "url": URL,
                    "target": str(args.target),
                    "bytes": EXPECTED_BYTES,
                    "sha256": digest,
                },
            )
            state("completed", "preexisting final target verified", 0)
            return
        state("running", "validated parallel HTTP range download", None)
        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()
        results = []
        with ThreadPoolExecutor(max_workers=args.connections) as executor:
            futures = {
                executor.submit(
                    download_range, index, start, end, args.control, args.retries
                ): index
                for index, (start, end) in enumerate(ranges)
            }
            for future in as_completed(futures):
                results.append(future.result())
                state("running", "validated parallel HTTP range download", None)
        stop_event.set()
        monitor_thread.join(timeout=10)
        results.sort(key=lambda item: int(item["index"]))
        temporary_target = args.target.with_name(args.target.name + ".range.tmp")
        with temporary_target.open("wb") as output:
            for item in results:
                with Path(str(item["path"])).open("rb") as source:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        output.write(block)
        if temporary_target.stat().st_size != EXPECTED_BYTES:
            raise RuntimeError("combined target has unexpected byte count")
        digest = sha256(temporary_target)
        if not digest.startswith(EXPECTED_SHA256_PREFIX):
            raise RuntimeError(
                f"combined target SHA256 {digest} does not start with official prefix"
            )
        os.replace(temporary_target, args.target)
        receipt = {
            "schema_version": 1,
            "status": "PASS",
            "claim_level": "official_timm_pretrained_cfg_direct_url_range_receipt",
            "url": URL,
            "target": str(args.target),
            "bytes": EXPECTED_BYTES,
            "sha256": digest,
            "expected_sha256_prefix": EXPECTED_SHA256_PREFIX,
            "connections": args.connections,
            "parts": results,
        }
        atomic_json(receipt_path, receipt)
        state("completed", "validated parallel HTTP range download completed", 0)
        print(json.dumps(receipt, indent=2))
    except Exception as exc:
        stop_event.set()
        state("failed", repr(exc), 1)
        raise


if __name__ == "__main__":
    main()
