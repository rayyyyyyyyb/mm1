from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
import torch

from src.teachers import clap_text
from src.teachers.clap_text import _strict_load_clap_checkpoint
from src.teachers.internvideo2_visual import (
    InternVideo2ClipB14Teacher,
    _compose_internvideo_checkpoint,
)
from src.teachers import beats_audio

try:
    from src.teachers.beats_audio import _load_waveform_array
except (ImportError, ModuleNotFoundError):
    _load_waveform_array = None

try:
    from src.teachers.common import verify_checkpoint_sha256
except ImportError:
    verify_checkpoint_sha256 = None


def test_beats_numpy_waveforms_disable_pickle_and_require_exact_npz_key(tmp_path: Path) -> None:
    assert _load_waveform_array is not None, "safe BEATs NumPy loader is missing"
    waveform = np.asarray([0.1, -0.2, 0.3], dtype=np.float32)
    np.save(tmp_path / "wave.npy", waveform, allow_pickle=False)
    np.savez(tmp_path / "wave.npz", waveform=waveform)

    assert _load_waveform_array(tmp_path / "wave.npy").tolist() == pytest.approx(waveform.tolist())
    assert _load_waveform_array(tmp_path / "wave.npz").tolist() == pytest.approx(waveform.tolist())

    np.savez(tmp_path / "wrong.npz", arr_0=waveform)
    with pytest.raises(ValueError, match="exactly one npz key named 'waveform'"):
        _load_waveform_array(tmp_path / "wrong.npz")
    np.save(tmp_path / "object.npy", np.asarray([{"unsafe": True}], dtype=object), allow_pickle=True)
    with pytest.raises(ValueError, match="Object arrays cannot be loaded"):
        _load_waveform_array(tmp_path / "object.npy")
    np.save(tmp_path / "nonfinite.npy", np.asarray([0.0, np.nan], dtype=np.float32))
    with pytest.raises(ValueError, match="non-empty and finite"):
        _load_waveform_array(tmp_path / "nonfinite.npy")


def test_beats_zero_pads_short_official_wav_to_the_ten_second_task_window(
) -> None:
    normalize = getattr(beats_audio, "_fit_waveform_to_task_duration", None)
    assert callable(normalize), "BEATs task-window padding helper is missing"

    fitted = normalize(
        torch.ones(9 * 16_000),
        sample_rate=16_000,
        duration_seconds=10,
        short_policy="zero_pad_to_task_duration",
        long_policy="truncate_to_task_duration",
    )

    assert list(fitted.shape) == [10 * 16_000]
    assert torch.count_nonzero(fitted[: 9 * 16_000]).item() == 9 * 16_000
    assert torch.count_nonzero(fitted[9 * 16_000 :]).item() == 0


def test_checkpoint_hash_is_verified_before_any_deserialization(tmp_path: Path) -> None:
    assert verify_checkpoint_sha256 is not None, "checkpoint hash binding helper is missing"
    checkpoint = tmp_path / "teacher.pt"
    checkpoint.write_bytes(b"locked checkpoint bytes")
    expected = hashlib.sha256(checkpoint.read_bytes()).hexdigest()

    evidence = verify_checkpoint_sha256(checkpoint, expected, label="teacher")

    assert evidence == {"bytes": checkpoint.stat().st_size, "sha256": expected}
    with pytest.raises(RuntimeError, match="SHA256 mismatch"):
        verify_checkpoint_sha256(checkpoint, "0" * 64, label="teacher")
    with pytest.raises(ValueError, match="64 lowercase hex"):
        verify_checkpoint_sha256(checkpoint, "UNRESOLVED", label="teacher")


def test_internvideo_canonical_keyframe_mode_rejects_png_extension() -> None:
    teacher = InternVideo2ClipB14Teacher.__new__(InternVideo2ClipB14Teacher)
    teacher.input_mode = "official_segment_keyframes"
    teacher.frame_expansion = "repeat_last_to_num_frames"
    teacher.num_frames = 8

    with pytest.raises(ValueError, match="official .jpg extension"):
        teacher._select_frame_paths(["single.png"])


def test_clap_checkpoint_is_weights_only_and_strict(tmp_path: Path, monkeypatch) -> None:
    model = torch.nn.Linear(3, 2)
    checkpoint = tmp_path / "clap.pth"
    torch.save({"model": model.state_dict()}, checkpoint)
    real_load = torch.load
    observed: dict[str, object] = {}

    def recording_load(*args, **kwargs):
        observed.update(kwargs)
        return real_load(*args, **kwargs)

    monkeypatch.setattr(torch, "load", recording_load)
    _strict_load_clap_checkpoint(model, checkpoint)

    assert observed["weights_only"] is True
    assert observed["map_location"] == "cpu"

    torch.save({"model": {"weight": model.weight.detach().clone()}}, checkpoint)
    with pytest.raises(RuntimeError, match="bias"):
        _strict_load_clap_checkpoint(model, checkpoint)


def test_clap_tokenizer_uses_the_pinned_upstream_padding_token() -> None:
    class Tokenizer:
        pad_token = None

        def add_special_tokens(self, value):
            self.pad_token = value["pad_token"]
            return 0

    tokenizer = Tokenizer()
    configure = getattr(clap_text, "_configure_clap_tokenizer", None)

    assert callable(configure), "CLAP tokenizer compatibility helper is missing"
    configure(tokenizer)

    assert tokenizer.pad_token == "!"


def test_clap_strict_load_accepts_only_value_verified_nonpersistent_gpt2_masks(
    tmp_path: Path,
) -> None:
    class Attention(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.weight = torch.nn.Parameter(torch.ones(1))
            self.register_buffer(
                "bias", torch.tril(torch.ones(1, 1, 4, 4)).bool(), persistent=False
            )
            self.register_buffer("masked_bias", torch.tensor(-1e4), persistent=False)

    class Caption(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.base = torch.nn.Module()
            layer = torch.nn.Module()
            layer.attn = Attention()
            self.base.h = torch.nn.ModuleList([layer])

    class Model(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.caption_encoder = Caption()

    model = Model()
    state = dict(model.state_dict())
    state.update({name: value.clone() for name, value in model.named_buffers()})
    state["caption_encoder.base.h.0.attn.bias"] = state[
        "caption_encoder.base.h.0.attn.bias"
    ].float()
    checkpoint = tmp_path / "clap_compat.pth"
    torch.save({"model": state}, checkpoint)

    _strict_load_clap_checkpoint(model, checkpoint)

    state["caption_encoder.base.h.0.attn.masked_bias"] = torch.tensor(-999.0)
    torch.save({"model": state}, checkpoint)
    with pytest.raises(RuntimeError, match="buffer value mismatch"):
        _strict_load_clap_checkpoint(model, checkpoint)


def test_internvideo_checkpoint_composition_matches_fixed_upstream_rules() -> None:
    vision = {
        "encoder.weight": torch.ones(1),
        "clip_decoder.block": torch.ones(1),
        "clip_pos_embed": torch.ones(1),
    }
    text = {
        "text_encoder.token_embedding.weight": torch.ones(1),
        "unrelated": torch.ones(1),
    }
    extra = {
        "temp": torch.ones(()),
        "vision_align.1.bias": torch.ones(1),
    }

    combined = _compose_internvideo_checkpoint(vision, text, extra)

    assert set(combined) == {
        "vision_encoder.encoder.weight",
        "text_encoder.token_embedding.weight",
        "temp",
        "vision_align.1.bias",
    }
