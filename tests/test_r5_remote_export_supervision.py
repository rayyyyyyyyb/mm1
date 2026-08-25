from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_sidecar_supervisor_is_split_scoped_resumable_and_retrying() -> None:
    script = (
        PROJECT_ROOT / "scripts" / "supervise_r5_teacher_split_export.ps1"
    ).read_text(encoding="utf-8")

    assert '[ValidateSet("val", "test")]' in script
    assert '"data\\ov_ave\\source\\$Split.jsonl"' in script
    assert '"data\\ov_ave\\exported\\$Split.jsonl"' in script
    assert '"reports\\teachers\\receipts\\$Split.jsonl"' in script
    assert '"reports\\teachers\\errors\\$Split.jsonl"' in script
    assert '"reports\\teachers\\progress\\$Split.json"' in script
    assert "--teacher-lock configs/locks/mm26_teacher_lock.yaml" in script
    assert "--resume" in script
    assert "for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++)" in script
    assert "Start-Sleep -Seconds $RetryDelaySeconds" in script


def test_remote_runner_can_start_and_monitor_one_sidecar_split() -> None:
    script = (PROJECT_ROOT / "scripts" / "run_r5_remote_stage.ps1").read_text(
        encoding="utf-8"
    )

    assert '"StartSidecarExport"' in script
    assert '[ValidateSet("val", "test")]' in script
    assert 'scripts\\supervise_r5_teacher_split_export.ps1' in script
    assert 'sidecar_states' in script
