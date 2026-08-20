from __future__ import annotations

from argparse import Namespace
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import scripts.export_teacher_artifacts as export_module
from scripts.export_teacher_artifacts import validate_teacher_lock_binding


def _args(*, strong: str, weak: str, text: str) -> Namespace:
    return Namespace(
        strong_visual_backend=strong,
        weak_audio_backend=weak,
        text_backend=text,
        internvideo2_repo_root=None,
        internvideo2_vision_ckpt=None,
        internvideo2_text_ckpt=None,
        internvideo2_extra_ckpt=None,
        beats_repo_root=None,
        beats_ckpt=None,
        clap_repo_root=None,
        clap_ckpt=None,
    )


def test_every_non_mock_export_requires_a_teacher_lock() -> None:
    args = _args(strong="internvideo2_clip_b14", weak="none", text="none")
    config = {"data": {"path_root": "."}, "teacher_export": {}}

    with pytest.raises(ValueError, match="Every non-mock export requires"):
        validate_teacher_lock_binding(args, config, None)


def test_mock_only_export_is_explicitly_classified_without_a_lock() -> None:
    args = _args(strong="mock", weak="mock", text="mock")
    config = {"data": {"path_root": "."}, "teacher_export": {}}

    assert validate_teacher_lock_binding(args, config, None) == "MOCK_ONLY_UNLOCKED"


def test_export_binding_rejects_duplicate_checkpoint_roles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "internvideo2"
    repository.mkdir()
    checkpoint_path = tmp_path / "vision.pt"
    checkpoint_path.write_bytes(b"vision checkpoint")
    checkpoint_sha = hashlib.sha256(checkpoint_path.read_bytes()).hexdigest()
    commit = "1" * 40
    repository_url = "https://example.invalid/internvideo2"
    entry = {
        "role": "vision",
        "filename": checkpoint_path.name,
        "bytes": checkpoint_path.stat().st_size,
        "sha256": checkpoint_sha,
    }
    lock_path = tmp_path / "teacher-lock.yaml"
    lock_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "ready",
                "teachers": {
                    "internvideo2": {
                        "status": "resolved",
                        "repository": repository_url,
                        "commit": commit,
                        "working_tree_clean": True,
                        "module": "internvideo.module",
                        "imported_class": "InternVideo2_CLIP_small",
                        "preprocessing": "locked",
                        "output_dim": 512,
                        "determinism_tolerance": 0.0,
                        "checkpoint_files": [dict(entry) for _ in range(3)],
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    config = {
        "data": {"path_root": str(tmp_path), "strong_teacher_dim": 512},
        "teacher_export": {
            "strong_visual_backend": "internvideo2_clip_b14",
            "weak_audio_backend": "none",
            "text_backend": "none",
            "determinism_tolerance": 0.0,
            "internvideo2": {
                "repo_root": str(repository),
                "vision_ckpt_path": str(checkpoint_path),
                "vision_ckpt_sha256": checkpoint_sha,
                "text_ckpt_path": str(checkpoint_path),
                "text_ckpt_sha256": checkpoint_sha,
                "extra_ckpt_path": str(checkpoint_path),
                "extra_ckpt_sha256": checkpoint_sha,
            },
        },
    }

    def fake_run(command, **kwargs):
        del kwargs
        if command[1:3] == ["rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout=commit + "\n", stderr="")
        if command[1:4] == ["remote", "get-url", "origin"]:
            return SimpleNamespace(returncode=0, stdout=repository_url + "\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(export_module.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="checkpoint roles"):
        validate_teacher_lock_binding(
            _args(strong="internvideo2_clip_b14", weak="none", text="none"),
            config,
            lock_path,
        )
