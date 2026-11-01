"""Startup classification of a previous update attempt."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from idm.updater.backup import create_pre_update_backup, sha256_file
from idm.updater.recovery import (
    finalize_startup,
    matching_rollback_plan,
    read_pending_safely,
)
from idm.updater.rollback import build_rollback_plan, write_rollback_plan
from idm.updater.state import PendingUpdate, write_pending_update


class FakeDatabase:
    def __init__(self, path: Path, *, corrupt: bool = False) -> None:
        self.path = path
        self.corrupt = corrupt

    def backup(self, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.path, destination)
        return destination

    def load_queue(self) -> list[dict]:
        return []

    def load_downloads(self) -> list[dict]:
        return []

    def schema_version(self) -> int:
        return 7

    def quick_check(self) -> None:
        if self.corrupt:
            raise RuntimeError("SQLite quick_check failed: corrupt")


class FakeSettings:
    def __init__(self, *, corrupt: bool = False) -> None:
        self.database = FakeDatabase(Path("unused"), corrupt=corrupt)
        self.success_version = ""

    def note_update_success(self, version: str) -> None:
        self.success_version = version


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    live = tmp_path / "live.sqlite3"
    connection = sqlite3.connect(str(live))
    try:
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.commit()
    finally:
        connection.close()
    backup = create_pre_update_backup(
        database=FakeDatabase(live),
        from_version="1.0.0",
        target_version="1.1.0",
        settings_snapshot={},
        base_dir=tmp_path / "backups",
    )
    return tmp_path, backup


def _pending(tmp_path, backup) -> PendingUpdate:
    return PendingUpdate(
        from_version="1.0.0",
        target_version="1.1.0",
        started_at="2026-11-01T10:00:00+00:00",
        backup_dir=str(backup.directory),
        db_backup=str(backup.database),
        app_exe=str(tmp_path / "app" / "IDM.exe"),
    )


def test_no_pending_update_returns_none(environment):
    assert read_pending_safely() is None
    report = finalize_startup(FakeSettings(), "2.0.0")
    assert report.status == "none"
    assert report.pending is None
    assert report.needs_attention is False


def test_successful_update_is_reported(environment, tmp_path):
    _, backup = environment
    write_pending_update(_pending(tmp_path, backup))
    settings = FakeSettings()

    report = finalize_startup(settings, "1.1.0")

    assert report.status == "succeeded"
    assert report.succeeded is True
    assert settings.success_version == "1.1.0"
    assert "installed successfully" in report.message


def test_successful_reinstall_is_reported(environment, tmp_path):
    _, backup = environment
    write_pending_update(
        PendingUpdate(
            from_version="1.0.0",
            target_version="1.0.0",
            started_at="2026-11-01T10:00:00+00:00",
            backup_dir=str(backup.directory),
            db_backup=str(backup.database),
            app_exe=str(tmp_path / "app" / "IDM.exe"),
            reinstall=True,
        )
    )
    settings = FakeSettings()

    report = finalize_startup(settings, "1.0.0")

    assert report.status == "succeeded"
    assert report.succeeded is True
    assert settings.success_version == "1.0.0"
    assert "reinstalled successfully" in report.message


def test_failed_update_needs_attention(environment, tmp_path):
    _, backup = environment
    write_pending_update(_pending(tmp_path, backup))

    report = finalize_startup(FakeSettings(), "1.0.0")

    assert report.status == "not-installed"
    assert report.needs_attention is True
    assert "did not finish" in report.message


def test_database_damage_is_reported(environment, tmp_path):
    _, backup = environment
    write_pending_update(_pending(tmp_path, backup))

    report = finalize_startup(FakeSettings(corrupt=True), "1.1.0")

    assert report.status == "database-error"
    assert report.needs_attention is True
    assert "integrity" in report.message


def test_database_restored_flag_is_included(environment, tmp_path):
    _, backup = environment
    write_pending_update(_pending(tmp_path, backup))

    report = finalize_startup(FakeSettings(), "1.1.0", database_restored=True)

    assert report.database_restored is True
    assert "restored during startup" in report.message


def test_corrupt_pending_file_is_ignored(environment, tmp_path):
    pending_file = tmp_path / "appdata" / "IDM Download Manager" / "updates" / "pending-update.json"
    pending_file.parent.mkdir(parents=True)
    pending_file.write_text("{", encoding="utf-8")
    assert read_pending_safely() is None


def test_matching_rollback_plan_requires_same_versions(environment, tmp_path):
    _, backup = environment
    installer = tmp_path / "IDM_Setup_1.0.0.exe"
    installer.write_bytes(b"MZprevious")
    plan = build_rollback_plan(
        from_version="1.0.0",
        target_version="1.1.0",
        backup_dir=backup.directory,
        db_backup=backup.database,
        previous_installer=installer,
        previous_installer_sha256=sha256_file(installer),
        previous_publisher="IDM",
        binary_snapshot=None,
        app_exe=tmp_path / "app" / "IDM.exe",
        log_file=tmp_path / "updater.log",
    )
    plan_file = write_rollback_plan(plan, tmp_path / "last-rollback.json")
    base = _pending(tmp_path, backup)
    pending = PendingUpdate(
        from_version=base.from_version,
        target_version=base.target_version,
        started_at=base.started_at,
        backup_dir=base.backup_dir,
        db_backup=base.db_backup,
        previous_installer=str(installer),
        previous_installer_sha256=sha256_file(installer),
        previous_publisher="IDM",
        app_exe=base.app_exe,
    )

    assert matching_rollback_plan(pending, plan_file) == plan

    other = PendingUpdate(
        from_version="0.9.0",
        target_version="1.1.0",
        started_at=pending.started_at,
        backup_dir=pending.backup_dir,
        db_backup=pending.db_backup,
        previous_installer=pending.previous_installer,
        previous_installer_sha256=pending.previous_installer_sha256,
        previous_publisher=pending.previous_publisher,
        app_exe=pending.app_exe,
    )
    assert matching_rollback_plan(other, plan_file) is None
