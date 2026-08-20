from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import yaml

from scripts.create_mm26_smoke_fixture import create_mm26_smoke_fixture
from scripts.train_ov_orthkd import apply_cli_config_overrides
from src.teachers.common import load_records


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str) -> dict:
    with (PROJECT_ROOT / "configs" / name).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_canonical_mm26_config_is_strict_and_uses_approved_reconstruction_locks() -> None:
    config = _load("ov_orthkd_mm26_repro.yaml")

    assert config["reproduction"]["full_run_blocked"] is True
    assert config["reproduction"]["claim_level"] == "paper_specified_reconstruction"
    assert config["reproduction"]["implementation_mode"] == "camera_ready_explicit_paths"
    assert config["reproduction"]["asset_download_lock_required"] is True
    assert config["reproduction"]["approved_reconstruction_assumptions"] == (
        "configs/locks/mm26_archival_facts.yaml"
    )
    assert set(config["reproduction"]["readiness"]) >= {
        "data_lock",
        "archival_lock",
        "teacher_lock",
        "preprocessing_lock",
        "evaluator_lock",
        "exported_audit",
        "download_lock",
        "teacher_environment",
        "real_preflight",
        "readiness_receipt",
    }
    assert config["student"]["path_mode"] == "explicit_projected"
    assert config["loss"]["text_alignment_mode"] == "paper_probability"
    assert config["loss"]["alpha_strong_logit"] == 0.0
    assert config["loss"]["alpha_weak_logit"] == 0.0
    assert config["data"]["allow_missing_modalities"] is False
    assert config["data"]["persistent_workers"] is False
    assert set(config["data"]["required_artifacts"]) == {
        "strong_teacher_features",
        "weak_teacher_features",
        "text_embedding",
    }
    assert config["training"]["scheduler"] == {
        "type": "CosineAnnealingLR",
        "T_max": 30,
        "interval": "epoch",
    }
    assert config["training"]["max_batches_per_epoch"] == 400
    assert config["training"]["max_optimizer_steps"] is None


def test_mm26_smoke_config_is_bounded_and_explicitly_mock_only() -> None:
    config = _load("ov_orthkd_mm26_smoke.yaml")

    assert config["reproduction"]["full_run_blocked"] is False
    assert config["reproduction"]["mock_only"] is True
    assert config["teacher_export"]["strong_visual_backend"] == "mock"
    assert config["teacher_export"]["weak_audio_backend"] == "mock"
    assert config["teacher_export"]["text_backend"] == "mock"
    assert config["data"]["batch_size"] == 2
    assert config["data"]["num_workers"] == 0
    assert config["data"]["allow_missing_modalities"] is False
    assert config["data"]["train_augment"] is False
    assert config["student"]["pretrained"] is False
    assert config["training"]["epochs"] == 2
    assert config["training"]["max_batches_per_epoch"] == 2
    assert config["training"]["scheduler"]["type"] == "cosine"


def test_smoke_fixture_builder_creates_strict_mock_manifests(tmp_path: Path) -> None:
    summary = create_mm26_smoke_fixture(tmp_path, records_per_split=4, segments=2, image_size=32)

    assert summary["mock_only"] is True
    for split in ("train", "val", "test"):
        manifest = tmp_path / "data" / "ov_ave_smoke" / f"{split}.jsonl"
        records = load_records(manifest)
        assert len(records) == 4
        first = records[0]
        assert first["split_type"] in {"seen", "unseen"}
        assert (tmp_path / first["frame_paths"][0]).is_file()
        assert (tmp_path / first["spectrogram_paths"][0]).is_file()
        assert (tmp_path / first["strong_teacher_features_path"]).is_file()
        assert (tmp_path / first["strong_teacher_logits_path"]).is_file()
        assert (tmp_path / first["weak_teacher_features_path"]).is_file()
        assert (tmp_path / first["text_embedding_path"]).is_file()
        cache_relative = Path(first["strong_teacher_features_path"]).relative_to(
            tmp_path / "data" / "teacher_cache" / "mm26_smoke"
        )
        assert cache_relative.parts[0] == split
        assert cache_relative.parts[:2] != (split, split)


def test_training_cli_overrides_are_written_into_fingerprinted_config() -> None:
    config = {"training": {}, "logging": {"log_dir": "original"}}
    args = Namespace(
        output_dir="new-output",
        epochs=17,
        max_batches_per_epoch=None,
        max_optimizer_steps=None,
        max_train_steps=None,
        early_stop_patience=4,
        early_stop_min_delta=0.125,
    )

    apply_cli_config_overrides(config, args)

    assert config["logging"]["log_dir"] == "new-output"
    assert config["training"] == {
        "epochs": 17,
        "early_stop_patience": 4,
        "early_stop_min_delta": 0.125,
    }
