from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_SPLIT_TYPE_ALIASES = {
    "close": "seen",
    "seen": "seen",
    "open": "unseen",
    "unseen": "unseen",
}


def normalize_split_type(value: Any, *, allow_unknown: bool = False) -> str:
    """Normalize an official OV-AVEBench class group to seen/unseen."""

    normalized = str(value).strip().lower() if value is not None else ""
    if normalized in _SPLIT_TYPE_ALIASES:
        return _SPLIT_TYPE_ALIASES[normalized]
    if allow_unknown and normalized in {"", "unknown"}:
        return "unknown"
    raise ValueError(f"Invalid split type: {value!r}")


def split_type_from_record(record: Mapping[str, Any], *, default: str = "unknown") -> str:
    """Read all supported split fields and reject contradictory metadata."""

    meta_value = record.get("meta", {})
    meta = meta_value if isinstance(meta_value, Mapping) else {}
    raw_candidates = [
        record.get("split_type"),
        record.get("seen_unseen"),
        record.get("novelty"),
        record.get("cls_type"),
        meta.get("split_type"),
        meta.get("seen_unseen"),
        meta.get("novelty"),
        meta.get("cls_type"),
    ]
    candidates = [normalize_split_type(value) for value in raw_candidates if value not in (None, "")]
    distinct = set(candidates)
    if len(distinct) > 1:
        raise ValueError(f"Contradictory split type fields: {sorted(distinct)}")
    if candidates:
        return candidates[0]
    return normalize_split_type(default, allow_unknown=True)
