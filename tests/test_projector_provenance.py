from pathlib import Path

from scripts.audit_projector_provenance import (
    classify_fact_evidence,
    redact_text,
    _scan_file,
    _source_type,
)


def test_redact_text_removes_common_credentials() -> None:
    value = "token=abc123 password: hunter2 user=alice@example.com"
    redacted = redact_text(value)
    assert "abc123" not in redacted
    assert "hunter2" not in redacted
    assert "alice@example.com" not in redacted
    assert "[REDACTED]" in redacted


def test_task_book_only_evidence_is_not_found() -> None:
    result = classify_fact_evidence(
        [
            {
                "path": Path("MM26_OVORTHKD_R0_REPRODUCTION_IMPLEMENTATION_TASK.md"),
                "source_type": "task_book",
                "excerpt": "teacher_target_projector_trainable: true",
                "value": "true",
            }
        ]
    )
    assert result["status"] == "NOT_FOUND"
    assert result["historical_evidence"] is False


def test_conflicting_historical_values_are_ambiguous() -> None:
    result = classify_fact_evidence(
        [
            {"path": Path("old_a.yaml"), "source_type": "config", "excerpt": "x", "value": "sum"},
            {"path": Path("old_b.yaml"), "source_type": "config", "excerpt": "y", "value": "mean"},
        ]
    )
    assert result["status"] == "AMBIGUOUS"
    assert result["values"] == ["mean", "sum"]


def test_single_historical_value_is_found() -> None:
    result = classify_fact_evidence(
        [{"path": Path("old.yaml"), "source_type": "config", "excerpt": "x", "value": "frozen"}]
    )
    assert result["status"] == "FOUND"
    assert result["value"] == "frozen"


def test_current_diagnostic_paths_are_not_historical() -> None:
    assert _source_type(Path("reports/formal_reproduction/current.json")) == "current_diagnostic"
    assert _source_type(Path("all.md")) == "current_diagnostic"


def test_binary_checkpoint_is_not_decoded_as_text(tmp_path: Path) -> None:
    checkpoint = tmp_path / "weights.pt"
    checkpoint.write_bytes(b"teacher_target_projector_trainable: true\x00\xff")
    assert list(_scan_file(checkpoint, tmp_path)) == []
