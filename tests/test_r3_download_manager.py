from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.assets.download_mm26_assets import (
    DownloadPaths,
    SourceProbe,
    _merged_input,
    build_windows_runner_script,
    build_aria2_arguments,
    build_aria2_input,
    connection_limit_for_recent_statuses,
    parse_cim_launch_result,
    prepare_asset,
    probe_and_rank_sources,
    rank_sources,
    select_weight_assets,
)
from scripts.assets.mm26_asset_catalog import AssetSpec


def _spec(payload: bytes = b"verified model bytes") -> AssetSpec:
    return AssetSpec(
        name="fixture_weight",
        kind="weight",
        target=Path("weights/fixture/model.pth"),
        sources=(
            "https://official.example/model.pth",
            "https://mirror.example/model.pth",
        ),
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        checkpoint_format=None,
        min_bytes=1,
    )


def test_aria2_arguments_are_resumable_unbounded_and_non_overwriting(tmp_path: Path) -> None:
    paths = DownloadPaths.from_root(tmp_path)

    arguments = build_aria2_arguments(paths, connections=8)

    assert "--continue=true" in arguments
    assert "--max-tries=0" in arguments
    assert "--retry-wait=15" in arguments
    assert "--lowest-speed-limit=0" in arguments
    assert not any(argument == "--lowest-speed-limit=10K" for argument in arguments)
    assert "--allow-overwrite=false" in arguments
    assert "--auto-file-renaming=false" in arguments
    assert "--file-allocation=none" in arguments
    assert "--max-connection-per-server=8" in arguments
    assert "--split=8" in arguments
    assert f"--save-session={paths.session_file}" in arguments
    assert f"--input-file={paths.input_file}" in arguments
    assert "--enable-rpc=true" in arguments
    assert "--rpc-listen-all=false" in arguments
    assert "--rpc-listen-port=6800" in arguments
    assert not any(argument.startswith("--stop-with-process") for argument in arguments)


def test_single_asset_selection_supports_parallel_fallback_without_redownloading_others() -> None:
    selected = select_weight_assets(["clap_2023"])

    assert [spec.name for spec in selected] == ["clap_2023"]
    try:
        select_weight_assets(["not-a-real-asset"])
    except ValueError as error:
        assert "Unknown weight asset" in str(error)
    else:
        raise AssertionError("unknown single-asset selection was accepted")


def test_aria2_input_uses_incoming_path_and_exact_checksum(tmp_path: Path) -> None:
    spec = _spec()
    paths = DownloadPaths.from_root(tmp_path)

    text = build_aria2_input((spec,), paths)

    assert "https://official.example/model.pth\thttps://mirror.example/model.pth" in text
    assert f"  dir={paths.incoming_path(spec).parent}" in text
    assert "  out=model.pth" in text
    assert f"  checksum=sha-256={spec.expected_sha256}" in text
    assert str(tmp_path / "weights") not in text


def test_prepare_asset_skips_only_valid_final_file(tmp_path: Path) -> None:
    payload = b"verified model bytes"
    spec = _spec(payload)
    paths = DownloadPaths.from_root(tmp_path)
    final_path = paths.final_path(spec)
    final_path.parent.mkdir(parents=True)
    final_path.write_bytes(payload)

    plan = prepare_asset(spec, paths)

    assert plan.action == "skip_verified"
    assert plan.validation is not None
    assert plan.validation.status == "passed"
    assert final_path.read_bytes() == payload


def test_prepare_asset_quarantines_wrong_final_bytes_without_overwrite(tmp_path: Path) -> None:
    spec = _spec(b"expected")
    paths = DownloadPaths.from_root(tmp_path)
    final_path = paths.final_path(spec)
    final_path.parent.mkdir(parents=True)
    final_path.write_bytes(b"wrong")

    plan = prepare_asset(spec, paths)

    assert plan.action == "quarantined"
    assert not final_path.exists()
    assert plan.quarantine_path is not None
    assert plan.quarantine_path.read_bytes() == b"wrong"
    assert paths.quarantine_dir in plan.quarantine_path.parents


def test_prepare_asset_promotes_verified_incoming_file_atomically(tmp_path: Path) -> None:
    payload = b"verified model bytes"
    spec = _spec(payload)
    paths = DownloadPaths.from_root(tmp_path)
    incoming = paths.incoming_path(spec)
    incoming.parent.mkdir(parents=True)
    incoming.write_bytes(payload)

    plan = prepare_asset(spec, paths)

    assert plan.action == "promoted"
    assert paths.final_path(spec).read_bytes() == payload
    assert not incoming.exists()


def test_prepare_asset_detects_resumable_aria2_control_file(tmp_path: Path) -> None:
    spec = _spec()
    paths = DownloadPaths.from_root(tmp_path)
    incoming = paths.incoming_path(spec)
    incoming.parent.mkdir(parents=True)
    incoming.write_bytes(b"partial")
    Path(str(incoming) + ".aria2").write_bytes(b"control")

    plan = prepare_asset(spec, paths)

    assert plan.action == "resume"
    assert plan.validation is None
    assert incoming.read_bytes() == b"partial"
    assert Path(str(incoming) + ".aria2").exists()


def test_resume_input_prefers_generated_block_over_duplicate_session_task(
    tmp_path: Path,
) -> None:
    paths = DownloadPaths.from_root(tmp_path)
    generated = (
        "https://current.example/model.pth\n"
        f"  dir={paths.incoming_dir / 'weights' / 'fixture'}\n"
        "  out=model.pth\n"
        "  checksum=sha-256=" + "a" * 64 + "\n"
    )
    session = (
        "https://old.example/model.pth\n"
        f"  dir={paths.incoming_dir / 'weights' / 'fixture'}\n"
        "  out=model.pth\n"
        "  gid=old-gid\n"
    )

    merged = _merged_input(generated, tmp_path / "aria2.session")
    assert "current.example" in merged

    session_path = tmp_path / "aria2.session"
    session_path.write_text(session, encoding="utf-8")
    merged = _merged_input(generated, session_path)

    assert merged.count("  out=model.pth") == 1
    assert "current.example" in merged
    assert "old.example" not in merged
    assert "old-gid" not in merged


def test_repeated_throttling_reduces_connection_limit() -> None:
    assert connection_limit_for_recent_statuses([200, 429, 429]) == 2
    assert connection_limit_for_recent_statuses([503, 503]) == 2
    assert connection_limit_for_recent_statuses([429, 200, 503]) == 8
    assert connection_limit_for_recent_statuses([]) == 8


def test_rank_sources_filters_non_binary_and_orders_fastest_first() -> None:
    spec = _spec()
    results = (
        SourceProbe(
            url=spec.sources[0],
            status_code=206,
            elapsed_seconds=2.0,
            content_type="application/octet-stream",
            content_length=10_000_000,
            valid_binary=True,
            errors=(),
        ),
        SourceProbe(
            url=spec.sources[1],
            status_code=200,
            elapsed_seconds=0.1,
            content_type="text/html",
            content_length=5000,
            valid_binary=False,
            errors=("html_payload",),
        ),
        SourceProbe(
            url="https://fast.example/model.pth",
            status_code=206,
            elapsed_seconds=0.5,
            content_type="application/octet-stream",
            content_length=10_000_000,
            valid_binary=True,
            errors=(),
        ),
    )

    assert rank_sources(spec, results) == (
        "https://fast.example/model.pth",
        spec.sources[0],
    )


def test_windows_runner_survives_ssh_and_persists_exit_status(tmp_path: Path) -> None:
    paths = DownloadPaths.from_root(tmp_path)
    command = [r"E:\tool dir\aria2c.exe", "--continue=true", f"--input-file={paths.input_file}"]

    script = build_windows_runner_script(command, paths)

    assert script.startswith("@echo off\n")
    assert f'cd /d "{paths.root}"' in script
    assert '"E:\\tool dir\\aria2c.exe"' in script
    assert f'>> "{paths.console_log_file}" 2>&1' in script
    assert f'> "{paths.runner_state_tmp}"' in script
    assert f'move /Y "{paths.runner_state_tmp}" "{paths.runner_state}"' in script
    assert '"status":"exited"' in script
    assert '"exit_code":%MM26_EXIT_CODE%' in script


def test_cim_launch_result_requires_success_and_positive_pid() -> None:
    assert parse_cim_launch_result('{"ReturnValue":0,"ProcessId":8388}') == 8388

    for payload in (
        '{"ReturnValue":2,"ProcessId":0}',
        '{"ReturnValue":0,"ProcessId":0}',
        "not-json",
    ):
        try:
            parse_cim_launch_result(payload)
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"invalid CIM result was accepted: {payload}")


def test_fresh_successful_source_probe_cache_survives_transient_network_failure(
    tmp_path: Path, monkeypatch
) -> None:
    spec = _spec()
    paths = DownloadPaths.from_root(tmp_path)
    paths.create()
    cache = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "results": [
            {
                "url": spec.sources[0],
                "status_code": 206,
                "elapsed_seconds": 1.5,
                "content_type": "application/octet-stream",
                "content_length": 10_000_000,
                "valid_binary": True,
                "errors": [],
            }
        ],
        "ranked_sources": {spec.name: [spec.sources[0]]},
    }
    (paths.state_dir / "source_probes.json").write_text(
        json.dumps(cache), encoding="utf-8"
    )

    def unexpected_probe(*args, **kwargs):
        raise AssertionError("fresh successful probes must be reused")

    monkeypatch.setattr(
        "scripts.assets.download_mm26_assets.probe_source", unexpected_probe
    )

    ranked, results = probe_and_rank_sources((spec,), paths)

    assert ranked[0].sources == (spec.sources[0],)
    assert results[0].valid_binary is True
