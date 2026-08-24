from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _config() -> dict:
    return yaml.safe_load((ROOT / "configs/ov_orthkd_mm26_repro.yaml").read_text(encoding="utf-8"))


def test_taskbook_reconstruction_claim_and_temporal_protocol_are_exact() -> None:
    config = _config()

    assert config["reproduction"]["claim_level"] == "paper_specified_reconstruction"
    assert config["reproduction"]["asset_download_lock_required"] is True
    assert config["reproduction"]["full_run_blocked"] is True
    assert config["data"]["actual_segments"] == 10
    assert config["data"]["max_segments"] == 16
    assert config["data"]["temporal_resampling"] is False
    assert config["data"]["temporal_overflow_policy"] == "error"


def test_taskbook_student_and_visual_preprocessing_are_exact() -> None:
    config = _config()
    data = config["data"]

    assert config["student"]["visual_backbone"] == "convnextv2_tiny.fcmae_ft_in22k_in1k"
    assert config["student"]["audio_backbone"] == "tf_efficientnetv2_b2.in1k"
    assert config["student"]["pretrained"] is False
    assert config["student"]["fusion_mode"] == "concat_mlp_query_conditioned"
    assert data["batch_size"] == 4
    assert data["num_workers"] == 4
    assert data["persistent_workers"] is False
    assert data["visual_preprocessing"] == {
        "train": {
            "resize": [224, 224],
            "random_horizontal_flip_probability": 0.5,
            "color_jitter": {
                "brightness": 0.2,
                "contrast": 0.2,
                "saturation": 0.2,
                "hue": 0.02,
            },
            "to_tensor": True,
            "normalization": "imagenet_mean_std",
        },
        "validation_test": {
            "resize": [224, 224],
            "to_tensor": True,
            "normalization": "imagenet_mean_std",
        },
        "jpgs_per_segment": 1,
    }


def test_taskbook_audio_and_visual_teacher_preprocessing_are_exact() -> None:
    config = _config()
    audio = config["data"]["audio_preprocessing"]
    internvideo = config["teacher_export"]["internvideo2"]

    assert audio == {
        "source": "official_wav",
        "reference": "fixed_commit_ov_avel_imagebind_data_py",
        "sample_rate": 16000,
        "duration_seconds": 10,
        "segments": 10,
        "segment_seconds": 1,
        "repeat_waveform_to_seconds": 2,
        "representation": "kaldi_fbank",
        "num_mel_bins": 128,
        "frame_length_ms": 25,
        "frame_shift_ms": 10,
        "target_length": 204,
        "mean": -4.268,
        "std": 9.138,
        "student_channels": 3,
        "student_resize": [224, 224],
        "save_as_jpeg": False,
        "second_imagenet_normalization": False,
        "beats_source": "raw_16khz_waveform",
    }
    assert internvideo["source"] == "official_raw_video"
    assert internvideo["video_duration_seconds"] == 10
    assert internvideo["intervals"] == 10
    assert internvideo["decode"] == "deterministic_timestamps"
    assert internvideo["temporal_sampling_fps"] == 16
    assert internvideo["num_frames"] == 8
    assert internvideo["frame_sampling"] == "uniform_within_each_one_second_interval"
    assert internvideo["short_clip_policy"] == "error"
    assert internvideo["missing_video_policy"] == "block"
    assert internvideo["repo_root"] == (
        "external/teachers/InternVideo/InternVideo2/multi_modality"
    )
    assert internvideo["vision_ckpt_path"] == (
        "weights/internvideo2/B14_dist_1B_stage2.pth"
    )
    assert internvideo["vision_ckpt_sha256"] == (
        "1037a4785a830f9d663cab72da5751129e012042e428a74e019f84f016cd0be7"
    )
    assert internvideo["text_ckpt_path"] == "weights/internvideo2/mobileclip_blt.pt"
    assert internvideo["text_ckpt_sha256"] == (
        "670844f7a886dd6eff7a9285adfc53f3d3c889c03bfc8354010cb5c6bf27441a"
    )
    assert internvideo["extra_ckpt_path"] == (
        "weights/internvideo2/InternVideo2_CLIP_B14.pth"
    )
    assert internvideo["extra_ckpt_sha256"] == (
        "c76ebe61e955500056e83f137e028eb6ad5101e1ace137c62fbde6c3569fb05e"
    )
    assert config["teacher_export"]["beats"] == {
        "repo_root": "external/teachers/unilm/beats",
        "checkpoint_path": "weights/beats/BEATs_iter3_plus_AS2M.pt",
        "checkpoint_sha256": "d43cbfad4d7b56381c061d7a24774f908d4d94c72961f6eb1d9090ff18cd8d34",
    }
    assert config["teacher_export"]["clap"] == {
        "repo_root": "external/teachers/microsoft-clap",
        "checkpoint_path": "weights/clap/CLAP_weights_2023.pth",
        "checkpoint_sha256": "2cef4016d47d00eb28d153d522f397222057f95000e9bad6b9583c631284a1e6",
        "text_model_root": (
            "data/downloads/hf_cache/models--openai-community--gpt2/snapshots/"
            "607a30d783dfa663caf39e06633721c8d4cfcd7e"
        ),
        "text_model_repository": "openai-community/gpt2",
        "text_model_revision": "607a30d783dfa663caf39e06633721c8d4cfcd7e",
        "version": "2023",
        "normalize": False,
    }


def test_taskbook_training_loss_and_evaluator_values_are_exact() -> None:
    config = _config()

    assert config["training"] == {
        "deterministic": True,
        "epochs": 30,
        "learning_rate": 0.0002,
        "weight_decay": 0.0001,
        "grad_clip": 1.0,
        "mixed_precision": True,
        "max_batches_per_epoch": 400,
        "max_optimizer_steps": None,
        "early_stop_patience": None,
        "early_stop_min_delta": 0.0,
        "optimizer": {"type": "AdamW"},
        "scheduler": {"type": "CosineAnnealingLR", "T_max": 30, "interval": "epoch"},
        "model_selection": {
            "metric": "validation_segment_AP",
            "run_all_30_epochs": True,
            "save_best_checkpoint": True,
        },
    }
    assert config["loss"] | {} == {
        "projection_dim": 256,
        "temperature": 2.0,
        "alpha_bce": 1.0,
        "alpha_strong_logit": 0.0,
        "alpha_weak_logit": 0.0,
        "alpha_strong_feat": 0.4,
        "alpha_weak_feat": 0.1,
        "alpha_text_align": 0.8,
        "alpha_orth": 0.5,
        "text_alignment_mode": "paper_probability",
        "confidence_weighting": False,
        "confidence_scale": 2.0,
        "visual_l2_reduction": "mean_feature_then_masked_mean_segments",
    }
    assert config["evaluation"] == {
        "paper_f1_at_0_5_mapping": "ovavel_segment_f1_at_0_5",
        "validation_calibrated_f1_mapping": "ovavel_segment_f1_at_validation_selected_threshold",
    }


def test_taskbook_source_manifests_and_download_lock_are_bound() -> None:
    config = _config()
    readiness = config["reproduction"]["readiness"]

    assert readiness["download_lock"] == "configs/locks/mm26_download_lock.yaml"
    assert config["data"]["train_manifest"] == "data/ov_ave/source/train.jsonl"
    assert config["data"]["val_manifest"] == "data/ov_ave/source/val.jsonl"
    assert config["data"]["test_manifest"] == "data/ov_ave/source/test.jsonl"
