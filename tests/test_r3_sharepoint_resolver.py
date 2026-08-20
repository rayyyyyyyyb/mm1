from __future__ import annotations

import json
from pathlib import Path

from scripts.assets.resolve_sharepoint_download import (
    _restrict_windows_acl,
    classify_sharepoint_response,
    sanitize_url,
    secret_handoff_file,
    sharepoint_url_variants,
)


SHARE_URL = (
    "https://mailhfuteducn-my.sharepoint.com/:u:/g/personal/example/ABC?e=secretShareCode"
)


def test_login_redirect_is_auth_required_without_secret_leak() -> None:
    result = classify_sharepoint_response(
        "https://login.microsoftonline.com/common/oauth2/authorize?client_id=secret",
        "text/html; charset=utf-8",
        b"<html><title>Sign in to your account</title></html>",
        5432,
    )

    public = result.public_dict()
    serialized = json.dumps(public).lower()
    assert result.status == "AUTH_REQUIRED"
    assert public["final_url"] == "https://login.microsoftonline.com/common/oauth2/authorize"
    assert "client_id" not in serialized
    assert "cookie" not in serialized
    assert "token" not in serialized


def test_valid_large_binary_response_is_resolved() -> None:
    result = classify_sharepoint_response(
        "https://public.dm.files.1drv.com/archive.zip?authkey=temporary",
        "application/octet-stream",
        b"PK\x03\x04binary archive",
        5 * 1024**3,
    )

    assert result.status == "RESOLVED"
    assert result.errors == ()
    assert result.public_dict()["final_url"] == "https://public.dm.files.1drv.com/archive.zip"


def test_html_sharepoint_response_is_auth_required_not_resolved() -> None:
    result = classify_sharepoint_response(
        SHARE_URL,
        "text/html",
        b"<!doctype html><html>Redirecting</html>",
        15321,
    )

    assert result.status == "AUTH_REQUIRED"
    assert "html_payload" in result.errors


def test_tiny_non_html_error_response_is_invalid() -> None:
    result = classify_sharepoint_response(
        "https://public.dm.files.1drv.com/archive.zip",
        "text/plain",
        b"Access denied",
        13,
    )

    assert result.status == "INVALID_RESPONSE"
    assert "implausibly_small" in result.errors


def test_sharepoint_variants_are_unique_and_drop_share_code_when_replacing_query() -> None:
    variants = sharepoint_url_variants(SHARE_URL)

    assert variants[0] == SHARE_URL
    assert variants[1] == SHARE_URL + "&download=1"
    assert variants[2].endswith("?download=1")
    assert "secretShareCode" not in variants[2]
    assert len(variants) == len(set(variants)) == 3


def test_sanitize_url_removes_query_fragment_and_credentials() -> None:
    sanitized = sanitize_url("https://user:password@example.com/path/file?token=secret#fragment")

    assert sanitized == "https://example.com/path/file"


def test_secret_handoff_file_is_removed_after_context(tmp_path: Path) -> None:
    secret_path: Path
    with secret_handoff_file(
        tmp_path,
        {"url": "https://download.example/file?token=secret", "headers": {"Cookie": "x=y"}},
    ) as secret_path:
        assert secret_path.is_file()
        assert "Cookie" in secret_path.read_text(encoding="utf-8")
        assert secret_path.parent == tmp_path

    assert not secret_path.exists()


def test_windows_acl_output_uses_native_encoding_without_reader_thread_decode_warning(
    tmp_path: Path, monkeypatch,
) -> None:
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(
        "scripts.assets.resolve_sharepoint_download.subprocess.run", fake_run
    )

    _restrict_windows_acl(tmp_path / "handoff.json", "authorized-user")

    assert calls[0][1]["encoding"] == "mbcs"
    assert calls[0][1]["errors"] == "replace"
