"""Fail-closed validation for reproduction evidence locks."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


_TEACHER_NAMES = ("internvideo2", "beats", "clap")
_HEX_40 = re.compile(r"[0-9a-f]{40}")
_HEX_64 = re.compile(r"[0-9a-f]{64}")


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _require_string(
    record: Mapping[str, Any], key: str, prefix: str, errors: list[str]
) -> None:
    if not _nonempty_string(record.get(key)):
        errors.append(f"{prefix}.{key} must be a non-empty string")


def _validate_resolved_teacher(
    name: str, teacher: Mapping[str, Any], errors: list[str]
) -> None:
    prefix = f"teachers.{name}"
    for key in ("repository", "module", "imported_class"):
        _require_string(teacher, key, prefix, errors)

    repository = teacher.get("repository")
    if _nonempty_string(repository) and not repository.startswith("https://"):
        errors.append(f"{prefix}.repository must use https")

    commit = teacher.get("commit")
    if not isinstance(commit, str) or _HEX_40.fullmatch(commit) is None:
        errors.append(f"{prefix}.commit must be an exact 40-character lowercase hex commit")

    preprocessing = teacher.get("preprocessing")
    if not isinstance(preprocessing, Mapping) or not preprocessing:
        errors.append(f"{prefix}.preprocessing must be a non-empty mapping")

    checkpoints = teacher.get("checkpoint_files")
    if not isinstance(checkpoints, list) or not checkpoints:
        errors.append(f"{prefix}.checkpoint_files must be a non-empty list")
    else:
        for index, checkpoint in enumerate(checkpoints):
            checkpoint_prefix = f"{name}.checkpoint_files[{index}]"
            if not isinstance(checkpoint, Mapping):
                errors.append(f"{checkpoint_prefix} must be a mapping")
                continue
            for key in ("path", "source_url"):
                if not _nonempty_string(checkpoint.get(key)):
                    errors.append(f"{checkpoint_prefix}.{key} must be a non-empty string")
            source_url = checkpoint.get("source_url")
            if _nonempty_string(source_url) and not source_url.startswith("https://"):
                errors.append(f"{checkpoint_prefix}.source_url must use https")
            byte_count = checkpoint.get("bytes")
            if type(byte_count) is not int or byte_count <= 0:
                errors.append(f"{checkpoint_prefix}.bytes must be a positive integer")
            digest = checkpoint.get("sha256")
            if not isinstance(digest, str) or _HEX_64.fullmatch(digest) is None:
                errors.append(f"{checkpoint_prefix}.sha256 must be an exact lowercase SHA256")

    variant_key = {
        "internvideo2": "declared_variant",
        "beats": "variant",
        "clap": "version",
    }[name]
    _require_string(teacher, variant_key, name, errors)
    if name == "clap" and type(teacher.get("normalize")) is not bool:
        errors.append("clap.normalize must be an explicit boolean")


def validate_teacher_lock(lock: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a teacher lock without resolving identities or accessing a network."""

    errors: list[str] = []
    unresolved: list[str] = []

    if lock.get("schema_version") != 1:
        errors.append("schema_version must equal 1")
    status = lock.get("status")
    if status not in {"resolved", "blocked"}:
        errors.append("status must be resolved or blocked")

    teachers = lock.get("teachers")
    if not isinstance(teachers, Mapping):
        errors.append("teachers must be a mapping")
        teachers = {}

    for name in _TEACHER_NAMES:
        teacher = teachers.get(name)
        if not isinstance(teacher, Mapping):
            errors.append(f"teachers.{name} must be a mapping")
            continue
        teacher_status = teacher.get("status")
        if teacher_status == "unresolved":
            unresolved.append(name)
            continue
        if teacher_status != "resolved":
            errors.append(f"teachers.{name}.status must be resolved or unresolved")
            continue
        _validate_resolved_teacher(name, teacher, errors)

    unresolved.sort()
    ready = status == "resolved" and not errors and not unresolved
    return {"ready": ready, "errors": errors, "unresolved": unresolved}
