#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.safe_extract_official_archive import (
    _atomic_write_json,
    _sha256_file,
    safe_extract_archive,
)


def _reject_login_document(path: Path) -> None:
    prefix = path.read_bytes()[:4096].lstrip().lower()
    if prefix.startswith((b"<html", b"<!doctype html", b"<?xml")):
        raise ValueError("Official archive bytes are an HTML/XML login document")


def extract_with_7zip_preflight(
    archive: str | Path,
    output_dir: str | Path,
    receipt: str | Path,
    *,
    listing: str | Path | None = None,
    min_archive_bytes: int = 1_000_000,
    seven_zip: str | None = None,
) -> dict:
    archive_path = Path(archive).expanduser().resolve()
    if not archive_path.is_file():
        raise FileNotFoundError(f"Official archive not found: {archive_path}")
    if archive_path.stat().st_size < int(min_archive_bytes):
        raise ValueError(
            f"Official archive is suspiciously small: {archive_path.stat().st_size} bytes"
        )
    _reject_login_document(archive_path)
    executable = seven_zip or shutil.which("7z") or shutil.which("7z.exe")
    if not executable:
        raise RuntimeError("7-Zip is required for the official archive test and listing")
    tested = subprocess.run(
        [executable, "t", str(archive_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if tested.returncode != 0:
        raise RuntimeError(f"7-Zip archive test failed: {tested.stderr or tested.stdout}")
    listed = subprocess.run(
        [executable, "l", "-slt", str(archive_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if listed.returncode != 0:
        raise RuntimeError(f"7-Zip archive listing failed: {listed.stderr or listed.stdout}")
    receipt_path = Path(receipt).expanduser().resolve()
    listing_path = (
        Path(listing).expanduser().resolve()
        if listing is not None
        else receipt_path.with_name("official_archive_listing.txt")
    )
    listing_path.parent.mkdir(parents=True, exist_ok=True)
    listing_partial = listing_path.with_suffix(listing_path.suffix + ".partial")
    try:
        with listing_partial.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(listed.stdout)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(listing_partial, listing_path)
    finally:
        if listing_partial.exists():
            listing_partial.unlink()
    extracted = safe_extract_archive(archive_path, output_dir)
    extracted.update(
        {
            "archive_test": "passed",
            "content_magic_valid": True,
            "archive_listing": {
                "path": str(listing_path),
                "bytes": listing_path.stat().st_size,
                "sha256": _sha256_file(listing_path),
            },
            "seven_zip": {
                "executable": str(executable),
                "test_returncode": tested.returncode,
                "list_returncode": listed.returncode,
            },
        }
    )
    _atomic_write_json(receipt_path, extracted)
    return extracted


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="7-Zip-test and safely extract an official OV-AVEBench archive"
    )
    parser.add_argument("--archive", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--listing", default=None)
    parser.add_argument("--min-archive-bytes", type=int, default=1_000_000)
    parser.add_argument("--seven-zip", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = extract_with_7zip_preflight(
        args.archive,
        args.output_dir,
        args.receipt,
        listing=args.listing,
        min_archive_bytes=args.min_archive_bytes,
        seven_zip=args.seven_zip,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
