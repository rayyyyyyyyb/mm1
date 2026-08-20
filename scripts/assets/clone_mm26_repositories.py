"""Clone and lock the five official repositories used by the MM26 reproduction."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence
from urllib.parse import urlsplit, urlunsplit


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class RepositorySpec:
    name: str
    origin: str
    target: Path
    key_source_candidates: tuple[Path, ...]
    sparse_directory: str | None = None
    license_required: bool = True


REPOSITORIES = (
    RepositorySpec(
        name="internvideo",
        origin="https://github.com/OpenGVLab/InternVideo.git",
        target=Path("external/teachers/InternVideo"),
        key_source_candidates=(
            Path("InternVideo2/multi_modality/models/backbones/internvideo2.py"),
            Path("InternVideo2/multi_modality/models/internvideo2_clip.py"),
            Path("InternVideo2/multi_modality/models/internvideo2_clip_small.py"),
            Path("InternVideo2/multi_modality/models/utils.py"),
        ),
    ),
    RepositorySpec(
        name="unilm_beats",
        origin="https://github.com/microsoft/unilm.git",
        target=Path("external/teachers/unilm"),
        key_source_candidates=(Path("beats/BEATs.py"), Path("beats/Tokenizers.py")),
        sparse_directory="beats",
    ),
    RepositorySpec(
        name="microsoft_clap",
        origin="https://github.com/microsoft/CLAP.git",
        target=Path("external/teachers/microsoft-clap"),
        key_source_candidates=(
            Path("msclap/CLAPWrapper.py"),
            Path("msclap/models/clap.py"),
        ),
    ),
    RepositorySpec(
        name="mobileclip",
        origin="https://github.com/apple/ml-mobileclip.git",
        target=Path("external/teachers/ml-mobileclip"),
        key_source_candidates=(
            Path("mobileclip/models/mci.py"),
            Path("mobileclip/models/vit.py"),
        ),
    ),
    RepositorySpec(
        name="ov_avel",
        origin="https://github.com/jasongief/OV-AVEL.git",
        target=Path("external/OV-AVEL"),
        key_source_candidates=(
            Path("proposed_method/ImageBind-main/imagebind/data.py"),
            Path("proposed_method/ImageBind-main/dataloader.py"),
        ),
        license_required=False,
    ),
)


def _git(checkout: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-c", "http.version=HTTP/1.1", "-C", str(checkout), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[-4000:]
        raise RuntimeError(f"git {' '.join(args)} failed in {checkout}: {detail}")
    return completed.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalized_origin(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme and parsed.netloc:
        path = parsed.path.rstrip("/")
        if path.lower().endswith(".git"):
            path = path[:-4]
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))
    path = Path(value).expanduser().resolve()
    text = str(path).rstrip("/\\")
    return text[:-4] if text.lower().endswith(".git") else text


def _hashed_entry(path: Path, checkout: Path) -> dict[str, object]:
    relative = path.relative_to(checkout).as_posix()
    return {"path": relative, "bytes": path.stat().st_size, "sha256": _sha256(path)}


def audit_repository(spec: RepositorySpec, checkout: Path) -> dict[str, object]:
    checkout = checkout.resolve()
    if not (checkout / ".git").exists():
        raise ValueError(f"repository checkout is missing .git: {checkout}")
    origin = _git(checkout, "remote", "get-url", "origin")
    commit = _git(checkout, "rev-parse", "HEAD")
    branch = _git(checkout, "branch", "--show-current") or "DETACHED"
    status = _git(checkout, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise ValueError(f"repository must be clean: {spec.name}")

    licenses = sorted(
        path
        for path in checkout.iterdir()
        if path.is_file() and (path.name.upper().startswith("LICENSE") or path.name.upper().startswith("NOTICE"))
    )
    if not licenses and spec.license_required:
        raise ValueError(f"repository license is missing: {spec.name}")
    key_sources = [checkout / candidate for candidate in spec.key_source_candidates]
    key_sources = [path for path in key_sources if path.is_file()]
    if not key_sources:
        candidates = ", ".join(path.as_posix() for path in spec.key_source_candidates)
        raise ValueError(f"no expected key source exists for {spec.name}: {candidates}")

    receipt = {
        "schema_version": 1,
        "name": spec.name,
        "target": spec.target.as_posix(),
        "origin": origin,
        "commit": commit,
        "branch": branch,
        "clean": True,
        "license_status": "published" if licenses else "not_published_by_upstream",
        "licenses": [_hashed_entry(path, checkout) for path in licenses],
        "key_sources": [_hashed_entry(path, checkout) for path in key_sources],
    }
    return validate_repository_receipt(receipt, spec, checkout)


def validate_repository_receipt(
    receipt: dict[str, object], spec: RepositorySpec, checkout: Path
) -> dict[str, object]:
    commit = str(receipt.get("commit", ""))
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise ValueError(f"repository commit must be a lowercase 40-character SHA: {spec.name}")
    if _normalized_origin(str(receipt.get("origin", ""))) != _normalized_origin(spec.origin):
        raise ValueError(f"repository origin mismatch: {spec.name}")
    if receipt.get("clean") is not True:
        raise ValueError(f"repository receipt is not clean: {spec.name}")

    checkout = checkout.resolve()
    actual_commit = _git(checkout, "rev-parse", "HEAD")
    actual_origin = _git(checkout, "remote", "get-url", "origin")
    actual_branch = _git(checkout, "branch", "--show-current") or "DETACHED"
    actual_status = _git(checkout, "status", "--porcelain=v1", "--untracked-files=all")
    if actual_status:
        raise ValueError(f"repository checkout is not clean: {spec.name}")
    if commit != actual_commit or _normalized_origin(actual_origin) != _normalized_origin(spec.origin):
        raise ValueError(f"repository Git identity does not match checkout: {spec.name}")
    if receipt.get("branch") != actual_branch:
        raise ValueError(f"repository branch mismatch: {spec.name}")

    for field, label in (("licenses", "license"), ("key_sources", "key source")):
        entries = receipt.get(field)
        allow_empty = field == "licenses" and not spec.license_required
        if not isinstance(entries, list) or (not entries and not allow_empty):
            raise ValueError(f"repository {label} evidence is missing: {spec.name}")
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError(f"repository {label} entry is invalid: {spec.name}")
            relative = Path(str(entry.get("path", "")))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"repository {label} path is unsafe: {spec.name}")
            path = checkout / relative
            expected = str(entry.get("sha256", ""))
            if not path.is_file() or len(expected) != 64 or _sha256(path) != expected:
                raise ValueError(f"repository {label} hash mismatch: {spec.name}")
            if int(entry.get("bytes", -1)) != path.stat().st_size:
                raise ValueError(f"repository {label} size mismatch: {spec.name}")
    return receipt


def _clone(spec: RepositorySpec, root: Path) -> dict[str, object]:
    target = (root / spec.target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        receipt = audit_repository(spec, target)
        _git(target, "fetch", "--all", "--tags", "--prune")
        if receipt["branch"] != "DETACHED":
            _git(target, "pull", "--ff-only")
        return audit_repository(spec, target)

    partial = target.with_name(f"{target.name}.partial")
    if partial.exists():
        audit_repository(spec, partial)
        partial.replace(target)
        return audit_repository(spec, target)
    command = [
        "git",
        "-c",
        "http.version=HTTP/1.1",
        "clone",
        "--filter=blob:none",
        "--single-branch",
    ]
    if spec.sparse_directory:
        command.append("--sparse")
    command.extend([spec.origin, str(partial)])
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=3600)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[-4000:]
        raise RuntimeError(f"clone failed for {spec.name}: {detail}")
    if spec.sparse_directory:
        _git(partial, "sparse-checkout", "set", spec.sparse_directory)
    audit_repository(spec, partial)
    partial.replace(target)
    return audit_repository(spec, target)


def clone_and_audit(root: Path, jobs: int) -> list[dict[str, object]]:
    receipts: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=max(1, min(jobs, len(REPOSITORIES)))) as executor:
        futures = {executor.submit(_clone, spec, root): spec for spec in REPOSITORIES}
        for future in as_completed(futures):
            receipts.append(future.result())
    return sorted(receipts, key=lambda receipt: str(receipt["name"]))


def audit_existing(
    root: Path,
    jobs: int,
    specs: Sequence[RepositorySpec] = REPOSITORIES,
) -> list[dict[str, object]]:
    """Recompute receipts from fixed local checkouts without a network fetch."""

    receipts: list[dict[str, object]] = []
    selected = tuple(specs)
    with ThreadPoolExecutor(max_workers=max(1, min(jobs, len(selected)))) as executor:
        futures = {
            executor.submit(audit_repository, spec, (root / spec.target).resolve()): spec
            for spec in selected
        }
        for future in as_completed(futures):
            receipts.append(future.result())
    return sorted(receipts, key=lambda receipt: str(receipt["name"]))


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--jobs", type=int, default=5)
    parser.add_argument(
        "--audit-only",
        action="store_true",
        help="recompute receipts from the existing exact checkouts without fetching",
    )
    parser.add_argument(
        "--receipt", type=Path, default=Path("reports/downloads/repository_receipts.json")
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    receipts = (
        audit_existing(root, args.jobs)
        if args.audit_only
        else clone_and_audit(root, args.jobs)
    )
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed",
        "repositories": receipts,
    }
    receipt = args.receipt if args.receipt.is_absolute() else root / args.receipt
    _write_json_atomic(receipt, payload)
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        raise SystemExit(1) from error
