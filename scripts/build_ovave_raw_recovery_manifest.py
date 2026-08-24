#!/usr/bin/env python3
"""Build an evidence-only recovery manifest for zero-byte OV-AVEBench videos."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Callable


YOUTUBE_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{11}")
VGGSOUND_SOURCE_IDENTITY = {
    "repository": "https://github.com/hche11/VGGSound.git",
    "commit": "1e75f4d30de3a99115ee9333464854c5e3d161a7",
    "path": "data/vggsound.csv",
}


def _file_receipt(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": path.as_posix(),
        "bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def _read_ovavel_metadata(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        sample_id = row["vid_name"].strip()
        if sample_id in result:
            raise ValueError(f"duplicate OV-AVEL sample ID: {sample_id}")
        result[sample_id] = {
            "split": row["split"].strip(),
            "category": row["cls_name"].strip(),
            "class_type": row["cls_type"].strip(),
        }
    return result


def _read_vggsound_metadata(path: Path) -> dict[str, list[dict[str, Any]]]:
    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_source_keys: set[tuple[str, int]] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for line_number, row in enumerate(csv.reader(handle), start=1):
            if len(row) != 4:
                raise ValueError(
                    f"VGGSound row {line_number} has {len(row)} columns, expected 4"
                )
            youtube_id, start_text, label, split = (field.strip() for field in row)
            if not YOUTUBE_ID_PATTERN.fullmatch(youtube_id):
                raise ValueError(
                    f"malformed VGGSound YouTube ID at row {line_number}: {youtube_id!r}"
                )
            if not start_text or not label or not split:
                raise ValueError(f"empty required VGGSound field at row {line_number}")
            try:
                start_seconds = int(start_text)
            except ValueError as exc:
                raise ValueError(
                    f"non-integer VGGSound start seconds at row {line_number}: {start_text!r}"
                ) from exc
            if start_seconds < 0:
                raise ValueError(
                    f"negative VGGSound start seconds at row {line_number}: {start_seconds}"
                )
            source_key = (youtube_id, start_seconds)
            if source_key in seen_source_keys:
                raise ValueError(
                    "duplicate VGGSound (YouTube ID, start seconds): "
                    f"{youtube_id}, {start_seconds}"
                )
            seen_source_keys.add(source_key)
            by_id[youtube_id].append(
                {
                    "youtube_id": youtube_id,
                    "start_seconds": start_seconds,
                    "label": label,
                    "split": split,
                    "source_url": f"https://www.youtube.com/watch?v={youtube_id}",
                }
            )
    if not by_id:
        raise ValueError("VGGSound metadata is empty")
    return by_id


def build_manifest(
    ovavel_metadata: str | Path,
    vggsound_metadata: str | Path,
    zero_member_audit: str | Path,
    replacement_receipt: str | Path | None = None,
    *,
    probe_runner: Callable[[Path], dict[str, Any]] | None = None,
    vggsound_source_receipt: str | Path | None = None,
) -> dict[str, Any]:
    """Join official identity metadata without asserting replacement provenance."""

    ovavel_path = Path(ovavel_metadata)
    vggsound_path = Path(vggsound_metadata)
    zero_audit_path = Path(zero_member_audit)
    ovavel = _read_ovavel_metadata(ovavel_path)
    vggsound = _read_vggsound_metadata(vggsound_path)
    vggsound_file_receipt = _file_receipt(vggsound_path)
    vggsound_lock: dict[str, Any] | None = None
    if vggsound_source_receipt is not None:
        source_receipt_path = Path(vggsound_source_receipt)
        source_receipt = json.loads(
            source_receipt_path.read_text(encoding="utf-8-sig")
        )
        if (
            source_receipt.get("schema_version") != 1
            or source_receipt.get("status") != "passed"
            or not isinstance(source_receipt.get("source"), dict)
            or any(
                source_receipt["source"].get(key) != value
                for key, value in VGGSOUND_SOURCE_IDENTITY.items()
            )
            or source_receipt.get("download", {}).get("bytes")
            != vggsound_file_receipt["bytes"]
            or source_receipt.get("download", {}).get("sha256")
            != vggsound_file_receipt["sha256"]
        ):
            raise ValueError(
                "VGGSound source receipt does not match pinned identity or CSV bytes"
            )
        vggsound_lock = {
            **VGGSOUND_SOURCE_IDENTITY,
            "receipt": _file_receipt(source_receipt_path),
            "verified": True,
        }
    audit = json.loads(zero_audit_path.read_text(encoding="utf-8-sig"))
    if audit.get("status") != "passed":
        raise ValueError("zero-member archive audit did not pass")
    replacement_data: dict[str, Any] | None = None
    replacement_by_id: dict[str, dict[str, Any]] = {}
    if replacement_receipt is not None:
        replacement_data = json.loads(
            Path(replacement_receipt).read_text(encoding="utf-8-sig")
        )
        for replacement in replacement_data.get("records", []):
            sample_id = replacement.get("sample_id")
            if sample_id in replacement_by_id:
                raise ValueError(f"duplicate replacement receipt record: {sample_id}")
            replacement_by_id[sample_id] = replacement

    records: list[dict[str, Any]] = []
    for member in audit["zero_byte_members"]:
        sample_id = PurePosixPath(member).stem
        if sample_id not in ovavel:
            raise ValueError(f"missing OV-AVEL metadata for zero member: {sample_id}")
        candidates = sorted(
            vggsound.get(sample_id, []),
            key=lambda item: (item["start_seconds"], item["label"], item["split"]),
        )
        if not candidates:
            raise ValueError(f"missing VGGSound metadata for zero member: {sample_id}")
        resolution_status = (
            "source_timestamp_ambiguous"
            if len(candidates) > 1
            else "source_identified_only"
        )
        record = {
            "sample_id": sample_id,
            "archive_member": member,
            "ovavel": ovavel[sample_id],
            "vggsound_candidates": candidates,
            "resolution_status": resolution_status,
            "canonical_raw_video_usable": False,
        }
        replacement = replacement_by_id.get(sample_id)
        if replacement is not None:
            if replacement.get("candidate_kind") not in {
                "author_sharepoint_file",
                "author_corrected_archive",
            }:
                record["replacement_evidence_status"] = (
                    "rejected_unapproved_source_kind"
                )
            else:
                record["replacement_evidence_status"] = (
                    "rejected_unverified_author_receipt"
                )
        records.append(record)

    if replacement_data is not None:
        from scripts.verify_ovave_raw_replacements import (
            revalidate_verified_audit,
        )

        expected_by_id = {record["sample_id"]: record for record in records}
        audit_valid, audit_errors = revalidate_verified_audit(
            replacement_data,
            expected_by_id,
            probe_runner=probe_runner,
        )
        if audit_valid:
            for record in records:
                record["resolution_status"] = "author_replacement_verified"
                record["canonical_raw_video_usable"] = True
                record["replacement_evidence_status"] = "verified"
        else:
            for record in records:
                replacement = replacement_by_id.get(record["sample_id"])
                if replacement is not None and replacement.get(
                    "candidate_kind"
                ) in {"author_sharepoint_file", "author_corrected_archive"}:
                    record["replacement_evidence_status"] = (
                        "rejected_failed_revalidation"
                    )
                    record["replacement_evidence_errors"] = audit_errors.get(
                        record["sample_id"], audit_errors.get("__aggregate__", [])
                    )

    source_identified = sum(
        record["resolution_status"] == "source_identified_only" for record in records
    )
    ambiguous = sum(
        record["resolution_status"] == "source_timestamp_ambiguous"
        for record in records
    )
    unresolved = sum(not record["vggsound_candidates"] for record in records)
    verified = sum(
        record["resolution_status"] == "author_replacement_verified"
        for record in records
    )
    all_verified = bool(records) and verified == len(records)
    return {
        "schema_version": 1,
        "status": "passed" if all_verified else "blocked",
        # This scoped builder may verify replacement provenance, but it cannot
        # assert conference readiness without a fresh full raw-layout audit and
        # the remaining canonical teacher/preflight gates.
        "final_status": "BLOCKED_BEFORE_CONFERENCE_REPRO",
        "conference_readiness_delegated": True,
        "next_required_gate": (
            "fresh_full_raw_video_layout_audit"
            if all_verified
            else "complete_author_replacement_set"
        ),
        "summary": {
            "zero_member_count": len(records),
            "source_identified_count": source_identified,
            "source_timestamp_ambiguous_count": ambiguous,
            "author_replacement_verified_count": verified,
            "unresolved_count": unresolved,
        },
        "evidence_inputs": {
            "ovavel_metadata": _file_receipt(ovavel_path),
            "vggsound_metadata": vggsound_file_receipt,
            "zero_member_audit": _file_receipt(zero_audit_path),
        },
        **(
            {"vggsound_source_lock": vggsound_lock}
            if vggsound_lock is not None
            else {}
        ),
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ovavel-metadata", required=True, type=Path)
    parser.add_argument("--vggsound-metadata", required=True, type=Path)
    parser.add_argument("--zero-audit", required=True, type=Path)
    parser.add_argument("--replacement-receipt", type=Path)
    parser.add_argument("--vggsound-source-receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    manifest = build_manifest(
        args.ovavel_metadata,
        args.vggsound_metadata,
        args.zero_audit,
        args.replacement_receipt,
        vggsound_source_receipt=args.vggsound_source_receipt,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
