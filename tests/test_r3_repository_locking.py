from __future__ import annotations

import copy
import subprocess
from pathlib import Path

import pytest

from scripts.assets.clone_mm26_repositories import (
    REPOSITORIES,
    RepositorySpec,
    audit_existing,
    audit_repository,
    validate_repository_receipt,
)


def test_internvideo_repository_lock_hashes_the_exact_imported_class_source() -> None:
    internvideo = next(spec for spec in REPOSITORIES if spec.name == "internvideo")

    assert Path(
        "InternVideo2/multi_modality/models/internvideo2_clip_small.py"
    ) in internvideo.key_source_candidates


def _git(*args: str, cwd: Path) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def _checkout(tmp_path: Path, *, with_license: bool = True) -> tuple[Path, Path, RepositorySpec]:
    origin = tmp_path / "origin"
    origin.mkdir()
    _git("init", "-b", "main", cwd=origin)
    _git("config", "user.email", "fixture@example.test", cwd=origin)
    _git("config", "user.name", "Fixture", cwd=origin)
    (origin / "src").mkdir()
    (origin / "src" / "model.py").write_text("MODEL = 'exact'\n", encoding="utf-8")
    if with_license:
        (origin / "LICENSE").write_text("fixture license\n", encoding="utf-8")
    _git("add", ".", cwd=origin)
    _git("commit", "-m", "fixture", cwd=origin)

    checkout = tmp_path / "checkout"
    _git("clone", str(origin), str(checkout), cwd=tmp_path)
    spec = RepositorySpec(
        name="fixture",
        origin=str(origin),
        target=Path("checkout"),
        key_source_candidates=(Path("src/model.py"),),
    )
    return origin, checkout, spec


def test_repository_receipt_recomputes_exact_git_and_file_identity(tmp_path: Path) -> None:
    _, checkout, spec = _checkout(tmp_path)

    receipt = audit_repository(spec, checkout)
    validated = validate_repository_receipt(receipt, spec, checkout)

    assert validated["commit"] == _git("rev-parse", "HEAD", cwd=checkout)
    assert len(validated["commit"]) == 40
    assert validated["branch"] == "main"
    assert validated["clean"] is True
    assert validated["licenses"][0]["path"] == "LICENSE"
    assert validated["key_sources"][0]["path"] == "src/model.py"


def test_audit_only_reuses_existing_exact_checkout_without_network(tmp_path: Path) -> None:
    _, _, spec = _checkout(tmp_path)

    receipts = audit_existing(tmp_path, jobs=1, specs=(spec,))

    assert [receipt["name"] for receipt in receipts] == [spec.name]
    assert receipts[0]["clean"] is True


def test_wrong_origin_is_rejected(tmp_path: Path) -> None:
    _, checkout, spec = _checkout(tmp_path)
    receipt = audit_repository(spec, checkout)
    receipt["origin"] = "https://example.test/wrong.git"

    with pytest.raises(ValueError, match="origin"):
        validate_repository_receipt(receipt, spec, checkout)


def test_dirty_checkout_is_rejected(tmp_path: Path) -> None:
    _, checkout, spec = _checkout(tmp_path)
    receipt = audit_repository(spec, checkout)
    (checkout / "src" / "model.py").write_text("DIRTY = True\n", encoding="utf-8")

    with pytest.raises(ValueError, match="clean"):
        validate_repository_receipt(receipt, spec, checkout)


def test_abbreviated_commit_is_rejected(tmp_path: Path) -> None:
    _, checkout, spec = _checkout(tmp_path)
    receipt = audit_repository(spec, checkout)
    receipt["commit"] = str(receipt["commit"])[:12]

    with pytest.raises(ValueError, match="40-character"):
        validate_repository_receipt(receipt, spec, checkout)


def test_missing_license_is_rejected(tmp_path: Path) -> None:
    _, checkout, spec = _checkout(tmp_path, with_license=False)

    with pytest.raises(ValueError, match="license"):
        audit_repository(spec, checkout)


def test_explicit_upstream_without_license_is_recorded_not_invented(tmp_path: Path) -> None:
    _, checkout, original = _checkout(tmp_path, with_license=False)
    spec = RepositorySpec(
        name=original.name,
        origin=original.origin,
        target=original.target,
        key_source_candidates=original.key_source_candidates,
        license_required=False,
    )

    receipt = audit_repository(spec, checkout)

    assert receipt["license_status"] == "not_published_by_upstream"
    assert receipt["licenses"] == []


def test_mismatched_key_source_hash_is_rejected(tmp_path: Path) -> None:
    _, checkout, spec = _checkout(tmp_path)
    receipt = audit_repository(spec, checkout)
    forged = copy.deepcopy(receipt)
    forged["key_sources"][0]["sha256"] = "0" * 64

    with pytest.raises(ValueError, match="key source"):
        validate_repository_receipt(forged, spec, checkout)
