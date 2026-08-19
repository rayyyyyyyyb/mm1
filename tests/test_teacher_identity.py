from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import torch

from scripts.inspect_teacher_identity import inspect_teacher_identity


def _git_repo(path: Path) -> str:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test User"], check=True)
    marker = path / "README.md"
    marker.write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "fixture"], check=True)
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity_fixture(tmp_path: Path, *, declared_name: str = "InternVideo2 Small", finetuned: bool = False):
    iv_repo = tmp_path / "internvideo"
    beats_repo = tmp_path / "beats"
    clap_repo = tmp_path / "clap"
    iv_sha = _git_repo(iv_repo)
    beats_sha = _git_repo(beats_repo)
    clap_sha = _git_repo(clap_repo)

    vision = tmp_path / "vision.pth"
    text = tmp_path / "text.pt"
    extra = tmp_path / "extra.pth"
    beats = tmp_path / "beats.pt"
    clap = tmp_path / "clap.pth"
    torch.save({"model": {"weight": torch.ones(1)}}, vision)
    torch.save({"state_dict": {"weight": torch.ones(1)}}, text)
    torch.save({"clip": {"weight": torch.ones(1)}}, extra)
    torch.save(
        {
            "cfg": {"finetuned_model": finetuned, "encoder_embed_dim": 768},
            "model": {"weight": torch.ones(1)},
        },
        beats,
    )
    torch.save({"model_state_dict": {"weight": torch.ones(1)}}, clap)

    config = {
        "teachers": {"strong_visual": {"name": declared_name}},
        "data": {"strong_teacher_dim": 512, "weak_teacher_dim": 768, "text_dim": 1024},
        "teacher_export": {
            "strong_visual_backend": "internvideo2_clip_b14",
            "weak_audio_backend": "beats",
            "text_backend": "clap",
            "internvideo2": {
                "repo_root": str(iv_repo),
                "vision_ckpt_path": str(vision),
                "text_ckpt_path": str(text),
                "extra_ckpt_path": str(extra),
                "num_frames": 8,
                "align_dim": 512,
            },
            "beats": {"repo_root": str(beats_repo), "checkpoint_path": str(beats)},
            "clap": {"repo_root": str(clap_repo), "checkpoint_path": str(clap), "version": "2023"},
        },
    }
    expected = {
        "repo_shas": {"internvideo2": iv_sha, "beats": beats_sha, "clap": clap_sha},
        "checkpoints": {"vision": vision, "beats": beats},
    }
    return config, expected


def test_static_teacher_identity_records_exact_provenance(tmp_path: Path) -> None:
    config, expected = _identity_fixture(tmp_path)

    report = inspect_teacher_identity(config, run_smoke=False)

    assert report["status"] == "pass"
    assert report["teachers"]["internvideo2"]["wrapper_class"] == "InternVideo2ClipB14Teacher"
    assert report["teachers"]["internvideo2"]["upstream_class"] == "InternVideo2_CLIP_small"
    assert report["teachers"]["internvideo2"]["repo_git_sha"] == expected["repo_shas"]["internvideo2"]
    assert report["teachers"]["beats"]["repo_git_sha"] == expected["repo_shas"]["beats"]
    assert report["teachers"]["clap"]["repo_git_sha"] == expected["repo_shas"]["clap"]
    assert report["teachers"]["internvideo2"]["feature_dimension"] == 512
    assert report["teachers"]["internvideo2"]["num_frames"] == 8
    assert report["teachers"]["beats"]["finetuned_model"] is False
    assert report["teachers"]["clap"]["version"] == "2023"
    assert report["teachers"]["internvideo2"]["checkpoints"]["vision"]["sha256"] == _sha256(
        expected["checkpoints"]["vision"]
    )
    assert report["teachers"]["beats"]["checkpoint"]["top_level_keys"] == ["cfg", "model"]
    assert report["smoke"]["status"] == "not_requested"


def test_declared_base_b14_is_blocked_when_wrapper_imports_small(tmp_path: Path) -> None:
    config, _ = _identity_fixture(tmp_path, declared_name="InternVideo2-Base (CLIP-B14 line)")

    report = inspect_teacher_identity(config, run_smoke=False)

    assert report["status"] == "blocked"
    assert any(issue["code"] == "internvideo2_model_identity_mismatch" for issue in report["errors"])


def test_finetuned_beats_checkpoint_is_blocked(tmp_path: Path) -> None:
    config, _ = _identity_fixture(tmp_path, finetuned=True)

    report = inspect_teacher_identity(config, run_smoke=False)

    assert report["status"] == "blocked"
    assert any(issue["code"] == "beats_finetuned_checkpoint" for issue in report["errors"])
