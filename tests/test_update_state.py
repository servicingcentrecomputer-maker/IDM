"""Pending update state and update history."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from idm.updater.errors import UpdateStateError
from idm.updater.state import (
    InstallResult,
    PendingUpdate,
    append_history,
    clear_pending_update,
    evaluate_pending_update,
    finalize_pending_update,
    load_history,
    read_pending_update,
    record_event,
    write_install_result,
    write_pending_update,
)


def _pending(tmp_path, *, from_version="1.0.0", target_version="1.1.0"):
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir(exist_ok=True)
    db_backup = backup_dir / "idm.sqlite3"
    db_backup.write_bytes(b"database")
    return PendingUpdate(
        from_version=from_version,
        target_version=target_version,
        started_at="2026-11-01T10:00:00+00:00",
        backup_dir=str(backup_dir),
        db_backup=str(db_backup),
        previous_installer=str(tmp_path / "rollback" / "IDM_Setup_1.0.0.exe"),
        previous_installer_sha256="a" * 64,
        previous_publisher="IDM",
        app_exe=str(tmp_path / "app" / "IDM.exe"),
    )


class FakeDatabase:
    def __init__(self, *, corrupt: bool = False) -> None:
        self.corrupt = corrupt

    def quick_check(self) -> None:
        if self.corrupt:
            raise RuntimeError("SQLite quick_check failed: malformed")


class FakeSettings:
    def __init__(self, *, corrupt: bool = False) -> None:
        self.database = FakeDatabase(corrupt=corrupt)
        self.success_version = ""

    def note_update_success(self, version: str) -> None:
        self.success_version = version


def test_pending_update_round_trip(tmp_path):
    path = tmp_path / "pending-update.json"
    pending = _pending(tmp_path)
    write_pending_update(pending, path=path)

    loaded = read_pending_update(path)

    assert loaded == pending
    assert loaded.rollback_available is True

    clear_pending_update(path)
    assert read_pending_update(path) is None


def test_pending_update_rejects_invalid_version(tmp_path):
    path = tmp_path / "pending-update.json"
    path.write_text(
        json.dumps(
            {
                "from_version": "not-a-version",
                "target_version": "1.1.0",
                "backup_dir": str(tmp_path),
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(UpdateStateError):
        read_pending_update(path)


def test_reinstall_pending_update_round_trip(tmp_path):
    pending = _pending(tmp_path, from_version="1.0.0", target_version="1.0.0")
    pending = PendingUpdate(
        from_version=pending.from_version,
        target_version=pending.target_version,
        started_at=pending.started_at,
        backup_dir=pending.backup_dir,
        db_backup=pending.db_backup,
        app_exe=pending.app_exe,
        reinstall=True,
    )
    path = tmp_path / "pending-update.json"
    write_pending_update(pending, path=path)

    loaded = read_pending_update(path)

    assert loaded == pending
    assert loaded.reinstall is True
    assert loaded.rollback_available is False


def test_reinstall_pending_update_requires_matching_versions(tmp_path):
    with pytest.raises(UpdateStateError):
        write_pending_update(
            _pending(tmp_path, from_version="1.0.0", target_version="1.0.0"),
            path=tmp_path / "pending.json",
        )
    with pytest.raises(UpdateStateError):
        write_pending_update(
            PendingUpdate(
                from_version="1.0.0",
                target_version="1.1.0",
                started_at="2026-11-01T10:00:00+00:00",
                backup_dir=str(tmp_path),
                db_backup=str(tmp_path / "idm.sqlite3"),
                reinstall=True,
            ),
            path=tmp_path / "pending.json",
        )


def test_evaluate_reinstall_success_and_mismatch(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    path = tmp_path / "pending-update.json"
    pending = PendingUpdate(
        from_version="1.0.0",
        target_version="1.0.0",
        started_at="2026-11-01T10:00:00+00:00",
        backup_dir=str(tmp_path),
        db_backup=str(tmp_path / "idm.sqlite3"),
        reinstall=True,
    )
    write_pending_update(pending, path=path)

    assert evaluate_pending_update("1.0.0", path).status == "succeeded"
    mismatch = evaluate_pending_update("0.9.0", path)
    assert mismatch.status == "version-mismatch"
    assert "reinstall" in mismatch.message


def test_evaluate_reinstall_uses_installer_result(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    path = tmp_path / "pending-update.json"
    pending = PendingUpdate(
        from_version="1.0.0",
        target_version="1.0.0",
        started_at="2026-11-01T10:00:00+00:00",
        backup_dir=str(tmp_path),
        db_backup=str(tmp_path / "idm.sqlite3"),
        reinstall=True,
    )
    write_pending_update(pending, path=path)
    write_install_result(
        InstallResult(
            target_version="1.0.0",
            success=False,
            exit_code=1223,
            reinstall=True,
        )
    )

    outcome = evaluate_pending_update("1.0.0", path)

    assert outcome.status == "not-installed"
    assert "did not finish" in outcome.message

    write_install_result(
        InstallResult(
            target_version="1.0.0",
            success=True,
            exit_code=0,
            reinstall=True,
        )
    )
    assert evaluate_pending_update("1.0.0", path).status == "succeeded"


def test_finalize_reinstall_records_success(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    path = tmp_path / "pending-update.json"
    write_pending_update(
        PendingUpdate(
            from_version="1.0.0",
            target_version="1.0.0",
            started_at="2026-11-01T10:00:00+00:00",
            backup_dir=str(tmp_path),
            db_backup=str(tmp_path / "idm.sqlite3"),
            reinstall=True,
        ),
        path=path,
    )
    settings = FakeSettings()

    outcome = finalize_pending_update(settings, "1.0.0", path=path)

    assert outcome.status == "succeeded"
    assert settings.success_version == "1.0.0"
    assert read_pending_update(path) is None
    history = load_history()
    assert history[0]["event"] == "success"
    assert "Reinstall" in history[0]["message"]


def test_pending_update_requires_absolute_backup_path(tmp_path):
    pending = _pending(tmp_path)
    with pytest.raises(UpdateStateError):
        write_pending_update(
            PendingUpdate(
                from_version=pending.from_version,
                target_version=pending.target_version,
                started_at=pending.started_at,
                backup_dir="relative/backup",
                db_backup=pending.db_backup,
            ),
            path=tmp_path / "pending.json",
        )


def test_corrupt_state_file_is_reported(tmp_path):
    path = tmp_path / "pending-update.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(UpdateStateError):
        read_pending_update(path)


def test_evaluate_pending_success_not_installed_and_mismatch(tmp_path):
    path = tmp_path / "pending-update.json"
    write_pending_update(_pending(tmp_path), path=path)

    assert evaluate_pending_update("1.1.0", path).status == "succeeded"
    not_installed = evaluate_pending_update("1.0.0", path)
    assert not_installed.status == "not-installed"
    assert "did not finish" in not_installed.message
    assert evaluate_pending_update("0.9.0", path).status == "version-mismatch"


def test_finalize_success_records_history_and_clears_state(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    path = tmp_path / "pending-update.json"
    write_pending_update(_pending(tmp_path), path=path)
    settings = FakeSettings()

    outcome = finalize_pending_update(settings, "1.1.0", path=path)

    assert outcome.status == "succeeded"
    assert settings.success_version == "1.1.0"
    assert read_pending_update(path) is None
    history = load_history()
    assert history[0]["event"] == "success"


def test_finalize_detects_database_damage(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    path = tmp_path / "pending-update.json"
    write_pending_update(_pending(tmp_path), path=path)
    settings = FakeSettings(corrupt=True)

    outcome = finalize_pending_update(settings, "1.1.0", path=path)

    assert outcome.status == "database-error"
    assert settings.success_version == ""
    assert read_pending_update(path) is None


def test_finalize_failure_records_event(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    path = tmp_path / "pending-update.json"
    write_pending_update(_pending(tmp_path), path=path)

    outcome = finalize_pending_update(FakeSettings(), "1.0.0", path=path)

    assert outcome.status == "not-installed"
    history = load_history()
    assert history[0]["event"] == "failure"
    assert history[0]["target_version"] == "1.1.0"
    assert read_pending_update(path) is None


def test_history_is_newest_first_and_capped(tmp_path):
    path = tmp_path / "history.json"
    for index in range(30):
        append_history({"event": f"event-{index}"}, path=path)
    history = load_history(path)
    assert len(history) == 25
    assert history[0]["event"] == "event-29"
    assert all("at" in entry for entry in history)


def test_record_event_writes_expected_fields(tmp_path):
    path = tmp_path / "history.json"
    record_event(
        "success",
        from_version="1.0.0",
        target_version="1.1.0",
        message="done",
        backup_dir=str(tmp_path),
        path=path,
    )
    entry = load_history(path)[0]
    assert entry["event"] == "success"
    assert entry["from_version"] == "1.0.0"
    assert entry["target_version"] == "1.1.0"
    assert entry["message"] == "done"
    assert entry["backup_dir"] == str(tmp_path)
