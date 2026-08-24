from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from src.utils.reproduction_fingerprint import sha256_file


CODE_ROOT = Path(__file__).resolve().parents[2]
OFFICIAL_SPLIT_COUNTS = {"train": 13182, "val": 5798, "test": 5820}
REQUIRED_READINESS_PATHS = (
    "data_lock",
    "archival_lock",
    "teacher_lock",
    "preprocessing_lock",
    "evaluator_lock",
    "archive_receipt",
    "layout_discovery",
    "source_audit",
    "teacher_identity",
    "smoke_repeatability",
    "exported_audit",
    "real_preflight",
)
REQUIRED_ARCHIVAL_FACTS = {
    "temporal_protocol",
    "internvideo_identity",
    "scheduler_and_early_stop",
    "student_initialization_and_augmentation",
    "visual_l2_reduction",
    "query_aware_fusion",
    "frame_sampling",
    "student_audio_preprocessing",
    "evaluator_mapping",
}
REQUIRED_SCHEMA_VERSIONS = {
    "data_lock": 2,
    "archival_lock": 2,
    "teacher_lock": 1,
    "preprocessing_lock": 1,
    "evaluator_lock": 1,
    "archive_receipt": 1,
    "layout_discovery": 1,
    "source_audit": 1,
    "teacher_identity": 1,
    "smoke_repeatability": 1,
    "exported_audit": 1,
    "real_preflight": 1,
    "download_lock": 1,
    "teacher_environment": 1,
}
OFFICIAL_SPLIT_SEEN_UNSEEN_COUNTS = {
    "train": {"seen": 13182, "unseen": 0},
    "val": {"seen": 1651, "unseen": 4147},
    "test": {"seen": 1664, "unseen": 4156},
}
EXPECTED_CHECKPOINT_ROLES = {
    "internvideo2": {"vision", "text", "extra_clip"},
    "beats": {"encoder"},
    "clap": {"text_encoder"},
}
REQUIRED_DOWNLOAD_ASSETS = {
    "internvideo2_b14",
    "internvideo2_clip_b14",
    "mobileclip_blt",
    "beats_iter3_plus_as2m",
    "clap_2023",
    "ovave_preprocessed",
    "ovave_raw_videos",
    "vggsound_metadata",
}
PUBLISHED_WEIGHT_SHA256 = {
    "internvideo2_b14": "1037a4785a830f9d663cab72da5751129e012042e428a74e019f84f016cd0be7",
    "internvideo2_clip_b14": "c76ebe61e955500056e83f137e028eb6ad5101e1ace137c62fbde6c3569fb05e",
    "mobileclip_blt": "670844f7a886dd6eff7a9285adfc53f3d3c889c03bfc8354010cb5c6bf27441a",
    "beats_iter3_plus_as2m": "d43cbfad4d7b56381c061d7a24774f908d4d94c72961f6eb1d9090ff18cd8d34",
    "clap_2023": "2cef4016d47d00eb28d153d522f397222057f95000e9bad6b9583c631284a1e6",
}
REQUIRED_TEACHER_PACKAGES = {
    "decord": "0.6.0",
    "soundfile": "0.12.1",
    "librosa": "0.10.1",
    "torchlibrosa": "0.1.0",
    "peft": "0.20.0",
    "transformers": "4.45.1",
    "huggingface-hub": "0.36.2",
}
GPT2_REVISION = "607a30d783dfa663caf39e06633721c8d4cfcd7e"
GPT2_REQUIRED_FILES = {
    "config.json",
    "generation_config.json",
    "merges.txt",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
}
REQUIRED_ARCHIVAL_CONFIG_PATHS = {
    "temporal_protocol": {"data.max_segments", "task.label_mode"},
    "internvideo_identity": {
        "teacher_export.strong_visual_backend",
        "teacher_export.internvideo2.declared_model_class",
    },
    "scheduler_and_early_stop": {
        "training.epochs",
        "training.scheduler",
        "training.early_stop_patience",
        "training.early_stop_min_delta",
    },
    "student_initialization_and_augmentation": {"student.pretrained", "data.train_augment"},
    "visual_l2_reduction": {"loss.visual_l2_reduction"},
    "query_aware_fusion": {"student.fusion_mode"},
    "frame_sampling": {
        "teacher_export.internvideo2.num_frames",
        "teacher_export.internvideo2.frame_sampling",
        "teacher_export.internvideo2.short_clip_policy",
    },
    "student_audio_preprocessing": {"data.audio_preprocessing"},
    "evaluator_mapping": {
        "evaluation.paper_f1_at_0_5_mapping",
        "evaluation.validation_calibrated_f1_mapping",
    },
}
REQUIRED_PREPROCESSING_CONFIG_PATHS = {
    "data.preprocessing_mode",
    "data.frame_policy",
    "data.canonical_visual_extension",
}
EVALUATOR_CONFIG_PATHS = {
    "paper_f1_at_0_5_mapping": "evaluation.paper_f1_at_0_5_mapping",
    "validation_calibrated_f1_mapping": "evaluation.validation_calibrated_f1_mapping",
}
_MISSING = object()
_PATH_ONLY_CONFIG_KEYS = {
    "path_root",
    "project_root",
    "train_manifest",
    "val_manifest",
    "test_manifest",
}


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return (root / path).resolve() if not path.is_absolute() else path.resolve()


def _load_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"Canonical readiness gate failed: Missing readiness input: {path}")
    try:
        if path.suffix.lower() == ".json":
            value = json.loads(path.read_text(encoding="utf-8"))
        else:
            value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise RuntimeError(f"Invalid readiness input {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"Readiness input must be a mapping: {path}")
    return value


def validate_download_lock(
    document: Mapping[str, Any],
    root: Path,
    *,
    enforce_published_hashes: bool = True,
) -> list[str]:
    """Recompute every public data/weight asset named by the R3 download lock."""

    errors: list[str] = []
    assets = document.get("assets")
    if not isinstance(assets, Mapping):
        return ["download_lock: assets must be a mapping"]
    observed_names = set(str(name) for name in assets)
    if observed_names != REQUIRED_DOWNLOAD_ASSETS:
        errors.append(
            "download_lock: asset names must be exactly "
            f"{sorted(REQUIRED_DOWNLOAD_ASSETS)}, got {sorted(observed_names)}"
        )
    for name in sorted(REQUIRED_DOWNLOAD_ASSETS & observed_names):
        item = assets.get(name)
        if not isinstance(item, Mapping):
            errors.append(f"download_lock: {name} receipt must be a mapping")
            continue
        expected_kind = "weight" if name in PUBLISHED_WEIGHT_SHA256 else "data"
        if item.get("kind") != expected_kind:
            errors.append(f"download_lock: {name} kind must be {expected_kind}")
        path_value = item.get("path")
        path = _resolve(root, str(path_value)) if isinstance(path_value, str) and path_value else None
        expected_bytes = item.get("bytes")
        expected_sha = item.get("sha256")
        if path is None or not path.is_file():
            errors.append(f"download_lock: {name} asset file is missing: {path}")
        elif (
            not isinstance(expected_bytes, int)
            or expected_bytes <= 0
            or path.stat().st_size != expected_bytes
            or not _is_sha256(expected_sha)
            or sha256_file(path) != expected_sha
        ):
            errors.append(f"download_lock: {name} byte count or SHA256 mismatch")
        if enforce_published_hashes and name in PUBLISHED_WEIGHT_SHA256:
            if expected_sha != PUBLISHED_WEIGHT_SHA256[name]:
                errors.append(f"download_lock: {name} published SHA256 mismatch")
        source_url = item.get("source_url")
        if not isinstance(source_url, str) or not source_url.startswith("https://"):
            errors.append(f"download_lock: {name} final source URL must be HTTPS")
        alternates = item.get("alternate_urls")
        if not isinstance(alternates, list) or any(
            not isinstance(url, str) or not url.startswith("https://") for url in alternates
        ):
            errors.append(f"download_lock: {name} alternate URLs must be an HTTPS list")
        for field in ("download_started_at", "download_completed_at"):
            try:
                value = datetime.fromisoformat(str(item.get(field)).replace("Z", "+00:00"))
                if value.tzinfo is None:
                    raise ValueError
            except ValueError:
                errors.append(f"download_lock: {name} {field} must be timezone-aware ISO-8601")
        resume_count = item.get("resume_count")
        if not isinstance(resume_count, int) or isinstance(resume_count, bool) or resume_count < 0:
            errors.append(f"download_lock: {name} resume_count must be a non-negative integer")
        content_type = str(item.get("content_type", "")).strip().casefold()
        if not content_type or "html" in content_type or "xml" in content_type:
            errors.append(f"download_lock: {name} Content-Type is missing or non-binary")
        if item.get("validation_result") != "passed":
            errors.append(f"download_lock: {name} validation_result must be passed")
    return errors


def validate_teacher_environment_receipt(document: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    packages = document.get("packages")
    if not isinstance(packages, Mapping):
        errors.append("teacher_environment: packages must be a mapping")
    else:
        if set(packages) != set(REQUIRED_TEACHER_PACKAGES):
            errors.append("teacher_environment: direct package set mismatch")
        for name, expected in REQUIRED_TEACHER_PACKAGES.items():
            item = packages.get(name)
            if (
                not isinstance(item, Mapping)
                or item.get("expected_version") != expected
                or item.get("installed_version") != expected
                or item.get("verified") is not True
            ):
                errors.append(f"teacher_environment: {name} version is not exactly {expected}")

    torch_info = document.get("torch")
    if (
        not isinstance(torch_info, Mapping)
        or not str(torch_info.get("version", "")).startswith("2.10.0+")
        or torch_info.get("cuda_available") is not True
        or torch_info.get("cuda_version") != "12.8"
        or torch_info.get("device_name") != "NVIDIA GeForce RTX 5090"
    ):
        errors.append("teacher_environment: validated RTX 5090 CUDA runtime mismatch")

    gpt2 = document.get("gpt2")
    if not isinstance(gpt2, Mapping):
        return errors + ["teacher_environment: gpt2 receipt must be a mapping"]
    if gpt2.get("repository") != "openai-community/gpt2" or gpt2.get("revision") != GPT2_REVISION:
        errors.append("teacher_environment: GPT-2 repository/revision mismatch")
    root_value = gpt2.get("root")
    root = Path(str(root_value)).expanduser().resolve() if root_value else None
    files = gpt2.get("files")
    if not isinstance(files, Mapping) or set(files) != GPT2_REQUIRED_FILES:
        errors.append("teacher_environment: GPT-2 required file set mismatch")
        files = files if isinstance(files, Mapping) else {}
    root_digest = hashlib.sha256()
    for relative_path in sorted(GPT2_REQUIRED_FILES & set(files)):
        item = files.get(relative_path)
        path = root / relative_path if root is not None else None
        if not isinstance(item, Mapping) or path is None or not path.is_file():
            errors.append(f"teacher_environment: GPT-2 file missing: {relative_path}")
            continue
        actual_sha = sha256_file(path)
        actual_bytes = path.stat().st_size
        if item.get("sha256") != actual_sha or item.get("bytes") != actual_bytes:
            errors.append(f"teacher_environment: GPT-2 SHA256/bytes mismatch: {relative_path}")
        root_digest.update(relative_path.encode("utf-8"))
        root_digest.update(b"\0")
        root_digest.update(str(actual_bytes).encode("ascii"))
        root_digest.update(b"\0")
        root_digest.update(actual_sha.encode("ascii"))
        root_digest.update(b"\n")
    if len(GPT2_REQUIRED_FILES & set(files)) == len(GPT2_REQUIRED_FILES):
        if gpt2.get("root_sha256") != root_digest.hexdigest():
            errors.append("teacher_environment: GPT-2 root SHA256 mismatch")
    return errors


def _walk_file_evidence(value: Any) -> Sequence[Mapping[str, Any]]:
    found: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
            found.append(value)
        for child in value.values():
            found.extend(_walk_file_evidence(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_file_evidence(child))
    return found


def _validate_file_evidence(root: Path, documents: Mapping[str, Mapping[str, Any]]) -> list[str]:
    errors: list[str] = []
    for document_name, document in documents.items():
        for evidence in _walk_file_evidence(document):
            path = _resolve(root, str(evidence["path"]))
            expected = str(evidence["sha256"]).lower()
            if not path.is_file():
                errors.append(f"{document_name}: evidence file is missing: {path}")
                continue
            actual = sha256_file(path)
            if actual != expected:
                errors.append(
                    f"{document_name}: SHA256 mismatch for {path}: expected {expected}, actual {actual}"
                )
    return errors


def _status(document: Mapping[str, Any]) -> str:
    return str(document.get("status", "")).strip().lower()


def _is_sha256(value: Any) -> bool:
    text = str(value or "").lower()
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _normalized_experiment_config(value: Any, path: tuple[str, ...] = ()) -> Any:
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for raw_key, child in value.items():
            key = str(raw_key)
            if not path and key == "logging":
                continue
            if path == ("reproduction",) and key in {
                "readiness",
                "full_run_blocked",
                "blocked_archival_facts",
            }:
                continue
            if (
                key in _PATH_ONLY_CONFIG_KEYS
                or key.endswith("_path")
                or key.endswith("_root")
                or key.endswith("_dir")
            ):
                continue
            normalized[key] = _normalized_experiment_config(child, (*path, key))
        return normalized
    if isinstance(value, list):
        return [_normalized_experiment_config(item, (*path, "[]")) for item in value]
    if isinstance(value, tuple):
        return [_normalized_experiment_config(item, (*path, "[]")) for item in value]
    return value


def canonical_experiment_config_sha256(config: Mapping[str, Any]) -> str:
    """Hash every experiment-affecting value while excluding location/output-only fields."""

    payload = json.dumps(
        _normalized_experiment_config(config),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_archival_evidence(
    fact_name: str,
    evidence: Any,
    *,
    fact_status: str,
    claim_level: str,
    project_root: Path,
) -> list[str]:
    if not isinstance(evidence, list) or not evidence:
        return [f"archival_lock: {fact_name} evidence must be a non-empty list"]
    errors: list[str] = []
    for index, item in enumerate(evidence):
        prefix = f"archival_lock: {fact_name}.evidence[{index}]"
        if not isinstance(item, Mapping):
            errors.append(f"{prefix} must be a structured file or Git locator")
            continue
        kind = str(item.get("kind", "")).strip().lower()
        if kind == "file":
            if not isinstance(item.get("path"), str) or not _is_sha256(item.get("sha256")):
                errors.append(f"{prefix} must be a structured file or Git locator")
        elif kind == "user_approval":
            if not (
                claim_level == "paper_specified_reconstruction"
                and fact_status == "approved_reconstruction_assumption"
                and item.get("approved_by") == "user"
                and isinstance(item.get("path"), str)
                and _is_sha256(item.get("sha256"))
            ):
                errors.append(
                    f"{prefix} user approval is only valid for an explicitly approved reconstruction assumption"
                )
        elif kind == "git":
            commit = str(item.get("commit", "")).lower()
            if not (
                isinstance(item.get("repository"), str)
                and len(commit) == 40
                and all(character in "0123456789abcdef" for character in commit)
                and isinstance(item.get("path"), str)
                and _is_sha256(item.get("blob_sha256"))
                and isinstance(item.get("checkout_root"), str)
            ):
                errors.append(f"{prefix} must be a structured file or Git locator")
                continue
            checkout = _resolve(project_root, str(item["checkout_root"]))
            try:
                remote = subprocess.run(
                    ["git", "remote", "get-url", "origin"],
                    cwd=checkout,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                blob = subprocess.run(
                    ["git", "show", f"{commit}:{item['path']}"],
                    cwd=checkout,
                    capture_output=True,
                    text=False,
                    check=False,
                )
            except OSError as exc:
                errors.append(f"{prefix} cannot verify Git locator: {exc}")
                continue
            expected_repository = str(item["repository"]).removesuffix(".git")
            observed_repository = remote.stdout.strip().removesuffix(".git") if remote.returncode == 0 else ""
            observed_blob_sha256 = hashlib.sha256(blob.stdout).hexdigest() if blob.returncode == 0 else None
            if (
                remote.returncode != 0
                or blob.returncode != 0
                or observed_repository != expected_repository
                or observed_blob_sha256 != item.get("blob_sha256")
            ):
                errors.append(f"{prefix} Git locator bytes/repository cannot be reproduced")
        else:
            errors.append(f"{prefix} must be a structured file or Git locator")
    return errors


def _unresolved_markers(value: Any, prefix: str = "") -> list[str]:
    markers: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            if key in {"blocked_by", "blockers"} and child:
                markers.append(child_prefix)
            markers.extend(_unresolved_markers(child, child_prefix))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            markers.extend(_unresolved_markers(child, f"{prefix}[{index}]"))
    elif isinstance(value, str):
        normalized = value.strip().lower()
        if (
            normalized in {"blocked", "unresolved"}
            or normalized.startswith("not_executed")
            or value.strip().upper().startswith("UNRESOLVED")
        ):
            markers.append(prefix)
    return markers


def _get_config_value(config: Mapping[str, Any], dotted_path: str) -> Any:
    current: Any = config
    for component in dotted_path.split("."):
        if not component or not isinstance(current, Mapping) or component not in current:
            return _MISSING
        current = current[component]
    return current


def _validate_config_bindings(
    document_name: str,
    bindings: Any,
    config: Mapping[str, Any],
    *,
    required_paths: set[str],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(bindings, list):
        return [f"{document_name}: config_bindings must be a list"]
    observed_paths: list[str] = []
    for index, binding in enumerate(bindings):
        if not isinstance(binding, Mapping):
            errors.append(f"{document_name}: config_bindings[{index}] must be a mapping")
            continue
        path = binding.get("path")
        if not isinstance(path, str) or not path.strip() or "value" not in binding:
            errors.append(f"{document_name}: config_bindings[{index}] requires path and value")
            continue
        observed_paths.append(path)
        actual = _get_config_value(config, path)
        if actual is _MISSING or actual != binding["value"]:
            observed = "<missing>" if actual is _MISSING else repr(actual)
            errors.append(
                f"{document_name}: config binding mismatch at {path}: "
                f"locked {binding['value']!r}, runtime {observed}"
            )
    if len(observed_paths) != len(set(observed_paths)):
        errors.append(f"{document_name}: config binding paths must be unique")
    if set(observed_paths) != required_paths:
        errors.append(
            f"{document_name}: config binding paths must be exactly {sorted(required_paths)}, "
            f"got {sorted(set(observed_paths))}"
        )
    return errors


def _actual_git_dirty(root: Path) -> bool:
    if not (root / ".git").exists():
        raise RuntimeError(f"Cannot inspect canonical Git state: repository metadata missing at {root}")
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"Cannot inspect canonical Git state: {exc}") from exc
    if completed.returncode != 0:
        raise RuntimeError(f"Cannot inspect canonical Git state: {completed.stderr.strip()}")
    return bool(completed.stdout.strip())


def _checkpoint_config_entries(config: Mapping[str, Any], root: Path) -> dict[tuple[str, str], dict[str, Any]]:
    export = config.get("teacher_export", {})
    if not isinstance(export, Mapping):
        return {}
    definitions = {
        ("internvideo2", "vision"): ("internvideo2", "vision_ckpt_path", "vision_ckpt_sha256"),
        ("internvideo2", "text"): ("internvideo2", "text_ckpt_path", "text_ckpt_sha256"),
        ("internvideo2", "extra_clip"): ("internvideo2", "extra_ckpt_path", "extra_ckpt_sha256"),
        ("beats", "encoder"): ("beats", "checkpoint_path", "checkpoint_sha256"),
        ("clap", "text_encoder"): ("clap", "checkpoint_path", "checkpoint_sha256"),
    }
    entries: dict[tuple[str, str], dict[str, Any]] = {}
    for identity, (section_name, path_key, hash_key) in definitions.items():
        section = export.get(section_name, {})
        if not isinstance(section, Mapping):
            continue
        raw_path = section.get(path_key)
        path = _resolve(root, str(raw_path)) if raw_path else None
        entries[identity] = {"path": path, "sha256": section.get(hash_key)}
    return entries


def validate_canonical_readiness(
    config: Mapping[str, Any],
    *,
    require_real_preflight: bool = True,
) -> dict[str, Any]:
    """Validate the complete, versioned canonical evidence chain or raise."""

    reproduction = config.get("reproduction", {})
    if not isinstance(reproduction, Mapping):
        raise RuntimeError("Canonical readiness gate failed: reproduction config is invalid")
    claim_level = str(reproduction.get("claim_level", "")).strip().lower()
    if claim_level not in {"archival_exact", "paper_specified_reconstruction"}:
        raise RuntimeError("Canonical readiness gate failed: unsupported or missing claim_level")
    readiness = reproduction.get("readiness", {})
    if not isinstance(readiness, Mapping):
        raise RuntimeError("Canonical readiness gate failed: reproduction.readiness must be a mapping")
    required_readiness_paths = list(REQUIRED_READINESS_PATHS)
    if not require_real_preflight:
        required_readiness_paths.remove("real_preflight")
    if reproduction.get("asset_download_lock_required") is True:
        required_readiness_paths.extend(("download_lock", "teacher_environment"))
    missing_keys = sorted(set(required_readiness_paths) - set(readiness))
    if missing_keys:
        raise RuntimeError(
            "Canonical readiness gate failed: missing readiness paths: " + ", ".join(missing_keys)
        )

    data = config.get("data", {})
    root = Path(data.get("path_root", ".") if isinstance(data, Mapping) else ".").expanduser().resolve()
    derived_project_root = CODE_ROOT.resolve()
    project_root_value = reproduction.get("project_root")
    if not isinstance(project_root_value, (str, Path)) or not str(project_root_value).strip():
        configured_project_root = None
        project_root_error = "reproduction.project_root is required for canonical Git inspection"
    else:
        configured_project_root = _resolve(derived_project_root, project_root_value)
        project_root_error = (
            None
            if configured_project_root == derived_project_root
            else "reproduction.project_root must resolve to the actual code root"
        )
    project_root = derived_project_root
    paths = {
        name: _resolve(project_root, str(readiness[name]))
        for name in required_readiness_paths
    }
    documents = {name: _load_mapping(path) for name, path in paths.items()}
    errors: list[str] = []
    if project_root_error:
        errors.append(project_root_error)

    for name, document in documents.items():
        expected_version = REQUIRED_SCHEMA_VERSIONS[name]
        if document.get("schema_version") != expected_version:
            errors.append(
                f"{name}: schema_version must be {expected_version}, got {document.get('schema_version')!r}"
            )

    expected_statuses = {
        "data_lock": "ready",
        "archival_lock": "resolved",
        "teacher_lock": "ready",
        "preprocessing_lock": "resolved",
        "evaluator_lock": "resolved",
        "archive_receipt": "passed",
        "layout_discovery": "passed",
        "source_audit": "passed",
        "teacher_identity": "pass",
        "smoke_repeatability": "pass",
        "exported_audit": "passed",
    }
    if require_real_preflight:
        expected_statuses["real_preflight"] = "passed"
    if "download_lock" in documents:
        expected_statuses["download_lock"] = "ready"
    if "teacher_environment" in documents:
        expected_statuses["teacher_environment"] = "ready"
    for name, expected in expected_statuses.items():
        observed = _status(documents[name])
        if observed != expected:
            errors.append(f"{name}: status must be {expected!r}, got {observed!r}")

    if "download_lock" in documents:
        errors.extend(validate_download_lock(documents["download_lock"], project_root))
    if "teacher_environment" in documents:
        errors.extend(validate_teacher_environment_receipt(documents["teacher_environment"]))

    for name, document in documents.items():
        if name == "real_preflight" and not require_real_preflight:
            continue
        markers = _unresolved_markers(document)
        if markers:
            errors.append(f"{name}: unresolved/blocked markers remain at {sorted(set(markers))}")

    training = config.get("training", {})
    if not isinstance(training, Mapping):
        errors.append("training config must be a mapping")
    elif (
        claim_level == "paper_specified_reconstruction"
        and reproduction.get("asset_download_lock_required") is True
    ):
        if training.get("max_batches_per_epoch") != 400:
            errors.append("paper-specified reconstruction requires exactly 400 batches per epoch")
        if training.get("max_optimizer_steps") is not None:
            errors.append("formal canonical training cannot contain an optimizer-step limit")
    elif any(training.get(key) is not None for key in ("max_batches_per_epoch", "max_optimizer_steps")):
        errors.append("formal canonical training cannot contain batch or optimizer-step limits")

    archive = documents["archive_receipt"]
    if (
        archive.get("extraction_status") != "passed"
        or archive.get("archive_test") != "passed"
        or archive.get("content_magic_valid") is not True
        or not _is_sha256(archive.get("archive_sha256"))
    ):
        errors.append(
            "archive_receipt: 7-Zip test, content magic, extraction and archive SHA256 must pass"
        )
    archive_path_value = archive.get("archive") or archive.get("path")
    if not archive_path_value:
        errors.append("archive_receipt: archive path is required")
    else:
        archive_path = _resolve(root, str(archive_path_value))
        if not archive_path.is_file():
            errors.append(f"archive_receipt: archive file is missing: {archive_path}")
        elif sha256_file(archive_path) != archive.get("archive_sha256"):
            errors.append("archive_receipt: archive file SHA256 mismatch")

    layout = documents["layout_discovery"]
    if (
        layout.get("split_counts") != OFFICIAL_SPLIT_COUNTS
        or layout.get("errors") != []
        or layout.get("warnings") != []
        or layout.get("metadata_bijection_verified") is not True
        or layout.get("missing_clip_ids") not in ({}, {split: [] for split in OFFICIAL_SPLIT_COUNTS})
        or layout.get("extra_clip_ids") not in ({}, {split: [] for split in OFFICIAL_SPLIT_COUNTS})
        or layout.get("duplicate_clip_ids") != []
        or layout.get("duplicate_logical_basenames") != []
        or layout.get("zero_byte_files") != []
    ):
        errors.append("layout_discovery: full metadata/file bijection and zero-error inventory are required")

    data_lock = documents["data_lock"]
    official_archive = data_lock.get("official_archive", {})
    if not isinstance(official_archive, Mapping) or official_archive.get("sha256") != archive.get("archive_sha256"):
        errors.append("data_lock: official archive SHA256 does not match extraction receipt")
    manifests = data_lock.get("source_manifests", data_lock.get("manifests", {}))
    if not isinstance(manifests, Mapping):
        errors.append("data_lock: source_manifests must be a mapping")
        manifests = {}

    source_audit = documents["source_audit"]
    if (
        source_audit.get("stage") != "source"
        or source_audit.get("artifact_scan") != "none"
        or source_audit.get("errors") != []
        or source_audit.get("warnings") != []
        or source_audit.get("record_count") != 24800
        or source_audit.get("split_counts") != OFFICIAL_SPLIT_COUNTS
        or source_audit.get("split_seen_unseen_counts") != OFFICIAL_SPLIT_SEEN_UNSEEN_COUNTS
    ):
        errors.append("source_audit: exact official counts, seen/unseen matrix and zero issues are required")
    source_hashes = source_audit.get("source_manifest_sha256", {})
    source_bytes = source_audit.get("manifest_bytes", {})
    for split, expected_count in OFFICIAL_SPLIT_COUNTS.items():
        item = manifests.get(split, {}) if isinstance(manifests, Mapping) else {}
        if not isinstance(item, Mapping) or item.get("count") != expected_count:
            errors.append(f"data_lock: source_manifests.{split}.count must be {expected_count}")
            continue
        source_path_value = item.get("path")
        manifest_path = _resolve(root, str(source_path_value)) if source_path_value else None
        if manifest_path is None or not manifest_path.is_file():
            errors.append(f"source manifest is missing for {split}: {manifest_path}")
            continue
        actual_hash = sha256_file(manifest_path)
        if item.get("sha256") != actual_hash or source_hashes.get(split) != actual_hash:
            errors.append(f"source manifest SHA256 mismatch for {split}")
        if source_bytes.get(split) != manifest_path.stat().st_size:
            errors.append(f"source manifest byte count mismatch for {split}")

    archival_lock = documents["archival_lock"]
    expected_config_sha256 = canonical_experiment_config_sha256(config)
    if archival_lock.get("canonical_experiment_config_sha256") != expected_config_sha256:
        errors.append(
            "archival_lock: canonical experiment config SHA256 mismatch: "
            f"locked {archival_lock.get('canonical_experiment_config_sha256')!r}, "
            f"runtime {expected_config_sha256}"
        )
    facts = archival_lock.get("facts", {})
    accepted_fact_statuses = {"resolved"}
    if claim_level == "paper_specified_reconstruction":
        accepted_fact_statuses.add("approved_reconstruction_assumption")
    if not isinstance(facts, Mapping) or set(facts) != REQUIRED_ARCHIVAL_FACTS:
        observed = sorted(facts) if isinstance(facts, Mapping) else []
        errors.append(f"archival_lock: expected exactly nine facts, got {observed}")
    else:
        for fact_name, fact in facts.items():
            if not isinstance(fact, Mapping) or _status(fact) not in accepted_fact_statuses:
                errors.append(f"archival_lock: {fact_name} is not resolved/approved")
            elif not fact.get("evidence") or fact.get("selected_value", fact.get("value")) in (None, ""):
                errors.append(f"archival_lock: {fact_name} lacks selected value or evidence")
            elif _status(fact) == "approved_reconstruction_assumption" and fact.get("approved_by") != "user":
                errors.append(f"archival_lock: {fact_name} lacks explicit user approval")
            else:
                evidence_errors = _validate_archival_evidence(
                    fact_name,
                    fact.get("evidence"),
                    fact_status=_status(fact),
                    claim_level=claim_level,
                    project_root=project_root,
                )
                errors.extend(evidence_errors)
                errors.extend(
                    _validate_config_bindings(
                        f"archival_lock: {fact_name}",
                        fact.get("config_bindings"),
                        config,
                        required_paths=REQUIRED_ARCHIVAL_CONFIG_PATHS[fact_name],
                    )
                )
                bindings = fact.get("config_bindings")
                binding_map = {
                    str(item["path"]): item["value"]
                    for item in bindings
                    if isinstance(item, Mapping) and "path" in item and "value" in item
                } if isinstance(bindings, list) else {}
                if fact.get("selected_value", fact.get("value")) != binding_map:
                    errors.append(
                        f"archival_lock: {fact_name} selected_value must equal config binding map"
                    )

    teacher_lock = documents["teacher_lock"]
    teachers = teacher_lock.get("teachers", {})
    checkpoint_hashes: list[str] = []
    config_checkpoints = _checkpoint_config_entries(config, root)
    if not isinstance(teachers, Mapping):
        errors.append("teacher_lock: teachers must be a mapping")
        teachers = {}
    for teacher_name, expected_roles in EXPECTED_CHECKPOINT_ROLES.items():
        teacher = teachers.get(teacher_name, {})
        if not isinstance(teacher, Mapping) or _status(teacher) != "resolved":
            errors.append(f"teacher_lock: {teacher_name} must be resolved")
            continue
        repository = teacher.get("repository", teacher.get("repository_url"))
        commit = str(teacher.get("commit", teacher.get("repository_commit", "")))
        for identity_key, value in (
            ("repository", repository),
            ("commit", commit),
            ("imported_class", teacher.get("imported_class")),
            ("module", teacher.get("module", teacher.get("module_path"))),
            ("preprocessing", teacher.get("preprocessing", teacher.get("input_preprocessing"))),
            ("output_dim", teacher.get("output_dim")),
            ("determinism_tolerance", teacher.get("determinism_tolerance")),
        ):
            if value in (None, ""):
                errors.append(f"teacher_lock: {teacher_name}.{identity_key} is required")
        if teacher.get("working_tree_clean") is not True:
            errors.append(f"teacher_lock: {teacher_name}.working_tree_clean must be true")
        if len(commit) != 40:
            errors.append(f"teacher_lock: {teacher_name}.commit must be an exact 40-hex commit")
        checkpoint_files = teacher.get("checkpoint_files", [])
        if not isinstance(checkpoint_files, list):
            errors.append(f"teacher_lock: {teacher_name}.checkpoint_files must be a list")
            continue
        roles = [str(item.get("role", "")) for item in checkpoint_files if isinstance(item, Mapping)]
        if len(roles) != len(checkpoint_files) or len(roles) != len(set(roles)) or set(roles) != expected_roles:
            errors.append(
                f"teacher_lock: {teacher_name} checkpoint roles must be exactly "
                f"{sorted(expected_roles)} with no duplicates, got {roles}"
            )
        for checkpoint in checkpoint_files:
            if not isinstance(checkpoint, Mapping):
                errors.append(f"teacher_lock: malformed {teacher_name} checkpoint")
                continue
            role = str(checkpoint.get("role", ""))
            expected = config_checkpoints.get((teacher_name, role), {})
            path = expected.get("path")
            sha = str(checkpoint.get("sha256", ""))
            checkpoint_hashes.append(sha)
            if (
                not role
                or not checkpoint.get("source_url_or_archive")
                or not checkpoint.get("filename")
                or int(checkpoint.get("bytes") or 0) <= 0
                or not _is_sha256(sha)
                or not checkpoint.get("top_level_keys")
                or checkpoint.get("pretrained_or_finetuned") in (None, "")
            ):
                errors.append(f"teacher_lock: incomplete {teacher_name}/{role or '<missing>'} checkpoint identity")
                continue
            if path is None or not path.is_file():
                errors.append(f"teacher_lock: checkpoint file is missing for {teacher_name}/{role}: {path}")
                continue
            actual_sha = sha256_file(path)
            if path.name != checkpoint.get("filename") or path.stat().st_size != checkpoint.get("bytes"):
                errors.append(f"teacher_lock: checkpoint filename/bytes mismatch for {teacher_name}/{role}")
            if actual_sha != sha or expected.get("sha256") != sha:
                errors.append(f"teacher_lock: checkpoint SHA256 mismatch for {teacher_name}/{role}")

    real_smoke = teacher_lock.get("real_smoke", {})
    full_export = teacher_lock.get("full_export", {})
    if not isinstance(real_smoke, Mapping) or _status(real_smoke) != "passed":
        errors.append("teacher_lock: real_smoke must be passed")
    if not isinstance(full_export, Mapping) or _status(full_export) != "passed":
        errors.append("teacher_lock: full_export must be passed")
        full_export = {}
    elif full_export.get("records") != 24800 or full_export.get("errors") != 0:
        errors.append("teacher_lock: full_export must contain 24800 records and zero errors")
    cache_root_sha256 = str(full_export.get("cache_root_sha256", ""))
    if not _is_sha256(cache_root_sha256):
        errors.append("teacher_lock: full_export.cache_root_sha256 must be a SHA256")

    identity = documents["teacher_identity"]
    repeatability = documents["smoke_repeatability"]
    if identity.get("errors") != [] or _status(identity.get("smoke", {})) not in {"pass", "passed"}:
        errors.append("teacher_identity: real smoke must pass with zero errors")
    if _status(repeatability) != "pass" or repeatability.get("all_finite") is False:
        errors.append("smoke_repeatability: repeat-2 finite comparison must pass")

    preprocessing_lock = documents["preprocessing_lock"]
    if preprocessing_lock.get("mode") != "canonical_official_jpg_wav":
        errors.append("preprocessing_lock: mode must be canonical_official_jpg_wav")
    if preprocessing_lock.get("frame_policy") != "natural_sorted_no_repeat":
        errors.append("preprocessing_lock: frame policy must forbid silent repeats")
    if preprocessing_lock.get("canonical_visual_extension") != ".jpg":
        errors.append("preprocessing_lock: canonical visual extension must be .jpg")
    errors.extend(
        _validate_config_bindings(
            "preprocessing_lock",
            preprocessing_lock.get("config_bindings"),
            config,
            required_paths=REQUIRED_PREPROCESSING_CONFIG_PATHS,
        )
    )

    evaluator_lock = documents["evaluator_lock"]
    for identity_key in ("repository", "commit", "source"):
        if not evaluator_lock.get(identity_key):
            errors.append(f"evaluator_lock: {identity_key} is required")
    parity = evaluator_lock.get("parity", {})
    if not isinstance(parity, Mapping) or _status(parity) != "passed":
        errors.append("evaluator_lock: parity must be passed")
    else:
        for path_key, hash_key in (("fixture_path", "fixture_sha256"), ("receipt_path", "receipt_sha256")):
            parity_path = _resolve(project_root, str(parity.get(path_key, "")))
            if not parity_path.is_file() or sha256_file(parity_path) != parity.get(hash_key):
                errors.append(f"evaluator_lock: parity {path_key} bytes do not match the lock")
    for field in ("paper_f1_at_0_5_mapping", "validation_calibrated_f1_mapping"):
        mapping = evaluator_lock.get(field, {})
        if not isinstance(mapping, Mapping) or _status(mapping) != "resolved" or mapping.get("value") in (None, ""):
            errors.append(f"evaluator_lock: {field} must be resolved")
            continue
        expected_path = EVALUATOR_CONFIG_PATHS[field]
        if mapping.get("config_path") != expected_path:
            errors.append(f"evaluator_lock: {field}.config_path must be {expected_path}")
        actual = _get_config_value(config, expected_path)
        if actual is _MISSING or actual != mapping.get("value"):
            observed = "<missing>" if actual is _MISSING else repr(actual)
            errors.append(
                f"evaluator_lock: {field} config binding mismatch at {expected_path}: "
                f"locked {mapping.get('value')!r}, runtime {observed}"
            )

    audit = documents["exported_audit"]
    if (
        audit.get("stage") != "exported"
        or audit.get("artifact_scan") != "full"
        or audit.get("errors") != []
        or audit.get("warnings") != []
        or audit.get("record_count") != 24800
        or audit.get("split_counts") != OFFICIAL_SPLIT_COUNTS
        or audit.get("split_seen_unseen_counts") != OFFICIAL_SPLIT_SEEN_UNSEEN_COUNTS
    ):
        errors.append("exported_audit: full exact official audit with zero issues is required")
    if audit.get("cache_root_sha256") != cache_root_sha256:
        errors.append("exported_audit: cache root SHA256 does not match teacher lock")
    exported_hashes = audit.get("exported_manifest_sha256", {})
    exported_bytes = audit.get("manifest_bytes", {})
    for split in OFFICIAL_SPLIT_COUNTS:
        config_path_value = data.get(f"{split}_manifest") if isinstance(data, Mapping) else None
        exported_path = _resolve(root, str(config_path_value)) if config_path_value else None
        if exported_path is None or not exported_path.is_file():
            errors.append(f"exported manifest is missing for {split}: {exported_path}")
            continue
        actual_hash = sha256_file(exported_path)
        if not isinstance(exported_hashes, Mapping) or exported_hashes.get(split) != actual_hash:
            errors.append(f"exported manifest SHA256 mismatch for {split}")
        if not isinstance(exported_bytes, Mapping) or exported_bytes.get(split) != exported_path.stat().st_size:
            errors.append(f"exported manifest byte count mismatch for {split}")
        if full_export.get(f"{split}_manifest_sha256") != actual_hash:
            errors.append(f"teacher_lock: full_export {split} manifest SHA256 mismatch")
    audit_checkpoint_hashes = audit.get("teacher_checkpoint_sha256", [])
    if not isinstance(audit_checkpoint_hashes, list):
        errors.append("exported_audit: teacher_checkpoint_sha256 must be a list")
        audit_checkpoint_hashes = []
    if sorted(str(value) for value in audit_checkpoint_hashes) != sorted(checkpoint_hashes):
        errors.append("exported_audit: teacher checkpoint hashes do not match teacher lock")

    if require_real_preflight:
        preflight = documents["real_preflight"]
        if not (
            preflight.get("real_data") is True
            and preflight.get("optimizer_steps") == 1
            and preflight.get("invocation_count_this_stage") == 1
            and preflight.get("formal_metrics_emitted") is False
            and preflight.get("forward_completed") is True
            and preflight.get("backward_completed") is True
            and preflight.get("checkpoint_resume_completed") is True
            and preflight.get("losses_finite") is True
        ):
            errors.append("real_preflight: exactly one structural real-data step must pass without formal metrics")

    errors.extend(_validate_file_evidence(project_root, documents))
    try:
        git_dirty = _actual_git_dirty(project_root)
    except RuntimeError as exc:
        git_dirty = None
        errors.append(str(exc))
    if git_dirty is True:
        errors.append("canonical Git working tree must be clean")
    if errors:
        raise RuntimeError("Canonical readiness gate failed:\n- " + "\n- ".join(errors))

    return {
        "schema_version": 2,
        "status": "ready",
        "claim_level": claim_level,
        "official_counts": dict(sorted(OFFICIAL_SPLIT_COUNTS.items())),
        "official_split_seen_unseen_counts": OFFICIAL_SPLIT_SEEN_UNSEEN_COUNTS,
        "cache_root_sha256": cache_root_sha256,
        "canonical_experiment_config_sha256": expected_config_sha256,
        "checkpoint_sha256": sorted(checkpoint_hashes),
        "input_sha256": {name: sha256_file(path) for name, path in sorted(paths.items())},
        "git_dirty": git_dirty,
        "errors": [],
    }
