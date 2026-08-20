"""Immutable public-asset catalog for the MM26 OV-OrthKD reproduction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


AssetKind = Literal["weight", "data", "repository"]


@dataclass(frozen=True)
class AssetSpec:
    """A single externally acquired asset with an exact local identity."""

    name: str
    kind: AssetKind
    target: Path
    sources: tuple[str, ...]
    expected_sha256: str | None
    checkpoint_format: str | None = None
    min_bytes: int = 1

    def __post_init__(self) -> None:
        if not self.name or not self.sources:
            raise ValueError("Asset name and at least one source are required")
        if self.target.is_absolute() or ".." in self.target.parts:
            raise ValueError(f"Asset target must be repository-relative: {self.target}")
        if self.expected_sha256 is not None and (
            len(self.expected_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.expected_sha256)
        ):
            raise ValueError(f"Invalid SHA256 for asset {self.name}")
        if self.min_bytes < 1:
            raise ValueError("min_bytes must be positive")


_WEIGHTS = (
    AssetSpec(
        name="internvideo2_b14",
        kind="weight",
        target=Path("weights/internvideo2/B14_dist_1B_stage2.pth"),
        sources=(
            "https://huggingface.co/OpenGVLab/InternVideo2_distillation_models/resolve/main/stage1/B14/B14_dist_1B_stage2/pytorch_model.bin?download=true",
            "https://hf-mirror.com/OpenGVLab/InternVideo2_distillation_models/resolve/main/stage1/B14/B14_dist_1B_stage2/pytorch_model.bin?download=true",
        ),
        expected_sha256="1037a4785a830f9d663cab72da5751129e012042e428a74e019f84f016cd0be7",
        checkpoint_format="torch_state_dict",
        min_bytes=1024 * 1024,
    ),
    AssetSpec(
        name="internvideo2_clip_b14",
        kind="weight",
        target=Path("weights/internvideo2/InternVideo2_CLIP_B14.pth"),
        sources=(
            "https://huggingface.co/OpenGVLab/InternVideo2_distillation_models/resolve/main/clip/B14/pytorch_model.bin?download=true",
            "https://hf-mirror.com/OpenGVLab/InternVideo2_distillation_models/resolve/main/clip/B14/pytorch_model.bin?download=true",
        ),
        expected_sha256="c76ebe61e955500056e83f137e028eb6ad5101e1ace137c62fbde6c3569fb05e",
        checkpoint_format="torch_state_dict",
        min_bytes=1024 * 1024,
    ),
    AssetSpec(
        name="mobileclip_blt",
        kind="weight",
        target=Path("weights/internvideo2/mobileclip_blt.pt"),
        sources=(
            "https://docs-assets.developer.apple.com/ml-research/datasets/mobileclip/mobileclip_blt.pt",
            "https://huggingface.co/apple/MobileCLIP-B-LT/resolve/main/mobileclip_blt.pt?download=true",
            "https://hf-mirror.com/apple/MobileCLIP-B-LT/resolve/main/mobileclip_blt.pt?download=true",
        ),
        expected_sha256="670844f7a886dd6eff7a9285adfc53f3d3c889c03bfc8354010cb5c6bf27441a",
        checkpoint_format="torch_checkpoint",
        min_bytes=1024 * 1024,
    ),
    AssetSpec(
        name="beats_iter3_plus_as2m",
        kind="weight",
        target=Path("weights/beats/BEATs_iter3_plus_AS2M.pt"),
        sources=(
            "https://1drv.ms/u/s!AqeByhGUtINrgcpke6_lRSZEKD5j2Q?e=A3FpOf",
            "https://huggingface.co/lpepino/beats_ckpts/resolve/main/BEATs_iter3_plus_AS2M.pt?download=true",
            "https://hf-mirror.com/lpepino/beats_ckpts/resolve/main/BEATs_iter3_plus_AS2M.pt?download=true",
        ),
        expected_sha256="d43cbfad4d7b56381c061d7a24774f908d4d94c72961f6eb1d9090ff18cd8d34",
        checkpoint_format="beats_pretrained",
        min_bytes=1024 * 1024,
    ),
    AssetSpec(
        name="clap_2023",
        kind="weight",
        target=Path("weights/clap/CLAP_weights_2023.pth"),
        sources=(
            "https://huggingface.co/microsoft/msclap/resolve/main/CLAP_weights_2023.pth?download=true",
            "https://hf-mirror.com/microsoft/msclap/resolve/main/CLAP_weights_2023.pth?download=true",
            "https://zenodo.org/api/records/8378278",
            "https://zenodo.org/records/8378278/files/CLAP_weights_2023.pth?download=1",
        ),
        expected_sha256="2cef4016d47d00eb28d153d522f397222057f95000e9bad6b9583c631284a1e6",
        checkpoint_format="torch_state_dict",
        min_bytes=1024 * 1024,
    ),
)

_DATA = (
    AssetSpec(
        name="ovave_preprocessed",
        kind="data",
        target=Path("data/downloads/incoming/ovave_preprocessed"),
        sources=(
            "https://mailhfuteducn-my.sharepoint.com/:u:/g/personal/2018110964_mail_hfut_edu_cn/Efm9NKaGQFBAsOC2ZOMZRvcB26TKXJ84H4VW6g8BR5SukQ?e=OPgMOt",
        ),
        expected_sha256=None,
    ),
    AssetSpec(
        name="ovave_raw_videos",
        kind="data",
        target=Path("data/downloads/incoming/ovave_raw_videos"),
        sources=(
            "https://mailhfuteducn-my.sharepoint.com/:u:/g/personal/2018110964_mail_hfut_edu_cn/EcVHOp2zOyVHvi1Au-i1zFQBf5wQNi-Yff9Aso_SJ4MV8Q?e=OeRlQh",
        ),
        expected_sha256=None,
    ),
)

_REPOSITORIES = (
    AssetSpec(
        name="internvideo",
        kind="repository",
        target=Path("external/teachers/InternVideo"),
        sources=("https://github.com/OpenGVLab/InternVideo.git",),
        expected_sha256=None,
    ),
    AssetSpec(
        name="unilm",
        kind="repository",
        target=Path("external/teachers/unilm"),
        sources=("https://github.com/microsoft/unilm.git",),
        expected_sha256=None,
    ),
    AssetSpec(
        name="microsoft_clap",
        kind="repository",
        target=Path("external/teachers/microsoft-clap"),
        sources=("https://github.com/microsoft/CLAP.git",),
        expected_sha256=None,
    ),
    AssetSpec(
        name="mobileclip",
        kind="repository",
        target=Path("external/teachers/ml-mobileclip"),
        sources=("https://github.com/apple/ml-mobileclip.git",),
        expected_sha256=None,
    ),
    AssetSpec(
        name="ov_avel",
        kind="repository",
        target=Path("external/OV-AVEL"),
        sources=("https://github.com/jasongief/OV-AVEL.git",),
        expected_sha256=None,
    ),
)


def weight_assets() -> tuple[AssetSpec, ...]:
    return _WEIGHTS


def data_assets() -> tuple[AssetSpec, ...]:
    return _DATA


def repository_assets() -> tuple[AssetSpec, ...]:
    return _REPOSITORIES


def all_assets() -> tuple[AssetSpec, ...]:
    return _WEIGHTS + _DATA + _REPOSITORIES
