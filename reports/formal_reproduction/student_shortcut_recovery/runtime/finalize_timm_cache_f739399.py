#!/usr/bin/env python3

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any


ASSETS: tuple[dict[str, Any], ...] = (
    {
        "role": "visual",
        "model": "convnextv2_tiny.fcmae_ft_in22k_in1k",
        "url": "https://dl.fbaipublicfiles.com/convnext/convnextv2/im22k/convnextv2_tiny_22k_224_ema.pt",
        "filename": "convnextv2_tiny_22k_224_ema.pt",
        "expected_bytes": 114_604_362,
        "expected_sha256_prefix": None,
        "allow_complete_partial": True,
    },
    {
        "role": "audio",
        "model": "tf_efficientnetv2_b2.in1k",
        "url": "https://github.com/rwightman/pytorch-image-models/releases/download/v0.1-effv2-weights/tf_efficientnetv2_b2-847de54e.pth",
        "filename": "tf_efficientnetv2_b2-847de54e.pth",
        "expected_bytes": 40_795_861,
        "expected_sha256_prefix": "847de54e",
        "allow_complete_partial": False,
    },
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _load_audio_receipt(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"audio range receipt is missing: {path}")
    receipt = json.loads(path.read_text(encoding="utf-8-sig"))
    if receipt.get("status") != "PASS":
        raise RuntimeError("audio range receipt is not PASS")
    return receipt


def finalize_cache(
    cache_dir: Path,
    control_dir: Path,
    audio_receipt_path: Path,
    assets: tuple[dict[str, Any], ...] = ASSETS,
) -> dict[str, Any]:
    cache_dir = cache_dir.resolve()
    control_dir = control_dir.resolve()
    audio_receipt = _load_audio_receipt(audio_receipt_path)
    candidates: dict[str, dict[str, Any]] = {}

    for asset in assets:
        role = str(asset["role"])
        final = cache_dir / str(asset["filename"])
        partial = Path(str(final) + ".part")
        if final.is_file():
            candidate = final
            source = "preexisting_final"
        elif bool(asset["allow_complete_partial"]) and partial.is_file():
            candidate = partial
            source = "complete_partial"
        else:
            raise RuntimeError(f"verified candidate is missing for {role}: {final}")

        expected_bytes = int(asset["expected_bytes"])
        actual_bytes = candidate.stat().st_size
        if actual_bytes != expected_bytes:
            raise RuntimeError(
                f"{role} byte count mismatch: expected {expected_bytes}, got {actual_bytes}"
            )
        digest = sha256(candidate)
        prefix = asset["expected_sha256_prefix"]
        if prefix is not None and not digest.startswith(str(prefix)):
            raise RuntimeError(f"{role} SHA256 does not match official filename prefix")
        candidates[role] = {
            "asset": asset,
            "candidate": candidate,
            "final": final,
            "source": source,
            "bytes": actual_bytes,
            "sha256": digest,
        }

    if set(candidates) != {"audio", "visual"}:
        raise RuntimeError("cache finalizer requires exactly audio and visual assets")
    audio = candidates["audio"]
    expected_audio = audio["asset"]
    if (
        audio_receipt.get("url") != expected_audio["url"]
        or int(audio_receipt.get("bytes", -1)) != audio["bytes"]
        or audio_receipt.get("sha256") != audio["sha256"]
        or Path(str(audio_receipt.get("target", ""))).resolve() != audio["final"].resolve()
    ):
        raise RuntimeError("audio range receipt does not bind the verified final audio file")

    for item in candidates.values():
        candidate = item["candidate"]
        final = item["final"]
        if candidate != final:
            if final.exists():
                raise RuntimeError(f"refusing to overwrite final cache file: {final}")
            os.replace(candidate, final)
        if final.stat().st_size != item["bytes"] or sha256(final) != item["sha256"]:
            raise RuntimeError(f"post-finalization verification failed: {final}")

    receipt_assets: dict[str, Any] = {}
    for role, item in sorted(candidates.items()):
        asset = item["asset"]
        receipt_assets[role] = {
            "status": "PASS",
            "model": asset["model"],
            "url": asset["url"],
            "target": str(item["final"]),
            "bytes": item["bytes"],
            "sha256": item["sha256"],
            "expected_sha256_prefix": asset["expected_sha256_prefix"],
            "candidate_source": item["source"],
        }

    receipt = {
        "schema_version": 1,
        "status": "PASS",
        "claim_level": "official_timm_1.0.28_pretrained_cfg_direct_url_cache_lock",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "cache_dir": str(cache_dir),
        "source_policy": "exact_url_from_locked_timm_1.0.28_pretrained_cfg",
        "audio_range_receipt": {
            "path": str(audio_receipt_path.resolve()),
            "sha256": sha256(audio_receipt_path),
        },
        "assets": receipt_assets,
    }
    atomic_json(control_dir / "official_cache_receipt.json", receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--control-dir", required=True, type=Path)
    parser.add_argument("--audio-receipt", required=True, type=Path)
    args = parser.parse_args()
    receipt = finalize_cache(args.cache_dir, args.control_dir, args.audio_receipt)
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
