"""Resolve official SharePoint links without leaking authentication material."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator, Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.assets.asset_validation import probe_response  # noqa: E402


_BINARY_MINIMUM_BYTES = 1024 * 1024
_PROBE_BYTES = 4096


def sanitize_url(url: str) -> str:
    """Remove credentials, query parameters, and fragments from a public URL."""

    parsed = urllib.parse.urlsplit(url)
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    port = f":{parsed.port}" if parsed.port is not None else ""
    return urllib.parse.urlunsplit((parsed.scheme, hostname + port, parsed.path, "", ""))


@dataclass(frozen=True)
class ResolutionStatus:
    status: str
    final_url: str
    content_type: str | None
    content_length: int | None
    errors: tuple[str, ...]

    def public_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["final_url"] = sanitize_url(self.final_url)
        return payload


def classify_sharepoint_response(
    final_url: str,
    content_type: str | None,
    prefix: bytes,
    content_length: int | None,
) -> ResolutionStatus:
    """Classify a small response without treating an authentication page as data."""

    parsed = urllib.parse.urlsplit(final_url)
    hostname = (parsed.hostname or "").casefold()
    errors = probe_response(prefix, content_type, content_length)
    if content_length is None or content_length < _BINARY_MINIMUM_BYTES:
        errors.append("implausibly_small")
    unique_errors = tuple(dict.fromkeys(errors))
    is_login = hostname == "login.microsoftonline.com" or hostname.endswith(
        ".login.microsoftonline.com"
    )
    is_sharepoint_html = hostname.endswith(".sharepoint.com") and "html_payload" in unique_errors
    if is_login or is_sharepoint_html:
        status = "AUTH_REQUIRED"
    elif unique_errors:
        status = "INVALID_RESPONSE"
    else:
        status = "RESOLVED"
    return ResolutionStatus(status, final_url, content_type, content_length, unique_errors)


def sharepoint_url_variants(url: str) -> tuple[str, ...]:
    parsed = urllib.parse.urlsplit(url)
    appended_query = parsed.query + ("&" if parsed.query else "") + "download=1"
    appended = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, appended_query, parsed.fragment)
    )
    replaced = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "download=1", ""))
    return tuple(dict.fromkeys((url, appended, replaced)))


def _restrict_windows_acl(path: Path, username: str) -> None:
    """Restrict a secret handoff without decoding localized icacls output as UTF-8."""

    acl = subprocess.run(
        [
            "icacls.exe",
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"{username}:(R,W)",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="mbcs",
        errors="replace",
    )
    if acl.returncode != 0:
        raise RuntimeError("Failed to restrict the SharePoint handoff ACL")


@contextmanager
def secret_handoff_file(directory: str | Path, payload: Mapping[str, object]) -> Iterator[Path]:
    """Create a current-user-only JSON handoff and securely remove it afterwards."""

    parent = Path(directory)
    parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(prefix="sharepoint-", suffix=".secret.json", dir=parent)
    path = Path(raw_path)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(dict(payload), handle, ensure_ascii=False)
            handle.write("\n")
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        if os.name == "nt":
            username = os.environ.get("USERNAME")
            if not username:
                raise RuntimeError("USERNAME is required to restrict the SharePoint handoff ACL")
            _restrict_windows_acl(path, username)
        yield path
    finally:
        if path.exists():
            try:
                size = path.stat().st_size
                with path.open("r+b", buffering=0) as handle:
                    handle.write(b"\0" * size)
            finally:
                path.unlink(missing_ok=True)


def _content_length(headers: Mapping[str, str]) -> int | None:
    value = headers.get("Content-Length") or headers.get("content-length")
    if not value:
        content_range = headers.get("Content-Range") or headers.get("content-range")
        if content_range and "/" in content_range:
            value = content_range.rsplit("/", 1)[1]
    try:
        return int(value) if value and value != "*" else None
    except ValueError:
        return None


def probe_anonymous_url(url: str) -> ResolutionStatus:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/128.0 Safari/537.36"
            ),
            "Range": f"bytes=0-{_PROBE_BYTES - 1}",
            "Accept": "*/*",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            prefix = response.read(_PROBE_BYTES)
            headers = dict(response.headers.items())
            return classify_sharepoint_response(
                response.geturl(),
                headers.get("Content-Type"),
                prefix,
                _content_length(headers),
            )
    except urllib.error.HTTPError as error:
        prefix = error.read(_PROBE_BYTES)
        headers = dict(error.headers.items()) if error.headers else {}
        result = classify_sharepoint_response(
            error.geturl(),
            headers.get("Content-Type"),
            prefix,
            _content_length(headers),
        )
        return ResolutionStatus(
            "AUTH_REQUIRED" if error.code in {401, 403} else result.status,
            result.final_url,
            result.content_type,
            result.content_length,
            tuple(dict.fromkeys((*result.errors, f"http_{error.code}"))),
        )
    except (OSError, urllib.error.URLError) as error:
        return ResolutionStatus("NETWORK_ERROR", url, None, None, (type(error).__name__,))


def resolve_anonymous(url: str) -> tuple[ResolutionStatus, list[dict[str, object]]]:
    attempts: list[ResolutionStatus] = []
    for variant in sharepoint_url_variants(url):
        result = probe_anonymous_url(variant)
        attempts.append(result)
        if result.status == "RESOLVED":
            return result, [attempt.public_dict() for attempt in attempts]
    auth = next((attempt for attempt in attempts if attempt.status == "AUTH_REQUIRED"), None)
    selected = auth or attempts[-1]
    return selected, [attempt.public_dict() for attempt in attempts]


def _write_auth_report(root: Path, name: str, result: ResolutionStatus) -> Path:
    path = root / "reports" / "downloads" / "SHAREPOINT_AUTH_REQUIRED.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(
        [
            "# SharePoint Authorization Required",
            "",
            f"Asset: `{name}`",
            f"Status: `{result.status}`",
            f"Sanitized endpoint: `{sanitize_url(result.final_url)}`",
            "",
            "A single legal Microsoft sign-in is required. No password, cookie, token, or full signed URL is stored in this report.",
            "Other public downloads and code work may continue while authorization is pending.",
            "",
        ]
    )
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--interactive", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.interactive:
        raise SystemExit(
            "Interactive Playwright handoff is enabled only after anonymous AUTH_REQUIRED is recorded"
        )
    result, attempts = resolve_anonymous(args.url)
    payload = {"result": result.public_dict(), "attempts": attempts}
    if result.status == "AUTH_REQUIRED":
        payload["instruction_report"] = str(_write_auth_report(Path(args.root), args.name, result))
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    raise SystemExit(0 if result.status == "RESOLVED" else 2 if result.status == "AUTH_REQUIRED" else 1)


if __name__ == "__main__":
    main()
