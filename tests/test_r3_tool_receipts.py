from __future__ import annotations

import hashlib
from pathlib import Path

from scripts.assets.tool_receipts import validate_windows_tool_receipt


REQUIRED = ("aria2", "curl", "ffmpeg", "git_lfs", "jq", "python", "seven_zip")


def _receipt(tmp_path: Path) -> dict:
    tools = {}
    for name in REQUIRED:
        executable = tmp_path / f"{name}.exe"
        executable.write_bytes(f"{name} binary".encode())
        tools[name] = {
            "status": "verified",
            "version": "fixture-1",
            "path": str(executable),
            "bytes": executable.stat().st_size,
            "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            "source": "https://official.example/tool",
        }
    return {
        "schema_version": 1,
        "status": "ready",
        "platform": "windows",
        "tools": tools,
        "replacements": {
            "tmux": {"status": "replaced", "by": "windows_cim_background_process"},
            "rsync": {"status": "replaced", "by": "scp_and_hash_verified_copy"},
            "wget": {"status": "replaced", "by": "windows_curl"},
        },
    }


def test_verified_windows_tool_receipt_recomputes_every_executable_hash(tmp_path) -> None:
    assert validate_windows_tool_receipt(_receipt(tmp_path)) == []


def test_tool_receipt_rejects_tampered_binary_and_missing_native_replacement(tmp_path) -> None:
    receipt = _receipt(tmp_path)
    Path(receipt["tools"]["ffmpeg"]["path"]).write_bytes(b"tampered")
    receipt["replacements"].pop("tmux")

    errors = validate_windows_tool_receipt(receipt)

    assert any("ffmpeg" in error and "SHA256" in error for error in errors)
    assert any("tmux" in error and "replacement" in error for error in errors)


def test_windows_bootstrap_runner_persists_log_and_exit_receipt() -> None:
    project_root = Path(__file__).resolve().parents[1]
    runner = project_root / "scripts/assets/bootstrap_windows_tools.cmd"

    text = runner.read_text(encoding="utf-8")

    assert "bootstrap_windows_tools.ps1" in text
    assert "bootstrap_windows_tools.log" in text
    assert "bootstrap_windows_tools_exit.json.tmp" in text
    assert '"status":"exited"' in text
    assert "move /Y" in text


def test_windows_bootstrap_uses_unambiguous_powershell_url_interpolation() -> None:
    project_root = Path(__file__).resolve().parents[1]
    script = (project_root / "scripts/assets/bootstrap_windows_tools.ps1").read_text(
        encoding="utf-8"
    )

    assert "$Url:" not in script
    assert "${Url}:" in script


def test_windows_tool_downloads_use_resumable_multiconnection_aria2() -> None:
    project_root = Path(__file__).resolve().parents[1]
    script = (project_root / "scripts/assets/bootstrap_windows_tools.ps1").read_text(
        encoding="utf-8"
    )

    assert "aria2c.exe" in script
    assert "--continue=true" in script
    assert "--max-connection-per-server=4" in script
    assert "--split=4" in script
    assert "--lowest-speed-limit=0" in script
