"""Fail-closed loading and fingerprinting of a locked timm checkpoint."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import yaml
import torch


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _state_key_sha256(state: Mapping[str, Any]) -> str:
    payload = "\n".join(sorted(str(key) for key in state))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _state_tensor_sha256(state: Mapping[str, Any]) -> str:
    """Hash tensor metadata and bytes in deterministic key order."""

    digest = hashlib.sha256()
    for key in sorted(state, key=str):
        value = state[key]
        if not hasattr(value, "detach"):
            raise TypeError(f"state entry {key!r} is not a tensor")
        tensor = value.detach().cpu().contiguous()
        digest.update(str(key).encode("utf-8"))
        digest.update(str(tensor.dtype).encode("ascii"))
        digest.update(json.dumps(list(tensor.shape), separators=(",", ":")).encode("ascii"))
        digest.update(tensor.view(torch.uint8).numpy().tobytes(order="C"))
    return digest.hexdigest()


def load_asset_lock(lock_path: str | Path) -> dict[str, Any]:
    path = Path(lock_path).resolve()
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise ValueError(f"asset lock must be a mapping: {path}")
    model = document.get("model")
    files = model.get("files") if isinstance(model, Mapping) else None
    if not isinstance(model, Mapping) or not isinstance(files, Mapping):
        raise ValueError("asset lock requires model and model.files mappings")
    model_id = str(model.get("id", "")).strip()
    revision = str(model.get("revision", "")).strip()
    if not model_id or not revision:
        raise ValueError("asset lock requires non-empty model.id and model.revision")
    for filename in ("config.json", "model.safetensors"):
        entry = files.get(filename)
        if not isinstance(entry, Mapping):
            raise ValueError(f"asset lock is missing model.files.{filename}")
        if int(entry.get("size_bytes", -1)) <= 0 or len(str(entry.get("sha256", ""))) != 64:
            raise ValueError(f"asset lock has invalid size or sha256 for {filename}")
    return dict(document)


def resolve_locked_asset(
    lock_path: str | Path,
    asset_root: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Path]]:
    """Resolve and byte-verify the exact files named by a lock."""

    lock_file = Path(lock_path).resolve()
    lock = load_asset_lock(lock_file)
    if asset_root is None:
        local_directory = lock.get("local_receipt", {}).get("directory")
        if not isinstance(local_directory, str) or not local_directory:
            raise ValueError("asset_root is required when local_receipt.directory is absent")
        project_root = lock_file.parents[3] if len(lock_file.parents) >= 4 else lock_file.parent
        root = Path(local_directory)
        if not root.is_absolute():
            root = project_root / root
    else:
        root = Path(asset_root).expanduser().resolve()
    files = lock["model"]["files"]
    resolved: dict[str, Path] = {}
    for filename in ("config.json", "model.safetensors"):
        path = root / filename
        entry = files[filename]
        if not path.is_file():
            raise FileNotFoundError(f"locked asset file is missing: {path}")
        expected_size = int(entry["size_bytes"])
        actual_size = path.stat().st_size
        if actual_size != expected_size:
            raise ValueError(f"{path}: size {actual_size} != locked {expected_size}")
        actual_sha = _sha256_file(path)
        if actual_sha != str(entry["sha256"]):
            raise ValueError(f"{path}: sha256 {actual_sha} != locked {entry['sha256']}")
        resolved[filename] = path
    return lock, resolved


def load_locked_timm_encoder(
    model_name: str,
    lock_path: str | Path,
    *,
    asset_root: str | Path | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Construct a timm encoder without network access and load the locked state."""

    lock, files = resolve_locked_asset(lock_path, asset_root)
    locked_id = str(lock["model"]["id"])
    expected_name = locked_id.removeprefix("timm/")
    if str(model_name) != expected_name:
        raise ValueError(f"model name {model_name!r} does not match locked id {locked_id!r}")

    import timm
    from safetensors.torch import load_file

    # Explicitly disable timm's pretrained lookup.  The only weights entering
    # the model are the bytes verified above.
    backbone = timm.create_model(
        str(model_name), pretrained=False, num_classes=0, global_pool="avg"
    )
    source_state = load_file(str(files["model.safetensors"]), device="cpu")
    target_state = backbone.state_dict()
    missing_source = sorted(set(target_state) - set(source_state))
    unexpected_source = sorted(set(source_state) - set(target_state))
    allowed_unexpected = [key for key in unexpected_source if str(key).startswith("head.")]
    if missing_source or set(unexpected_source) != set(allowed_unexpected):
        raise ValueError(
            "locked timm state keys do not match model: "
            f"missing={missing_source}, unexpected={unexpected_source}"
        )
    load_result = backbone.load_state_dict(source_state, strict=False)
    if load_result.missing_keys or set(load_result.unexpected_keys) != set(allowed_unexpected):
        raise ValueError(
            "locked timm state load was not exact: "
            f"missing={load_result.missing_keys}, unexpected={load_result.unexpected_keys}"
        )
    receipt = {
        "model_id": locked_id,
        "revision": str(lock["model"]["revision"]),
        "config_path": str(files["config.json"]),
        "weights_path": str(files["model.safetensors"]),
        "weights_sha256": _sha256_file(files["model.safetensors"]),
        "source_state_key_sha256": _state_key_sha256(source_state),
        "source_state_tensor_sha256": _state_tensor_sha256(source_state),
        "loaded_backbone_key_sha256": _state_key_sha256(target_state),
        "loaded_backbone_tensor_sha256": _state_tensor_sha256(target_state),
        "missing_keys": list(load_result.missing_keys),
        "unexpected_head_keys": sorted(allowed_unexpected),
        "parameter_count": int(sum(parameter.numel() for parameter in backbone.parameters())),
        "feature_dim": int(getattr(backbone, "num_features", 0)),
        "pretrained_lookup_disabled": True,
        "offline_only": True,
    }
    return backbone, receipt


def compare_nonvisual_initialization(
    reference_state: Mapping[str, Any],
    candidate_state: Mapping[str, Any],
    *,
    excluded_prefix: str = "visual_encoder.",
) -> dict[str, Any]:
    """Check bitwise equality of all parameters outside the visual encoder."""

    reference_keys = {str(key) for key in reference_state if not str(key).startswith(excluded_prefix)}
    candidate_keys = {str(key) for key in candidate_state if not str(key).startswith(excluded_prefix)}
    if reference_keys != candidate_keys:
        raise ValueError(
            "non-visual initialization key mismatch: "
            f"missing={sorted(reference_keys - candidate_keys)}, "
            f"extra={sorted(candidate_keys - reference_keys)}"
        )
    differing: list[str] = []
    for key in sorted(reference_keys):
        left = reference_state[key]
        right = candidate_state[key]
        if getattr(left, "shape", None) != getattr(right, "shape", None) or not bool(
            (left.detach().cpu() == right.detach().cpu()).all()
        ):
            differing.append(key)
    if differing:
        raise ValueError(f"non-visual initialization differs at {differing}")
    return {
        "pass": True,
        "excluded_prefix": excluded_prefix,
        "compared_key_count": len(reference_keys),
        "reference_nonvisual_sha256": _state_tensor_sha256(
            {key: reference_state[key] for key in sorted(reference_keys)}
        ),
        "candidate_nonvisual_sha256": _state_tensor_sha256(
            {key: candidate_state[key] for key in sorted(candidate_keys)}
        ),
    }
