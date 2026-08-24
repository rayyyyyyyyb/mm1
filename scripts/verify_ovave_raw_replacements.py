#!/usr/bin/env python3
"""Strictly audit author-issued OV-AVEBench raw-video replacements."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse


ALLOWED_SOURCE_KINDS = {"author_sharepoint_file", "author_corrected_archive"}
OFFICIAL_AUTHOR_HOSTS = {"mailhfuteducn-my.sharepoint.com"}
VERIFIER_ID = "ovave_raw_replacement_audit/v1"


def _run_ffprobe(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _official_author_locator(locator: Any) -> bool:
    parsed = urlparse(locator if isinstance(locator, str) else "")
    return parsed.scheme == "https" and parsed.hostname in OFFICIAL_AUTHOR_HOSTS


def _audit_media(
    path: Path, probe_runner: Callable[[Path], dict[str, Any]]
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    try:
        probe = probe_runner(path)
        stream_types = {
            stream.get("codec_type") for stream in probe.get("streams", [])
        }
        video_present = "video" in stream_types
        audio_present = "audio" in stream_types
        duration = float(probe.get("format", {}).get("duration"))
        if not video_present:
            errors.append("missing_video_stream")
        if not audio_present:
            errors.append("missing_audio_stream")
        if not 9.5 <= duration <= 10.5:
            errors.append("duration_outside_ten_second_protocol")
        return (
            {
                "audio_stream_present": audio_present,
                "duration_seconds": duration,
                "status": "passed" if not errors else "failed",
                "video_stream_present": video_present,
            },
            errors,
        )
    except (
        OSError,
        TypeError,
        ValueError,
        KeyError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
    ):
        return {"status": "failed"}, ["ffprobe_failed"]


def revalidate_verified_audit(
    audit: dict[str, Any],
    expected_by_id: dict[str, dict[str, Any]],
    *,
    probe_runner: Callable[[Path], dict[str, Any]] | None = None,
) -> tuple[bool, dict[str, list[str]]]:
    """Recompute bytes and media checks before a builder trusts an audit."""

    if probe_runner is None:
        probe_runner = _run_ffprobe
    errors_by_id: dict[str, list[str]] = {}
    rows = audit.get("records", [])
    row_ids = [row.get("sample_id") for row in rows]
    if (
        audit.get("schema_version") != 1
        or audit.get("verifier") != VERIFIER_ID
        or audit.get("status") != "passed"
        or len(row_ids) != len(set(row_ids))
        or set(row_ids) != set(expected_by_id)
    ):
        errors_by_id["__aggregate__"] = ["invalid_or_incomplete_verifier_receipt"]

    aggregate_tuples: list[str] = []
    for row in rows:
        sample_id = row.get("sample_id")
        errors: list[str] = []
        expected = expected_by_id.get(sample_id)
        if expected is None:
            errors.append("unexpected_sample_id")
        elif row.get("archive_member") != expected.get("archive_member"):
            errors.append("archive_member_mismatch")
        if row.get("candidate_kind") not in ALLOWED_SOURCE_KINDS:
            errors.append("unapproved_source_kind")
        if not _official_author_locator(row.get("source_locator")):
            errors.append("unapproved_author_locator")
        path = Path(str(row.get("file_path", "")))
        if path.stem != sample_id:
            errors.append("filename_sample_id_mismatch")
        if not path.is_file():
            errors.append("replacement_file_missing")
        else:
            size_bytes = path.stat().st_size
            sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            if size_bytes == 0:
                errors.append("zero_byte_file")
            if row.get("size_bytes") != size_bytes:
                errors.append("size_mismatch")
            if row.get("sha256") != sha256:
                errors.append("sha256_mismatch")
            media_audit, media_errors = _audit_media(path, probe_runner)
            errors.extend(media_errors)
            if row.get("media_audit") != media_audit:
                errors.append("media_audit_mismatch")
            if expected is not None:
                split = expected.get("ovavel", {}).get("split", "")
                aggregate_tuples.append(f"{split}\0{sample_id}\0{sha256}")
        if errors:
            errors_by_id[str(sample_id)] = errors

    aggregate_sha256 = hashlib.sha256(
        ("\n".join(sorted(aggregate_tuples)) + "\n").encode("utf-8")
    ).hexdigest()
    if audit.get("aggregate_sha256") != aggregate_sha256:
        errors_by_id.setdefault("__aggregate__", []).append(
            "aggregate_sha256_mismatch"
        )
    return not errors_by_id, errors_by_id


def verify_replacements(
    declaration_path: str | Path,
    expected_manifest_path: str | Path,
    *,
    probe_runner: Callable[[Path], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Audit declared replacements against the recovery manifest."""

    if probe_runner is None:
        probe_runner = _run_ffprobe
    declaration = json.loads(
        Path(declaration_path).read_text(encoding="utf-8-sig")
    )
    expected = json.loads(
        Path(expected_manifest_path).read_text(encoding="utf-8-sig")
    )
    expected_by_id = {
        record["sample_id"]: record for record in expected.get("records", [])
    }
    overlay_root = Path(declaration["overlay_root"])
    if not overlay_root.is_absolute():
        overlay_root = Path(declaration_path).resolve().parent / overlay_root
    overlay_root = overlay_root.resolve()

    records: list[dict[str, Any]] = []
    for candidate in declaration.get("records", []):
        sample_id = candidate.get("sample_id")
        errors: list[str] = []
        size_bytes: int | None = None
        sha256: str | None = None
        if sample_id not in expected_by_id:
            errors.append("unexpected_sample_id")
        if candidate.get("candidate_kind") not in ALLOWED_SOURCE_KINDS:
            errors.append("unapproved_source_kind")
        if not _official_author_locator(candidate.get("source_locator")):
            errors.append("unapproved_author_locator")
        expected_record = expected_by_id.get(sample_id)
        if expected_record is not None and candidate.get("archive_member") != expected_record.get(
            "archive_member"
        ):
            errors.append("archive_member_mismatch")

        media_audit: dict[str, Any] | None = None
        file_path = (overlay_root / str(candidate.get("file_path", ""))).resolve()
        if overlay_root not in file_path.parents:
            errors.append("file_path_outside_overlay")
        elif file_path.stem != sample_id:
            errors.append("filename_sample_id_mismatch")
        elif not file_path.is_file():
            errors.append("replacement_file_missing")
        else:
            size_bytes = file_path.stat().st_size
            if size_bytes == 0:
                errors.append("zero_byte_file")
            sha256 = hashlib.sha256(file_path.read_bytes()).hexdigest()
            if not errors:
                media_audit, media_errors = _audit_media(file_path, probe_runner)
                errors.extend(media_errors)
        records.append(
            {
                "sample_id": sample_id,
                "archive_member": candidate.get("archive_member"),
                "candidate_kind": candidate.get("candidate_kind"),
                "source_locator": candidate.get("source_locator"),
                "file_path": str(file_path),
                "status": "failed" if errors else "passed",
                "errors": errors,
                "size_bytes": size_bytes,
                "sha256": sha256,
                "media_audit": media_audit,
            }
        )

    declared_ids = [record.get("sample_id") for record in declaration.get("records", [])]
    complete_set = len(declared_ids) == len(set(declared_ids)) and set(declared_ids) == set(
        expected_by_id
    )
    status = (
        "passed"
        if records and complete_set and all(row["status"] == "passed" for row in records)
        else "blocked"
    )
    aggregate_sha256 = None
    if status == "passed":
        tuples = []
        for row in records:
            split = expected_by_id[row["sample_id"]].get("ovavel", {}).get("split", "")
            tuples.append(f"{split}\0{row['sample_id']}\0{row['sha256']}")
        aggregate_sha256 = hashlib.sha256(
            ("\n".join(sorted(tuples)) + "\n").encode("utf-8")
        ).hexdigest()
    return {
        "schema_version": 1,
        "verifier": VERIFIER_ID,
        "status": status,
        "expected_record_count": len(expected_by_id),
        "declared_record_count": len(declared_ids),
        "complete_unique_expected_set": complete_set,
        "aggregate_sha256": aggregate_sha256,
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--declaration", required=True, type=Path)
    parser.add_argument("--expected-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    audit = verify_replacements(args.declaration, args.expected_manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if audit["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
