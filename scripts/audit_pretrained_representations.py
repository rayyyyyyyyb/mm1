"""Zero-training QP/VQP probes for independent visual/audio initialization."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import torch
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.audit_teacher_sampling import select_stratified_mixed_records  # noqa: E402
from src.utils.teacher_signal_probe import (  # noqa: E402
    build_common_space,
    build_interaction_design,
    fit_probe_and_score,
)


def _overlay(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(base))
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = _overlay(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _resolve_config_file(path: str | Path, stack: tuple[Path, ...] = ()) -> dict[str, Any]:
    """Resolve project-root-relative diagnostic wrappers and their overrides."""

    source = Path(path).resolve()
    if source in stack:
        raise ValueError("cyclic base_config chain: " + " -> ".join(str(item) for item in (*stack, source)))
    document = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise ValueError(f"config must be a mapping: {source}")
    current = copy.deepcopy(dict(document))
    diagnostic = current.get("diagnostic")
    base_ref = current.pop("base_config", None)
    if base_ref is None and isinstance(diagnostic, Mapping):
        diagnostic_copy = copy.deepcopy(dict(diagnostic))
        base_ref = diagnostic_copy.pop("base_config", None)
        current["diagnostic"] = diagnostic_copy
    if base_ref is not None:
        base_path = Path(str(base_ref))
        if not base_path.is_absolute():
            base_path = PROJECT_ROOT / base_path
        if not base_path.is_file():
            raise FileNotFoundError(f"config base is missing: {base_path}")
        base = _resolve_config_file(base_path, (*stack, source))
        overrides = current.pop("overrides", None)
        if overrides is not None:
            if not isinstance(overrides, Mapping):
                raise ValueError(f"config overrides must be a mapping: {source}")
            base = _overlay(base, overrides)
        current = _overlay(base, current)
    return current


def _load_probe_config(path: str | Path) -> dict[str, Any]:
    """Resolve the diagnostic wrapper over its locked full C2 base config."""

    source = Path(path).resolve()
    wrapper = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(wrapper, Mapping):
        raise ValueError("pretrained probe config must be a mapping")
    diagnostic = wrapper.get("diagnostic")
    if not isinstance(diagnostic, Mapping) or not diagnostic.get("base_config"):
        raise ValueError("pretrained probe config requires diagnostic.base_config")
    resolved = _resolve_config_file(source)
    student = resolved.get("student")
    if not isinstance(student, Mapping):
        raise ValueError("resolved pretrained probe config requires student settings")
    if student.get("visual_pretrained") is not True or student.get("audio_pretrained") is not False:
        raise ValueError("D2 zero-training probe requires visual_pretrained=true and audio_pretrained=false")
    if resolved.get("protocol", {}).get("zero_training_only") is not True:
        raise ValueError("D2 representation probe must remain zero-training-only")
    return resolved


def _load_records(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def _load_visual_encoder(model_name: str, pretrained: bool, checkpoint: str | Path | None, seed: int):
    from src.models.ov_orthkd import SequenceImageEncoder

    torch.manual_seed(int(seed))
    encoder = SequenceImageEncoder(model_name, pretrained=bool(pretrained))
    checkpoint_sha = None
    if checkpoint is not None:
        path = Path(checkpoint)
        payload = torch.load(path, map_location="cpu", weights_only=True)
        state = payload.get("student_state_dict") if isinstance(payload, Mapping) else None
        if not isinstance(state, Mapping):
            raise ValueError(f"{path}: checkpoint has no student_state_dict")
        visual_state = {
            key.removeprefix("visual_encoder."): value
            for key, value in state.items()
            if str(key).startswith("visual_encoder.")
        }
        if not visual_state:
            raise ValueError(f"{path}: checkpoint has no visual_encoder state")
        encoder.load_state_dict(visual_state, strict=True)
        checkpoint_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    encoder.eval()
    return encoder, checkpoint_sha


def _encode_split(loader, encoder, device: torch.device) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    features: list[np.ndarray] = []
    queries: list[np.ndarray] = []
    labels: list[np.ndarray] = []
    ids: list[str] = []
    with torch.inference_mode():
        for batch in loader:
            frame = batch["frame"].to(device)
            encoded = encoder(frame).detach().cpu().numpy().astype(np.float32)
            features.append(encoded)
            queries.append(batch["text_embedding"].cpu().numpy().astype(np.float32))
            labels.append(batch["segment_label"].cpu().numpy().astype(np.int64))
            ids.extend(str(value) for value in batch["id"])
    return np.concatenate(features), np.concatenate(queries), np.concatenate(labels), np.asarray(ids, dtype=str)


def _probe_pair(
    train_visual: np.ndarray,
    train_queries: np.ndarray,
    train_labels: np.ndarray,
    val_visual: np.ndarray,
    val_queries: np.ndarray,
    val_labels: np.ndarray,
    *,
    name: str,
    seed: int,
) -> dict[str, Any]:
    train_query = np.broadcast_to(train_queries[:, None, :], (train_queries.shape[0], 10, train_queries.shape[1])).copy()
    val_query = np.broadcast_to(val_queries[:, None, :], (val_queries.shape[0], 10, val_queries.shape[1])).copy()
    train_zero = np.zeros((train_visual.shape[0], 10, 1), dtype=np.float32)
    val_zero = np.zeros((val_visual.shape[0], 10, 1), dtype=np.float32)
    _, train_q, _ = build_common_space(train_zero, train_query, output_dim=128, seed=seed)
    _, val_q, _ = build_common_space(val_zero, val_query, output_dim=128, seed=seed)
    qp = fit_probe_and_score(
        build_interaction_design(np.zeros_like(train_q), train_q, mode="qp"),
        train_labels,
        build_interaction_design(np.zeros_like(val_q), val_q, mode="qp"),
        val_labels,
        np.ones_like(val_labels, dtype=bool),
        sample_ids=np.arange(val_labels.shape[0]).astype(str),
        query_ids=np.arange(val_labels.shape[0]).astype(str),
        offsets=np.arange(0, val_labels.shape[0] * 10 + 1, 10),
        seed=seed,
        shuffle_repeats=100,
    )
    train_v, train_q2, _ = build_common_space(train_visual, train_query, output_dim=128, seed=seed + 17)
    val_v, val_q2, _ = build_common_space(val_visual, val_query, output_dim=128, seed=seed + 17)
    vqp = fit_probe_and_score(
        build_interaction_design(train_v, train_q2, mode="interaction"),
        train_labels,
        build_interaction_design(val_v, val_q2, mode="interaction"),
        val_labels,
        np.ones_like(val_labels, dtype=bool),
        sample_ids=np.arange(val_labels.shape[0]).astype(str),
        query_ids=np.arange(val_labels.shape[0]).astype(str),
        offsets=np.arange(0, val_labels.shape[0] * 10 + 1, 10),
        seed=seed,
        shuffle_repeats=100,
    )
    return {
        "name": name,
        "qp": qp["metrics"],
        "vqp": vqp["metrics"],
        "visual_shape": list(val_visual.shape),
        "query_shape": list(val_queries.shape),
    }


def audit_zero_training_representations(
    config_path: str | Path,
    current_checkpoint: str | Path,
    *,
    output: str | Path,
    train_manifest: str | Path,
    validation_manifest: str | Path,
    sample_count: int = 512,
    seed: int = 42,
) -> dict[str, Any]:
    from scripts.train_ov_orthkd import create_ov_avel_data_loaders, set_seed

    config = _load_probe_config(config_path)
    set_seed(seed, deterministic=bool(config.get("training", {}).get("deterministic", True)))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    train_records = select_stratified_mixed_records(_load_records(train_manifest), sample_count, seed)
    val_records = select_stratified_mixed_records(_load_records(validation_manifest), sample_count, seed + 1)
    root = Path(output).parent / "pretrained_probe_subsets"
    root.mkdir(parents=True, exist_ok=True)
    train_path = root / "train.jsonl"
    val_path = root / "val.jsonl"
    train_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in train_records), encoding="utf-8")
    val_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in val_records), encoding="utf-8")
    local_config = copy.deepcopy(config)
    local_config["data"]["train_manifest"] = str(train_path)
    local_config["data"]["val_manifest"] = str(val_path)
    local_config["data"]["test_manifest"] = None
    local_config["data"]["batch_size"] = 8
    local_config["data"]["num_workers"] = 0
    local_config["data"]["train_augment"] = False
    train_loader, val_loader, _ = create_ov_avel_data_loaders(local_config)
    visual_name = str(config["student"]["visual_backbone"])
    audio_name = str(config["student"]["audio_backbone"])
    results: dict[str, Any] = {}
    try:
        random_encoder, _ = _load_visual_encoder(visual_name, False, None, seed)
        random_encoder.to(device)
        train_visual, train_query, train_labels, train_ids = _encode_split(train_loader, random_encoder, device)
        val_visual, val_query, val_labels, val_ids = _encode_split(val_loader, random_encoder, device)
        results["random_visual"] = _probe_pair(train_visual, train_query, train_labels, val_visual, val_query, val_labels, name="random_visual", seed=seed)
        del random_encoder
        pretrained_error = None
        try:
            pretrained_encoder, _ = _load_visual_encoder(visual_name, True, None, seed)
            pretrained_encoder.to(device)
            train_pre, _, _, _ = _encode_split(train_loader, pretrained_encoder, device)
            val_pre, _, _, _ = _encode_split(val_loader, pretrained_encoder, device)
            results["timm_pretrained_visual"] = _probe_pair(train_pre, train_query, train_labels, val_pre, val_query, val_labels, name="timm_pretrained_visual", seed=seed)
            del pretrained_encoder
        except Exception as exc:  # pragma: no cover - depends on remote asset/network state
            pretrained_error = f"{type(exc).__name__}: {exc}"
            results["timm_pretrained_visual"] = {"name": "timm_pretrained_visual", "status": "BLOCKED_BY_PRETRAINED_BACKBONE_ASSET", "error": pretrained_error}
        current_encoder, current_checkpoint_sha = _load_visual_encoder(visual_name, False, current_checkpoint, seed)
        current_encoder.to(device)
        train_current, _, _, _ = _encode_split(train_loader, current_encoder, device)
        val_current, _, _, _ = _encode_split(val_loader, current_encoder, device)
        results["current_c2_visual"] = _probe_pair(train_current, train_query, train_labels, val_current, val_query, val_labels, name="current_c2_visual", seed=seed)
        del current_encoder
        audio_encoder, _ = _load_visual_encoder(audio_name, False, None, seed)
        audio_encoder.to(device)
        train_audio, _, _, _ = _encode_split(
            ((batch | {"frame": batch["spectrogram"]}) for batch in train_loader), audio_encoder, device
        )
        val_audio, _, _, _ = _encode_split(
            ((batch | {"frame": batch["spectrogram"]}) for batch in val_loader), audio_encoder, device
        )
        results["random_audio_control"] = _probe_pair(train_audio, train_query, train_labels, val_audio, val_query, val_labels, name="random_audio_control", seed=seed)
    finally:
        for path in (train_path, val_path):
            path.unlink(missing_ok=True)
        try:
            root.rmdir()
        except OSError:
            pass
    random_mixed = results["random_visual"]["vqp"]["mixed"]["pair_weighted_concordance"]
    pretrained_mixed = results["timm_pretrained_visual"].get("vqp", {}).get("mixed", {}).get("pair_weighted_concordance")
    qp_mixed = results["random_visual"]["qp"]["mixed"]["pair_weighted_concordance"]
    gate = bool(
        random_mixed is not None
        and pretrained_mixed is not None
        and qp_mixed is not None
        and float(pretrained_mixed) >= float(random_mixed) + 0.05
        and float(pretrained_mixed) >= float(qp_mixed) + 0.02
    )
    result = {
        "schema_version": 1,
        "status": "PASS" if pretrained_error is None else "BLOCKED_BY_PRETRAINED_BACKBONE_ASSET",
        "scientific_status": (
            "D2_BLOCKED_BY_PRETRAINED_ASSET_NOT_TESTED"
            if pretrained_error is not None
            else "VISUAL_PRETRAINING_CONTROL_PASS"
            if gate
            else "VISUAL_PRETRAINING_CONTROL_FAIL"
        ),
        "protocol": {
            "task_segments": 10,
            "sample_count_per_split": sample_count,
            "seed": seed,
            "zero_training_only": True,
            "optimizer_constructed": False,
            "optimizer_step_executed": False,
            "checkpoint_written": False,
            "probe_gate": "timm_pretrained_vqp_mixed_concordance >= random_vqp + 0.05 and >= qp + 0.02",
        },
        "subset_ids_sha256": {
            "train": hashlib.sha256("\n".join(str(row.get("id", "")) for row in train_records).encode()).hexdigest(),
            "validation": hashlib.sha256("\n".join(str(row.get("id", "")) for row in val_records).encode()).hexdigest(),
        },
        "checkpoint_sha256": hashlib.sha256(Path(current_checkpoint).read_bytes()).hexdigest(),
        "backbones": {"visual": visual_name, "audio": audio_name},
        "probes": results,
        "gate": {
            "random_vqp_mixed_concordance": random_mixed,
            "timm_pretrained_vqp_mixed_concordance": pretrained_mixed,
            "qp_mixed_concordance": qp_mixed,
            "pass": gate,
        },
    }
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(_jsonable(result), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--train-manifest", type=Path, required=True)
    parser.add_argument("--validation-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample-count", type=int, default=512)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    result = audit_zero_training_representations(
        args.config,
        args.checkpoint,
        output=args.output,
        train_manifest=args.train_manifest,
        validation_manifest=args.validation_manifest,
        sample_count=args.sample_count,
        seed=args.seed,
    )
    print(json.dumps(_jsonable(result), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
