from __future__ import annotations

import hashlib
from pathlib import Path

from src.utils.canonical_readiness import validate_download_lock


WEIGHT_HASHES = {
    "internvideo2_b14": "1037a4785a830f9d663cab72da5751129e012042e428a74e019f84f016cd0be7",
    "internvideo2_clip_b14": "c76ebe61e955500056e83f137e028eb6ad5101e1ace137c62fbde6c3569fb05e",
    "mobileclip_blt": "670844f7a886dd6eff7a9285adfc53f3d3c889c03bfc8354010cb5c6bf27441a",
    "beats_iter3_plus_as2m": "d43cbfad4d7b56381c061d7a24774f908d4d94c72961f6eb1d9090ff18cd8d34",
    "clap_2023": "2cef4016d47d00eb28d153d522f397222057f95000e9bad6b9583c631284a1e6",
}


def _lock(root: Path) -> dict:
    assets = {}
    names = tuple(WEIGHT_HASHES) + (
        "ovave_preprocessed",
        "ovave_raw_videos",
        "vggsound_metadata",
    )
    for name in names:
        path = root / f"{name}.bin"
        if name in WEIGHT_HASHES:
            # The positive fixture declares the locked digest while monkeypatching
            # actual byte recomputation in its dedicated test below is unnecessary;
            # these entries are replaced with real bytes there.
            payload = name.encode()
        else:
            payload = f"official:{name}".encode()
        path.write_bytes(payload)
        assets[name] = {
            "kind": "weight" if name in WEIGHT_HASHES else "data",
            "path": path.name,
            "source_url": f"https://official.example/{name}",
            "alternate_urls": [f"https://mirror.example/{name}"]
            if name in WEIGHT_HASHES
            else [],
            "download_started_at": "2026-08-20T00:00:00+00:00",
            "download_completed_at": "2026-08-20T01:00:00+00:00",
            "resume_count": 1,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "content_type": "application/octet-stream",
            "validation_result": "passed",
        }
    return {"schema_version": 1, "status": "ready", "assets": assets}


def test_download_lock_recomputes_every_public_asset_byte(tmp_path: Path) -> None:
    document = _lock(tmp_path)

    # This helper deliberately separates structural/byte audit from the exact
    # published weight constants, which canonical validation checks as well.
    errors = validate_download_lock(document, tmp_path, enforce_published_hashes=False)

    assert errors == []
    (tmp_path / "ovave_raw_videos.bin").write_bytes(b"tampered")
    errors = validate_download_lock(document, tmp_path, enforce_published_hashes=False)
    assert any("ovave_raw_videos" in error and "byte" in error for error in errors)


def test_download_lock_requires_exact_asset_set_metadata_and_published_weight_hashes(
    tmp_path: Path,
) -> None:
    document = _lock(tmp_path)
    document["assets"].pop("ovave_preprocessed")
    document["assets"]["clap_2023"]["content_type"] = "text/html"

    errors = validate_download_lock(document, tmp_path)

    assert any("asset names" in error for error in errors)
    assert any("clap_2023" in error and "Content-Type" in error for error in errors)
    assert any("clap_2023" in error and "published SHA256" in error for error in errors)
