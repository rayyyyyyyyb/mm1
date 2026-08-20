#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Mapping

import torch
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.teachers import TeacherExportBundle, export_manifest_file
from src.teachers.mock import MockStrongVisualTeacher, MockTextTeacher, MockWeakAudioTeacher
from src.utils.atomic_artifacts import sha256_file
from src.utils.canonical_readiness import EXPECTED_CHECKPOINT_ROLES


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export offline teacher artifacts for OV-OrthKD")
    parser.add_argument("--config", type=str, default="configs/ov_orthkd.yaml")
    parser.add_argument("--source-manifest", type=str, required=True)
    parser.add_argument("--output-manifest", type=str, required=True)
    parser.add_argument("--artifact-dir", type=str, default=None)
    parser.add_argument("--device", type=str, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--copy-unprocessed-records", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--receipt-jsonl", type=str, default=None)
    parser.add_argument("--error-jsonl", type=str, default=None)
    parser.add_argument("--progress-path", type=str, default=None)
    parser.add_argument("--teacher-lock", type=str, default=None)
    parser.add_argument("--split", type=str, choices=("train", "val", "test"), default=None)
    parser.add_argument("--resume", action="store_true")

    parser.add_argument(
        "--strong-visual-backend",
        type=str,
        default=None,
        choices=("internvideo2_clip_b14", "mock", "none"),
    )
    parser.add_argument(
        "--weak-audio-backend",
        type=str,
        default=None,
        choices=("beats", "mock", "none"),
    )
    parser.add_argument(
        "--text-backend",
        type=str,
        default=None,
        choices=("clap", "mock", "none"),
    )

    parser.add_argument("--internvideo2-repo-root", type=str, default=None)
    parser.add_argument("--internvideo2-vision-ckpt", type=str, default=None)
    parser.add_argument("--internvideo2-text-ckpt", type=str, default=None)
    parser.add_argument("--internvideo2-extra-ckpt", type=str, default=None)
    parser.add_argument("--internvideo2-num-frames", type=int, default=None)

    parser.add_argument("--beats-repo-root", type=str, default=None)
    parser.add_argument("--beats-ckpt", type=str, default=None)

    parser.add_argument("--clap-repo-root", type=str, default=None)
    parser.add_argument("--clap-ckpt", type=str, default=None)
    parser.add_argument("--clap-text-model-root", type=str, default=None)
    parser.add_argument("--clap-version", type=str, default=None)
    parser.add_argument("--clap-normalize", action="store_true")
    return parser.parse_args()


def load_config(path_str: str) -> Dict[str, Any]:
    with open(path_str, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def choose(cli_value: Any, cfg_value: Any, default: Any = None) -> Any:
    if cli_value is not None:
        return cli_value
    if cfg_value is not None:
        return cfg_value
    return default


def require(value: Any, label: str) -> Any:
    if value in (None, ""):
        raise ValueError(f"Missing required setting: {label}")
    return value


def _resolved_from_data_root(config: Mapping[str, Any], value: str | Path) -> Path:
    root = Path(config.get("data", {}).get("path_root", ".")).expanduser().resolve()
    path = Path(value).expanduser()
    return (root / path).resolve() if not path.is_absolute() else path.resolve()


def _non_mock_backends(args: argparse.Namespace, config: Mapping[str, Any]) -> dict[str, str]:
    export_cfg = config.get("teacher_export", {})
    return {
        "internvideo2": str(choose(args.strong_visual_backend, export_cfg.get("strong_visual_backend"), "internvideo2_clip_b14")),
        "beats": str(choose(args.weak_audio_backend, export_cfg.get("weak_audio_backend"), "beats")),
        "clap": str(choose(args.text_backend, export_cfg.get("text_backend"), "clap")),
    }


def validate_teacher_lock_binding(
    args: argparse.Namespace,
    config: Mapping[str, Any],
    teacher_lock_path: str | Path | None,
) -> str:
    """Bind every real export to the exact ready lock before importing upstream code."""

    backends = _non_mock_backends(args, config)
    real_teachers = {
        name for name, backend in backends.items() if backend not in {"mock", "none"}
    }
    if not real_teachers:
        if teacher_lock_path is None:
            return "MOCK_ONLY_UNLOCKED"
        path = _resolved_from_data_root(config, teacher_lock_path)
        if not path.is_file():
            raise FileNotFoundError(f"Teacher lock not found: {path}")
        return sha256_file(path)
    if teacher_lock_path is None:
        raise ValueError("Every non-mock export requires teacher_export.teacher_lock_path")
    path = _resolved_from_data_root(config, teacher_lock_path)
    if not path.is_file():
        raise FileNotFoundError(f"Teacher lock not found: {path}")
    lock = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(lock, Mapping) or lock.get("schema_version") != 1 or lock.get("status") != "ready":
        raise RuntimeError("Non-mock export requires a schema_version=1 ready teacher lock")

    export_cfg = config.get("teacher_export", {})
    teacher_cfg = {
        "internvideo2": export_cfg.get("internvideo2", {}),
        "beats": export_cfg.get("beats", {}),
        "clap": export_cfg.get("clap", {}),
    }
    role_fields = {
        ("internvideo2", "vision"): ("vision_ckpt_path", "vision_ckpt_sha256", "internvideo2_vision_ckpt"),
        ("internvideo2", "text"): ("text_ckpt_path", "text_ckpt_sha256", "internvideo2_text_ckpt"),
        ("internvideo2", "extra_clip"): ("extra_ckpt_path", "extra_ckpt_sha256", "internvideo2_extra_ckpt"),
        ("beats", "encoder"): ("checkpoint_path", "checkpoint_sha256", "beats_ckpt"),
        ("clap", "text_encoder"): ("checkpoint_path", "checkpoint_sha256", "clap_ckpt"),
    }
    locked_teachers = lock.get("teachers", {})
    repository_fields = {
        "internvideo2": ("repo_root", "internvideo2_repo_root", "InternVideo2_CLIP_small"),
        "beats": ("repo_root", "beats_repo_root", "BEATs"),
        "clap": ("repo_root", "clap_repo_root", "msclap.CLAP"),
    }
    for teacher_name in sorted(real_teachers):
        identity = locked_teachers.get(teacher_name, {}) if isinstance(locked_teachers, Mapping) else {}
        if not isinstance(identity, Mapping) or identity.get("status") != "resolved":
            raise RuntimeError(f"Teacher lock identity is unresolved: {teacher_name}")
        repo_key, repo_cli_key, expected_class = repository_fields[teacher_name]
        section = teacher_cfg[teacher_name]
        repo_value = choose(getattr(args, repo_cli_key), section.get(repo_key))
        repo_path = _resolved_from_data_root(
            config,
            require(repo_value, f"teacher_export.{teacher_name}.{repo_key}"),
        )
        if not repo_path.is_dir():
            raise FileNotFoundError(f"Locked teacher repository not found: {repo_path}")
        if identity.get("imported_class") != expected_class:
            raise RuntimeError(f"Teacher imported class does not match wrapper: {teacher_name}")
        expected_dims = {
            "internvideo2": int(config.get("data", {}).get("strong_teacher_dim", 512)),
            "beats": int(config.get("data", {}).get("weak_teacher_dim", 768)),
            "clap": int(config.get("data", {}).get("text_dim", 1024)),
        }
        if int(identity.get("output_dim", -1)) != expected_dims[teacher_name]:
            raise RuntimeError(f"Teacher output dimension does not match config: {teacher_name}")
        if not identity.get("preprocessing", identity.get("input_preprocessing")):
            raise RuntimeError(f"Teacher preprocessing is not locked: {teacher_name}")
        locked_tolerance = identity.get("determinism_tolerance")
        configured_tolerance = export_cfg.get("determinism_tolerance")
        if (
            locked_tolerance is None
            or configured_tolerance is None
            or float(locked_tolerance) != float(configured_tolerance)
        ):
            raise RuntimeError(f"Teacher determinism tolerance does not match config: {teacher_name}")
        git_values: dict[str, str] = {}
        for label, command in {
            "commit": ["git", "rev-parse", "HEAD"],
            "repository": ["git", "remote", "get-url", "origin"],
            "status": ["git", "status", "--porcelain"],
        }.items():
            completed = subprocess.run(
                command,
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(f"Cannot verify {teacher_name} repository {label}: {completed.stderr.strip()}")
            git_values[label] = completed.stdout.strip()
        locked_repository = str(identity.get("repository", identity.get("repository_url", ""))).removesuffix(".git")
        actual_repository = git_values["repository"].removesuffix(".git")
        if (
            git_values["commit"] != identity.get("commit", identity.get("repository_commit"))
            or actual_repository != locked_repository
            or git_values["status"]
            or identity.get("working_tree_clean") is not True
        ):
            raise RuntimeError(f"Teacher repository identity/cleanliness does not match lock: {teacher_name}")
        checkpoints = identity.get("checkpoint_files", [])
        if not isinstance(checkpoints, list):
            raise RuntimeError(f"Teacher lock checkpoint_files is invalid: {teacher_name}")
        roles = [
            str(checkpoint.get("role", ""))
            for checkpoint in checkpoints
            if isinstance(checkpoint, Mapping)
        ]
        expected_roles = EXPECTED_CHECKPOINT_ROLES[teacher_name]
        if (
            len(roles) != len(checkpoints)
            or len(roles) != len(set(roles))
            or set(roles) != expected_roles
        ):
            raise RuntimeError(
                f"Teacher lock checkpoint roles for {teacher_name} must be exactly "
                f"{sorted(expected_roles)} with no duplicates, got {roles}"
            )
        for checkpoint in checkpoints:
            if not isinstance(checkpoint, Mapping):
                raise RuntimeError(f"Malformed checkpoint lock entry: {teacher_name}")
            role = str(checkpoint.get("role", ""))
            fields = role_fields.get((teacher_name, role))
            if fields is None:
                raise RuntimeError(f"Unexpected checkpoint role in teacher lock: {teacher_name}/{role}")
            path_key, hash_key, cli_key = fields
            section = teacher_cfg[teacher_name]
            selected_value = choose(getattr(args, cli_key), section.get(path_key))
            selected_path = _resolved_from_data_root(config, require(selected_value, f"teacher_export.{teacher_name}.{path_key}"))
            selected_hash = str(require(section.get(hash_key), f"teacher_export.{teacher_name}.{hash_key}"))
            if not selected_path.is_file():
                raise FileNotFoundError(f"Locked checkpoint not found: {selected_path}")
            if (
                selected_path.name != checkpoint.get("filename")
                or selected_path.stat().st_size != checkpoint.get("bytes")
                or selected_hash != checkpoint.get("sha256")
                or sha256_file(selected_path) != selected_hash
            ):
                raise RuntimeError(f"Teacher checkpoint does not match lock: {teacher_name}/{role}")
    return sha256_file(path)


def build_teachers(args: argparse.Namespace, config: Dict[str, Any]) -> tuple[TeacherExportBundle, str, str]:
    data_cfg = config["data"]
    export_cfg = config.get("teacher_export", {})
    device = choose(args.device, export_cfg.get("device"), "cuda" if torch.cuda.is_available() else "cpu")

    strong_backend = choose(args.strong_visual_backend, export_cfg.get("strong_visual_backend"), "internvideo2_clip_b14")
    weak_backend = choose(args.weak_audio_backend, export_cfg.get("weak_audio_backend"), "beats")
    text_backend = choose(args.text_backend, export_cfg.get("text_backend"), "clap")

    bundle = TeacherExportBundle()

    if strong_backend == "mock":
        bundle.strong_visual = MockStrongVisualTeacher(int(data_cfg.get("strong_teacher_dim", 512)))
    elif strong_backend == "internvideo2_clip_b14":
        from src.teachers.internvideo2_visual import InternVideo2ClipB14Teacher

        iv_cfg = export_cfg.get("internvideo2", {})
        bundle.strong_visual = InternVideo2ClipB14Teacher(
            repo_root=require(choose(args.internvideo2_repo_root, iv_cfg.get("repo_root")), "teacher_export.internvideo2.repo_root"),
            vision_ckpt_path=require(choose(args.internvideo2_vision_ckpt, iv_cfg.get("vision_ckpt_path")), "teacher_export.internvideo2.vision_ckpt_path"),
            text_ckpt_path=require(choose(args.internvideo2_text_ckpt, iv_cfg.get("text_ckpt_path")), "teacher_export.internvideo2.text_ckpt_path"),
            extra_ckpt_path=require(choose(args.internvideo2_extra_ckpt, iv_cfg.get("extra_ckpt_path")), "teacher_export.internvideo2.extra_ckpt_path"),
            vision_ckpt_sha256=require(iv_cfg.get("vision_ckpt_sha256"), "teacher_export.internvideo2.vision_ckpt_sha256"),
            text_ckpt_sha256=require(iv_cfg.get("text_ckpt_sha256"), "teacher_export.internvideo2.text_ckpt_sha256"),
            extra_ckpt_sha256=require(iv_cfg.get("extra_ckpt_sha256"), "teacher_export.internvideo2.extra_ckpt_sha256"),
            device=device,
            num_frames=int(choose(args.internvideo2_num_frames, iv_cfg.get("num_frames"), 8)),
            align_dim=int(iv_cfg.get("align_dim", data_cfg.get("strong_teacher_dim", 512))),
            intervals=int(iv_cfg.get("intervals", 10)),
            video_duration_seconds=int(iv_cfg.get("video_duration_seconds", 10)),
            sampling_fps=int(iv_cfg.get("temporal_sampling_fps", 16)),
        )

    if weak_backend == "mock":
        bundle.weak_audio = MockWeakAudioTeacher(int(data_cfg.get("weak_teacher_dim", 768)))
    elif weak_backend == "beats":
        from src.teachers.beats_audio import BEATsAudioTeacher

        beats_cfg = export_cfg.get("beats", {})
        bundle.weak_audio = BEATsAudioTeacher(
            repo_root=require(choose(args.beats_repo_root, beats_cfg.get("repo_root")), "teacher_export.beats.repo_root"),
            checkpoint_path=require(choose(args.beats_ckpt, beats_cfg.get("checkpoint_path")), "teacher_export.beats.checkpoint_path"),
            checkpoint_sha256=require(beats_cfg.get("checkpoint_sha256"), "teacher_export.beats.checkpoint_sha256"),
            device=device,
        )

    if text_backend == "mock":
        bundle.text_teacher = MockTextTeacher(int(data_cfg.get("text_dim", 1024)))
    elif text_backend == "clap":
        from src.teachers.clap_text import ClapTextTeacher

        clap_cfg = export_cfg.get("clap", {})
        bundle.text_teacher = ClapTextTeacher(
            repo_root=require(choose(args.clap_repo_root, clap_cfg.get("repo_root")), "teacher_export.clap.repo_root"),
            checkpoint_path=require(choose(args.clap_ckpt, clap_cfg.get("checkpoint_path")), "teacher_export.clap.checkpoint_path"),
            checkpoint_sha256=require(clap_cfg.get("checkpoint_sha256"), "teacher_export.clap.checkpoint_sha256"),
            text_model_root=require(
                choose(args.clap_text_model_root, clap_cfg.get("text_model_root")),
                "teacher_export.clap.text_model_root",
            ),
            version=str(choose(args.clap_version, clap_cfg.get("version"), "2023")),
            device=device,
            normalize=bool(args.clap_normalize or clap_cfg.get("normalize", False)),
        )

    return bundle, str(device), str(require(choose(args.artifact_dir, export_cfg.get("artifact_dir")), "teacher_export.artifact_dir"))


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    export_cfg = config.get("teacher_export", {})
    receipt_jsonl = choose(args.receipt_jsonl, export_cfg.get("receipt_jsonl"))
    error_jsonl = choose(args.error_jsonl, export_cfg.get("error_jsonl"))
    readiness = config.get("reproduction", {}).get("readiness", {})
    teacher_lock_value = choose(
        args.teacher_lock,
        export_cfg.get("teacher_lock_path"),
        readiness.get("teacher_lock") if isinstance(readiness, Mapping) else None,
    )
    teacher_lock_sha256 = validate_teacher_lock_binding(args, config, teacher_lock_value)
    teachers, device, artifact_dir = build_teachers(args, config)
    split = args.split or Path(args.output_manifest).stem
    if split not in {"train", "val", "test"}:
        raise ValueError("--split must be train, val, or test for receipt-bound export")
    progress_path = choose(
        args.progress_path,
        str(Path(export_cfg.get("progress_dir", "reports/teachers/progress")) / f"{split}.json"),
    )

    summary = export_manifest_file(
        source_manifest=args.source_manifest,
        artifact_dir=artifact_dir,
        output_manifest=args.output_manifest,
        teachers=teachers,
        overwrite=args.overwrite,
        limit=args.limit,
        copy_unprocessed_records=args.copy_unprocessed_records,
        receipt_jsonl=receipt_jsonl,
        error_jsonl=error_jsonl,
        teacher_lock_sha256=teacher_lock_sha256,
        split=split,
        resume=bool(args.resume),
        progress_path=progress_path,
    )
    summary["device"] = device
    summary["source_manifest"] = str(Path(args.source_manifest).resolve())
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
