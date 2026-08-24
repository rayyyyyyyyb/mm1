#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile
import tempfile
from typing import Any, BinaryIO, Iterable
import zipfile


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative_name(raw_name: str) -> Path:
    normalized = raw_name.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if (
        not normalized
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
        or any(":" in part for part in pure.parts)
    ):
        raise ValueError(f"unsafe archive member: {raw_name!r}")
    return Path(*pure.parts)


def _copy_member(source: BinaryIO, destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with destination.open("xb") as output:
        while chunk := source.read(1024 * 1024):
            output.write(chunk)
            total += len(chunk)
        output.flush()
        os.fsync(output.fileno())
    return total


def _check_duplicate(relative: Path, seen: set[str]) -> None:
    key = relative.as_posix().casefold()
    if key in seen:
        raise ValueError(f"duplicate archive destination: {relative.as_posix()}")
    seen.add(key)


def _update_listing_digest(
    digest: Any,
    *,
    kind: str,
    relative: Path,
    size: int,
) -> None:
    """Bind every accepted member name, type, and logical size deterministically."""

    for value in (kind.encode("ascii"), relative.as_posix().encode("utf-8")):
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)
    digest.update(int(size).to_bytes(8, "big"))


def _extract_zip(
    archive_path: Path,
    staging: Path,
    *,
    max_files: int,
    max_total_bytes: int,
    max_compression_ratio: float,
) -> tuple[int, int, int, str]:
    files = 0
    total_bytes = 0
    member_count = 0
    listing_digest = hashlib.sha256()
    seen: set[str] = set()
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            relative = _safe_relative_name(member.filename.rstrip("/"))
            _check_duplicate(relative, seen)
            member_count += 1
            unix_mode = member.external_attr >> 16
            if stat.S_ISLNK(unix_mode):
                raise ValueError(f"unsafe archive member is a symlink: {member.filename!r}")
            destination = staging / relative
            if member.is_dir():
                _update_listing_digest(
                    listing_digest, kind="directory", relative=relative, size=0
                )
                destination.mkdir(parents=True, exist_ok=False)
                continue
            _update_listing_digest(
                listing_digest,
                kind="file",
                relative=relative,
                size=member.file_size,
            )
            files += 1
            if files > max_files:
                raise ValueError(f"archive exceeds max_files={max_files}")
            ratio = member.file_size / max(1, member.compress_size)
            if ratio > max_compression_ratio:
                raise ValueError(
                    f"archive member compression ratio {ratio:.1f} exceeds {max_compression_ratio}: {member.filename}"
                )
            total_bytes += int(member.file_size)
            if total_bytes > max_total_bytes:
                raise ValueError(f"archive exceeds max_total_bytes={max_total_bytes}")
            with archive.open(member, "r") as source:
                written = _copy_member(source, destination)
            if written != member.file_size:
                raise OSError(f"short extraction for {member.filename}: {written} != {member.file_size}")
    return files, total_bytes, member_count, listing_digest.hexdigest()


def _extract_tar(
    archive_path: Path,
    staging: Path,
    *,
    max_files: int,
    max_total_bytes: int,
    max_compression_ratio: float,
) -> tuple[int, int, int, str]:
    files = 0
    total_bytes = 0
    member_count = 0
    listing_digest = hashlib.sha256()
    seen: set[str] = set()
    with tarfile.open(archive_path, mode="r:*") as archive:
        members = archive.getmembers()
        for member in members:
            relative = _safe_relative_name(member.name.rstrip("/"))
            _check_duplicate(relative, seen)
            member_count += 1
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                raise ValueError(f"unsafe archive member type: {member.name!r}")
            destination = staging / relative
            if member.isdir():
                _update_listing_digest(
                    listing_digest, kind="directory", relative=relative, size=0
                )
                destination.mkdir(parents=True, exist_ok=False)
                continue
            if not member.isfile():
                raise ValueError(f"unsupported archive member type: {member.name!r}")
            _update_listing_digest(
                listing_digest,
                kind="file",
                relative=relative,
                size=member.size,
            )
            files += 1
            total_bytes += int(member.size)
            if files > max_files:
                raise ValueError(f"archive exceeds max_files={max_files}")
            if total_bytes > max_total_bytes:
                raise ValueError(f"archive exceeds max_total_bytes={max_total_bytes}")
            source = archive.extractfile(member)
            if source is None:
                raise OSError(f"cannot read archive member: {member.name}")
            with source:
                written = _copy_member(source, destination)
            if written != member.size:
                raise OSError(f"short extraction for {member.name}: {written} != {member.size}")
    ratio = total_bytes / max(1, archive_path.stat().st_size)
    if ratio > max_compression_ratio:
        raise ValueError(f"archive compression ratio {ratio:.1f} exceeds {max_compression_ratio}")
    return files, total_bytes, member_count, listing_digest.hexdigest()


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda p: p.as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        size = path.stat().st_size
        digest.update(size.to_bytes(8, "big"))
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    return digest.hexdigest()


def safe_extract_archive(
    archive_path: str | Path,
    destination: str | Path,
    *,
    max_files: int = 2_000_000,
    max_total_bytes: int = 2_000_000_000_000,
    max_compression_ratio: float = 500.0,
) -> dict[str, Any]:
    archive = Path(archive_path).expanduser().resolve()
    target = Path(destination).expanduser().resolve()
    if not archive.is_file():
        raise FileNotFoundError(f"Official archive not found: {archive}")
    if target.exists():
        raise FileExistsError(f"Extraction destination already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.partial-", dir=target.parent))
    try:
        if zipfile.is_zipfile(archive):
            archive_type = "zip"
            files, total_bytes, member_count, listing_sha256 = _extract_zip(
                archive,
                staging,
                max_files=max_files,
                max_total_bytes=max_total_bytes,
                max_compression_ratio=max_compression_ratio,
            )
        elif tarfile.is_tarfile(archive):
            archive_type = "tar"
            files, total_bytes, member_count, listing_sha256 = _extract_tar(
                archive,
                staging,
                max_files=max_files,
                max_total_bytes=max_total_bytes,
                max_compression_ratio=max_compression_ratio,
            )
        else:
            raise ValueError(
                "Unsupported archive format. Use ZIP or TAR; 7z/RAR require an audited external extractor."
            )
        tree_sha256 = _tree_sha256(staging)
        os.replace(staging, target)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    archive_sha256 = _sha256_file(archive)
    return {
        "schema_version": 1,
        "status": "passed",
        "extraction_status": "passed",
        "archive_test": "passed",
        "content_magic_valid": True,
        "archive": str(archive),
        "archive_type": archive_type,
        "archive_bytes": archive.stat().st_size,
        "archive_sha256": archive_sha256,
        "archive_listing": {
            "algorithm": "ovorthkd-safe-member-listing-v1",
            "sha256": listing_sha256,
            "member_count": member_count,
            "file_count": files,
        },
        "destination": str(target),
        "files": files,
        "files_extracted": files,
        "uncompressed_bytes": total_bytes,
        "tree_sha256": tree_sha256,
        "extracted_tree_sha256": tree_sha256,
        "safety": {
            "path_traversal_rejected": True,
            "links_rejected": True,
            "duplicate_destinations_rejected": True,
            "max_files": max_files,
            "max_total_bytes": max_total_bytes,
            "max_compression_ratio": max_compression_ratio,
        },
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    try:
        with partial.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(partial, path)
    finally:
        if partial.exists():
            partial.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely extract a manually downloaded official archive")
    parser.add_argument("--archive", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--max-files", type=int, default=2_000_000)
    parser.add_argument("--max-total-bytes", type=int, default=2_000_000_000_000)
    parser.add_argument("--max-compression-ratio", type=float, default=500.0)
    args = parser.parse_args()
    receipt = safe_extract_archive(
        args.archive,
        args.destination,
        max_files=args.max_files,
        max_total_bytes=args.max_total_bytes,
        max_compression_ratio=args.max_compression_ratio,
    )
    _atomic_write_json(Path(args.receipt), receipt)
    print(json.dumps(receipt, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
