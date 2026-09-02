from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Mapping

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
S0_PATH = (
    PROJECT_ROOT
    / "configs"
    / "diagnostics"
    / "causal"
    / "ov_orthkd_s0_learned_concat_seed42.yaml"
)
S3_PATH = (
    PROJECT_ROOT
    / "configs"
    / "diagnostics"
    / "recovery"
    / "ov_orthkd_s3_pretrained_seed42.yaml"
)
S4_PATH = (
    PROJECT_ROOT
    / "configs"
    / "diagnostics"
    / "recovery"
    / "ov_orthkd_s4_no_augment_seed42.yaml"
)
VISUAL_ONLY_PATH = (
    PROJECT_ROOT
    / "configs"
    / "diagnostics"
    / "ov_orthkd_mm26_visual_only_seed42.yaml"
)
VISUAL_SUM_PATH = (
    PROJECT_ROOT
    / "configs"
    / "diagnostics"
    / "recovery"
    / "ov_orthkd_visual_only_sum_feature_seed42.yaml"
)
VISUAL_SUM_SINGLE_WORKER_PATH = (
    PROJECT_ROOT
    / "configs"
    / "diagnostics"
    / "recovery"
    / "ov_orthkd_visual_only_sum_feature_seed42_single_worker.yaml"
)


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _normalized(config: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(config)
    result["reproduction"]["variant"] = "NORMALIZED"
    result["logging"]["log_dir"] = "NORMALIZED"
    return result


def _different_paths(left: Any, right: Any, prefix: str = "") -> set[str]:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        paths: set[str] = set()
        for key in set(left) | set(right):
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in left or key not in right:
                paths.add(path)
            else:
                paths.update(_different_paths(left[key], right[key], path))
        return paths
    return set() if left == right else {prefix}


def test_s3_changes_only_pretrained_after_identity_output_normalization() -> None:
    s0 = _normalized(_load(S0_PATH))
    s3 = _normalized(_load(S3_PATH))

    assert _different_paths(s0, s3) == {"student.pretrained"}
    assert s0["student"]["pretrained"] is False
    assert s3["student"]["pretrained"] is True


def test_s3_remains_short_noncanonical_t10_control_with_original_schedule() -> None:
    config = _load(S3_PATH)

    assert config["seed"] == 42
    assert config["reproduction"]["claim_level"] == "noncanonical_diagnostic"
    assert config["reproduction"]["diagnostic_only"] is True
    assert config["data"]["num_segments"] == 10
    assert config["student"]["max_position_segments"] == 16
    assert config["data"]["train_augment"] is True
    assert config["training"]["epochs"] == 3
    assert config["training"]["max_batches_per_epoch"] == 400
    assert config["training"]["max_optimizer_steps"] is None
    assert config["training"]["scheduler"]["T_max"] == 30
    assert config["evaluation"]["test_views"] == 1
    assert config["training"]["model_selection"]["run_all_30_epochs"] is False
    assert all(
        config["loss"][name] == 0.0
        for name in (
            "alpha_strong_logit",
            "alpha_weak_logit",
            "alpha_strong_feat",
            "alpha_weak_feat",
            "alpha_text_align",
            "alpha_orth",
        )
    )


def test_s4_changes_only_train_augment_after_identity_output_normalization() -> None:
    s0 = _normalized(_load(S0_PATH))
    s4 = _normalized(_load(S4_PATH))

    assert _different_paths(s0, s4) == {"data.train_augment"}
    assert s0["data"]["train_augment"] is True
    assert s4["data"]["train_augment"] is False


def test_s4_remains_short_noncanonical_t10_random_init_control() -> None:
    config = _load(S4_PATH)

    assert config["seed"] == 42
    assert config["reproduction"]["claim_level"] == "noncanonical_diagnostic"
    assert config["reproduction"]["diagnostic_only"] is True
    assert config["data"]["num_segments"] == 10
    assert config["student"]["max_position_segments"] == 16
    assert config["student"]["pretrained"] is False
    assert config["data"]["train_augment"] is False
    assert config["training"]["epochs"] == 3
    assert config["training"]["max_batches_per_epoch"] == 400
    assert config["training"]["max_optimizer_steps"] is None
    assert config["training"]["scheduler"]["T_max"] == 30
    assert config["evaluation"]["test_views"] == 1
    assert config["training"]["model_selection"]["run_all_30_epochs"] is False
    assert all(
        config["loss"][name] == 0.0
        for name in (
            "alpha_strong_logit",
            "alpha_weak_logit",
            "alpha_strong_feat",
            "alpha_weak_feat",
            "alpha_text_align",
            "alpha_orth",
        )
    )


def test_visual_sum_control_changes_only_visual_feature_reduction() -> None:
    baseline = _normalized(_load(VISUAL_ONLY_PATH))
    control = _normalized(_load(VISUAL_SUM_PATH))

    # Claim/guard/output metadata are intentionally diagnostic-only identity
    # changes; the scientific configuration must differ in exactly one field.
    for config in (baseline, control):
        config["reproduction"].pop("claim_level", None)
        config["reproduction"].pop("diagnostic_only", None)
        config["reproduction"].pop("full_run_blocked", None)
        config["reproduction"].pop("blocked_archival_facts", None)
    assert _different_paths(baseline, control) == {
        "loss.visual_l2_reduction"
    }
    assert baseline["loss"]["visual_l2_reduction"] == (
        "mean_feature_then_masked_mean_segments"
    )
    assert control["loss"]["visual_l2_reduction"] == (
        "sum_feature_then_masked_mean_segments"
    )


def test_visual_sum_control_is_explicitly_noncanonical_and_guarded() -> None:
    config = _load(VISUAL_SUM_PATH)

    assert config["seed"] == 42
    assert config["reproduction"]["claim_level"] == "noncanonical_diagnostic"
    assert config["reproduction"]["diagnostic_only"] is True
    assert config["reproduction"]["full_run_blocked"] is True
    assert "diagnostic" in config["logging"]["log_dir"]
    assert config["data"]["num_segments"] == 10
    assert config["student"]["max_position_segments"] == 16
    assert config["training"]["epochs"] == 30
    assert config["training"]["max_batches_per_epoch"] == 400
    assert config["training"]["max_optimizer_steps"] is None
    assert config["training"]["scheduler"]["T_max"] == 30
    assert config["evaluation"]["test_views"] == 1


def test_single_worker_retry_only_adds_runtime_worker_override() -> None:
    control = _normalized(_load(VISUAL_ONLY_PATH))
    retry = _normalized(_load(VISUAL_SUM_SINGLE_WORKER_PATH))

    for config in (control, retry):
        config["reproduction"].pop("claim_level", None)
        config["reproduction"].pop("diagnostic_only", None)
        config["reproduction"].pop("full_run_blocked", None)
        config["reproduction"].pop("blocked_archival_facts", None)
        config["reproduction"].pop("runtime_overrides", None)
    assert _different_paths(control, retry) == {
        "loss.visual_l2_reduction",
        "data.num_workers",
    }
    assert retry["loss"]["visual_l2_reduction"] == (
        "sum_feature_then_masked_mean_segments"
    )
    assert control["data"]["num_workers"] == 4
    assert retry["data"]["num_workers"] == 1


def test_single_worker_retry_is_guarded_and_declares_resource_reason() -> None:
    config = _load(VISUAL_SUM_SINGLE_WORKER_PATH)

    assert config["seed"] == 42
    assert config["reproduction"]["claim_level"] == "noncanonical_diagnostic"
    assert config["reproduction"]["diagnostic_only"] is True
    assert config["reproduction"]["full_run_blocked"] is True
    assert config["reproduction"]["runtime_overrides"]["data.num_workers"] == {
        "from": 4,
        "to": 1,
        "reason": "Windows shared-file-mapping error 1455 during four-worker validation",
    }
    assert config["data"]["num_segments"] == 10
    assert config["student"]["max_position_segments"] == 16
    assert config["training"]["epochs"] == 30
    assert config["training"]["max_batches_per_epoch"] == 400
    assert config["training"]["max_optimizer_steps"] is None
    assert config["training"]["scheduler"]["T_max"] == 30
    assert config["evaluation"]["test_views"] == 1
