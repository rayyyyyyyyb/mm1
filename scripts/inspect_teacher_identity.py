#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import torch
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.teachers.common import (
    load_records,
    record_id,
    resolve_audio_segments,
    resolve_frame_groups,
    resolve_query,
    segment_count,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect exact identities of the three MM26 teacher models")
    parser.add_argument("--config", default="configs/ov_orthkd_mm26_repro.yaml")
    parser.add_argument("--source-manifest", default=None, help="Source manifest used for one-record smoke inference")
    parser.add_argument("--record-index", type=int, default=0)
    parser.add_argument("--device", default=None)
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--fail-on-unresolved", action="store_true")
    parser.add_argument("--skip-smoke", action="store_true", help="Only inventory identities; not sufficient for export approval")
    parser.add_argument("--output", default="reports/teacher_identity.json")
    return parser.parse_args()


def _issue(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _path(value: Any, path_root: Path) -> Path:
    if value in (None, ""):
        return Path("")
    candidate = Path(str(value)).expanduser()
    if not candidate.is_absolute():
        candidate = path_root / candidate
    return candidate.resolve()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_sha(repo: Path, errors: list[dict[str, str]], label: str) -> str | None:
    if not repo.exists():
        errors.append(_issue("missing_teacher_repo", f"{label} repository does not exist: {repo}"))
        return None
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        errors.append(_issue("teacher_repo_git_sha_unavailable", f"Cannot resolve {label} git SHA at {repo}"))
        return None
    return result.stdout.strip()


def _torch_load(path: Path) -> Any:
    return torch.load(path, map_location="cpu", weights_only=True)


def _checkpoint_identity(
    path: Path,
    errors: list[dict[str, str]],
    label: str,
) -> tuple[dict[str, Any], Any | None]:
    identity: dict[str, Any] = {
        "absolute_path": str(path),
        "exists": path.is_file(),
        "sha256": None,
        "top_level_keys": None,
    }
    if not path.is_file():
        errors.append(_issue("missing_teacher_checkpoint", f"{label} checkpoint does not exist: {path}"))
        return identity, None

    identity["sha256"] = sha256_file(path)
    try:
        payload = _torch_load(path)
    except Exception as exc:  # checkpoint errors must remain reportable
        errors.append(_issue("teacher_checkpoint_unreadable", f"Cannot read {label} checkpoint {path}: {exc}"))
        return identity, None

    if isinstance(payload, Mapping):
        identity["top_level_keys"] = sorted(str(key) for key in payload.keys())
    else:
        identity["top_level_keys"] = []
        errors.append(
            _issue(
                "teacher_checkpoint_top_level_not_mapping",
                f"{label} checkpoint top level is {type(payload).__name__}, expected a mapping",
            )
        )
    return identity, payload


def _cfg_value(config: Any, name: str, default: Any = None) -> Any:
    if isinstance(config, Mapping):
        return config.get(name, default)
    return getattr(config, name, default)


def _array_stats(value: Any) -> dict[str, Any]:
    array = np.asarray(value)
    finite = bool(np.isfinite(array).all())
    flattened = array.reshape(-1, array.shape[-1]) if array.ndim > 1 else array.reshape(1, -1)
    norms = np.linalg.norm(flattened.astype(np.float64), axis=-1)
    return {
        "shape": list(array.shape),
        "dtype": str(array.dtype),
        "finite": finite,
        "norm": {
            "min": float(norms.min()),
            "max": float(norms.max()),
            "mean": float(norms.mean()),
        },
    }


def compare_repeated_outputs(
    repeated_outputs: list[dict[str, Any]], *, tolerance: float
) -> dict[str, Any]:
    if len(repeated_outputs) < 2:
        raise ValueError("Repeatability inspection requires at least two exports")
    if tolerance < 0:
        raise ValueError("determinism tolerance must be non-negative")
    output_names = sorted(set().union(*(outputs.keys() for outputs in repeated_outputs)))
    output_reports: dict[str, Any] = {}
    all_passed = True
    for name in output_names:
        present = all(name in outputs for outputs in repeated_outputs)
        arrays = [np.asarray(outputs[name]) for outputs in repeated_outputs if name in outputs]
        baseline = arrays[0] if arrays else np.asarray([])
        shape_identical = present and all(array.shape == baseline.shape for array in arrays[1:])
        finite = present and all(bool(np.isfinite(array).all()) for array in arrays)
        bitwise_identical = shape_identical and all(
            np.array_equal(array, baseline, equal_nan=False) for array in arrays[1:]
        )
        max_abs_diff: float | None = None
        if shape_identical and arrays:
            max_abs_diff = max(
                (float(np.max(np.abs(array.astype(np.float64) - baseline.astype(np.float64))))
                 if array.size else 0.0)
                for array in arrays[1:]
            )
        passed = bool(
            present
            and shape_identical
            and finite
            and max_abs_diff is not None
            and max_abs_diff <= tolerance
        )
        all_passed = all_passed and passed
        output_reports[name] = {
            "shape": list(baseline.shape),
            "present_each_repeat": present,
            "shape_identical": shape_identical,
            "finite": finite,
            "bitwise_identical": bitwise_identical,
            "max_abs_diff": max_abs_diff,
            "tolerance": float(tolerance),
            "passed": passed,
        }
    return {
        "status": "pass" if all_passed else "failed",
        "repeat_count": len(repeated_outputs),
        "tolerance": float(tolerance),
        "outputs": output_reports,
    }


def _run_smoke(
    config: dict[str, Any],
    source_manifest: str | Path,
    record_index: int,
    device: str,
    path_root: Path,
    repeat: int,
) -> dict[str, Any]:
    from src.teachers.beats_audio import BEATsAudioTeacher
    from src.teachers.clap_text import ClapTextTeacher
    from src.teachers.internvideo2_visual import InternVideo2ClipB14Teacher

    export_cfg = config["teacher_export"]
    iv_cfg = export_cfg["internvideo2"]
    beats_cfg = export_cfg["beats"]
    clap_cfg = export_cfg["clap"]
    records = load_records(_path(source_manifest, path_root))
    if not 0 <= record_index < len(records):
        raise IndexError(f"record-index {record_index} is outside manifest length {len(records)}")
    record = records[record_index]
    expected_segments = segment_count(record)
    query = resolve_query(record)

    strong = InternVideo2ClipB14Teacher(
        repo_root=_path(iv_cfg["repo_root"], path_root),
        vision_ckpt_path=_path(iv_cfg["vision_ckpt_path"], path_root),
        text_ckpt_path=_path(iv_cfg["text_ckpt_path"], path_root),
        extra_ckpt_path=_path(iv_cfg["extra_ckpt_path"], path_root),
        vision_ckpt_sha256=str(iv_cfg["vision_ckpt_sha256"]),
        text_ckpt_sha256=str(iv_cfg["text_ckpt_sha256"]),
        extra_ckpt_sha256=str(iv_cfg["extra_ckpt_sha256"]),
        device=device,
        num_frames=int(iv_cfg.get("num_frames", 8)),
        align_dim=int(iv_cfg.get("align_dim", config["data"].get("strong_teacher_dim", 512))),
    )
    weak = BEATsAudioTeacher(
        repo_root=_path(beats_cfg["repo_root"], path_root),
        checkpoint_path=_path(beats_cfg["checkpoint_path"], path_root),
        checkpoint_sha256=str(beats_cfg["checkpoint_sha256"]),
        device=device,
    )
    text = ClapTextTeacher(
        repo_root=_path(clap_cfg["repo_root"], path_root),
        checkpoint_path=_path(clap_cfg["checkpoint_path"], path_root),
        checkpoint_sha256=str(clap_cfg["checkpoint_sha256"]),
        version=str(clap_cfg.get("version", "2023")),
        device=device,
        normalize=bool(clap_cfg.get("normalize", False)),
    )

    if repeat < 2:
        raise ValueError("--repeat must be at least 2 for real teacher smoke")
    frame_groups = resolve_frame_groups(record, expected_segments)[:1]
    audio_segments = resolve_audio_segments(record, expected_segments)[:1]
    repeated_outputs: list[dict[str, Any]] = []
    for _ in range(repeat):
        visual_features, visual_logits = strong.export_segments(frame_groups, query=query)
        audio_features = weak.export_segments(audio_segments)
        text_features = text.encode_queries([query])
        repeated_outputs.append(
            {
                "internvideo2_features": np.asarray(visual_features),
                "internvideo2_logits": np.asarray(visual_logits),
                "beats_features": np.asarray(audio_features),
                "clap_text_features": np.asarray(text_features),
            }
        )
    tolerance = float(export_cfg.get("determinism_tolerance", 0.0))
    repeatability = compare_repeated_outputs(repeated_outputs, tolerance=tolerance)
    return {
        "status": "pass" if repeatability["status"] == "pass" else "failed",
        "source_manifest": str(_path(source_manifest, path_root)),
        "record_index": record_index,
        "record_id": record_id(record, record_index),
        "query": query,
        "outputs": {
            name: _array_stats(value) for name, value in repeated_outputs[0].items()
        },
        "repeatability": repeatability,
    }


def inspect_teacher_identity(
    config: dict[str, Any],
    *,
    source_manifest: str | Path | None = None,
    record_index: int = 0,
    device: str | None = None,
    run_smoke: bool = True,
    repeat: int = 2,
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    data_cfg = config.get("data", {})
    export_cfg = config.get("teacher_export", {})
    path_root = _path(data_cfg.get("path_root", "."), Path.cwd())

    required_backends = {
        "strong_visual_backend": "internvideo2_clip_b14",
        "weak_audio_backend": "beats",
        "text_backend": "clap",
    }
    for field, expected in required_backends.items():
        actual = export_cfg.get(field)
        if actual != expected:
            errors.append(_issue("teacher_backend_not_canonical", f"{field}={actual!r}; expected {expected!r}"))

    iv_cfg = export_cfg.get("internvideo2", {})
    beats_cfg = export_cfg.get("beats", {})
    clap_cfg = export_cfg.get("clap", {})
    iv_repo = _path(iv_cfg.get("repo_root"), path_root)
    beats_repo = _path(beats_cfg.get("repo_root"), path_root)
    clap_repo = _path(clap_cfg.get("repo_root"), path_root)

    iv_checkpoints: dict[str, Any] = {}
    for name, field in (
        ("vision", "vision_ckpt_path"),
        ("text", "text_ckpt_path"),
        ("extra_clip", "extra_ckpt_path"),
    ):
        iv_checkpoints[name], _ = _checkpoint_identity(
            _path(iv_cfg.get(field), path_root), errors, f"InternVideo2 {name}"
        )
    beats_checkpoint, beats_payload = _checkpoint_identity(
        _path(beats_cfg.get("checkpoint_path"), path_root), errors, "BEATs"
    )
    clap_checkpoint, _ = _checkpoint_identity(
        _path(clap_cfg.get("checkpoint_path"), path_root), errors, "CLAP"
    )

    beats_finetuned: bool | None = None
    beats_dimension = int(data_cfg.get("weak_teacher_dim", 768))
    if isinstance(beats_payload, Mapping):
        if "cfg" not in beats_payload or "model" not in beats_payload:
            errors.append(_issue("beats_checkpoint_schema", "BEATs checkpoint must contain cfg and model keys"))
        beats_payload_cfg = beats_payload.get("cfg", {})
        beats_finetuned = bool(_cfg_value(beats_payload_cfg, "finetuned_model", False))
        beats_dimension = int(_cfg_value(beats_payload_cfg, "encoder_embed_dim", beats_dimension))
        if beats_finetuned:
            errors.append(_issue("beats_finetuned_checkpoint", "BEATs checkpoint has finetuned_model=True"))

    declared_name = str(config.get("teachers", {}).get("strong_visual", {}).get("name", ""))
    declared_model_class = str(iv_cfg.get("declared_model_class", declared_name))
    if any(token in declared_model_class.lower() for token in ("base", "b14")):
        errors.append(
            _issue(
                "internvideo2_model_identity_mismatch",
                f"Configured teacher identity {declared_model_class!r} conflicts with wrapper upstream class InternVideo2_CLIP_small",
            )
        )

    teachers = {
        "internvideo2": {
            "wrapper_class": "InternVideo2ClipB14Teacher",
            "upstream_class": "InternVideo2_CLIP_small",
            "declared_name": declared_name,
            "declared_model_class": declared_model_class,
            "repo_absolute_path": str(iv_repo),
            "repo_git_sha": _git_sha(iv_repo, errors, "InternVideo2"),
            "checkpoints": iv_checkpoints,
            "feature_dimension": int(iv_cfg.get("align_dim", data_cfg.get("strong_teacher_dim", 512))),
            "num_frames": int(iv_cfg.get("num_frames", 8)),
        },
        "beats": {
            "wrapper_class": "BEATsAudioTeacher",
            "upstream_class": "BEATs",
            "repo_absolute_path": str(beats_repo),
            "repo_git_sha": _git_sha(beats_repo, errors, "BEATs"),
            "checkpoint": beats_checkpoint,
            "feature_dimension": beats_dimension,
            "finetuned_model": beats_finetuned,
        },
        "clap": {
            "wrapper_class": "ClapTextTeacher",
            "upstream_class": "msclap.CLAP",
            "repo_absolute_path": str(clap_repo),
            "repo_git_sha": _git_sha(clap_repo, errors, "CLAP"),
            "checkpoint": clap_checkpoint,
            "feature_dimension": int(data_cfg.get("text_dim", 1024)),
            "version": str(clap_cfg.get("version", "2023")),
        },
    }

    if run_smoke:
        if source_manifest is None:
            errors.append(_issue("smoke_manifest_missing", "--source-manifest is required unless --skip-smoke is used"))
            smoke: dict[str, Any] = {"status": "blocked", "reason": "source manifest missing"}
        elif any(issue["code"] in {"missing_teacher_repo", "missing_teacher_checkpoint"} for issue in errors):
            smoke = {"status": "blocked", "reason": "teacher resources missing"}
        else:
            try:
                smoke = _run_smoke(
                    config,
                    source_manifest=source_manifest,
                    record_index=record_index,
                    device=str(device or export_cfg.get("device", "cuda" if torch.cuda.is_available() else "cpu")),
                    path_root=path_root,
                    repeat=repeat,
                )
                for name, stats in smoke["outputs"].items():
                    if not stats["finite"]:
                        errors.append(_issue("teacher_smoke_nonfinite", f"{name} contains NaN or Inf"))
                if smoke["repeatability"]["status"] != "pass":
                    errors.append(
                        _issue("teacher_smoke_not_repeatable", "Repeated teacher outputs exceeded tolerance")
                    )
            except Exception as exc:
                errors.append(_issue("teacher_smoke_failed", str(exc)))
                smoke = {"status": "failed", "error": str(exc)}
    else:
        smoke = {"status": "not_requested"}
        warnings.append(_issue("teacher_smoke_not_run", "Static inventory alone does not approve teacher export"))

    return {
        "status": "pass" if not errors else "blocked",
        "teachers": teachers,
        "smoke": smoke,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> None:
    args = parse_args()
    config_path = Path(args.config).resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    report = inspect_teacher_identity(
        config,
        source_manifest=args.source_manifest,
        record_index=args.record_index,
        device=args.device,
        run_smoke=not args.skip_smoke,
        repeat=args.repeat,
    )
    report["config"] = str(config_path)
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    raise SystemExit(0 if report["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
