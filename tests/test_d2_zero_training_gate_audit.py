from __future__ import annotations

import copy
import json
from pathlib import Path

from scripts.audit_d2_zero_training_gate import audit_d2_zero_training_gate


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = (
    PROJECT_ROOT
    / "reports"
    / "formal_reproduction"
    / "student_shortcut_recovery"
    / "evidence"
    / "d2_zero_training_gate"
)


def _audit(directory: Path) -> dict:
    return audit_d2_zero_training_gate(
        directory / "d2_zero_training_gate.json",
        directory / "input_receipt.json",
        directory / "state.json",
        directory / "exit_code.txt",
        directory / "stderr.log",
    )


def _tampered_evidence(tmp_path: Path) -> tuple[Path, dict, dict]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    for name in ("state.json", "exit_code.txt", "stderr.log"):
        (tmp_path / name).write_bytes((EVIDENCE / name).read_bytes())
    result = json.loads((EVIDENCE / "d2_zero_training_gate.json").read_text(encoding="utf-8"))
    inputs = json.loads((EVIDENCE / "input_receipt.json").read_text(encoding="utf-8-sig"))
    return tmp_path, result, inputs


def _write_documents(directory: Path, result: dict, inputs: dict) -> None:
    (directory / "d2_zero_training_gate.json").write_text(json.dumps(result), encoding="utf-8")
    (directory / "input_receipt.json").write_text(json.dumps(inputs), encoding="utf-8")


def test_real_d2_gate_artifacts_pass_integrity_but_fail_scientific_gate() -> None:
    report = _audit(EVIDENCE)
    assert report["status"] == "ARTIFACT_AUDIT_PASS"
    assert report["scientific_status"] == "D2_ZERO_TRAINING_DECODABILITY_GATE_FAIL"
    assert report["producer_scientific_status"] == "VISUAL_PRETRAINING_CONTROL_FAIL"
    assert report["gate_recomputation"]["pass"] is False
    assert report["authorization"]["d2_800_step"] is False
    assert report["errors"] == []


def test_audit_rejects_cross_pass_alignment_drift(tmp_path: Path) -> None:
    directory, result, inputs = _tampered_evidence(tmp_path)
    result["alignment"]["timm_pretrained_visual"]["train"]["label_hash"] = "0" * 64
    _write_documents(directory, result, inputs)
    report = _audit(directory)
    assert report["status"] == "ARTIFACT_AUDIT_FAIL"
    assert any("canonically aligned" in error for error in report["errors"])


def test_audit_rejects_nonshared_projection_map(tmp_path: Path) -> None:
    directory, result, inputs = _tampered_evidence(tmp_path)
    result["probes"]["timm_pretrained_visual"]["projection_maps"] = copy.deepcopy(
        result["projection_maps"]
    )
    result["probes"]["timm_pretrained_visual"]["projection_maps"]["query_map_sha256"] = "1" * 64
    _write_documents(directory, result, inputs)
    report = _audit(directory)
    assert report["status"] == "ARTIFACT_AUDIT_FAIL"
    assert any("shared maps" in error for error in report["errors"])


def test_audit_rejects_fabricated_gate_pass(tmp_path: Path) -> None:
    directory, result, inputs = _tampered_evidence(tmp_path)
    result["gate"]["pass"] = True
    result["scientific_status"] = "VISUAL_PRETRAINING_CONTROL_PASS"
    _write_documents(directory, result, inputs)
    report = _audit(directory)
    assert report["status"] == "ARTIFACT_AUDIT_FAIL"
    assert any("recomputation" in error or "recomputed" in error for error in report["errors"])


def test_audit_rejects_test_manifest_or_changed_qp(tmp_path: Path) -> None:
    directory, result, inputs = _tampered_evidence(tmp_path)
    inputs["test_manifest"] = "data/ov_ave/exported/test.jsonl"
    result["probes"]["current_c2_visual"]["qp"]["mixed"]["pair_weighted_concordance"] += 0.1
    _write_documents(directory, result, inputs)
    report = _audit(directory)
    assert report["status"] == "ARTIFACT_AUDIT_FAIL"
    assert any("test manifest" in error for error in report["errors"])
    assert any("QP baseline changed" in error for error in report["errors"])
