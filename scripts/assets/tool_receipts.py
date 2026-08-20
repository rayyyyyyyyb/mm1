"""Validation for the native-Windows operational tool receipt."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Mapping


REQUIRED_WINDOWS_TOOLS = {
    "aria2",
    "curl",
    "ffmpeg",
    "git_lfs",
    "jq",
    "python",
    "seven_zip",
}
REQUIRED_WINDOWS_REPLACEMENTS = {"tmux", "rsync", "wget"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_windows_tool_receipt(receipt: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    if receipt.get("schema_version") != 1:
        errors.append("tool receipt schema_version must be 1")
    if receipt.get("status") != "ready" or receipt.get("platform") != "windows":
        errors.append("tool receipt must be ready for platform windows")

    tools = receipt.get("tools")
    if not isinstance(tools, Mapping):
        return errors + ["tool receipt tools must be a mapping"]
    missing = REQUIRED_WINDOWS_TOOLS - set(tools)
    if missing:
        errors.append(f"tool receipt is missing required tools: {sorted(missing)}")
    for name in sorted(REQUIRED_WINDOWS_TOOLS & set(tools)):
        item = tools[name]
        if not isinstance(item, Mapping) or item.get("status") != "verified":
            errors.append(f"{name}: status must be verified")
            continue
        path_value = item.get("path")
        if not isinstance(path_value, str) or not path_value:
            errors.append(f"{name}: executable path is missing")
            continue
        path = Path(path_value)
        if not path.is_file():
            errors.append(f"{name}: executable is missing: {path}")
            continue
        if item.get("bytes") != path.stat().st_size:
            errors.append(f"{name}: byte count mismatch")
        actual_sha256 = _sha256(path)
        if item.get("sha256") != actual_sha256:
            errors.append(f"{name}: SHA256 mismatch")
        if not isinstance(item.get("version"), str) or not str(item["version"]).strip():
            errors.append(f"{name}: version is missing")
        if not isinstance(item.get("source"), str) or not str(item["source"]).strip():
            errors.append(f"{name}: source is missing")

    replacements = receipt.get("replacements")
    if not isinstance(replacements, Mapping):
        return errors + ["native Windows replacements must be a mapping"]
    for name in sorted(REQUIRED_WINDOWS_REPLACEMENTS):
        item = replacements.get(name)
        if not isinstance(item, Mapping) or item.get("status") != "replaced" or not item.get("by"):
            errors.append(f"{name}: a documented native Windows replacement is required")
    return errors
