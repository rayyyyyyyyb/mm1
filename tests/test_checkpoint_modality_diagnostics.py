from __future__ import annotations

import numpy as np
import pytest
from pathlib import Path
import subprocess
import sys
import torch
from torch import nn

from scripts.diagnose_checkpoint_modalities import (
    ABLATION_MODES,
    apply_content_ablation,
    collect_ablation_matrix,
    collect_ablation_predictions,
    summarize_model_paths,
    summarize_prediction_response,
    summarize_tensor_scale,
)


def _batch() -> dict[str, object]:
    return {
        "id": ["sample-a", "sample-b"],
        "query": ["query-a", "query-b"],
        "split_type": ["seen", "unseen"],
        "frame": torch.tensor([[[[[1.0]]], [[[2.0]]]], [[[[3.0]]], [[[4.0]]]]]),
        "spectrogram": torch.tensor(
            [[[[[10.0]]], [[[20.0]]]], [[[[30.0]]], [[[40.0]]]]]
        ),
        "text_embedding": torch.zeros(2, 1),
        "segment_label": torch.tensor([[1.0, 0.0], [0.0, 1.0]]),
        "sequence_mask": torch.ones(2, 2),
        "frame_valid": torch.tensor([[1.0, 0.0], [1.0, 1.0]]),
        "audio_valid": torch.tensor([[1.0, 1.0], [0.0, 1.0]]),
    }


@pytest.mark.parametrize(
    "mode,visual_zero,audio_zero",
    [
        ("original", False, False),
        ("visual_zero", True, False),
        ("audio_zero", False, True),
        ("both_zero", True, True),
    ],
)
def test_content_ablation_zeros_only_selected_inputs_and_preserves_validity(
    mode: str, visual_zero: bool, audio_zero: bool
) -> None:
    source = _batch()
    original_frame = source["frame"].clone()
    original_audio = source["spectrogram"].clone()

    result = apply_content_ablation(source, mode)

    assert torch.equal(source["frame"], original_frame)
    assert torch.equal(source["spectrogram"], original_audio)
    assert torch.equal(result["frame_valid"], source["frame_valid"])
    assert torch.equal(result["audio_valid"], source["audio_valid"])
    assert torch.equal(result["sequence_mask"], source["sequence_mask"])
    assert torch.count_nonzero(result["frame"]).item() == (
        0 if visual_zero else torch.count_nonzero(original_frame).item()
    )
    assert torch.count_nonzero(result["spectrogram"]).item() == (
        0 if audio_zero else torch.count_nonzero(original_audio).item()
    )


def test_content_ablation_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="Unsupported ablation mode"):
        apply_content_ablation(_batch(), "drop-validity")


def test_tensor_scale_summary_has_literal_valid_row_and_temporal_semantics() -> None:
    tensor = torch.tensor(
        [[[3.0, 4.0], [0.0, 0.0]], [[6.0, 8.0], [9.0, 12.0]]]
    )
    mask = torch.tensor([[1, 1], [1, 0]])

    summary = summarize_tensor_scale(tensor, mask)

    assert summary["shape"] == [2, 2, 2]
    assert summary["valid_rows"] == 3
    assert summary["feature_dim"] == 2
    assert summary["absolute_mean"] == pytest.approx(3.5)
    assert summary["rms"] == pytest.approx(np.sqrt(125.0 / 6.0))
    assert summary["row_l2_mean"] == pytest.approx(5.0)
    assert summary["within_sample_temporal_std_mean"] == pytest.approx(0.875)


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA-only device-boundary regression")
def test_tensor_scale_accepts_cpu_mask_for_cuda_model_output() -> None:
    tensor = torch.ones(1, 2, 3, device="cuda")
    cpu_mask = torch.ones(1, 2)

    summary = summarize_tensor_scale(tensor, cpu_mask)

    assert summary["valid_rows"] == 2
    assert summary["feature_dim"] == 3


def _valid_outputs() -> dict[str, torch.Tensor]:
    base = torch.arange(8, dtype=torch.float32).reshape(2, 2, 2)
    return {
        "query_features": base,
        "visual_tokens": base + 1,
        "audio_tokens": base + 2,
        "fused_tokens_before_position": base + 3,
        "shared_features": base + 4,
        "decision_features": base + 5,
        "segment_logits": base[..., 0],
    }


def test_model_path_summary_requires_all_finite_bt_aligned_outputs() -> None:
    mask = torch.ones(2, 2)
    summary = summarize_model_paths(_valid_outputs(), mask)
    assert set(summary) == {
        "query_features",
        "visual_tokens",
        "audio_tokens",
        "fused_tokens_before_position",
        "shared_features",
        "decision_features",
        "segment_logits",
    }

    missing = _valid_outputs()
    del missing["audio_tokens"]
    with pytest.raises(RuntimeError, match="audio_tokens"):
        summarize_model_paths(missing, mask)

    nonfinite = _valid_outputs()
    nonfinite["shared_features"] = nonfinite["shared_features"].clone()
    nonfinite["shared_features"][0, 0, 0] = torch.nan
    with pytest.raises(ValueError, match="shared_features"):
        summarize_model_paths(nonfinite, mask)

    wrong_shape = _valid_outputs()
    wrong_shape["decision_features"] = torch.zeros(2, 3, 2)
    with pytest.raises(ValueError, match="decision_features"):
        summarize_model_paths(wrong_shape, mask)


class _DummyStudent(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict[str, torch.Tensor]] = []

    def forward(self, **kwargs: torch.Tensor) -> dict[str, torch.Tensor]:
        self.calls.append({name: value.detach().clone() for name, value in kwargs.items()})
        visual = kwargs["frame"].mean(dim=(-3, -2, -1)).unsqueeze(-1)
        audio = kwargs["spectrogram"].mean(dim=(-3, -2, -1)).unsqueeze(-1)
        query = kwargs["text_embedding"][:, None, :].expand_as(visual)
        fused = visual + audio + query
        return {
            "query_features": query,
            "visual_tokens": visual,
            "audio_tokens": audio,
            "fused_tokens_before_position": fused,
            "shared_features": fused,
            "decision_features": fused,
            "segment_logits": fused.squeeze(-1),
        }


def test_collection_keeps_t2_alignment_and_receipts_both_zero_semantics() -> None:
    student = _DummyStudent()

    predictions, paths = collect_ablation_predictions(
        student,
        [_batch()],
        torch.device("cpu"),
        mode="both_zero",
        expected_task_segments=2,
        collect_paths=True,
    )

    assert predictions["sample_offsets"].tolist() == [0, 2, 4]
    assert predictions["segment_indices"].tolist() == [0, 1, 0, 1]
    assert predictions["labels"].tolist() == [1.0, 0.0, 0.0, 1.0]
    assert predictions["logits"].tolist() == [0.0, 0.0, 0.0, 0.0]
    assert set(paths) == set(_valid_outputs())
    assert len(student.calls) == 1
    call = student.calls[0]
    assert torch.count_nonzero(call["frame"]).item() == 0
    assert torch.count_nonzero(call["spectrogram"]).item() == 0
    assert torch.equal(call["frame_valid"], _batch()["frame_valid"])
    assert torch.equal(call["audio_valid"], _batch()["audio_valid"])

    response = summarize_prediction_response(predictions, threshold=0.5)
    assert response["sample_count"] == 2
    assert response["segment_count"] == 4
    assert response["predicted_positive_rate"] == pytest.approx(1.0)
    assert response["within_sample_logit_std"]["mean"] == pytest.approx(0.0)


def test_full_ablation_matrix_reads_loader_once_and_changes_only_content() -> None:
    class CountingLoader:
        def __init__(self) -> None:
            self.iterations = 0

        def __iter__(self):
            self.iterations += 1
            yield _batch()

    loader = CountingLoader()
    student = _DummyStudent()

    predictions, original_paths = collect_ablation_matrix(
        student,
        loader,
        torch.device("cpu"),
        expected_task_segments=2,
    )

    assert loader.iterations == 1
    assert len(student.calls) == 4
    assert predictions["original"]["logits"].tolist() == [11.0, 22.0, 33.0, 44.0]
    assert predictions["visual_zero"]["logits"].tolist() == [10.0, 20.0, 30.0, 40.0]
    assert predictions["audio_zero"]["logits"].tolist() == [1.0, 2.0, 3.0, 4.0]
    assert predictions["both_zero"]["logits"].tolist() == [0.0, 0.0, 0.0, 0.0]
    assert set(original_paths) == set(_valid_outputs())


def test_collection_rejects_non_task_length_before_reporting_metrics() -> None:
    batch = _batch()
    batch["segment_label"] = torch.ones(2, 3)
    batch["sequence_mask"] = torch.ones(2, 3)

    with pytest.raises((ValueError, RuntimeError), match="10|2|shape|segment|temporal"):
        collect_ablation_predictions(
            _DummyStudent(),
            [batch],
            torch.device("cpu"),
            mode="original",
            expected_task_segments=2,
            collect_paths=False,
        )


def test_declared_ablation_matrix_is_exact() -> None:
    assert ABLATION_MODES == ("original", "visual_zero", "audio_zero", "both_zero")


def test_cli_help_runs_without_importing_timm_from_an_external_cwd(
    tmp_path: Path,
) -> None:
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "diagnose_checkpoint_modalities.py"
    )

    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--checkpoint" in completed.stdout
