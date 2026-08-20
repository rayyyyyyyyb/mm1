"""Resumable aria2 asset manager for the MM26 conference reproduction."""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.assets.asset_validation import (  # noqa: E402
    ValidationReceipt,
    probe_response,
    validate_download,
)
from scripts.assets.mm26_asset_catalog import (  # noqa: E402
    AssetSpec,
    data_assets,
    weight_assets,
)


@dataclass(frozen=True)
class DownloadPaths:
    root: Path
    download_root: Path
    incoming_dir: Path
    state_dir: Path
    logs_dir: Path
    tmp_dir: Path
    quarantine_dir: Path
    session_file: Path
    input_file: Path
    log_file: Path
    console_log_file: Path
    process_state: Path
    runner_file: Path
    runner_state: Path
    runner_state_tmp: Path

    @classmethod
    def from_root(cls, root: str | Path) -> "DownloadPaths":
        normalized_root = Path(root).resolve()
        download_root = normalized_root / "data" / "downloads"
        state_dir = download_root / "state"
        logs_dir = download_root / "logs"
        return cls(
            root=normalized_root,
            download_root=download_root,
            incoming_dir=download_root / "incoming",
            state_dir=state_dir,
            logs_dir=logs_dir,
            tmp_dir=download_root / "tmp",
            quarantine_dir=download_root / "quarantine",
            session_file=state_dir / "aria2.session",
            input_file=state_dir / "aria2.input",
            log_file=logs_dir / "weights.log",
            console_log_file=logs_dir / "weights.console.log",
            process_state=state_dir / "aria2_process.json",
            runner_file=state_dir / "aria2_runner.cmd",
            runner_state=state_dir / "aria2_runner_exit.json",
            runner_state_tmp=state_dir / "aria2_runner_exit.json.tmp",
        )

    def create(self) -> None:
        for directory in (
            self.incoming_dir,
            self.state_dir,
            self.logs_dir,
            self.tmp_dir,
            self.quarantine_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self.session_file.touch(exist_ok=True)

    def incoming_path(self, spec: AssetSpec) -> Path:
        if spec.kind == "weight":
            return self.incoming_dir / "weights" / spec.name / spec.target.name
        return self.incoming_dir / spec.name

    def final_path(self, spec: AssetSpec) -> Path:
        return self.root / spec.target


@dataclass(frozen=True)
class AssetPlan:
    asset: str
    action: str
    final_path: Path
    incoming_path: Path
    quarantine_path: Path | None = None
    validation: ValidationReceipt | None = None

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for name in ("final_path", "incoming_path", "quarantine_path"):
            value = payload[name]
            payload[name] = str(value) if value is not None else None
        return payload


@dataclass(frozen=True)
class SourceProbe:
    url: str
    status_code: int | None
    elapsed_seconds: float
    content_type: str | None
    content_length: int | None
    valid_binary: bool
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _response_total_bytes(headers: object, downloaded_bytes: int) -> int | None:
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return downloaded_bytes or None
    content_range = getter("Content-Range")
    if content_range and "/" in str(content_range):
        total = str(content_range).rsplit("/", 1)[1]
        if total != "*":
            try:
                return int(total)
            except ValueError:
                pass
    content_length = getter("Content-Length")
    try:
        return int(content_length) if content_length is not None else (downloaded_bytes or None)
    except (TypeError, ValueError):
        return downloaded_bytes or None


def probe_source(url: str, *, minimum_bytes: int, range_bytes: int = 1024 * 1024) -> SourceProbe:
    """Download a small Range from one public source and classify its real payload."""

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "OV-OrthKD-R3-Asset-Probe/1.0",
            "Range": f"bytes=0-{range_bytes - 1}",
            "Accept": "*/*",
        },
        method="GET",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = response.read(range_bytes)
            elapsed = max(time.perf_counter() - started, 1e-9)
            status_code = getattr(response, "status", None) or response.getcode()
            content_type = response.headers.get("Content-Type")
            total_bytes = _response_total_bytes(response.headers, len(payload))
            errors = probe_response(payload[:4096], content_type, total_bytes)
            if status_code not in {200, 206}:
                errors.append(f"http_{status_code}")
            if total_bytes is None or total_bytes < minimum_bytes:
                errors.append("implausibly_small")
            unique_errors = tuple(dict.fromkeys(errors))
            return SourceProbe(
                url=url,
                status_code=int(status_code) if status_code is not None else None,
                elapsed_seconds=elapsed,
                content_type=content_type,
                content_length=total_bytes,
                valid_binary=not unique_errors,
                errors=unique_errors,
            )
    except urllib.error.HTTPError as error:
        elapsed = max(time.perf_counter() - started, 1e-9)
        prefix = error.read(4096)
        content_type = error.headers.get("Content-Type") if error.headers else None
        total_bytes = _response_total_bytes(error.headers, len(prefix))
        errors = probe_response(prefix, content_type, total_bytes)
        errors.append(f"http_{error.code}")
        return SourceProbe(
            url=url,
            status_code=error.code,
            elapsed_seconds=elapsed,
            content_type=content_type,
            content_length=total_bytes,
            valid_binary=False,
            errors=tuple(dict.fromkeys(errors)),
        )
    except (OSError, urllib.error.URLError) as error:
        return SourceProbe(
            url=url,
            status_code=None,
            elapsed_seconds=max(time.perf_counter() - started, 1e-9),
            content_type=None,
            content_length=None,
            valid_binary=False,
            errors=(type(error).__name__,),
        )


def rank_sources(spec: AssetSpec, results: Sequence[SourceProbe]) -> tuple[str, ...]:
    """Return valid sources fastest-first without admitting failed payloads."""

    del spec
    valid = sorted(
        (result for result in results if result.valid_binary),
        key=lambda result: (result.elapsed_seconds, result.url),
    )
    return tuple(dict.fromkeys(result.url for result in valid))


def _fresh_cached_probes(
    specs: Sequence[AssetSpec], paths: DownloadPaths, *, max_age: timedelta = timedelta(hours=6)
) -> tuple[dict[str, tuple[str, ...]], list[SourceProbe]]:
    cache_path = paths.state_dir / "source_probes.json"
    if not cache_path.is_file():
        return {}, []
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        generated_at = datetime.fromisoformat(str(payload["generated_at"]).replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - generated_at.astimezone(timezone.utc)
        if age < timedelta(minutes=-5) or age > max_age:
            return {}, []
        raw_results = payload["results"]
        raw_ranked = payload["ranked_sources"]
        if not isinstance(raw_results, list) or not isinstance(raw_ranked, dict):
            return {}, []
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return {}, []

    results: list[SourceProbe] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        try:
            results.append(
                SourceProbe(
                    url=str(item["url"]),
                    status_code=(int(item["status_code"]) if item.get("status_code") is not None else None),
                    elapsed_seconds=float(item["elapsed_seconds"]),
                    content_type=(str(item["content_type"]) if item.get("content_type") is not None else None),
                    content_length=(int(item["content_length"]) if item.get("content_length") is not None else None),
                    valid_binary=item.get("valid_binary") is True,
                    errors=tuple(str(error) for error in item.get("errors", [])),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue

    result_by_url = {result.url: result for result in results}
    ranked: dict[str, tuple[str, ...]] = {}
    for spec in specs:
        cached_sources = raw_ranked.get(spec.name, [])
        if not isinstance(cached_sources, list):
            continue
        accepted: list[str] = []
        for url in cached_sources:
            result = result_by_url.get(str(url))
            if (
                str(url) in spec.sources
                and result is not None
                and result.valid_binary
                and result.content_length is not None
                and result.content_length >= spec.min_bytes
            ):
                accepted.append(str(url))
        if accepted:
            ranked[spec.name] = tuple(dict.fromkeys(accepted))
    used_urls = {url for sources in ranked.values() for url in sources}
    return ranked, [result for result in results if result.url in used_urls]


def probe_and_rank_sources(
    specs: Sequence[AssetSpec], paths: DownloadPaths
) -> tuple[tuple[AssetSpec, ...], tuple[SourceProbe, ...]]:
    cached_ranked, cached_results = _fresh_cached_probes(specs, paths)
    pending_specs = [spec for spec in specs if spec.name not in cached_ranked]
    jobs = [(spec, source) for spec in pending_specs for source in spec.sources]
    by_asset: dict[str, list[SourceProbe]] = {spec.name: [] for spec in specs}
    all_results: list[SourceProbe] = list(cached_results)
    with ThreadPoolExecutor(max_workers=min(12, max(1, len(jobs)))) as executor:
        futures = {
            executor.submit(probe_source, source, minimum_bytes=spec.min_bytes): spec
            for spec, source in jobs
        }
        for future in as_completed(futures):
            spec = futures[future]
            result = future.result()
            by_asset[spec.name].append(result)
            all_results.append(result)

    ranked: list[AssetSpec] = []
    for spec in specs:
        sources = cached_ranked.get(spec.name) or rank_sources(spec, by_asset[spec.name])
        if not sources:
            errors = {result.url: result.errors for result in by_asset[spec.name]}
            raise RuntimeError(f"No valid binary source for {spec.name}: {errors}")
        ranked.append(replace(spec, sources=sources))

    _write_json_atomic(
        paths.state_dir / "source_probes.json",
        {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "results": [result.to_dict() for result in all_results],
            "ranked_sources": {spec.name: list(spec.sources) for spec in ranked},
        },
    )
    return tuple(ranked), tuple(all_results)


def connection_limit_for_recent_statuses(statuses: Sequence[int]) -> int:
    """Reduce concurrency after at least two consecutive throttle responses."""

    consecutive = 0
    for status in reversed(statuses):
        if status not in {429, 503}:
            break
        consecutive += 1
    return 2 if consecutive >= 2 else 8


def build_aria2_arguments(paths: DownloadPaths, *, connections: int) -> list[str]:
    if connections not in {2, 4, 8}:
        raise ValueError("connections must be one of 2, 4 or 8")
    return [
        "--continue=true",
        "--max-tries=0",
        "--retry-wait=15",
        "--connect-timeout=30",
        "--timeout=120",
        "--lowest-speed-limit=0",
        "--max-file-not-found=5",
        "--auto-file-renaming=false",
        "--allow-overwrite=false",
        "--file-allocation=none",
        "--remote-time=true",
        f"--max-connection-per-server={connections}",
        f"--split={connections}",
        "--min-split-size=20M",
        "--summary-interval=30",
        "--console-log-level=notice",
        "--log-level=notice",
        "--check-integrity=true",
        "--max-concurrent-downloads=5",
        "--enable-rpc=true",
        "--rpc-listen-all=false",
        "--rpc-listen-port=6800",
        f"--save-session={paths.session_file}",
        "--save-session-interval=30",
        f"--input-file={paths.input_file}",
        f"--log={paths.log_file}",
    ]


def build_aria2_input(specs: Iterable[AssetSpec], paths: DownloadPaths) -> str:
    lines: list[str] = []
    for spec in specs:
        if spec.kind != "weight":
            raise ValueError(f"Direct aria2 input requires a resolved file URL: {spec.name}")
        incoming = paths.incoming_path(spec)
        lines.append("\t".join(spec.sources))
        lines.append(f"  dir={incoming.parent}")
        lines.append(f"  out={incoming.name}")
        if spec.expected_sha256 is not None:
            lines.append(f"  checksum=sha-256={spec.expected_sha256}")
    return "\n".join(lines) + ("\n" if lines else "")


def _unique_quarantine_path(candidate: Path, spec: AssetSpec, paths: DownloadPaths, sha256: str) -> Path:
    directory = paths.quarantine_dir / spec.name
    directory.mkdir(parents=True, exist_ok=True)
    base = directory / f"{candidate.name}.{sha256[:12]}.invalid"
    if not base.exists():
        return base
    index = 1
    while True:
        alternative = Path(f"{base}.{index}")
        if not alternative.exists():
            return alternative
        index += 1


def _quarantine(candidate: Path, spec: AssetSpec, paths: DownloadPaths, receipt: ValidationReceipt) -> Path:
    sha256 = receipt.sha256 or "unknown"
    target = _unique_quarantine_path(candidate, spec, paths, sha256)
    candidate.replace(target)
    control = Path(str(candidate) + ".aria2")
    if control.exists():
        control.replace(Path(str(target) + ".aria2"))
    return target


def prepare_asset(spec: AssetSpec, paths: DownloadPaths) -> AssetPlan:
    """Prepare one weight for verified skip, quarantine, promotion, resume or download."""

    paths.create()
    final_path = paths.final_path(spec)
    incoming_path = paths.incoming_path(spec)

    if final_path.exists():
        receipt = validate_download(final_path, spec)
        if receipt.status == "passed":
            return AssetPlan(spec.name, "skip_verified", final_path, incoming_path, validation=receipt)
        quarantine_path = _quarantine(final_path, spec, paths, receipt)
        return AssetPlan(
            spec.name,
            "quarantined",
            final_path,
            incoming_path,
            quarantine_path=quarantine_path,
            validation=receipt,
        )

    if incoming_path.exists():
        control = Path(str(incoming_path) + ".aria2")
        if control.exists():
            return AssetPlan(spec.name, "resume", final_path, incoming_path)
        receipt = validate_download(incoming_path, spec)
        if receipt.status == "passed":
            final_path.parent.mkdir(parents=True, exist_ok=True)
            incoming_path.replace(final_path)
            control = Path(str(incoming_path) + ".aria2")
            if control.exists():
                control.unlink()
            return AssetPlan(spec.name, "promoted", final_path, incoming_path, validation=receipt)
        return AssetPlan(spec.name, "resume", final_path, incoming_path, validation=receipt)

    return AssetPlan(spec.name, "download", final_path, incoming_path)


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _write_json_atomic(path: Path, payload: object) -> None:
    _write_text_atomic(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def _input_blocks(text: str) -> list[str]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        if line and not line[0].isspace():
            if current:
                blocks.append(current)
            current = [line]
        elif current and line.strip():
            current.append(line)
    if current:
        blocks.append(current)
    return ["\n".join(block) for block in blocks]


def _input_identity(block: str) -> str | None:
    directory: str | None = None
    output: str | None = None
    for line in block.splitlines()[1:]:
        option = line.strip()
        if option.startswith("dir="):
            directory = option[4:]
        elif option.startswith("out="):
            output = option[4:]
    if not directory or not output:
        return None
    return os.path.normcase(os.path.normpath(str(Path(directory) / output)))


def _merged_input(generated: str, session_file: Path) -> str:
    session = session_file.read_text(encoding="utf-8", errors="replace") if session_file.exists() else ""
    generated_blocks = _input_blocks(generated)
    blocks = list(generated_blocks)
    identities = {_input_identity(block) for block in generated_blocks}
    raw_blocks = set(generated_blocks)
    for block in _input_blocks(session):
        identity = _input_identity(block)
        if (identity is not None and identity in identities) or block in raw_blocks:
            continue
        blocks.append(block)
        identities.add(identity)
        raw_blocks.add(block)
    return "\n".join(blocks) + ("\n" if blocks else "")


def _resolve_aria2(executable: str | None) -> str:
    if executable:
        path = Path(executable)
        if not path.is_file():
            raise FileNotFoundError(f"aria2c executable does not exist: {path}")
        return str(path)
    resolved = shutil.which("aria2c") or shutil.which("aria2c.exe")
    if not resolved:
        raise FileNotFoundError("aria2c was not found; run the R3 Windows tool bootstrap first")
    return resolved


def _process_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        completed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            check=False,
            capture_output=True,
            text=True,
        )
        return str(pid) in completed.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def build_windows_runner_script(command: Sequence[str], paths: DownloadPaths) -> str:
    """Build the WMI-owned wrapper used to survive an OpenSSH session closing."""

    command_line = subprocess.list2cmdline([str(part) for part in command])
    return (
        "@echo off\n"
        "setlocal\n"
        f'cd /d "{paths.root}"\n'
        f'{command_line} >> "{paths.console_log_file}" 2>&1\n'
        "set MM26_EXIT_CODE=%ERRORLEVEL%\n"
        f'> "{paths.runner_state_tmp}" echo '
        '{"schema_version":1,"status":"exited","exit_code":%MM26_EXIT_CODE%}\n'
        f'move /Y "{paths.runner_state_tmp}" "{paths.runner_state}" >NUL\n'
        "exit /b %MM26_EXIT_CODE%\n"
    )


def parse_cim_launch_result(stdout: str) -> int:
    """Return a service-owned PID from a PowerShell CIM response."""

    payload: object | None = None
    for line in reversed(stdout.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            break
    if not isinstance(payload, dict):
        raise RuntimeError("Windows CIM launcher returned no JSON result")
    return_value = int(payload.get("ReturnValue", -1))
    pid = int(payload.get("ProcessId", 0))
    if return_value != 0 or pid <= 0:
        raise RuntimeError(f"Windows CIM launch failed: return={return_value}, pid={pid}")
    return pid


def _launch_via_windows_cim(command: Sequence[str], paths: DownloadPaths) -> int:
    if os.name != "nt":
        raise RuntimeError("windows-cim launcher is available only on Windows")
    _write_text_atomic(paths.runner_file, build_windows_runner_script(command, paths))
    for stale in (paths.runner_state, paths.runner_state_tmp):
        if stale.exists():
            stale.unlink()
    wrapper_command = f'cmd.exe /d /s /c ""{paths.runner_file}""'
    escaped = wrapper_command.replace("'", "''")
    powershell = (
        "$ErrorActionPreference='Stop';"
        f"$r=Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{{CommandLine='{escaped}'}};"
        "$r | Select-Object ReturnValue,ProcessId | ConvertTo-Json -Compress"
    )
    encoded = base64.b64encode(powershell.encode("utf-16le")).decode("ascii")
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[-2000:]
        raise RuntimeError(f"Windows CIM launcher failed with exit {completed.returncode}: {detail}")
    return parse_cim_launch_result(completed.stdout)


def _selected_launcher(requested: str) -> str:
    if requested not in {"auto", "popen", "windows-cim"}:
        raise ValueError(f"unsupported launcher: {requested}")
    if requested != "auto":
        return requested
    if os.name == "nt" and (os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_CLIENT")):
        return "windows-cim"
    return "popen"


def launch_weights(
    paths: DownloadPaths,
    specs: Sequence[AssetSpec],
    *,
    aria2c: str | None,
    connections: int,
    launcher: str = "auto",
) -> dict[str, object]:
    paths.create()
    existing_state: dict[str, object] = {}
    if paths.process_state.exists():
        try:
            existing_state = json.loads(paths.process_state.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing_state = {}
    existing_pid = int(existing_state.get("pid", 0) or 0)
    if _process_is_running(existing_pid):
        return {"status": "already_running", **existing_state}

    plans = [prepare_asset(spec, paths) for spec in specs]
    pending_names = {plan.asset for plan in plans if plan.action in {"download", "resume"}}
    pending_specs = [spec for spec in specs if spec.name in pending_names]
    if not pending_specs:
        return {"status": "nothing_to_download", "plans": [plan.to_dict() for plan in plans]}

    probing_state = {
        "schema_version": 1,
        "status": "probing_sources",
        "pid": os.getpid(),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "assets": [spec.name for spec in pending_specs],
        "plans": [plan.to_dict() for plan in plans],
    }
    _write_json_atomic(paths.process_state, probing_state)
    try:
        pending_specs, probe_results = probe_and_rank_sources(pending_specs, paths)
    except Exception as error:
        _write_json_atomic(
            paths.process_state,
            {
                **probing_state,
                "status": "source_probe_failed",
                "error_type": type(error).__name__,
                "error": str(error),
            },
        )
        raise
    throttled_statuses = [
        result.status_code for result in probe_results if result.status_code is not None
    ]
    connections = min(connections, connection_limit_for_recent_statuses(throttled_statuses))
    generated = build_aria2_input(pending_specs, paths)
    _write_text_atomic(paths.input_file, _merged_input(generated, paths.session_file))
    executable = _resolve_aria2(aria2c)
    command = [executable, *build_aria2_arguments(paths, connections=connections)]
    paths.log_file.parent.mkdir(parents=True, exist_ok=True)
    selected_launcher = _selected_launcher(launcher)
    if selected_launcher == "windows-cim":
        pid = _launch_via_windows_cim(command, paths)
    else:
        log_handle = paths.console_log_file.open("ab", buffering=0)
        creationflags = 0
        if os.name == "nt":
            creationflags = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NO_WINDOW
            )
        try:
            process = subprocess.Popen(
                command,
                cwd=paths.root,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                close_fds=True,
                creationflags=creationflags,
            )
            pid = process.pid
        finally:
            log_handle.close()

    time.sleep(2.0)
    running = _process_is_running(pid)
    runner_exit: dict[str, object] | None = None
    if paths.runner_state.exists():
        try:
            runner_exit = json.loads(paths.runner_state.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            runner_exit = {"status": "invalid_runner_state"}

    state = {
        "schema_version": 1,
        "status": "running" if running else "launch_failed",
        "pid": pid,
        "launcher": selected_launcher,
        "runner_exit": runner_exit,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "connections_per_server": connections,
        "input_file": str(paths.input_file),
        "session_file": str(paths.session_file),
        "log_file": str(paths.log_file),
        "rpc_url": "http://127.0.0.1:6800/jsonrpc",
        "assets": [spec.name for spec in pending_specs],
        "plans": [plan.to_dict() for plan in plans],
    }
    _write_json_atomic(paths.process_state, state)
    if not running:
        raise RuntimeError(f"aria2 launcher exited during startup: {runner_exit}")
    return state


def select_weight_assets(names: Sequence[str] | None) -> tuple[AssetSpec, ...]:
    catalog = weight_assets()
    if not names:
        return catalog
    requested = set(names)
    known = {spec.name for spec in catalog}
    unknown = sorted(requested - known)
    if unknown:
        raise ValueError(f"Unknown weight asset(s): {unknown}")
    return tuple(spec for spec in catalog if spec.name in requested)


def verify_weights(
    paths: DownloadPaths, specs: Sequence[AssetSpec] | None = None
) -> tuple[list[dict[str, object]], bool]:
    receipts: list[dict[str, object]] = []
    passed = True
    for spec in specs or weight_assets():
        receipt = validate_download(paths.final_path(spec), spec)
        receipts.append(receipt.to_dict())
        passed = passed and receipt.status == "passed"
    return receipts, passed


def status_payload(
    paths: DownloadPaths, specs: Sequence[AssetSpec] | None = None
) -> dict[str, object]:
    process: dict[str, object] = {}
    if paths.process_state.exists():
        try:
            process = json.loads(paths.process_state.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            process = {"status": "invalid_state", "error": str(error)}
    pid = int(process.get("pid", 0) or 0)
    return {
        "schema_version": 1,
        "process": {**process, "running": _process_is_running(pid)},
        "assets": [prepare_asset(spec, paths).to_dict() for spec in (specs or weight_assets())],
        "data_assets": [
            {"asset": spec.name, "status": "resolution_required", "target": str(spec.target)}
            for spec in data_assets()
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--all", action="store_true")
    mode.add_argument("--weights-only", action="store_true")
    mode.add_argument("--data-only", action="store_true")
    mode.add_argument("--resume", action="store_true")
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--aria2c")
    parser.add_argument("--connections", type=int, choices=(2, 4, 8), default=8)
    parser.add_argument("--launcher", choices=("auto", "popen", "windows-cim"), default="auto")
    parser.add_argument(
        "--asset",
        action="append",
        help="Limit a weight operation to one named catalog asset; may be repeated.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = DownloadPaths.from_root(args.root)
    selected_weights = select_weight_assets(args.asset)
    if args.status:
        print(json.dumps(status_payload(paths, selected_weights), indent=2, ensure_ascii=False))
        return
    if args.verify:
        receipts, passed = verify_weights(paths, selected_weights)
        print(json.dumps({"status": "passed" if passed else "failed", "assets": receipts}, indent=2))
        raise SystemExit(0 if passed else 1)
    if args.data_only:
        print(
            json.dumps(
                {
                    "status": "resolution_required",
                    "assets": [spec.name for spec in data_assets()],
                    "next": "run resolve_sharepoint_download.py before aria2",
                },
                indent=2,
            )
        )
        return
    state = launch_weights(
        paths,
        selected_weights,
        aria2c=args.aria2c,
        connections=args.connections,
        launcher=args.launcher,
    )
    if args.all:
        state["data_assets"] = [
            {"asset": spec.name, "status": "resolution_required"} for spec in data_assets()
        ]
    print(json.dumps(state, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
