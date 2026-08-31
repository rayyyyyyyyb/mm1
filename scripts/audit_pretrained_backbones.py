#!/usr/bin/env python3

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

import torch
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


EncoderFactory = Callable[..., torch.nn.Module]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def state_dict_sha256(state_dict: Mapping[str, torch.Tensor]) -> str:
    digest = hashlib.sha256()
    for name, tensor in sorted(state_dict.items()):
        if not isinstance(tensor, torch.Tensor):
            raise TypeError(f"State entry {name} is not a tensor")
        contiguous = tensor.detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(contiguous.dtype).encode("ascii"))
        digest.update(json.dumps(list(contiguous.shape)).encode("ascii"))
        digest.update(
            contiguous.reshape(-1).view(torch.uint8).numpy().tobytes(order="C")
        )
    return digest.hexdigest()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _default_encoder_factory() -> EncoderFactory:
    from src.models.ov_orthkd import SequenceImageEncoder

    return SequenceImageEncoder


def _construct_and_receipt(
    model_name: str,
    *,
    pretrained: bool,
    seed: int,
    encoder_factory: EncoderFactory,
) -> dict[str, Any]:
    torch.manual_seed(int(seed))
    encoder = encoder_factory(model_name, pretrained=pretrained)
    backbone = getattr(encoder, "backbone", None)
    if not isinstance(backbone, torch.nn.Module):
        raise TypeError("Encoder factory did not return an object with a backbone module")
    feature_dim = getattr(encoder, "feature_dim", None)
    if feature_dim is None:
        raise ValueError("Encoder did not expose feature_dim")
    receipt = {
        "requested_pretrained": bool(pretrained),
        "state_sha256": state_dict_sha256(backbone.state_dict()),
        "parameter_count": int(sum(parameter.numel() for parameter in backbone.parameters())),
        "feature_dim": int(feature_dim),
        "resolved_pretrained_cfg": _json_safe(
            getattr(backbone, "pretrained_cfg", {})
        ),
    }
    del backbone
    del encoder
    gc.collect()
    return receipt


def audit_backbone_initialization(
    model_name: str,
    *,
    seed: int,
    encoder_factory: EncoderFactory | None = None,
) -> dict[str, Any]:
    if not isinstance(model_name, str) or not model_name.strip():
        raise ValueError("model_name must be non-empty")
    factory = encoder_factory or _default_encoder_factory()
    pretrained = _construct_and_receipt(
        model_name,
        pretrained=True,
        seed=seed,
        encoder_factory=factory,
    )
    random_reference = _construct_and_receipt(
        model_name,
        pretrained=False,
        seed=seed,
        encoder_factory=factory,
    )
    if pretrained["state_sha256"] == random_reference["state_sha256"]:
        raise RuntimeError(
            f"Pretrained and random state hashes are identical for {model_name}"
        )
    if pretrained["parameter_count"] != random_reference["parameter_count"]:
        raise RuntimeError(
            f"Pretrained and random parameter counts differ for {model_name}"
        )
    if pretrained["feature_dim"] != random_reference["feature_dim"]:
        raise RuntimeError(
            f"Pretrained and random feature dimensions differ for {model_name}"
        )
    return {
        "status": "PASS",
        "model_name": model_name,
        "seed": int(seed),
        "pretrained_requested": True,
        "random_reference_requested": False,
        "pretrained_state_sha256": pretrained["state_sha256"],
        "random_state_sha256": random_reference["state_sha256"],
        "state_hashes_differ": True,
        "parameter_count": pretrained["parameter_count"],
        "feature_dim": pretrained["feature_dim"],
        "resolved_pretrained_cfg": pretrained["resolved_pretrained_cfg"],
        "random_reference_pretrained_cfg": random_reference[
            "resolved_pretrained_cfg"
        ],
    }


def build_pretrained_backbone_report(
    config_path: str | Path,
    *,
    encoder_factory: EncoderFactory | None = None,
) -> dict[str, Any]:
    source = Path(config_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    config = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Config must be a mapping")
    student = config.get("student")
    if not isinstance(student, dict):
        raise ValueError("Config is missing student mapping")
    if student.get("pretrained") is not True:
        raise ValueError("Pretrained receipt requires student.pretrained=true")
    seed = int(config.get("seed", 42))
    model_names = {
        "visual": student.get("visual_backbone"),
        "audio": student.get("audio_backbone"),
    }
    if not all(isinstance(value, str) and value.strip() for value in model_names.values()):
        raise ValueError("Config must declare non-empty visual/audio backbone names")
    return {
        "schema_version": 1,
        "status": "PASS",
        "claim_level": "runtime_construction_receipt_not_archival_fact",
        "config": {
            "path": str(source),
            "bytes": source.stat().st_size,
            "sha256": _sha256(source),
        },
        "seed": seed,
        "comparison": (
            "same_seed_pretrained_true_vs_pretrained_false_constructed_encoder_state"
        ),
        "fallback_policy": "construction_or_download_failure_propagates_and_blocks",
        "backbones": {
            role: audit_backbone_initialization(
                str(model_name),
                seed=seed,
                encoder_factory=encoder_factory,
            )
            for role, model_name in model_names.items()
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Receipt actual pretrained and same-seed random backbone construction"
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_pretrained_backbone_report(args.config)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
