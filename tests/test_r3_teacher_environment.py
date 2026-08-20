from __future__ import annotations

import hashlib
from pathlib import Path

import scripts.assets.audit_teacher_environment as environment_audit
from scripts.assets.audit_teacher_environment import (
    GPT2_REQUIRED_FILES,
    build_teacher_environment_receipt,
)
from src.utils.canonical_readiness import validate_teacher_environment_receipt


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_environment_receipt_hashes_every_required_gpt2_file(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "gpt2"
    root.mkdir()
    for name in GPT2_REQUIRED_FILES:
        (root / name).write_bytes(f"fixture:{name}".encode())
    model_path = root / "model.safetensors"
    monkeypatch.setattr(environment_audit, "GPT2_MODEL_BYTES", model_path.stat().st_size)
    monkeypatch.setattr(environment_audit, "GPT2_MODEL_SHA256", _sha256(model_path))

    versions = {
        "decord": "0.6.0",
        "soundfile": "0.12.1",
        "librosa": "0.10.1",
        "torchlibrosa": "0.1.0",
        "peft": "0.20.0",
        "transformers": "4.45.1",
        "huggingface-hub": "0.36.2",
    }
    receipt = build_teacher_environment_receipt(
        gpt2_root=root,
        installed_versions=versions,
        torch_version="2.10.0+cu128",
        cuda_available=True,
        cuda_version="12.8",
        device_name="NVIDIA GeForce RTX 5090",
    )

    assert receipt["status"] == "ready"
    assert receipt["gpt2"]["revision"] == "607a30d783dfa663caf39e06633721c8d4cfcd7e"
    for name in GPT2_REQUIRED_FILES:
        assert receipt["gpt2"]["files"][name]["sha256"] == _sha256(root / name)


def test_environment_receipt_fails_closed_on_missing_or_wrong_dependency(
    tmp_path: Path,
) -> None:
    root = tmp_path / "gpt2"
    root.mkdir()
    for name in GPT2_REQUIRED_FILES[:-1]:
        (root / name).write_bytes(b"fixture")
    versions = {
        "decord": "0.6.0",
        "soundfile": "0.12.1",
        "librosa": "0.10.1",
        "torchlibrosa": "0.1.0",
        "peft": "wrong",
        "transformers": "4.45.1",
        "huggingface-hub": "0.36.2",
    }

    receipt = build_teacher_environment_receipt(
        gpt2_root=root,
        installed_versions=versions,
        torch_version="2.10.0+cu128",
        cuda_available=True,
        cuda_version="12.8",
        device_name="NVIDIA GeForce RTX 5090",
    )

    assert receipt["status"] == "blocked"
    assert any("peft" in error for error in receipt["errors"])
    assert any(GPT2_REQUIRED_FILES[-1] in error for error in receipt["errors"])


def test_teacher_environment_bootstrap_is_pinned_resumable_and_detached() -> None:
    root = Path(__file__).resolve().parents[1]
    powershell = (root / "scripts/assets/bootstrap_teacher_environment.ps1").read_text(
        encoding="utf-8"
    )
    runner = (root / "scripts/assets/bootstrap_teacher_environment.cmd").read_text(
        encoding="utf-8"
    )

    for requirement in (
        "decord==0.6.0",
        "soundfile==0.12.1",
        "librosa==0.10.1",
        "torchlibrosa==0.1.0",
        "peft==0.20.0",
        "transformers==4.45.1",
        "huggingface-hub==0.36.2",
    ):
        assert requirement in powershell
    assert "607a30d783dfa663caf39e06633721c8d4cfcd7e" in powershell
    assert "--max-workers" in powershell
    assert "--revision" in powershell
    assert "--retries 100" in powershell
    assert "--extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple" in powershell
    assert "aria2c.exe" in powershell
    assert "--continue=true" in powershell
    assert "--max-tries=0" in powershell
    assert "--split=8" in powershell
    assert (
        "https://huggingface.co/openai-community/gpt2/resolve/"
        "$revision/model.safetensors"
    ) in powershell
    assert "https://hf-mirror.com/openai-community/gpt2/resolve/$revision/" in powershell
    assert "teacher_environment.log" in runner
    assert "teacher_environment_exit.json.tmp" in runner
    assert "move /Y" in runner


def test_canonical_teacher_environment_recomputes_gpt2_snapshot_bytes(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "gpt2"
    root.mkdir()
    for name in GPT2_REQUIRED_FILES:
        (root / name).write_bytes(f"fixture:{name}".encode())
    model_path = root / "model.safetensors"
    monkeypatch.setattr(environment_audit, "GPT2_MODEL_BYTES", model_path.stat().st_size)
    monkeypatch.setattr(environment_audit, "GPT2_MODEL_SHA256", _sha256(model_path))
    receipt = build_teacher_environment_receipt(
        gpt2_root=root,
        installed_versions={
            "decord": "0.6.0",
            "soundfile": "0.12.1",
            "librosa": "0.10.1",
            "torchlibrosa": "0.1.0",
            "peft": "0.20.0",
            "transformers": "4.45.1",
            "huggingface-hub": "0.36.2",
        },
        torch_version="2.10.0+cu128",
        cuda_available=True,
        cuda_version="12.8",
        device_name="NVIDIA GeForce RTX 5090",
    )

    assert validate_teacher_environment_receipt(receipt) == []
    (root / "config.json").write_bytes(b"tampered")
    assert any(
        "config.json" in error and "SHA256" in error
        for error in validate_teacher_environment_receipt(receipt)
    )


def test_standalone_gpt2_transfer_is_resumable_hashed_and_receipted() -> None:
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts/assets/download_gpt2_model.ps1"
    ).read_text(encoding="utf-8")

    assert "607a30d783dfa663caf39e06633721c8d4cfcd7e" in script
    assert "--continue=true" in script
    assert "--max-tries=0" in script
    assert "--split=8" in script
    assert "248dfc3911869ec493c76e65bf2fcf7f615828b0254c12b473182f0f81d3a707" in script
    assert "--checksum=sha-256=$expectedSha256" in script
    assert "548105171" in script
    assert "gpt2_model_download.json" in script
