"""Audit the exact runtime and local GPT-2 bytes used by the real teachers."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


GPT2_REPOSITORY = "openai-community/gpt2"
GPT2_REVISION = "607a30d783dfa663caf39e06633721c8d4cfcd7e"
GPT2_REQUIRED_FILES = (
    "config.json",
    "generation_config.json",
    "merges.txt",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
)
REQUIRED_DISTRIBUTIONS = {
    "decord": "0.6.0",
    "soundfile": "0.12.1",
    "librosa": "0.10.1",
    "torchlibrosa": "0.1.0",
    "peft": "0.20.0",
    "transformers": "4.45.1",
    "huggingface-hub": "0.36.2",
}
GPT2_MODEL_SHA256 = "248dfc3911869ec493c76e65bf2fcf7f615828b0254c12b473182f0f81d3a707"
GPT2_MODEL_BYTES = 548_105_171


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree_sha256(files: Mapping[str, Mapping[str, object]]) -> str:
    digest = hashlib.sha256()
    for relative_path in sorted(files):
        item = files[relative_path]
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(item["bytes"]).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(item["sha256"]).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def build_teacher_environment_receipt(
    *,
    gpt2_root: Path,
    installed_versions: Mapping[str, str],
    torch_version: str,
    cuda_available: bool,
    cuda_version: str | None,
    device_name: str | None,
) -> dict[str, object]:
    errors: list[str] = []
    packages: dict[str, dict[str, object]] = {}
    for name, expected in REQUIRED_DISTRIBUTIONS.items():
        actual = installed_versions.get(name)
        packages[name] = {
            "expected_version": expected,
            "installed_version": actual,
            "verified": actual == expected,
        }
        if actual != expected:
            errors.append(f"{name}: expected {expected}, found {actual!r}")

    files: dict[str, dict[str, object]] = {}
    for relative_path in GPT2_REQUIRED_FILES:
        path = gpt2_root / relative_path
        if not path.is_file():
            errors.append(f"GPT-2 required file missing: {relative_path}")
            continue
        files[relative_path] = {
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
    model = files.get("model.safetensors")
    if model and (
        model["bytes"] != GPT2_MODEL_BYTES or model["sha256"] != GPT2_MODEL_SHA256
    ):
        errors.append("GPT-2 model.safetensors size or SHA256 mismatch")
    if not torch_version.startswith("2.10.0+"):
        errors.append(f"torch: expected the validated 2.10.0 CUDA build, found {torch_version}")
    if not cuda_available:
        errors.append("CUDA is unavailable")
    if device_name != "NVIDIA GeForce RTX 5090":
        errors.append(f"expected NVIDIA GeForce RTX 5090, found {device_name!r}")

    return {
        "schema_version": 1,
        "status": "ready" if not errors else "blocked",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "packages": packages,
        "torch": {
            "version": torch_version,
            "cuda_available": cuda_available,
            "cuda_version": cuda_version,
            "device_name": device_name,
        },
        "gpt2": {
            "repository": GPT2_REPOSITORY,
            "revision": GPT2_REVISION,
            "root": str(gpt2_root.resolve()),
            "files": files,
            "root_sha256": _tree_sha256(files),
        },
        "errors": errors,
    }


def _installed_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for distribution in REQUIRED_DISTRIBUTIONS:
        try:
            versions[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            continue
    return versions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gpt2-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    import torch

    cuda_available = bool(torch.cuda.is_available())
    receipt = build_teacher_environment_receipt(
        gpt2_root=args.gpt2_root,
        installed_versions=_installed_versions(),
        torch_version=str(torch.__version__),
        cuda_available=cuda_available,
        cuda_version=str(torch.version.cuda) if torch.version.cuda else None,
        device_name=torch.cuda.get_device_name(0) if cuda_available else None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
