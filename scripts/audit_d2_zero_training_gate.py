"""Independently audit a completed D2 zero-training representation gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping


EXPECTED_PROBES = (
    "random_visual",
    "timm_pretrained_visual",
    "current_c2_visual",
    "random_audio_control",
)
EXPECTED_MODEL_ID = "timm/convnextv2_tiny.fcmae_ft_in22k_in1k"
EXPECTED_REVISION = "b1dd46230e80bf4cc3fa0c3c905db2c3ec53a817"
EXPECTED_WEIGHTS_SHA256 = "6652fd90fc9c23977659e58515778e16fbbcd43f0b01fc693089cebe6d64c2a9"
EXPECTED_LOADED_BACKBONE_SHA256 = "d8bcbc7225bedef0202e5f47613a4232eab9a7bbeef2be571831266361bafe90"
EXPECTED_PROBE_SCRIPT_SHA256 = "c57d69ea3c4c80ad53bb459d55c283bdc539000229f9cf1c1e37f98b599fde1e"
EXPECTED_D2_CONFIG_SHA256 = "b9c32df24aef4c30e2ca5869b52c5dbc16a4c517ab46fe35332f2e548110643d"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(document, Mapping):
        raise ValueError(f"JSON document must be a mapping: {path}")
    return dict(document)


def _nested(mapping: Mapping[str, Any], *keys: str) -> Any:
    value: Any = mapping
    for key in keys:
        if not isinstance(value, Mapping) or key not in value:
            raise KeyError(".".join(keys))
        value = value[key]
    return value


def _finite_float(value: Any, field: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} is not finite")
    return result


def audit_d2_zero_training_gate(
    result_path: str | Path,
    input_receipt_path: str | Path,
    state_path: str | Path,
    exit_code_path: str | Path,
    stderr_path: str | Path,
) -> dict[str, Any]:
    """Validate artifacts and independently recompute the preregistered gate."""

    paths = {
        "result": Path(result_path).resolve(),
        "input_receipt": Path(input_receipt_path).resolve(),
        "state": Path(state_path).resolve(),
        "exit_code": Path(exit_code_path).resolve(),
        "stderr": Path(stderr_path).resolve(),
    }
    errors: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    try:
        result = _load_json(paths["result"])
        inputs = _load_json(paths["input_receipt"])
        state = _load_json(paths["state"])
    except Exception as exc:
        return {
            "schema_version": 1,
            "status": "ARTIFACT_AUDIT_FAIL",
            "errors": [f"artifact parse failure: {type(exc).__name__}: {exc}"],
        }

    try:
        exit_code = int(paths["exit_code"].read_text(encoding="ascii").strip())
    except Exception as exc:
        exit_code = -1
        errors.append(f"exit-code parse failure: {type(exc).__name__}: {exc}")
    require(exit_code == 0, f"producer exit code is {exit_code}, expected 0")
    require(paths["stderr"].stat().st_size == 0, "producer stderr is not empty")
    require(state.get("status") == "completed", "worker state is not completed")
    require(state.get("exit_code") == 0, "worker state exit_code is not 0")

    protocol = result.get("protocol", {})
    require(protocol.get("task_segments") == 10, "result task_segments is not 10")
    require(protocol.get("sample_count_per_split") == 256, "result sample budget is not 256")
    require(protocol.get("seed") == 42, "result seed is not 42")
    require(protocol.get("zero_training_only") is True, "result is not zero-training-only")
    require(protocol.get("optimizer_constructed") is False, "result reports an optimizer")
    require(protocol.get("optimizer_step_executed") is False, "result reports an optimizer step")
    require(protocol.get("checkpoint_written") is False, "result reports a model checkpoint write")

    require(inputs.get("status") == "INPUTS_LOCKED", "input receipt is not locked")
    require(inputs.get("host") == "DESKTOP-LPN6MT3", "input receipt host is not the locked target")
    require("RTX 5090" in str(inputs.get("gpu", "")), "input receipt GPU is not RTX 5090")
    require(inputs.get("task_segments") == 10, "input task_segments is not 10")
    require(inputs.get("sample_count_per_split") == 256, "input sample budget is not 256")
    require(inputs.get("seed") == 42, "input seed is not 42")
    require(inputs.get("evaluation_split") == "validation", "input split is not validation")
    require(inputs.get("test_manifest") is None, "input receipt names a test manifest")
    for field in (
        "optimizer_constructed",
        "backward_or_update",
        "model_checkpoint_write",
        "d2_800_step",
        "d3",
        "formal_full",
    ):
        require(inputs.get(field) is False, f"input boundary field {field} is not false")
    require(inputs.get("offline_only") is True, "input receipt is not offline-only")

    input_files = inputs.get("files", {})
    try:
        require(
            _nested(input_files, "probe_script", "sha256") == EXPECTED_PROBE_SCRIPT_SHA256,
            "probe-script SHA256 is not the reviewed E0.1 implementation",
        )
        require(
            _nested(input_files, "d2_config", "sha256") == EXPECTED_D2_CONFIG_SHA256,
            "D2 config SHA256 is not the reviewed wrapper",
        )
        checkpoint_sha = str(_nested(input_files, "c2_checkpoint", "sha256"))
        require(result.get("checkpoint_sha256") == checkpoint_sha, "result/checkpoint SHA256 mismatch")
        receipt_weights_sha = str(_nested(input_files, "asset_weights", "sha256"))
        require(receipt_weights_sha == EXPECTED_WEIGHTS_SHA256, "input asset SHA256 is not locked")
        require(
            int(_nested(input_files, "asset_weights", "size_bytes")) == 114_561_694,
            "input asset byte count is not locked",
        )
    except Exception as exc:
        errors.append(f"input-file receipt failure: {type(exc).__name__}: {exc}")

    asset = result.get("pretrained_asset_receipt", {})
    require(asset.get("model_id") == EXPECTED_MODEL_ID, "loaded model ID mismatch")
    require(asset.get("revision") == EXPECTED_REVISION, "loaded model revision mismatch")
    require(asset.get("weights_sha256") == EXPECTED_WEIGHTS_SHA256, "loaded weight SHA256 mismatch")
    require(
        asset.get("loaded_backbone_tensor_sha256") == EXPECTED_LOADED_BACKBONE_SHA256,
        "loaded backbone tensor fingerprint mismatch",
    )
    require(asset.get("parameter_count") == 27_866_496, "loaded parameter count mismatch")
    require(asset.get("feature_dim") == 768, "loaded visual feature dimension mismatch")
    require(asset.get("missing_keys") == [], "locked load has missing keys")
    require(
        sorted(asset.get("unexpected_head_keys", [])) == ["head.fc.bias", "head.fc.weight"],
        "locked load has unapproved unexpected keys",
    )
    require(asset.get("pretrained_lookup_disabled") is True, "pretrained lookup was not disabled")
    require(asset.get("offline_only") is True, "loaded asset receipt is not offline-only")

    probes = result.get("probes", {})
    alignment = result.get("alignment", {})
    require(set(probes) == set(EXPECTED_PROBES), "probe set is incomplete or unexpected")
    require(set(alignment) == set(EXPECTED_PROBES), "alignment receipt set is incomplete or unexpected")
    alignment_fields = (
        "canonical_post_alignment_id_hash",
        "label_hash",
        "query_string_hash",
        "query_embedding_hash",
        "sequence_mask_hash",
        "selected_segment_indices_hash",
    )
    try:
        for split in ("train", "validation"):
            reference = _nested(alignment, "random_visual", split)
            for probe_name in EXPECTED_PROBES:
                candidate = _nested(alignment, probe_name, split)
                for field in alignment_fields:
                    require(
                        candidate.get(field) == reference.get(field),
                        f"{probe_name}/{split} {field} is not canonically aligned",
                    )
            if split == "validation":
                require(
                    result.get("subset_ids_sha256", {}).get("validation")
                    == reference.get("canonical_post_alignment_id_hash"),
                    "validation subset/order hash does not match aligned validation IDs",
                )
    except Exception as exc:
        errors.append(f"alignment receipt failure: {type(exc).__name__}: {exc}")

    projection_maps = result.get("projection_maps", {})
    require(projection_maps.get("seed") == 42, "projection-map seed is not 42")
    require(projection_maps.get("output_dim") == 128, "projection-map output dimension is not 128")
    require(len(str(projection_maps.get("query_map_sha256", ""))) == 64, "query-map hash is invalid")
    visual_map_hashes = projection_maps.get("visual_map_sha256", {})
    require(set(visual_map_hashes) == {"768", "1408"}, "visual-map dimensions are unexpected")
    for probe_name in EXPECTED_PROBES:
        probe = probes.get(probe_name, {})
        require(probe.get("projection_maps") == projection_maps, f"{probe_name} did not reuse shared maps")
        require(probe.get("query_shape") == [256, 1024], f"{probe_name} query shape is unexpected")
        visual_shape = probe.get("visual_shape", [])
        require(visual_shape[:2] == [256, 10], f"{probe_name} visual shape is not [256,10,D]")

    try:
        reference_qp = _nested(probes, "random_visual", "qp")
        for probe_name in EXPECTED_PROBES:
            require(_nested(probes, probe_name, "qp") == reference_qp, f"{probe_name} QP baseline changed")
            macro = _nested(probes, probe_name, "macro_grouping")
            require(macro.get("source") == "batch.query", f"{probe_name} uses a synthetic query source")
            require(macro.get("validation_sample_count") == 256, f"{probe_name} macro sample count is not 256")
            counts = macro.get("validation_query_counts", {})
            require(isinstance(counts, Mapping), f"{probe_name} query counts are malformed")
            if isinstance(counts, Mapping):
                require(sum(int(value) for value in counts.values()) == 256, f"{probe_name} query counts do not sum to 256")
                require(macro.get("unique_query_count") == len(counts), f"{probe_name} unique-query count mismatch")
            require(
                macro.get("validation_query_ids_sha256") == macro.get("qp_query_ids_sha256")
                == macro.get("vqp_query_ids_sha256"),
                f"{probe_name} query IDs differ between QP and VQP",
            )
            require(
                macro.get("validation_sample_ids_sha256") == macro.get("qp_sample_ids_sha256")
                == macro.get("vqp_sample_ids_sha256"),
                f"{probe_name} sample IDs differ between QP and VQP",
            )
    except Exception as exc:
        errors.append(f"probe identity failure: {type(exc).__name__}: {exc}")

    random_vqp = pretrained_vqp = qp = math.nan
    gate_pass = False
    try:
        random_vqp = _finite_float(
            _nested(probes, "random_visual", "vqp", "mixed", "pair_weighted_concordance"),
            "random visual VQP",
        )
        pretrained_vqp = _finite_float(
            _nested(probes, "timm_pretrained_visual", "vqp", "mixed", "pair_weighted_concordance"),
            "pretrained visual VQP",
        )
        qp = _finite_float(
            _nested(probes, "random_visual", "qp", "mixed", "pair_weighted_concordance"),
            "QP",
        )
        reported_gate = result.get("gate", {})
        require(math.isclose(float(reported_gate.get("random_vqp_mixed_concordance")), random_vqp, abs_tol=1e-15), "reported random VQP differs from probe")
        require(math.isclose(float(reported_gate.get("timm_pretrained_vqp_mixed_concordance")), pretrained_vqp, abs_tol=1e-15), "reported pretrained VQP differs from probe")
        require(math.isclose(float(reported_gate.get("qp_mixed_concordance")), qp, abs_tol=1e-15), "reported QP differs from probe")
        gate_pass = pretrained_vqp >= random_vqp + 0.05 and pretrained_vqp >= qp + 0.02
        require(reported_gate.get("pass") is gate_pass, "producer gate boolean differs from independent recomputation")
        precise_scientific_status = (
            "D2_ZERO_TRAINING_DECODABILITY_GATE_PASS"
            if gate_pass
            else "D2_ZERO_TRAINING_DECODABILITY_GATE_FAIL"
        )
        legacy_scientific_status = (
            "VISUAL_PRETRAINING_CONTROL_PASS"
            if gate_pass
            else "VISUAL_PRETRAINING_CONTROL_FAIL"
        )
        require(
            result.get("scientific_status")
            in {precise_scientific_status, legacy_scientific_status},
            "scientific status differs from recomputed gate",
        )
    except Exception as exc:
        errors.append(f"gate recomputation failure: {type(exc).__name__}: {exc}")

    audit_status = "ARTIFACT_AUDIT_PASS" if not errors else "ARTIFACT_AUDIT_FAIL"
    return {
        "schema_version": 1,
        "status": audit_status,
        "scientific_status": (
            "D2_ZERO_TRAINING_DECODABILITY_GATE_PASS"
            if gate_pass
            else "D2_ZERO_TRAINING_DECODABILITY_GATE_FAIL"
        ),
        "producer_scientific_status": result.get("scientific_status"),
        "errors": errors,
        "source_artifacts": {
            name: {"path": str(path), "size_bytes": path.stat().st_size, "sha256": _sha256_file(path)}
            for name, path in paths.items()
        },
        "gate_recomputation": {
            "random_vqp_mixed_concordance": random_vqp,
            "pretrained_vqp_mixed_concordance": pretrained_vqp,
            "qp_mixed_concordance": qp,
            "pretrained_minus_random": pretrained_vqp - random_vqp,
            "required_pretrained_minus_random": 0.05,
            "pretrained_minus_qp": pretrained_vqp - qp,
            "required_pretrained_minus_qp": 0.02,
            "random_margin": pretrained_vqp - (random_vqp + 0.05),
            "qp_margin": pretrained_vqp - (qp + 0.02),
            "pass": gate_pass,
        },
        "identity_checks": {
            "sample_alignment": not any("aligned" in error or "alignment" in error for error in errors),
            "shared_projection_maps": not any("shared maps" in error for error in errors),
            "real_query_grouping": not any("query" in error.lower() for error in errors),
            "locked_offline_asset": not any("asset" in error.lower() or "loaded" in error.lower() for error in errors),
        },
        "authorization": {
            "d2_800_step": bool(audit_status == "ARTIFACT_AUDIT_PASS" and gate_pass),
            "d3": False,
            "formal_full": False,
            "test_evaluation": False,
            "second_seed": False,
            "schedule_extension": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--input-receipt", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--exit-code", type=Path, required=True)
    parser.add_argument("--stderr", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit_d2_zero_training_gate(
        args.result,
        args.input_receipt,
        args.state,
        args.exit_code,
        args.stderr,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "ARTIFACT_AUDIT_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
