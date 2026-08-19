from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _temporary_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")


def _fsync_parent(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_bytes(path_str: str | Path, content: bytes) -> None:
    path = Path(path_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_path(path)
    try:
        with temporary.open("wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_parent(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_text(path_str: str | Path, content: str) -> None:
    atomic_write_bytes(path_str, content.encode("utf-8"))


def atomic_write_jsonl(path_str: str | Path, records: Iterable[Mapping[str, Any]]) -> None:
    content = "".join(
        json.dumps(dict(record), ensure_ascii=False, sort_keys=True) + "\n"
        for record in records
    )
    atomic_write_text(path_str, content)


def artifact_metadata(path_str: str | Path, *, relative_to: str | Path | None = None) -> dict[str, Any]:
    path = Path(path_str).resolve()
    display_path = path
    if relative_to is not None:
        display_path = path.relative_to(Path(relative_to).resolve())
    if path.suffix.lower() == ".npz":
        with np.load(path, allow_pickle=False) as archive:
            key = "arr_0" if "arr_0" in archive else next(iter(archive.keys()))
            normalized = np.asarray(archive[key])
            shape = list(normalized.shape)
            finite = bool(np.isfinite(normalized).all())
    else:
        normalized = np.load(path, allow_pickle=False)
        shape = list(normalized.shape)
        finite = bool(np.isfinite(normalized).all())
    if not finite:
        raise ValueError(f"Artifact must contain only finite values: {path}")
    return {
        "path": display_path.as_posix(),
        "bytes": path.stat().st_size,
        "shape": shape,
        "sha256": sha256_file(path),
    }


def atomic_save_array(
    path_str: str | Path,
    array: np.ndarray,
    *,
    expected_shape: Sequence[int] | None = None,
) -> dict[str, Any]:
    path = Path(path_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_path(path)
    try:
        with temporary.open("wb") as handle:
            np.save(handle, np.asarray(array, dtype=np.float32), allow_pickle=False)
            handle.flush()
            os.fsync(handle.fileno())
        loaded = np.load(temporary, allow_pickle=False)
        try:
            if expected_shape is not None and tuple(loaded.shape) != tuple(expected_shape):
                raise ValueError(
                    f"Artifact shape {tuple(loaded.shape)} does not match expected shape {tuple(expected_shape)}"
                )
            if not np.isfinite(loaded).all():
                raise ValueError("Artifact must contain only finite values")
        finally:
            del loaded
        os.replace(temporary, path)
        _fsync_parent(path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return artifact_metadata(path)


def canonical_tree_hash(root_str: str | Path) -> dict[str, Any]:
    root = Path(root_str).resolve()
    entries: list[dict[str, Any]] = []
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.relative_to(root).as_posix()):
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    canonical_rows = "".join(
        f"{entry['path']}|{entry['bytes']}|{entry['sha256']}\n" for entry in entries
    ).encode("utf-8")
    return {
        "schema_version": 1,
        "files": len(entries),
        "bytes": sum(int(entry["bytes"]) for entry in entries),
        "sha256": hashlib.sha256(canonical_rows).hexdigest(),
    }
