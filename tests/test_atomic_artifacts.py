from pathlib import Path


def test_atomic_write_retries_a_transient_replace_permission_error(
    tmp_path: Path, monkeypatch
) -> None:
    import src.utils.atomic_artifacts as atomic_module

    destination = tmp_path / "progress.json"
    original_replace = atomic_module.os.replace
    attempts = 0

    def transient_replace(source, target) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("simulated Windows reader sharing conflict")
        original_replace(source, target)

    monkeypatch.setattr(atomic_module.os, "replace", transient_replace)

    atomic_module.atomic_write_text(destination, '{"status":"running"}\n')

    assert attempts == 2
    assert destination.read_text(encoding="utf-8") == '{"status":"running"}\n'
    assert list(tmp_path.glob("*.tmp")) == []
