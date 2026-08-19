#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

import torch
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.teachers import TeacherExportBundle, export_manifest_file
from src.teachers.mock import MockStrongVisualTeacher, MockTextTeacher, MockWeakAudioTeacher
from src.utils.atomic_artifacts import sha256_file


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
            device=device,
            num_frames=int(choose(args.internvideo2_num_frames, iv_cfg.get("num_frames"), 8)),
            align_dim=int(iv_cfg.get("align_dim", data_cfg.get("strong_teacher_dim", 512))),
        )

    if weak_backend == "mock":
        bundle.weak_audio = MockWeakAudioTeacher(int(data_cfg.get("weak_teacher_dim", 768)))
    elif weak_backend == "beats":
        from src.teachers.beats_audio import BEATsAudioTeacher

        beats_cfg = export_cfg.get("beats", {})
        bundle.weak_audio = BEATsAudioTeacher(
            repo_root=require(choose(args.beats_repo_root, beats_cfg.get("repo_root")), "teacher_export.beats.repo_root"),
            checkpoint_path=require(choose(args.beats_ckpt, beats_cfg.get("checkpoint_path")), "teacher_export.beats.checkpoint_path"),
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
            version=str(choose(args.clap_version, clap_cfg.get("version"), "2023")),
            device=device,
            normalize=bool(args.clap_normalize or clap_cfg.get("normalize", False)),
        )

    return bundle, str(device), str(require(choose(args.artifact_dir, export_cfg.get("artifact_dir")), "teacher_export.artifact_dir"))


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    teachers, device, artifact_dir = build_teachers(args, config)
    export_cfg = config.get("teacher_export", {})
    receipt_jsonl = choose(args.receipt_jsonl, export_cfg.get("receipt_jsonl"))
    error_jsonl = choose(args.error_jsonl, export_cfg.get("error_jsonl"))
    teacher_lock_value = choose(args.teacher_lock, export_cfg.get("teacher_lock_path"))
    teacher_lock_sha256 = "UNSPECIFIED"
    if receipt_jsonl is not None:
        teacher_lock_path = Path(require(teacher_lock_value, "teacher_export.teacher_lock_path"))
        if not teacher_lock_path.is_file():
            raise FileNotFoundError(f"Teacher lock not found: {teacher_lock_path}")
        teacher_lock_sha256 = sha256_file(teacher_lock_path)
    split = args.split or Path(args.output_manifest).stem
    if split not in {"train", "val", "test"}:
        raise ValueError("--split must be train, val, or test for receipt-bound export")

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
    )
    summary["device"] = device
    summary["source_manifest"] = str(Path(args.source_manifest).resolve())
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
