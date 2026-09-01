from __future__ import annotations

from pathlib import Path

import pytest
import torch

from scripts import train_ov_orthkd as train_module


def test_diagnostic_checkpoint_is_absent_when_step_is_not_requested(
    tmp_path: Path,
) -> None:
    result = train_module.save_requested_diagnostic_checkpoint(
        checkpoint={"global_step": 399},
        diagnostic_config={"checkpoint_steps": [400, 800, 1200]},
        output_dir=tmp_path,
        global_step=399,
    )

    assert result is None
    assert not (tmp_path / "diagnostic_checkpoints").exists()


def test_diagnostic_checkpoint_saves_the_exact_supplied_payload(tmp_path: Path) -> None:
    checkpoint = {
        "global_step": 400,
        "student": {"weight": torch.tensor([1.0, 2.0])},
    }

    result = train_module.save_requested_diagnostic_checkpoint(
        checkpoint=checkpoint,
        diagnostic_config={"checkpoint_steps": [400, 800, 1200]},
        output_dir=tmp_path,
        global_step=400,
    )

    expected_path = tmp_path / "diagnostic_checkpoints" / "step_000400.pt"
    assert result == expected_path
    loaded = torch.load(expected_path, map_location="cpu", weights_only=True)
    assert loaded["global_step"] == checkpoint["global_step"]
    assert torch.equal(loaded["student"]["weight"], checkpoint["student"]["weight"])


@pytest.mark.parametrize(
    "checkpoint_steps",
    [400, [0], [400, 400], [800, 400], [400.0]],
)
def test_diagnostic_checkpoint_steps_fail_closed_on_invalid_configuration(
    tmp_path: Path,
    checkpoint_steps: object,
) -> None:
    with pytest.raises(
        ValueError,
        match="checkpoint_steps must be a strictly increasing list of positive integers",
    ):
        train_module.save_requested_diagnostic_checkpoint(
            checkpoint={"global_step": 400},
            diagnostic_config={"checkpoint_steps": checkpoint_steps},
            output_dir=tmp_path,
            global_step=400,
        )


def test_diagnostic_checkpoint_refuses_to_overwrite_existing_evidence(
    tmp_path: Path,
) -> None:
    checkpoint_dir = tmp_path / "diagnostic_checkpoints"
    checkpoint_dir.mkdir()
    existing = checkpoint_dir / "step_000400.pt"
    existing.write_bytes(b"existing evidence")

    with pytest.raises(FileExistsError, match="diagnostic checkpoint already exists"):
        train_module.save_requested_diagnostic_checkpoint(
            checkpoint={"global_step": 400},
            diagnostic_config={"checkpoint_steps": [400]},
            output_dir=tmp_path,
            global_step=400,
        )

    assert existing.read_bytes() == b"existing evidence"


def test_diagnostic_checkpoint_rejects_payload_step_mismatch(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="checkpoint payload global_step mismatch"):
        train_module.save_requested_diagnostic_checkpoint(
            checkpoint={"global_step": 399},
            diagnostic_config={"checkpoint_steps": [400]},
            output_dir=tmp_path,
            global_step=400,
        )
