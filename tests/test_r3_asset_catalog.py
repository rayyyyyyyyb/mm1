from __future__ import annotations

from scripts.assets.mm26_asset_catalog import (
    all_assets,
    data_assets,
    repository_assets,
    weight_assets,
)


EXPECTED_WEIGHTS = {
    "internvideo2_b14": (
        "weights/internvideo2/B14_dist_1B_stage2.pth",
        "1037a4785a830f9d663cab72da5751129e012042e428a74e019f84f016cd0be7",
    ),
    "internvideo2_clip_b14": (
        "weights/internvideo2/InternVideo2_CLIP_B14.pth",
        "c76ebe61e955500056e83f137e028eb6ad5101e1ace137c62fbde6c3569fb05e",
    ),
    "mobileclip_blt": (
        "weights/internvideo2/mobileclip_blt.pt",
        "670844f7a886dd6eff7a9285adfc53f3d3c889c03bfc8354010cb5c6bf27441a",
    ),
    "beats_iter3_plus_as2m": (
        "weights/beats/BEATs_iter3_plus_AS2M.pt",
        "d43cbfad4d7b56381c061d7a24774f908d4d94c72961f6eb1d9090ff18cd8d34",
    ),
    "clap_2023": (
        "weights/clap/CLAP_weights_2023.pth",
        "2cef4016d47d00eb28d153d522f397222057f95000e9bad6b9583c631284a1e6",
    ),
}


def test_weight_catalog_has_exact_targets_hashes_and_unique_sources() -> None:
    specs = {item.name: item for item in weight_assets()}

    assert set(specs) == set(EXPECTED_WEIGHTS)
    for name, (target, sha256) in EXPECTED_WEIGHTS.items():
        spec = specs[name]
        assert spec.kind == "weight"
        assert spec.target.as_posix() == target
        assert spec.expected_sha256 == sha256
        assert spec.sources
        assert len(spec.sources) == len(set(spec.sources))
        assert all(source.startswith("https://") for source in spec.sources)


def test_data_catalog_contains_only_the_two_official_sharepoint_assets() -> None:
    specs = {item.name: item for item in data_assets()}

    assert set(specs) == {"ovave_preprocessed", "ovave_raw_videos"}
    assert specs["ovave_preprocessed"].target.as_posix() == (
        "data/downloads/incoming/ovave_preprocessed"
    )
    assert specs["ovave_raw_videos"].target.as_posix() == (
        "data/downloads/incoming/ovave_raw_videos"
    )
    assert all("mailhfuteducn-my.sharepoint.com" in item.sources[0] for item in specs.values())
    assert all(item.expected_sha256 is None for item in specs.values())


def test_repository_catalog_has_exact_official_origins_and_targets() -> None:
    specs = {item.name: item for item in repository_assets()}

    assert {name: (item.sources[0], item.target.as_posix()) for name, item in specs.items()} == {
        "internvideo": (
            "https://github.com/OpenGVLab/InternVideo.git",
            "external/teachers/InternVideo",
        ),
        "unilm": (
            "https://github.com/microsoft/unilm.git",
            "external/teachers/unilm",
        ),
        "microsoft_clap": (
            "https://github.com/microsoft/CLAP.git",
            "external/teachers/microsoft-clap",
        ),
        "mobileclip": (
            "https://github.com/apple/ml-mobileclip.git",
            "external/teachers/ml-mobileclip",
        ),
        "ov_avel": (
            "https://github.com/jasongief/OV-AVEL.git",
            "external/OV-AVEL",
        ),
    }


def test_all_asset_names_and_targets_are_unique() -> None:
    specs = all_assets()

    assert len({item.name for item in specs}) == len(specs)
    assert len({item.target.as_posix().casefold() for item in specs}) == len(specs)
