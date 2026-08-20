from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from scripts import train_ov_orthkd as train_module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_static_evidence_is_complete_and_dirty_run_is_downgraded(
    tmp_path: Path, monkeypatch
) -> None:
    for split in ("train", "val", "test"):
        (tmp_path / f"{split}.jsonl").write_text(f'{{"id":"{split}"}}\n', encoding="utf-8")
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()
    evaluator_source = tmp_path / "official_eval.py"
    evaluator_source.write_text("def official(): return True\n", encoding="utf-8")
    lock_paths: dict[str, str] = {}
    for name in ("data", "archival", "teacher", "preprocessing"):
        path = lock_dir / f"{name}.yaml"
        path.write_text(f"status: ready\nname: {name}\n", encoding="utf-8")
        lock_paths[f"{name}_lock"] = str(path)
    evaluator_lock = lock_dir / "evaluator.yaml"
    evaluator_lock.write_text(
        yaml.safe_dump(
            {
                "status": "ready",
                "source_file": str(evaluator_source),
                "source_sha256": _sha256(evaluator_source),
            }
        ),
        encoding="utf-8",
    )
    lock_paths["evaluator_lock"] = str(evaluator_lock)
    cache = tmp_path / "teacher-cache"
    cache.mkdir()
    (cache / "artifact.npy").write_bytes(b"artifact")

    def fake_command(command: list[str]) -> dict[str, object]:
        stdout = ""
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            stdout = "a" * 40
        elif command[:2] == ["git", "branch"]:
            stdout = "repro/test"
        elif command[:2] == ["git", "status"]:
            stdout = " M local.py"
        elif command[-2:] == ["pip", "freeze"]:
            stdout = "numpy==1.0"
        return {"command": command, "returncode": 0, "stdout": stdout, "stderr": ""}

    monkeypatch.setattr(train_module, "_run_evidence_command", fake_command)
    config = {
        "reproduction": {
            "claim_level": "archival_exact",
            "variant": "conference_baseline",
            "readiness": lock_paths,
        },
        "data": {
            "path_root": str(tmp_path),
            **{f"{split}_manifest": f"{split}.jsonl" for split in ("train", "val", "test")},
        },
        "teacher_export": {"artifact_dir": str(cache)},
    }
    output = tmp_path / "evidence"
    output.mkdir()

    train_module.write_static_run_evidence(output, config)

    expected = {
        "config_resolved.yaml",
        "claim_level.txt",
        "git_state.json",
        "manifest_hashes.json",
        "lock_hashes.json",
        "teacher_cache_hash.json",
        "official_evaluator_hash.json",
        "experiment_variant.json",
        "requirements_freeze.txt",
        "cuda_environment.json",
    }
    assert expected <= {path.name for path in output.iterdir()}
    assert (output / "claim_level.txt").read_text(encoding="utf-8").strip() == "noncanonical_diagnostic"
    variant = json.loads((output / "experiment_variant.json").read_text(encoding="utf-8"))
    assert variant["declared_claim_level"] == "archival_exact"
    assert variant["effective_claim_level"] == "noncanonical_diagnostic"
    assert variant["git_dirty"] is True
    lock_hashes = json.loads((output / "lock_hashes.json").read_text(encoding="utf-8"))
    assert set(lock_hashes) == set(lock_paths)
    assert all(item["exists"] and len(item["sha256"]) == 64 for item in lock_hashes.values())
    evaluator = json.loads((output / "official_evaluator_hash.json").read_text(encoding="utf-8"))
    assert evaluator["matches_lock"] is True
    cache_hash = json.loads((output / "teacher_cache_hash.json").read_text(encoding="utf-8"))
    assert cache_hash["files"] == 1
    assert len(cache_hash["sha256"]) == 64
