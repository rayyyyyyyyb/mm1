"""Audit D2 asset/load/parity readiness without running a scientific gate."""

from __future__ import annotations

import argparse
import copy
import json
import platform
import sys
from pathlib import Path
from typing import Any, Mapping

import torch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.audit_pretrained_representations import (  # noqa: E402
    _load_probe_config,
    _resolve_config_file,
)
from src.utils.locked_pretrained import (  # noqa: E402
    _sha256_file,
    _state_tensor_sha256,
    compare_nonvisual_initialization,
    load_locked_timm_encoder,
)


ALLOWED_STATUSES = {
    "D2_PROBE_READY_FOR_ZERO_TRAINING_GATE",
    "BLOCKED_BY_SAMPLE_ALIGNMENT",
    "BLOCKED_BY_ASSET_IDENTITY",
    "BLOCKED_BY_INITIALIZATION_PARITY",
    "BLOCKED_BY_TARGET_5090_ENVIRONMENT",
}


def _set_seed(seed: int) -> None:
    from scripts.train_ov_orthkd import set_seed

    set_seed(seed, deterministic=True)


def _build_model_and_loss(config: dict[str, Any], device: torch.device):
    from scripts.train_ov_orthkd import build_model_and_loss

    return build_model_and_loss(config, device)


def _combined_state(student: torch.nn.Module, loss_module: torch.nn.Module) -> dict[str, torch.Tensor]:
    state: dict[str, torch.Tensor] = {}
    for prefix, module in (("student.", student), ("loss.", loss_module)):
        for key, value in module.state_dict().items():
            state[prefix + str(key)] = value.detach().cpu().clone()
    return state


def _runtime_versions() -> dict[str, Any]:
    import safetensors
    import timm

    return {
        "python": platform.python_version(),
        "torch": str(torch.__version__),
        "timm": str(timm.__version__),
        "safetensors": str(safetensors.__version__),
        "cuda_available": bool(torch.cuda.is_available()),
        "cuda_runtime": str(torch.version.cuda),
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    }


def _write_result(path: Path, result: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(result), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def audit_d2_readiness(
    *,
    c2_config_path: str | Path,
    d2_config_path: str | Path,
    asset_lock_path: str | Path,
    asset_root: str | Path,
    output: str | Path,
    seed: int = 42,
    require_gpu_substring: str = "RTX 5090",
) -> dict[str, Any]:
    """Return a fail-closed readiness receipt; never fit a probe or optimizer."""

    output_path = Path(output).resolve()
    result: dict[str, Any] = {
        "schema_version": 1,
        "status": "BLOCKED_BY_TARGET_5090_ENVIRONMENT",
        "allowed_statuses": sorted(ALLOWED_STATUSES),
        "protocol": {
            "seed": int(seed),
            "zero_training_only": True,
            "scientific_gate_executed": False,
            "data_loader_constructed": False,
            "optimizer_constructed": False,
            "scheduler_constructed": False,
            "forward_executed": False,
            "backward_executed": False,
            "optimizer_step_executed": False,
            "checkpoint_written": False,
            "test_evaluation": False,
        },
    }
    try:
        versions = _runtime_versions()
        result["runtime"] = versions
        gpu_name = str(versions.get("gpu_name") or "")
        if require_gpu_substring and require_gpu_substring not in gpu_name:
            result["error"] = (
                f"target GPU must contain {require_gpu_substring!r}, got {gpu_name!r}"
            )
            _write_result(output_path, result)
            return result
        result["status"] = "BLOCKED_BY_ASSET_IDENTITY"
        input_paths = {
            "script": Path(__file__).resolve(),
            "c2_config": Path(c2_config_path).resolve(),
            "d2_config": Path(d2_config_path).resolve(),
            "asset_lock": Path(asset_lock_path).resolve(),
        }
        result["inputs"] = {
            name: {"path": str(path), "sha256": _sha256_file(path)}
            for name, path in input_paths.items()
        }

        d2_config = _load_probe_config(d2_config_path)
        c2_config = _resolve_config_file(c2_config_path)
        expected_lock = Path(str(d2_config["diagnostic"]["pretrained_asset_lock"]))
        supplied_lock = Path(asset_lock_path)
        if not expected_lock.is_absolute():
            expected_lock = PROJECT_ROOT / expected_lock
        if expected_lock.resolve() != supplied_lock.resolve():
            result.update(
                {
                    "status": "BLOCKED_BY_ASSET_IDENTITY",
                    "error": "D2 config asset lock does not match the supplied lock",
                }
            )
            _write_result(output_path, result)
            return result

        try:
            first_backbone, first_receipt = load_locked_timm_encoder(
                str(d2_config["student"]["visual_backbone"]),
                supplied_lock,
                asset_root=asset_root,
            )
            second_backbone, second_receipt = load_locked_timm_encoder(
                str(d2_config["student"]["visual_backbone"]),
                supplied_lock,
                asset_root=asset_root,
            )
        except Exception as exc:
            result.update(
                {
                    "status": "BLOCKED_BY_ASSET_IDENTITY",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            _write_result(output_path, result)
            return result
        repeat_fields = (
            "source_state_key_sha256",
            "source_state_tensor_sha256",
            "loaded_backbone_key_sha256",
            "loaded_backbone_tensor_sha256",
            "parameter_count",
            "feature_dim",
        )
        repeat_equal = all(first_receipt[key] == second_receipt[key] for key in repeat_fields)
        if not repeat_equal:
            result.update(
                {
                    "status": "BLOCKED_BY_ASSET_IDENTITY",
                    "error": "two offline loads produced different state receipts",
                    "locked_load_first": first_receipt,
                    "locked_load_second": second_receipt,
                }
            )
            _write_result(output_path, result)
            return result
        result["locked_load"] = {
            **first_receipt,
            "repeat_load_equal": True,
            "repeat_compared_fields": list(repeat_fields),
        }
        result["status"] = "BLOCKED_BY_INITIALIZATION_PARITY"

        device = torch.device("cpu")
        c2_initialization_config = copy.deepcopy(c2_config)
        c2_initialization_config["student"].pop("pretrained", None)
        c2_initialization_config["student"]["visual_pretrained"] = False
        c2_initialization_config["student"]["audio_pretrained"] = False
        _set_seed(int(seed))
        c2_student, c2_loss = _build_model_and_loss(c2_initialization_config, device)
        reference_state = _combined_state(c2_student, c2_loss)
        reference_visual_sha = _state_tensor_sha256(
            {
                key: value
                for key, value in reference_state.items()
                if key.startswith("student.visual_encoder.")
            }
        )
        del c2_student, c2_loss

        # Build D2 with the same random-construction path first.  Only after
        # every non-visual parameter exists do we replace the visual backbone
        # with the verified locked state.  This makes the parity claim
        # directly testable and prevents pretrained loading from changing RNG
        # consumption for the audio/fusion/temporal/loss parameters.
        d2_initialization_config = copy.deepcopy(d2_config)
        d2_initialization_config["student"].pop("pretrained", None)
        d2_initialization_config["student"]["visual_pretrained"] = False
        d2_initialization_config["student"]["audio_pretrained"] = False
        _set_seed(int(seed))
        d2_student, d2_loss = _build_model_and_loss(d2_initialization_config, device)
        d2_student.visual_encoder.backbone.load_state_dict(
            first_backbone.state_dict(), strict=True
        )
        d2_student.visual_pretrained = True
        candidate_state = _combined_state(d2_student, d2_loss)
        candidate_visual_sha = _state_tensor_sha256(
            {
                key: value
                for key, value in candidate_state.items()
                if key.startswith("student.visual_encoder.")
            }
        )
        try:
            parity = compare_nonvisual_initialization(
                reference_state,
                candidate_state,
                excluded_prefix="student.visual_encoder.",
            )
        except Exception as exc:
            result.update(
                {
                    "status": "BLOCKED_BY_INITIALIZATION_PARITY",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            _write_result(output_path, result)
            return result
        if reference_visual_sha == candidate_visual_sha:
            result.update(
                {
                    "status": "BLOCKED_BY_INITIALIZATION_PARITY",
                    "error": "locked visual state unexpectedly equals random C2 visual state",
                }
            )
            _write_result(output_path, result)
            return result
        parity.update(
            {
                "construction": "same_seed_random_model_then_locked_visual_state_replace",
                "reference_visual_sha256": reference_visual_sha,
                "candidate_visual_sha256": candidate_visual_sha,
                "visual_state_changed": True,
            }
        )
        result["initialization_parity"] = parity
        result["status"] = "D2_PROBE_READY_FOR_ZERO_TRAINING_GATE"
        _write_result(output_path, result)
        return result
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        _write_result(output_path, result)
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--c2-config", type=Path, required=True)
    parser.add_argument("--d2-config", type=Path, required=True)
    parser.add_argument("--asset-lock", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--require-gpu-substring", default="RTX 5090")
    args = parser.parse_args()
    result = audit_d2_readiness(
        c2_config_path=args.c2_config,
        d2_config_path=args.d2_config,
        asset_lock_path=args.asset_lock,
        asset_root=args.asset_root,
        output=args.output,
        seed=args.seed,
        require_gpu_substring=args.require_gpu_substring,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "D2_PROBE_READY_FOR_ZERO_TRAINING_GATE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
