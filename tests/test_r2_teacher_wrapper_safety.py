from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from src.teachers.internvideo2_visual import InternVideo2ClipB14Teacher

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


def test_internvideo_frame_selection_rejects_silent_short_clip_repetition() -> None:
    teacher = InternVideo2ClipB14Teacher.__new__(InternVideo2ClipB14Teacher)
    teacher.num_frames = 2

    with pytest.raises(ValueError, match="requires exactly 2 frames"):
        teacher._select_frame_paths(["single.png"])
