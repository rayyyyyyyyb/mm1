"""Fail-closed resolution of independent visual/audio pretrained settings."""

from __future__ import annotations

from typing import Any, Mapping


def _strict_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def resolve_modality_pretrained(student_cfg: Mapping[str, Any]) -> tuple[bool, bool]:
    """Resolve visual/audio flags, allowing legacy fallback only as a pair.

    A config that declares only one new field is ambiguous and is rejected;
    this prevents a visual-only diagnostic from silently changing audio.
    """

    if not isinstance(student_cfg, Mapping):
        raise ValueError("student config must be a mapping")
    has_visual = "visual_pretrained" in student_cfg
    has_audio = "audio_pretrained" in student_cfg
    if has_visual != has_audio:
        raise ValueError("visual_pretrained and audio_pretrained must be declared together")
    if has_visual:
        if "pretrained" in student_cfg:
            raise ValueError("legacy pretrained conflicts with explicit visual/audio pretrained fields")
        return (
            _strict_bool(student_cfg["visual_pretrained"], "visual_pretrained"),
            _strict_bool(student_cfg["audio_pretrained"], "audio_pretrained"),
        )
    if "pretrained" not in student_cfg:
        return False, False
    legacy = _strict_bool(student_cfg["pretrained"], "pretrained")
    return legacy, legacy
