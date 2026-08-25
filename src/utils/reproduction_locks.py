"""Fail-closed validation for reproduction evidence locks."""

from __future__ import annotations

import hashlib
import json
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
    if status not in {"resolved", "blocked", "smoke_passed_export_pending", "ready"}:
        errors.append(
            "status must be resolved, blocked, smoke_passed_export_pending, or ready"
        )

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
    ready = status in {"resolved", "ready"} and not errors and not unresolved
    return {"ready": ready, "errors": errors, "unresolved": unresolved}


def teacher_identity_payload(lock: Mapping[str, Any]) -> dict[str, Any]:
    """Project a lock onto immutable teacher identity and inference semantics."""

    validation = validate_teacher_lock(lock)
    if validation["errors"] or validation["unresolved"]:
        details = list(validation["errors"]) + [
            f"unresolved teacher: {name}" for name in validation["unresolved"]
        ]
        raise ValueError("Invalid teacher identity lock: " + "; ".join(details))

    teachers = lock["teachers"]
    payload_teachers: dict[str, Any] = {}
    for name in _TEACHER_NAMES:
        teacher = teachers[name]
        checkpoint_files = []
        for checkpoint in teacher["checkpoint_files"]:
            checkpoint_files.append(
                {
                    "role": checkpoint.get("role"),
                    "source_url": checkpoint.get("source_url"),
                    "filename": checkpoint.get("filename", checkpoint.get("path")),
                    "bytes": checkpoint.get("bytes"),
                    "sha256": checkpoint.get("sha256"),
                }
            )
        checkpoint_files.sort(key=lambda value: str(value["role"]))
        identity = {
            "repository": teacher.get("repository"),
            "commit": teacher.get("commit"),
            "module": teacher.get("module"),
            "imported_class": teacher.get("imported_class"),
            "wrapper_class": teacher.get("wrapper_class"),
            "preprocessing": teacher.get("preprocessing"),
            "output_dim": teacher.get("output_dim"),
            "determinism_tolerance": teacher.get("determinism_tolerance"),
            "checkpoint_files": checkpoint_files,
        }
        for variant_key in ("declared_variant", "variant", "version", "normalize"):
            if variant_key in teacher:
                identity[variant_key] = teacher[variant_key]
        payload_teachers[name] = identity
    return {
        "schema_version": 1,
        "binding": "immutable_teacher_identity_and_inference_semantics",
        "teachers": payload_teachers,
    }


def teacher_identity_sha256(lock: Mapping[str, Any]) -> str:
    payload = teacher_identity_payload(lock)
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_teacher_export_identity(lock: Mapping[str, Any]) -> dict[str, Any]:
    """Require exact resolved teachers and passed real smoke before export."""

    validation = validate_teacher_lock(lock)
    errors = list(validation["errors"])
    unresolved = list(validation["unresolved"])
    smoke = lock.get("real_smoke")
    if not isinstance(smoke, Mapping):
        errors.append("real_smoke must be a mapping")
    else:
        if smoke.get("status") != "passed":
            errors.append("real_smoke.status must be passed")
        if type(smoke.get("records")) is not int or smoke.get("records", 0) < 1:
            errors.append("real_smoke.records must be a positive integer")
        if type(smoke.get("repeat")) is not int or smoke.get("repeat", 0) < 2:
            errors.append("real_smoke.repeat must be at least 2")
        if smoke.get("input_mode") != "official_segment_keyframes":
            errors.append("real_smoke.input_mode must be official_segment_keyframes")
        if smoke.get("task_segments") != 10:
            errors.append("real_smoke.task_segments must be 10")
        if smoke.get("all_finite") is not True:
            errors.append("real_smoke.all_finite must be true")
        if smoke.get("bitwise_repeatable") is not True:
            errors.append("real_smoke.bitwise_repeatable must be true")
        expected_shapes = {
            "internvideo2_features": [10, 512],
            "internvideo2_logits": [10],
            "beats_features": [10, 768],
            "clap_text_features": [1024],
        }
        if smoke.get("output_shapes") != expected_shapes:
            errors.append("real_smoke.output_shapes must match the locked teacher dimensions")
    digest = None
    if not errors and not unresolved:
        try:
            digest = teacher_identity_sha256(lock)
        except ValueError as exc:
            errors.append(str(exc))
    declared_digest = lock.get("teacher_identity_sha256")
    if digest is not None and declared_digest is not None and declared_digest != digest:
        errors.append("teacher_identity_sha256 does not match teacher identities")
    return {
        "ready": not errors and not unresolved,
        "errors": errors,
        "unresolved": unresolved,
        "teacher_identity_sha256": digest,
    }
