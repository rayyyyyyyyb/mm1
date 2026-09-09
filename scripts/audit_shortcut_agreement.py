"""Stratified, read-only loss/gradient audit for the C2 student checkpoint."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import torch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def _positive_count(record: Mapping[str, Any]) -> int:
    labels = np.asarray(record.get("segment_labels"), dtype=np.int64)
    if labels.shape != (10,) or not np.isin(labels, (0, 1)).all():
        raise ValueError(f"{record.get('id', '<unknown>')}: expected binary labels [10]")
    return int(labels.sum())


def _stratum(record: Mapping[str, Any]) -> str:
    count = _positive_count(record)
    if count == 0:
        return "k0"
    if count == 10:
        return "k10"
    return "kmid"


def stratified_batches(
    records: Sequence[Mapping[str, Any]],
    strata: Sequence[str],
    batches_per_stratum: int,
    batch_size: int,
    seed: int,
) -> dict[str, list[list[dict[str, Any]]]]:
    """Build disjoint deterministic batches, reserving a separate mixed-only pool."""

    if batches_per_stratum <= 0 or batch_size <= 0:
        raise ValueError("batches_per_stratum and batch_size must be positive")
    requested = tuple(str(value) for value in strata)
    allowed = {"k0", "kmid", "k10", "mixed_only"}
    if not set(requested) <= allowed:
        raise ValueError(f"unsupported strata: {sorted(set(requested) - allowed)}")
    required = int(batches_per_stratum) * int(batch_size)
    rng = np.random.default_rng(int(seed))
    pools: dict[str, list[dict[str, Any]]] = {"k0": [], "kmid": [], "k10": []}
    for record in records:
        pools[_stratum(record)].append(dict(record))
    for name in pools:
        order = rng.permutation(len(pools[name]))
        pools[name] = [pools[name][int(index)] for index in order]
    output: dict[str, list[list[dict[str, Any]]]] = {}
    consumed: set[str] = set()
    cursors: dict[str, int] = {name: 0 for name in pools}
    for name in requested:
        source = "kmid" if name == "mixed_only" else name
        start = cursors[source]
        end = start + required
        if len(pools[source]) < end:
            raise ValueError(f"stratum {name} needs {end} records but has {len(pools[source])}")
        selected = pools[source][start:end]
        cursors[source] = end
        batches = [selected[index : index + batch_size] for index in range(0, required, batch_size)]
        output[name] = batches
        for batch in batches:
            for record in batch:
                sample_id = str(record.get("id", ""))
                if sample_id in consumed:
                    raise RuntimeError(f"sample reused across strata: {sample_id}")
                consumed.add(sample_id)
    return output


def mean_centered_decomposition(
    student: torch.Tensor,
    target: torch.Tensor,
    mask: torch.Tensor,
) -> dict[str, float]:
    if student.shape != target.shape or student.ndim != 3:
        raise ValueError("student and target must share [B,T,D]")
    if mask.shape != student.shape[:2]:
        raise ValueError("mask must have shape [B,T]")
    valid = mask.to(dtype=torch.bool)
    difference = student - target
    total = difference[valid].square().sum()
    mean = difference.new_zeros(())
    centered = difference.new_zeros(())
    for row in range(difference.shape[0]):
        selected = difference[row][valid[row]]
        if selected.numel() == 0:
            continue
        row_mean = selected.mean(dim=0)
        mean = mean + selected.shape[0] * row_mean.square().sum()
        centered = centered + (selected - row_mean).square().sum()
    return {
        "mean": float(mean.detach().cpu()),
        "centered": float(centered.detach().cpu()),
        "total": float(total.detach().cpu()),
        "identity_abs_error": float(torch.abs(total - mean - centered).detach().cpu()),
    }


def tie_aware_mixed_concordance(labels: np.ndarray, scores: np.ndarray) -> dict[str, Any]:
    y = np.asarray(labels, dtype=np.int64)
    s = np.asarray(scores, dtype=np.float64)
    if y.shape != s.shape or y.ndim != 2:
        raise ValueError("labels and scores must share [B,T]")
    hits = 0.0
    pairs = 0
    per_video: list[float] = []
    for row_y, row_s in zip(y, s):
        positive = row_s[row_y == 1]
        negative = row_s[row_y == 0]
        if positive.size == 0 or negative.size == 0:
            continue
        difference = positive[:, None] - negative[None, :]
        row_pairs = int(difference.size)
        hits += float((difference > 0).sum() + 0.5 * (difference == 0).sum())
        pairs += row_pairs
        per_video.append(float(((difference > 0).sum() + 0.5 * (difference == 0).sum()) / row_pairs))
    return {
        "pair_weighted_concordance": None if pairs == 0 else float(hits / pairs),
        "video_macro_concordance": None if not per_video else float(np.mean(per_video)),
        "mixed_videos": len(per_video),
        "mixed_pairs": pairs,
    }


def virtual_adamw_delta(
    parameters: Mapping[str, torch.Tensor],
    gradients: Mapping[str, torch.Tensor],
    *,
    learning_rate: float,
    weight_decay: float,
    max_norm: float,
) -> dict[str, Any]:
    """Compute a fresh-state AdamW delta on clones; never mutates arguments."""

    if set(parameters) != set(gradients):
        raise ValueError("parameters and gradients must have identical names")
    norm = float(torch.sqrt(sum(value.detach().float().square().sum() for value in gradients.values())).cpu())
    coefficient = 1.0 if norm <= max_norm or max_norm <= 0 else float(max_norm / max(norm, 1e-12))
    deltas: dict[str, torch.Tensor] = {}
    beta1, beta2, eps = 0.9, 0.999, 1e-8
    step_size = learning_rate * (1.0 - beta2) ** 0.5 / (1.0 - beta1)
    for name, parameter in parameters.items():
        clipped = gradients[name].detach().clone() * coefficient
        exp_avg = clipped * (1.0 - beta1)
        exp_avg_sq = clipped.square() * (1.0 - beta2)
        update = step_size * exp_avg / (exp_avg_sq.sqrt() + eps)
        deltas[name] = -learning_rate * weight_decay * parameter.detach().clone() - update
    return {
        "global_norm": norm,
        "clip_coefficient": coefficient,
        "delta_norm": float(torch.sqrt(sum(value.float().square().sum() for value in deltas.values())).cpu()),
        "deltas": deltas,
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, torch.Tensor):
        return value.detach().cpu().tolist()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    return value


def _vector_cosine(left: torch.Tensor, right: torch.Tensor) -> float | None:
    denominator = torch.linalg.vector_norm(left.float()) * torch.linalg.vector_norm(right.float())
    if float(denominator.detach().cpu()) <= 1e-12:
        return None
    return float((torch.sum(left.float() * right.float()) / denominator).detach().cpu())


def _differentiable_visual_terms(
    decision: torch.Tensor,
    target: torch.Tensor,
    mask: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    valid = mask.to(dtype=torch.bool)
    difference = decision - target
    mean_terms: list[torch.Tensor] = []
    centered_terms: list[torch.Tensor] = []
    for row in range(difference.shape[0]):
        selected = difference[row][valid[row]]
        if selected.numel() == 0:
            mean_terms.append(decision.new_zeros(()))
            centered_terms.append(decision.new_zeros(()))
            continue
        row_mean = selected.mean(dim=0)
        mean_terms.append(selected.shape[0] * row_mean.square().sum())
        centered_terms.append((selected - row_mean).square().sum())
    denominator = max(int(valid.sum().item()), 1)
    return torch.stack(mean_terms).sum() / denominator, torch.stack(centered_terms).sum() / denominator


def collect_loss_components(
    student: torch.nn.Module,
    loss_module: torch.nn.Module,
    batch: Mapping[str, Any],
    device: torch.device,
    *,
    optimizer_group_meta: Mapping[str, Mapping[str, float]] | None = None,
    grad_clip: float = 1.0,
    learning_rate: float = 2e-4,
    weight_decay: float = 1e-4,
) -> dict[str, Any]:
    """Collect values, gradients and virtual updates using autograd.grad only."""

    from scripts.audit_feature_loss_runtime import _student_inputs, _to_device
    from scripts.audit_per_loss_gradient_conflict import _loss_components
    from scripts.audit_optimizer_virtual_replay import replay_virtual_update

    parameter_items = [(f"student.{name}", parameter) for name, parameter in student.named_parameters()]
    parameter_items += [(f"loss.{name}", parameter) for name, parameter in loss_module.named_parameters()]
    parameter_items = [(name, parameter) for name, parameter in parameter_items if parameter.requires_grad]
    parameters = {name: parameter for name, parameter in parameter_items}
    before_parameters = {name: value.detach().clone() for name, value in parameters.items()}
    torch_rng = torch.random.get_rng_state()
    cuda_rng = torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None
    previous_student_mode, previous_loss_mode = student.training, loss_module.training
    try:
        student.eval()
        loss_module.eval()
        outputs = student(**_student_inputs(batch, device))
        components = _loss_components(outputs, loss_module, batch, device)
        decision = outputs["decision_features"]
        strong_features = _to_device(batch["strong_teacher_features"], device)
        sequence_mask = _to_device(batch["sequence_mask"], device)
        teacher_mask = _to_device(batch["strong_teacher_feature_mask"], device)
        target = loss_module.strong_teacher_proj(strong_features.detach())
        visual_mean, visual_centered = _differentiable_visual_terms(decision, target, sequence_mask * teacher_mask)
        alpha_visual = float(getattr(loss_module, "alpha_strong_feat", 0.4))
        component_tensors: dict[str, torch.Tensor] = {
            "bce": components["bce"],
            "visual": components["visual"],
            "text": components["text"],
            "visual_mean": alpha_visual * visual_mean,
            "visual_centered": alpha_visual * visual_centered,
        }
        component_tensors["total"] = component_tensors["bce"] + component_tensors["visual"] + component_tensors["text"]
        gradient_map: dict[str, dict[str, torch.Tensor]] = {}
        for name, value in component_tensors.items():
            raw = torch.autograd.grad(value, list(parameters.values()), retain_graph=True, allow_unused=True)
            gradient_map[name] = {
                parameter_name: (gradient.detach().float() if gradient is not None else torch.zeros_like(parameter).detach().float())
                for (parameter_name, parameter), gradient in zip(parameters.items(), raw)
            }
        module_names = sorted({name.split(".", 2)[1] for name in parameters if "." in name})
        receipts: dict[str, Any] = {}
        for component_name, value in component_tensors.items():
            gradients = gradient_map[component_name]
            modules: dict[str, Any] = {}
            for module_name in module_names:
                module_values = [gradient for name, gradient in gradients.items() if name.split(".", 2)[1] == module_name]
                vector = torch.cat([value.reshape(-1) for value in module_values]) if module_values else torch.zeros(0)
                modules[module_name] = {"norm": float(torch.linalg.vector_norm(vector).cpu()), "parameter_count": int(vector.numel())}
            receipts[component_name] = {
                "value": float(value.detach().cpu()),
                "gradient_norm": float(torch.sqrt(sum(gradient.square().sum() for gradient in gradients.values())).cpu()),
                "modules": modules,
            }
        cosines: dict[str, dict[str, float | None]] = {}
        for left, right in (("bce", "visual"), ("text", "visual"), ("visual_mean", "visual_centered")):
            per_module: dict[str, float | None] = {}
            for module_name in module_names:
                left_values = [value for name, value in gradient_map[left].items() if name.split(".", 2)[1] == module_name]
                right_values = [value for name, value in gradient_map[right].items() if name.split(".", 2)[1] == module_name]
                if left_values and right_values:
                    per_module[module_name] = _vector_cosine(torch.cat([value.reshape(-1) for value in left_values]), torch.cat([value.reshape(-1) for value in right_values]))
            cosines[f"{left}_vs_{right}"] = per_module
        group_meta = optimizer_group_meta or {name: {"lr": learning_rate, "weight_decay": weight_decay} for name in parameters}
        optimizer_state = {
            "groups": {name: dict(group_meta.get(name, {"lr": learning_rate, "weight_decay": weight_decay})) for name in parameters},
            "hyperparameters": {"betas": (0.9, 0.999), "eps": 1e-8, "max_norm": float(grad_clip)},
            "state": {},
        }
        virtual = {}
        for scope in ("current_global_all_grad_clip", "updating_parameters_only_clip"):
            replay = replay_virtual_update(
                {name: parameter.detach() for name, parameter in parameters.items()},
                optimizer_state,
                gradient_map["total"],
                clip_scope=scope,
            )
            virtual[scope] = {
                "global_norm": float(replay["global_norm"]),
                "clip_coefficient": float(replay["clip_coefficient"]),
                "delta_norm": float(torch.sqrt(sum(delta.float().square().sum() for delta in replay["deltas"].values())).cpu()),
            }
        return {
            "values": {name: receipt["value"] for name, receipt in receipts.items()},
            "receipts": receipts,
            "cosines": cosines,
            "mean_centered": mean_centered_decomposition(decision.detach(), target.detach(), (sequence_mask * teacher_mask).bool()),
            "virtual_adamw": virtual,
            "parameter_state_unchanged": all(torch.equal(before_parameters[name], parameter.detach()) for name, parameter in parameters.items()),
            "rng_state_unchanged": torch.equal(torch_rng, torch.random.get_rng_state()) and (not torch.cuda.is_available() or all(torch.equal(before, after) for before, after in zip(cuda_rng or [], torch.cuda.get_rng_state_all()))),
        }
    finally:
        student.train(previous_student_mode)
        loss_module.train(previous_loss_mode)
        torch.random.set_rng_state(torch_rng)
        if cuda_rng is not None:
            torch.cuda.set_rng_state_all(cuda_rng)


def _summarize_batches(batch_receipts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    names = ("bce", "visual", "text", "visual_mean", "visual_centered", "total")
    values = {name: float(np.mean([float(item["values"][name]) for item in batch_receipts])) for name in names}
    gradient_norms = {name: float(np.mean([float(item["receipts"][name]["gradient_norm"]) for item in batch_receipts])) for name in names}
    mean_grad = gradient_norms["visual_mean"]
    centered_grad = gradient_norms["visual_centered"]
    return {
        "batches": len(batch_receipts),
        "values_mean": values,
        "gradient_norms_mean": gradient_norms,
        "visual_mean_to_centered_gradient_ratio": None if centered_grad <= 1e-12 else float(mean_grad / centered_grad),
        "visual_mean_to_centered_loss_ratio": None if values["visual_centered"] <= 1e-12 else float(values["visual_mean"] / values["visual_centered"]),
        "clip_coefficient_mean": float(np.mean([item["virtual_adamw"]["updating_parameters_only_clip"]["clip_coefficient"] for item in batch_receipts])),
        "clip_engaged_fraction": float(np.mean([item["virtual_adamw"]["updating_parameters_only_clip"]["clip_coefficient"] < 0.999999 for item in batch_receipts])),
        "parameter_state_unchanged": bool(all(bool(item["parameter_state_unchanged"]) for item in batch_receipts)),
        "rng_state_unchanged": bool(all(bool(item["rng_state_unchanged"]) for item in batch_receipts)),
        "cosine_means": {
            pair: float(np.mean([value for item in batch_receipts for value in item["cosines"].get(pair, {}).values() if value is not None]))
            if any(value is not None for item in batch_receipts for value in item["cosines"].get(pair, {}).values())
            else None
            for pair in ("bce_vs_visual", "text_vs_visual", "visual_mean_vs_visual_centered")
        },
    }


def summarize_shortcut_agreement(receipts: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    mixed = receipts.get("mixed_only")
    strata = [receipts[name] for name in ("k0", "kmid", "k10") if name in receipts]
    evidence = ([mixed] if mixed is not None else []) + strata
    ratios = [item.get("visual_mean_to_centered_gradient_ratio") for item in evidence]
    clip = [item.get("clip_engaged_fraction", 0.0) for item in evidence]
    gate = bool(
        len(evidence) == 4
        and all(value is not None and float(value) >= 2.0 for value in ratios)
        and all(float(value) >= 0.5 for value in clip)
    )
    return {
        "classification": (
            "VISUAL_MEAN_COMPONENT_DOMINANCE_CONFIRMED"
            if gate
            else "VISUAL_MEAN_COMPONENT_DOMINANCE_UNRESOLVED"
        ),
        "preregistered_gate": {
            "four_strata_present": len(evidence) == 4,
            "mean_to_centered_gradient_ratio_ge_2": [None if value is None else bool(float(value) >= 2.0) for value in ratios],
            "clip_engaged_fraction_ge_0_5": [bool(float(value) >= 0.5) for value in clip],
        },
        "all_strata": {name: receipts[name] for name in ("k0", "kmid", "k10") if name in receipts},
        "mixed_only": mixed,
    }


def audit_model_checkpoint(
    config_path: str | Path,
    checkpoint_path: str | Path,
    *,
    output: str | Path,
    batches_per_stratum: int = 32,
    batch_size: int = 4,
    seed: int = 42,
) -> dict[str, Any]:
    from scripts.train_ov_orthkd import (
        build_model_and_loss,
        build_named_optimizer_groups,
        build_runtime_reproduction_fingerprint,
        create_ov_avel_data_loaders,
        load_config,
        load_evaluation_checkpoint,
        set_seed,
    )
    from src.utils.projector_update_modes import resolve_projector_update_modes

    config = load_config(str(config_path))
    set_seed(int(seed), deterministic=bool(config.get("training", {}).get("deterministic", True)))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    student, loss_module = build_model_and_loss(config, device)
    load_evaluation_checkpoint(
        student=student,
        resume_path=str(checkpoint_path),
        expected_fingerprint=build_runtime_reproduction_fingerprint(config),
        allow_incompatible=True,
        incompatible_marker_path=Path(output).parent / "INCOMPATIBLE_RESUME.txt",
    )
    checkpoint_sha = hashlib.sha256(Path(checkpoint_path).read_bytes()).hexdigest()
    train_manifest = Path(config["data"]["val_manifest"])
    records = [json.loads(line) for line in train_manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    batches = stratified_batches(records, ("k0", "kmid", "k10", "mixed_only"), batches_per_stratum, batch_size, seed)
    modes = resolve_projector_update_modes(config.get("loss", {}))
    groups = build_named_optimizer_groups(
        student,
        loss_module,
        learning_rate=float(config.get("training", {}).get("learning_rate", 2e-4)),
        weight_decay=float(config.get("training", {}).get("weight_decay", 1e-4)),
        modes=modes,
    )
    group_meta = {
        name: {"lr": float(group["lr"]), "weight_decay": float(group.get("weight_decay", 0.0))}
        for group in groups
        for name in group.get("param_names", [])
    }
    all_receipts: dict[str, Any] = {}
    subset_root = Path(output).parent / "shortcut_agreement_subsets"
    subset_root.mkdir(parents=True, exist_ok=True)
    try:
        for stratum, stratum_batches in batches.items():
            subset_path = subset_root / f"{stratum}.jsonl"
            subset_path.write_text(
                "".join(json.dumps(record, ensure_ascii=False) + "\n" for batch in stratum_batches for record in batch),
                encoding="utf-8",
            )
            local_config = copy.deepcopy(config)
            local_config["data"]["train_manifest"] = str(subset_path)
            local_config["data"]["val_manifest"] = str(subset_path)
            local_config["data"]["test_manifest"] = None
            local_config["data"]["batch_size"] = int(batch_size)
            local_config["data"]["num_workers"] = 0
            train_loader, _, _ = create_ov_avel_data_loaders(local_config)
            receipts: list[dict[str, Any]] = []
            for index, batch in enumerate(train_loader):
                if index >= batches_per_stratum:
                    break
                receipts.append(
                    collect_loss_components(
                        student,
                        loss_module,
                        batch,
                        device,
                        optimizer_group_meta=group_meta,
                        grad_clip=float(config.get("training", {}).get("grad_clip", 1.0)),
                        learning_rate=float(config.get("training", {}).get("learning_rate", 2e-4)),
                        weight_decay=float(config.get("training", {}).get("weight_decay", 1e-4)),
                    )
                )
            if len(receipts) != batches_per_stratum:
                raise RuntimeError(f"{stratum}: collected {len(receipts)} batches, expected {batches_per_stratum}")
            all_receipts[stratum] = _summarize_batches(receipts)
            all_receipts[stratum]["batch_ids_sha256"] = hashlib.sha256(
                "\n".join(str(record.get("id", "")) for batch in stratum_batches for record in batch).encode("utf-8")
            ).hexdigest()
    finally:
        for subset_path in subset_root.glob("*.jsonl"):
            subset_path.unlink(missing_ok=True)
        try:
            subset_root.rmdir()
        except OSError:
            pass
    summary = summarize_shortcut_agreement(all_receipts)
    return {
        "schema_version": 1,
        "status": "PASS",
        "scientific_status": summary["classification"],
        "protocol": {
            "task_segments": 10,
            "strata": ["k0", "kmid", "k10", "mixed_only"],
            "batches_per_stratum": int(batches_per_stratum),
            "batch_size": int(batch_size),
            "seed": int(seed),
            "optimizer_constructed": False,
            "optimizer_step_executed": False,
            "checkpoint_written": False,
            "validation_manifest_only": True,
        },
        "checkpoint_sha256": checkpoint_sha,
        "strata": all_receipts,
        "summary": summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batches-per-stratum", type=int, default=32)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    result = audit_model_checkpoint(
        args.config,
        args.checkpoint,
        output=args.output,
        batches_per_stratum=args.batches_per_stratum,
        batch_size=args.batch_size,
        seed=args.seed,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(_jsonable(result), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(_jsonable(result), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
