"""Zero-training QP/VQP probes for independent visual/audio initialization."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import torch
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.audit_teacher_sampling import select_stratified_mixed_records  # noqa: E402
from src.utils.teacher_signal_probe import (  # noqa: E402
    apply_common_space_maps,
    build_common_space_maps,
    build_interaction_design,
    fit_probe_and_score,
)
from src.utils.locked_pretrained import load_locked_timm_encoder  # noqa: E402


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
    protocol = resolved.get("protocol")
    if not isinstance(protocol, Mapping) or protocol.get("zero_training_only") is not True:
        raise ValueError("D2 representation probe must remain zero-training-only")
    diagnostic_resolved = resolved.get("diagnostic")
    lock_ref = diagnostic_resolved.get("pretrained_asset_lock") if isinstance(diagnostic_resolved, Mapping) else None
    if not isinstance(lock_ref, str) or not lock_ref:
        raise ValueError("D2 representation probe requires diagnostic.pretrained_asset_lock")
    lock_path = Path(lock_ref)
    if not lock_path.is_absolute():
        lock_path = PROJECT_ROOT / lock_path
    if not lock_path.is_file():
        raise FileNotFoundError(f"D2 pretrained asset lock is missing: {lock_path}")
    return resolved


def _load_records(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def _sha256_array(value: np.ndarray) -> str:
    array = np.ascontiguousarray(np.asarray(value))
    digest = hashlib.sha256()
    digest.update(str(array.dtype).encode("ascii"))
    digest.update(json.dumps(list(array.shape)).encode("ascii"))
    digest.update(array.tobytes(order="C"))
    return digest.hexdigest()


def _sha256_strings(values: Sequence[str]) -> str:
    return hashlib.sha256("\n".join(str(value) for value in values).encode("utf-8")).hexdigest()


def _sha256_indices(values: Sequence[Sequence[int]]) -> str:
    payload = json.dumps(
        [[int(index) for index in row] for row in values],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_encoded_split(split: Mapping[str, Any], name: str) -> None:
    required = {
        "features",
        "queries",
        "labels",
        "sequence_masks",
        "ids",
        "query_ids",
        "selected_segment_indices",
    }
    missing = sorted(required - set(split))
    if missing:
        raise ValueError(f"{name} encoded split is missing fields: {missing}")
    ids = [str(value) for value in split["ids"]]
    if len(ids) != len(set(ids)):
        duplicates = sorted({value for value in ids if ids.count(value) > 1})
        raise ValueError(f"{name} encoded split has duplicate sample IDs: {duplicates}")
    size = len(ids)
    for field in ("queries", "labels", "sequence_masks", "query_ids", "selected_segment_indices"):
        if len(split[field]) != size:
            raise ValueError(f"{name} field {field} has {len(split[field])} rows, expected {size}")
    features = np.asarray(split["features"])
    if features.ndim != 3 or features.shape[0] != size:
        raise ValueError(f"{name} features must have shape [N,T,D], got {features.shape}")


def _alignment_receipt(split: Mapping[str, Any], *, pre_alignment_ids: Sequence[str]) -> dict[str, Any]:
    return {
        "pre_alignment_id_hash": _sha256_strings(pre_alignment_ids),
        "canonical_post_alignment_id_hash": _sha256_strings(split["ids"]),
        "label_hash": _sha256_array(np.asarray(split["labels"])),
        "query_string_hash": _sha256_strings(split["query_ids"]),
        "query_embedding_hash": _sha256_array(np.asarray(split["queries"])),
        "sequence_mask_hash": _sha256_array(np.asarray(split["sequence_masks"])),
        "selected_segment_indices_hash": _sha256_indices(split["selected_segment_indices"]),
    }


def _align_encoded_split(
    reference: Mapping[str, Any], candidate: Mapping[str, Any], *, pass_name: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Align an encoder pass by real sample ID and verify all non-feature fields."""

    _validate_encoded_split(reference, "reference")
    _validate_encoded_split(candidate, pass_name)
    reference_ids = [str(value) for value in reference["ids"]]
    candidate_ids = [str(value) for value in candidate["ids"]]
    if set(reference_ids) != set(candidate_ids):
        missing = sorted(set(reference_ids) - set(candidate_ids))
        extra = sorted(set(candidate_ids) - set(reference_ids))
        raise ValueError(f"{pass_name} sample ID set mismatch: missing={missing}, extra={extra}")
    candidate_index = {sample_id: index for index, sample_id in enumerate(candidate_ids)}
    order = [candidate_index[sample_id] for sample_id in reference_ids]
    aligned = {
        "features": np.asarray(candidate["features"])[order].copy(),
        "queries": np.asarray(candidate["queries"])[order].copy(),
        "labels": np.asarray(candidate["labels"])[order].copy(),
        "sequence_masks": np.asarray(candidate["sequence_masks"])[order].copy(),
        "ids": list(reference_ids),
        "query_ids": [str(candidate["query_ids"][index]) for index in order],
        "selected_segment_indices": [
            [int(value) for value in candidate["selected_segment_indices"][index]]
            for index in order
        ],
    }
    for field in ("labels", "sequence_masks", "queries"):
        if not np.array_equal(np.asarray(aligned[field]), np.asarray(reference[field])):
            raise ValueError(f"{pass_name} {field} mismatch for aligned sample IDs")
    if aligned["query_ids"] != [str(value) for value in reference["query_ids"]]:
        raise ValueError(f"{pass_name} query string mismatch for aligned sample IDs")
    if aligned["selected_segment_indices"] != [
        [int(value) for value in row] for row in reference["selected_segment_indices"]
    ]:
        raise ValueError(f"{pass_name} selected segment indices mismatch for aligned sample IDs")
    return aligned, _alignment_receipt(aligned, pre_alignment_ids=candidate_ids)


def _load_visual_encoder(
    model_name: str,
    pretrained: bool,
    checkpoint: str | Path | None,
    seed: int,
    *,
    pretrained_asset_lock: str | Path | None = None,
    pretrained_asset_root: str | Path | None = None,
):
    from src.models.ov_orthkd import SequenceImageEncoder

    torch.manual_seed(int(seed))
    asset_receipt = None
    if pretrained:
        if pretrained_asset_lock is None:
            raise ValueError("pretrained visual encoder requires an exact asset lock")
        backbone, asset_receipt = load_locked_timm_encoder(
            model_name,
            pretrained_asset_lock,
            asset_root=pretrained_asset_root,
        )
        encoder = SequenceImageEncoder(model_name, pretrained=False)
        encoder.backbone.load_state_dict(backbone.state_dict(), strict=True)
    else:
        encoder = SequenceImageEncoder(model_name, pretrained=False)
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
    return encoder, checkpoint_sha, asset_receipt


def _encode_split(loader, encoder, device: torch.device) -> dict[str, Any]:
    features: list[np.ndarray] = []
    queries: list[np.ndarray] = []
    labels: list[np.ndarray] = []
    sequence_masks: list[np.ndarray] = []
    ids: list[str] = []
    query_ids: list[str] = []
    selected_segment_indices: list[list[int]] = []
    with torch.inference_mode():
        for batch in loader:
            frame = batch["frame"].to(device)
            encoded = encoder(frame).detach().cpu().numpy().astype(np.float32)
            features.append(encoded)
            queries.append(batch["text_embedding"].cpu().numpy().astype(np.float32))
            labels.append(batch["segment_label"].cpu().numpy().astype(np.int64))
            sequence_masks.append(batch["sequence_mask"].cpu().numpy().astype(np.float32))
            ids.extend(str(value) for value in batch["id"])
            query_ids.extend(str(value) for value in batch["query"])
            selected_segment_indices.extend(
                [[int(index) for index in row] for row in batch["selected_segment_indices"]]
            )
    split = {
        "features": np.concatenate(features),
        "queries": np.concatenate(queries),
        "labels": np.concatenate(labels),
        "sequence_masks": np.concatenate(sequence_masks),
        "ids": ids,
        "query_ids": query_ids,
        "selected_segment_indices": selected_segment_indices,
    }
    _validate_encoded_split(split, "encoded")
    return split


def _probe_pair(
    train_visual: np.ndarray,
    train_split: Mapping[str, Any],
    val_visual: np.ndarray,
    val_split: Mapping[str, Any],
    *,
    name: str,
    seed: int,
    maps: Mapping[str, Any],
    maps_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    train_queries = np.asarray(train_split["queries"], dtype=np.float32)
    val_queries = np.asarray(val_split["queries"], dtype=np.float32)
    train_labels = np.asarray(train_split["labels"], dtype=np.int64)
    val_labels = np.asarray(val_split["labels"], dtype=np.int64)
    train_mask = np.asarray(train_split["sequence_masks"]).astype(bool)
    val_mask = np.asarray(val_split["sequence_masks"]).astype(bool)
    train_query = np.broadcast_to(
        train_queries[:, None, :],
        (train_queries.shape[0], train_visual.shape[1], train_queries.shape[1]),
    ).copy()
    val_query = np.broadcast_to(
        val_queries[:, None, :],
        (val_queries.shape[0], val_visual.shape[1], val_queries.shape[1]),
    ).copy()
    train_v, train_q = apply_common_space_maps(train_visual, train_query, maps)
    val_v, val_q = apply_common_space_maps(val_visual, val_query, maps)
    train_zero = np.zeros_like(train_v)
    val_zero = np.zeros_like(val_v)
    train_valid = train_mask.reshape(-1)
    train_labels_flat = train_labels.reshape(-1)
    def offsets_for(mask: np.ndarray) -> np.ndarray:
        return np.concatenate(([0], np.cumsum(mask.sum(axis=1), dtype=np.int64)))

    train_qp_design = build_interaction_design(train_zero, train_q, mode="qp")
    val_qp_design = build_interaction_design(val_zero, val_q, mode="qp")
    qp = fit_probe_and_score(
        train_qp_design.reshape(-1, train_qp_design.shape[-1])[train_valid],
        train_labels_flat[train_valid],
        val_qp_design,
        val_labels,
        val_mask,
        sample_ids=np.asarray(val_split["ids"], dtype=str),
        query_ids=np.asarray(val_split["query_ids"], dtype=str),
        offsets=offsets_for(val_mask),
        seed=seed,
        shuffle_repeats=100,
    )
    train_vqp_design = build_interaction_design(train_v, train_q, mode="interaction")
    val_vqp_design = build_interaction_design(val_v, val_q, mode="interaction")
    vqp = fit_probe_and_score(
        train_vqp_design.reshape(-1, train_vqp_design.shape[-1])[train_valid],
        train_labels_flat[train_valid],
        val_vqp_design,
        val_labels,
        val_mask,
        sample_ids=np.asarray(val_split["ids"], dtype=str),
        query_ids=np.asarray(val_split["query_ids"], dtype=str),
        offsets=offsets_for(val_mask),
        seed=seed,
        shuffle_repeats=100,
    )
    validation_query_ids = [str(value) for value in val_split["query_ids"]]
    query_counts = dict(sorted(Counter(validation_query_ids).items()))
    return {
        "name": name,
        "qp": qp["metrics"],
        "vqp": vqp["metrics"],
        "visual_shape": list(val_visual.shape),
        "query_shape": list(val_queries.shape),
        "alignment": {
            "train_id_hash": _sha256_strings(train_split["ids"]),
            "validation_id_hash": _sha256_strings(val_split["ids"]),
            "train_query_id_hash": _sha256_strings(train_split["query_ids"]),
            "validation_query_id_hash": _sha256_strings(val_split["query_ids"]),
        },
        "projection_maps": dict(maps_receipt),
        "macro_grouping": {
            "source": "batch.query",
            "validation_sample_count": len(validation_query_ids),
            "unique_query_count": len(query_counts),
            "validation_query_counts": query_counts,
            "validation_query_ids_sha256": _sha256_strings(validation_query_ids),
            "qp_query_ids_sha256": qp["query_ids_sha256"],
            "vqp_query_ids_sha256": vqp["query_ids_sha256"],
            "validation_sample_ids_sha256": _sha256_strings(val_split["ids"]),
            "qp_sample_ids_sha256": qp["sample_ids_sha256"],
            "vqp_sample_ids_sha256": vqp["sample_ids_sha256"],
        },
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
    diagnostic_config = config.get("diagnostic", {})
    asset_lock_ref = diagnostic_config.get("pretrained_asset_lock")
    if not isinstance(asset_lock_ref, str):
        raise ValueError("resolved D2 config has no diagnostic.pretrained_asset_lock")
    asset_lock_path = Path(asset_lock_ref)
    if not asset_lock_path.is_absolute():
        asset_lock_path = PROJECT_ROOT / asset_lock_path
    results: dict[str, Any] = {}
    alignment: dict[str, Any] = {}
    pretrained_asset_receipt: dict[str, Any] | None = None
    try:
        random_encoder, _, _ = _load_visual_encoder(visual_name, False, None, seed)
        random_encoder.to(device)
        random_train = _encode_split(train_loader, random_encoder, device)
        random_val = _encode_split(val_loader, random_encoder, device)
        del random_encoder
        alignment["random_visual"] = {
            "train": _alignment_receipt(random_train, pre_alignment_ids=random_train["ids"]),
            "validation": _alignment_receipt(random_val, pre_alignment_ids=random_val["ids"]),
        }
        aligned_passes: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
            "random_visual": (random_train, random_val)
        }
        pretrained_error = None
        try:
            pretrained_encoder, _, pretrained_asset_receipt = _load_visual_encoder(
                visual_name,
                True,
                None,
                seed,
                pretrained_asset_lock=asset_lock_path,
            )
            pretrained_encoder.to(device)
            pretrained_train_raw = _encode_split(train_loader, pretrained_encoder, device)
            pretrained_val_raw = _encode_split(val_loader, pretrained_encoder, device)
            pretrained_train, train_receipt = _align_encoded_split(
                random_train, pretrained_train_raw, pass_name="timm_pretrained_visual/train"
            )
            pretrained_val, val_receipt = _align_encoded_split(
                random_val, pretrained_val_raw, pass_name="timm_pretrained_visual/validation"
            )
            alignment["timm_pretrained_visual"] = {
                "train": train_receipt,
                "validation": val_receipt,
            }
            aligned_passes["timm_pretrained_visual"] = (pretrained_train, pretrained_val)
            del pretrained_encoder
        except Exception as exc:  # pragma: no cover - depends on remote asset/network state
            pretrained_error = f"{type(exc).__name__}: {exc}"
            results["timm_pretrained_visual"] = {"name": "timm_pretrained_visual", "status": "BLOCKED_BY_ASSET_IDENTITY", "error": pretrained_error}
        current_encoder, current_checkpoint_sha, _ = _load_visual_encoder(visual_name, False, current_checkpoint, seed)
        current_encoder.to(device)
        current_train_raw = _encode_split(train_loader, current_encoder, device)
        current_val_raw = _encode_split(val_loader, current_encoder, device)
        current_train, train_receipt = _align_encoded_split(
            random_train, current_train_raw, pass_name="current_c2_visual/train"
        )
        current_val, val_receipt = _align_encoded_split(
            random_val, current_val_raw, pass_name="current_c2_visual/validation"
        )
        alignment["current_c2_visual"] = {"train": train_receipt, "validation": val_receipt}
        aligned_passes["current_c2_visual"] = (current_train, current_val)
        del current_encoder
        audio_encoder, _, _ = _load_visual_encoder(audio_name, False, None, seed)
        audio_encoder.to(device)
        audio_train_raw = _encode_split(
            ((batch | {"frame": batch["spectrogram"]}) for batch in train_loader), audio_encoder, device
        )
        audio_val_raw = _encode_split(
            ((batch | {"frame": batch["spectrogram"]}) for batch in val_loader), audio_encoder, device
        )
        audio_train, train_receipt = _align_encoded_split(
            random_train, audio_train_raw, pass_name="random_audio_control/train"
        )
        audio_val, val_receipt = _align_encoded_split(
            random_val, audio_val_raw, pass_name="random_audio_control/validation"
        )
        alignment["random_audio_control"] = {"train": train_receipt, "validation": val_receipt}
        aligned_passes["random_audio_control"] = (audio_train, audio_val)
        visual_dims = sorted(
            {
                int(train_split["features"].shape[-1])
                for train_split, _ in aligned_passes.values()
            }
        )
        maps, maps_receipt = build_common_space_maps(
            visual_dims,
            int(random_train["queries"].shape[-1]),
            output_dim=128,
            seed=seed,
        )
        for pass_name, (train_split, val_split) in aligned_passes.items():
            results[pass_name] = _probe_pair(
                train_split["features"],
                train_split,
                val_split["features"],
                val_split,
                name=pass_name,
                seed=seed,
                maps=maps,
                maps_receipt=maps_receipt,
            )
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
        "status": "D2_PROBE_READY_FOR_ZERO_TRAINING_GATE" if pretrained_error is None else "BLOCKED_BY_ASSET_IDENTITY",
        "scientific_status": (
            "BLOCKED_BY_ASSET_IDENTITY"
            if pretrained_error is not None
            else "D2_ZERO_TRAINING_DECODABILITY_GATE_PASS"
            if gate
            else "D2_ZERO_TRAINING_DECODABILITY_GATE_FAIL"
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
        "pretrained_asset_lock": str(asset_lock_path),
        "pretrained_asset_receipt": pretrained_asset_receipt,
        "alignment": alignment,
        "projection_maps": maps_receipt,
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
