from __future__ import annotations

import importlib
import hashlib
import json
from pathlib import Path

import pytest


def _build_manifest():
    try:
        module = importlib.import_module("scripts.build_ovave_raw_recovery_manifest")
    except ModuleNotFoundError:
        pytest.fail("scripts.build_ovave_raw_recovery_manifest is missing")
    return module.build_manifest


def _verify_replacements():
    try:
        module = importlib.import_module("scripts.verify_ovave_raw_replacements")
    except ModuleNotFoundError:
        pytest.fail("scripts.verify_ovave_raw_replacements is missing")
    return module.verify_replacements


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    ovavel = tmp_path / "ovave_dataset_meta.csv"
    ovavel.write_text(
        "split,cls_name,cls_type,vid_name\n"
        "train,arc welding,close,abcdefghijk\n",
        encoding="utf-8",
    )
    vggsound = tmp_path / "vggsound.csv"
    vggsound.write_text(
        "abcdefghijk,51,arc welding,train\n",
        encoding="utf-8",
    )
    zero_audit = tmp_path / "raw.zero_members.json"
    zero_audit.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "passed",
                "archive": "OV-AVEBench_raw_videos.tar.gz",
                "zero_byte_members": [
                    "dataset/train/arc welding/abcdefghijk.mp4"
                ],
            }
        ),
        encoding="utf-8",
    )
    return ovavel, vggsound, zero_audit


def test_build_manifest_joins_exact_official_rows(tmp_path: Path) -> None:
    # Catches a builder that drops official split/category/source-time evidence.
    ovavel, vggsound, zero_audit = _write_inputs(tmp_path)

    manifest = _build_manifest()(ovavel, vggsound, zero_audit)

    assert manifest["status"] == "blocked"
    assert manifest["final_status"] == "BLOCKED_BEFORE_CONFERENCE_REPRO"
    assert manifest["summary"] == {
        "zero_member_count": 1,
        "source_identified_count": 1,
        "source_timestamp_ambiguous_count": 0,
        "author_replacement_verified_count": 0,
        "unresolved_count": 0,
    }
    assert manifest["records"] == [
        {
            "sample_id": "abcdefghijk",
            "archive_member": "dataset/train/arc welding/abcdefghijk.mp4",
            "ovavel": {
                "split": "train",
                "category": "arc welding",
                "class_type": "close",
            },
            "vggsound_candidates": [
                {
                    "youtube_id": "abcdefghijk",
                    "start_seconds": 51,
                    "label": "arc welding",
                    "split": "train",
                    "source_url": "https://www.youtube.com/watch?v=abcdefghijk",
                }
            ],
            "resolution_status": "source_identified_only",
            "canonical_raw_video_usable": False,
        }
    ]


def test_build_manifest_rejects_missing_or_exact_duplicate_vggsound_rows(
    tmp_path: Path,
) -> None:
    # Missing identity evidence must block manifest construction rather than
    # quietly producing a usable-looking record.
    ovavel, vggsound, zero_audit = _write_inputs(tmp_path)
    vggsound.write_text("lmnopqrstuv,51,arc welding,train\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing VGGSound"):
        _build_manifest()(ovavel, vggsound, zero_audit)

    # Exact duplicate source keys are malformed source metadata.
    vggsound.write_text(
        "abcdefghijk,51,arc welding,train\n"
        "abcdefghijk,51,arc welding,train\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate VGGSound"):
        _build_manifest()(ovavel, vggsound, zero_audit)

    # Distinct official time candidates are preserved and explicitly ambiguous.
    vggsound.write_text(
        "abcdefghijk,51,arc welding,train\n"
        "abcdefghijk,359,arc welding,train\n",
        encoding="utf-8",
    )
    manifest = _build_manifest()(ovavel, vggsound, zero_audit)
    record = manifest["records"][0]
    assert record["resolution_status"] == "source_timestamp_ambiguous"
    assert [item["start_seconds"] for item in record["vggsound_candidates"]] == [
        51,
        359,
    ]
    assert manifest["summary"]["source_timestamp_ambiguous_count"] == 1


def test_build_manifest_rejects_malformed_vggsound_identity(tmp_path: Path) -> None:
    ovavel, vggsound, zero_audit = _write_inputs(tmp_path)
    vggsound.write_text("short,51,arc welding,train\n", encoding="utf-8")

    with pytest.raises(ValueError, match="malformed VGGSound YouTube ID"):
        _build_manifest()(ovavel, vggsound, zero_audit)


def test_build_manifest_recomputes_pinned_vggsound_source_receipt(
    tmp_path: Path,
) -> None:
    ovavel, vggsound, zero_audit = _write_inputs(tmp_path)
    receipt = tmp_path / "vggsound-receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "passed",
                "source": {
                    "repository": "https://github.com/hche11/VGGSound.git",
                    "commit": "1e75f4d30de3a99115ee9333464854c5e3d161a7",
                    "path": "data/vggsound.csv",
                },
                "download": {
                    "bytes": vggsound.stat().st_size,
                    "sha256": hashlib.sha256(vggsound.read_bytes()).hexdigest(),
                },
            }
        ),
        encoding="utf-8",
    )

    manifest = _build_manifest()(
        ovavel,
        vggsound,
        zero_audit,
        vggsound_source_receipt=receipt,
    )
    assert manifest["vggsound_source_lock"]["verified"] is True

    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["download"]["sha256"] = "f" * 64
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="VGGSound source receipt does not match"):
        _build_manifest()(
            ovavel,
            vggsound,
            zero_audit,
            vggsound_source_receipt=receipt,
        )


def test_build_manifest_never_marks_reconstructed_candidates_official(
    tmp_path: Path,
) -> None:
    ovavel, vggsound, zero_audit = _write_inputs(tmp_path)
    replacement_receipt = tmp_path / "replacement.json"
    replacement_receipt.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "passed",
                "records": [
                    {
                        "sample_id": "abcdefghijk",
                        "archive_member": "dataset/train/arc welding/abcdefghijk.mp4",
                        "candidate_kind": "reconstructed_source_clip",
                        "source_locator": "https://www.youtube.com/watch?v=abcdefghijk",
                        "size_bytes": 100,
                        "sha256": "a" * 64,
                        "media_audit": {"status": "passed"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    manifest = _build_manifest()(
        ovavel, vggsound, zero_audit, replacement_receipt
    )
    record = manifest["records"][0]
    assert record["resolution_status"] == "source_identified_only"
    assert record["canonical_raw_video_usable"] is False
    assert record["replacement_evidence_status"] == (
        "rejected_unapproved_source_kind"
    )
    assert manifest["summary"]["author_replacement_verified_count"] == 0


def _write_replacement_inputs(
    tmp_path: Path, *, candidate_kind: str = "author_sharepoint_file"
) -> tuple[Path, Path]:
    overlay = tmp_path / "overlay"
    overlay.mkdir()
    video = overlay / "abcdefghijk.mp4"
    video.write_bytes(b"not-a-real-video-but-nonzero")
    expected = tmp_path / "expected.json"
    expected.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "sample_id": "abcdefghijk",
                        "archive_member": "dataset/train/arc welding/abcdefghijk.mp4",
                        "ovavel": {"split": "train"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    declaration = tmp_path / "declaration.json"
    declaration.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "overlay_root": str(overlay),
                "records": [
                    {
                        "sample_id": "abcdefghijk",
                        "archive_member": "dataset/train/arc welding/abcdefghijk.mp4",
                        "candidate_kind": candidate_kind,
                        "source_locator": (
                            "https://mailhfuteducn-my.sharepoint.com/author-file"
                        ),
                        "file_path": "abcdefghijk.mp4",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return declaration, expected


@pytest.mark.parametrize(
    "candidate_kind", ["reconstructed_source_clip", "third_party_mirror"]
)
def test_replacement_verifier_rejects_unapproved_source_kind(
    tmp_path: Path, candidate_kind: str
) -> None:
    declaration, expected = _write_replacement_inputs(
        tmp_path, candidate_kind=candidate_kind
    )

    audit = _verify_replacements()(declaration, expected)

    assert audit["status"] == "blocked"
    assert audit["records"][0]["status"] == "failed"
    assert "unapproved_source_kind" in audit["records"][0]["errors"]


def test_replacement_verifier_accepts_windows_utf8_bom_declaration(
    tmp_path: Path,
) -> None:
    declaration, expected = _write_replacement_inputs(
        tmp_path, candidate_kind="third_party_mirror"
    )
    declaration.write_bytes(b"\xef\xbb\xbf" + declaration.read_bytes())

    audit = _verify_replacements()(declaration, expected)

    assert audit["status"] == "blocked"
    assert "unapproved_source_kind" in audit["records"][0]["errors"]


def test_replacement_verifier_rejects_zero_byte_and_wrong_id(
    tmp_path: Path,
) -> None:
    declaration, expected = _write_replacement_inputs(tmp_path)
    payload = json.loads(declaration.read_text(encoding="utf-8"))
    overlay = Path(payload["overlay_root"])

    (overlay / "abcdefghijk.mp4").write_bytes(b"")
    zero_audit = _verify_replacements()(declaration, expected)
    assert zero_audit["records"][0]["status"] == "failed"
    assert "zero_byte_file" in zero_audit["records"][0]["errors"]

    wrong = overlay / "wrong_id.mp4"
    wrong.write_bytes(b"nonzero")
    payload["records"][0]["file_path"] = wrong.name
    declaration.write_text(json.dumps(payload), encoding="utf-8")
    wrong_id_audit = _verify_replacements()(declaration, expected)
    assert wrong_id_audit["records"][0]["status"] == "failed"
    assert "filename_sample_id_mismatch" in wrong_id_audit["records"][0]["errors"]


def test_replacement_verifier_requires_ffprobe_and_ten_second_duration(
    tmp_path: Path,
) -> None:
    declaration, expected = _write_replacement_inputs(tmp_path)

    def no_audio(_: Path) -> dict:
        return {
            "streams": [{"codec_type": "video"}],
            "format": {"duration": "10.0"},
        }

    no_audio_audit = _verify_replacements()(
        declaration, expected, probe_runner=no_audio
    )
    assert "missing_audio_stream" in no_audio_audit["records"][0]["errors"]

    def wrong_duration(_: Path) -> dict:
        return {
            "streams": [{"codec_type": "video"}, {"codec_type": "audio"}],
            "format": {"duration": "12.0"},
        }

    duration_audit = _verify_replacements()(
        declaration, expected, probe_runner=wrong_duration
    )
    assert "duration_outside_ten_second_protocol" in (
        duration_audit["records"][0]["errors"]
    )

    def valid_probe(_: Path) -> dict:
        return {
            "streams": [{"codec_type": "video"}, {"codec_type": "audio"}],
            "format": {"duration": "10.0"},
        }

    passed = _verify_replacements()(
        declaration, expected, probe_runner=valid_probe
    )
    assert passed["status"] == "passed"
    assert passed["records"][0]["status"] == "passed"
    assert passed["records"][0]["media_audit"] == {
        "audio_stream_present": True,
        "duration_seconds": 10.0,
        "status": "passed",
        "video_stream_present": True,
    }
    assert len(passed["aggregate_sha256"]) == 64


def test_build_manifest_requires_author_issued_bytes_to_resolve(
    tmp_path: Path,
) -> None:
    ovavel, vggsound, zero_audit = _write_inputs(tmp_path)
    declaration, expected = _write_replacement_inputs(tmp_path)

    def valid_probe(_: Path) -> dict:
        return {
            "streams": [{"codec_type": "video"}, {"codec_type": "audio"}],
            "format": {"duration": "10.0"},
        }

    verified_audit = _verify_replacements()(
        declaration, expected, probe_runner=valid_probe
    )
    receipt = tmp_path / "verified-audit.json"
    receipt.write_text(json.dumps(verified_audit), encoding="utf-8")

    manifest = _build_manifest()(
        ovavel,
        vggsound,
        zero_audit,
        receipt,
        probe_runner=valid_probe,
    )
    assert manifest["status"] == "passed"
    assert manifest["final_status"] == "BLOCKED_BEFORE_CONFERENCE_REPRO"
    assert manifest["conference_readiness_delegated"] is True
    assert manifest["next_required_gate"] == "fresh_full_raw_video_layout_audit"
    assert manifest["summary"]["author_replacement_verified_count"] == 1
    assert manifest["records"][0]["resolution_status"] == (
        "author_replacement_verified"
    )
    assert manifest["records"][0]["canonical_raw_video_usable"] is True

    # Revalidation must fail closed if the verified bytes disappear later.
    Path(verified_audit["records"][0]["file_path"]).unlink()
    blocked = _build_manifest()(
        ovavel,
        vggsound,
        zero_audit,
        receipt,
        probe_runner=valid_probe,
    )
    assert blocked["status"] == "blocked"
    assert blocked["records"][0]["replacement_evidence_status"] == (
        "rejected_failed_revalidation"
    )
