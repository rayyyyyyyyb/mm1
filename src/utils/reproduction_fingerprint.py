from __future__ import annotations

import copy
import hashlib
import json
import random
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import torch


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_value(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _resolved_file(path_value: str | Path, path_root: Path) -> Path:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = path_root / path
    return path.resolve()


def _file_component(path: Path) -> dict[str, Any]:
    exists = path.is_file()
    return {
        "path": path.as_posix(),
        "exists": exists,
        "bytes": path.stat().st_size if exists else None,
        "sha256": sha256_file(path) if exists else None,
    }


def build_reproduction_fingerprint(
    config: Mapping[str, Any],
    *,
    lock_paths: Mapping[str, str | Path] | None = None,
) -> dict[str, Any]:
    normalized_config = copy.deepcopy(dict(config))
    logging_cfg = normalized_config.get("logging")
    if isinstance(logging_cfg, dict):
        logging_cfg.pop("log_dir", None)

    data_cfg = dict(config.get("data", {}))
    path_root = Path(data_cfg.get("path_root", ".")).expanduser().resolve()
    manifests: dict[str, Any] = {}
    for split in ("train", "val", "test"):
        value = data_cfg.get(f"{split}_manifest")
        if value:
            manifests[split] = _file_component(_resolved_file(value, path_root))

    locks: dict[str, Any] = {}
    for name, value in sorted((lock_paths or {}).items()):
        locks[str(name)] = _file_component(_resolved_file(value, path_root))

    components = {
        "config_sha256": _sha256_value(normalized_config),
        "manifests": manifests,
        "locks": locks,
    }
    return {
        "schema_version": 1,
        "sha256": _sha256_value(components),
        "components": components,
    }


def capture_rng_state(
    loader_generators: Mapping[str, torch.Generator] | None = None,
) -> dict[str, Any]:
    numpy_state = np.random.get_state()
    return {
        "python": random.getstate(),
        "numpy": {
            "bit_generator": numpy_state[0],
            "state": numpy_state[1].tolist(),
            "position": int(numpy_state[2]),
            "has_gauss": int(numpy_state[3]),
            "cached_gaussian": float(numpy_state[4]),
        },
        "torch_cpu": torch.get_rng_state(),
        "torch_cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else [],
        "loader_generators": {
            str(name): generator.get_state()
            for name, generator in sorted((loader_generators or {}).items())
        },
    }


def restore_rng_state(
    state: Mapping[str, Any],
    loader_generators: Mapping[str, torch.Generator] | None = None,
) -> None:
    random.setstate(state["python"])
    numpy_state = state["numpy"]
    np.random.set_state(
        (
            str(numpy_state["bit_generator"]),
            np.asarray(numpy_state["state"], dtype=np.uint32),
            int(numpy_state["position"]),
            int(numpy_state["has_gauss"]),
            float(numpy_state["cached_gaussian"]),
        )
    )
    torch.set_rng_state(state["torch_cpu"])
    cuda_states = list(state.get("torch_cuda", []))
    if cuda_states:
        if not torch.cuda.is_available():
            raise RuntimeError("Checkpoint contains CUDA RNG state but CUDA is unavailable")
        if len(cuda_states) != torch.cuda.device_count():
            raise RuntimeError(
                "Checkpoint CUDA RNG device count does not match the current runtime"
            )
        torch.cuda.set_rng_state_all(cuda_states)

    current_generators = dict(loader_generators or {})
    saved_generators = dict(state.get("loader_generators", {}))
    missing = sorted(set(saved_generators) - set(current_generators))
    if missing:
        raise RuntimeError(f"Missing DataLoader generators required by checkpoint: {missing}")
    for name, generator_state in saved_generators.items():
        current_generators[name].set_state(generator_state)
