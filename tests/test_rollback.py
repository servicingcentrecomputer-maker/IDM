"""Rollback plans, cached installers, snapshots and the updater rollback flow."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from idm.updater.backup import create_pre_update_backup, sha256_file
from idm.updater.errors import RollbackError, SignatureVerificationError
from idm.updater.package_verifier import SignatureInfo
from idm.updater.rollback import (
    build_rollback_plan,
    cache_installer,
    create_binary_snapshot,
    find_cached_installer,
    read_rollback_plan,
    restore_binary_snapshot,
    validate_plan,
    write_rollback_plan,
)
from idm.updater.updater import run_rollback

PUBLISHER = "IDM"


class FakeDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path

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


@pytest.fixture
def backup(tmp_path):
    live = tmp_path / "live.sqlite3"
    connection = sqlite3.connect(str(live))
    try:
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('kept')")
        connection.commit()
    finally:
        connection.close()
    return create_pre_update_backup(
        database=FakeDatabase(live),
        from_version="1.0.0",
        target_version="1.1.0",
        settings_snapshot={"theme": "dark"},
        base_dir=tmp_path / "backups",
    )


def _installer(tmp_path: Path, version: str = "1.0.0", payload: bytes = b"MZinstaller") -> Path:
    path = tmp_path / "installers" / f"IDM_Setup_{version}.exe"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def test_cached_installer_round_trip_and_tamper_detection(tmp_path):
    installer = _installer(tmp_path)
    digest = sha256_file(installer)

    cached = cache_installer(installer, "1.0.0", digest, base_dir=tmp_path / "cache")

    assert cached.is_file()
    found = find_cached_installer("1.0.0", base_dir=tmp_path / "cache")
    assert found is not None
    assert found[0] == cached
    assert found[1] == digest
    assert find_cached_installer("9.9.9", base_dir=tmp_path / "cache") is None

    changed = _installer(tmp_path, "1.2.0", b"MZother")
    with pytest.raises(RollbackError):
        cache_installer(changed, "1.2.0", digest, base_dir=tmp_path / "cache")


def test_binary_snapshot_can_restore_the_application(tmp_path):
    app_dir = tmp_path / "app"
    (app_dir / "nested").mkdir(parents=True)
    (app_dir / "IDM.exe").write_bytes(b"MZ-app")
    (app_dir / "nested" / "library.dll").write_bytes(b"library")

    snapshot = create_binary_snapshot(
        app_dir, "1.0.0", base_dir=tmp_path / "rollback", max_bytes=10_000
    )
    assert snapshot is not None
    assert snapshot.is_dir()
    assert snapshot.name.startswith("app-")

    (app_dir / "IDM.exe").write_bytes(b"MZ-new")
    (app_dir / "nested" / "library.dll").write_bytes(b"new library")
    (app_dir / "extra.txt").write_text("new", encoding="utf-8")

    restore_binary_snapshot(snapshot, app_dir)

    assert (app_dir / "IDM.exe").read_bytes() == b"MZ-app"
    assert (app_dir / "nested" / "library.dll").read_bytes() == b"library"
    assert not (app_dir / "extra.txt").exists()


def test_binary_snapshot_skips_oversized_directory(tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "big.bin").write_bytes(b"x" * 2048)
    assert (
        create_binary_snapshot(
            app_dir, "1.0.0", base_dir=tmp_path / "rollback", max_bytes=1024
        )
        is None
    )


def test_rollback_plan_with_installer_round_trip(tmp_path, backup):
    installer = _installer(tmp_path)
    plan = build_rollback_plan(
        from_version="1.0.0",
        target_version="1.1.0",
        backup_dir=backup.directory,
        db_backup=backup.database,
        previous_installer=installer,
        previous_installer_sha256=sha256_file(installer),
        previous_publisher=PUBLISHER,
        binary_snapshot=None,
        app_exe=tmp_path / "app" / "IDM.exe",
        log_file=tmp_path / "updater.log",
    )
    path = write_rollback_plan(plan, tmp_path / "last-rollback.json")

    loaded = read_rollback_plan(path)
    assert loaded == plan
    validate_plan(loaded)


def test_rollback_plan_accepts_sha256_only_installer(tmp_path, backup):
    installer = _installer(tmp_path)
    plan = build_rollback_plan(
        from_version="1.0.0",
        target_version="1.1.0",
        backup_dir=backup.directory,
        db_backup=backup.database,
        previous_installer=installer,
        previous_installer_sha256=sha256_file(installer),
        previous_publisher="",
        binary_snapshot=None,
        app_exe=tmp_path / "app" / "IDM.exe",
        log_file=tmp_path / "updater.log",
    )
    assert plan.previous_publisher == ""
    validate_plan(plan)


def test_rollback_plan_rejects_wrong_installer_hash(tmp_path, backup):
    installer = _installer(tmp_path)
    with pytest.raises(RollbackError):
        build_rollback_plan(
            from_version="1.0.0",
            target_version="1.1.0",
            backup_dir=backup.directory,
            db_backup=backup.database,
            previous_installer=installer,
            previous_installer_sha256="b" * 64,
            previous_publisher=PUBLISHER,
            binary_snapshot=None,
            app_exe=tmp_path / "app" / "IDM.exe",
            log_file=tmp_path / "updater.log",
        )


def test_rollback_plan_requires_a_restore_source(tmp_path, backup):
    with pytest.raises(RollbackError):
        build_rollback_plan(
            from_version="1.0.0",
            target_version="1.1.0",
            backup_dir=backup.directory,
            db_backup=backup.database,
            previous_installer=None,
            previous_installer_sha256="",
            previous_publisher="",
            binary_snapshot=None,
            app_exe=tmp_path / "app" / "IDM.exe",
            log_file=tmp_path / "updater.log",
        )


def test_rollback_plan_with_snapshot_is_valid(tmp_path, backup):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "IDM.exe").write_bytes(b"MZ")
    snapshot = create_binary_snapshot(
        app_dir, "1.0.0", base_dir=tmp_path / "rollback"
    )
    plan = build_rollback_plan(
        from_version="1.0.0",
        target_version="1.1.0",
        backup_dir=backup.directory,
        db_backup=backup.database,
        previous_installer=None,
        previous_installer_sha256="",
        previous_publisher="",
        binary_snapshot=snapshot,
        app_exe=app_dir / "IDM.exe",
        log_file=tmp_path / "updater.log",
    )
    validate_plan(plan)


def _ready_plan(tmp_path, backup, installer):
    return build_rollback_plan(
        from_version="1.0.0",
        target_version="1.1.0",
        backup_dir=backup.directory,
        db_backup=backup.database,
        previous_installer=installer,
        previous_installer_sha256=sha256_file(installer),
        previous_publisher=PUBLISHER,
        binary_snapshot=None,
        app_exe=tmp_path / "app" / "IDM.exe",
        log_file=tmp_path / "updater.log",
        parent_pid=0,
    )


def _signed(_path):
    return SignatureInfo(status="Valid", simple_name=PUBLISHER)


def test_run_rollback_installs_previous_version_and_restores_database(
    tmp_path, backup, monkeypatch
):
    installer = _installer(tmp_path)
    plan = _ready_plan(tmp_path, backup, installer)
    destination = tmp_path / "data" / "idm.sqlite3"
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr(
        "idm.updater.updater.database_file", lambda: destination
    )
    commands: list[list[str]] = []
    restarted: list[Path] = []

    code = run_rollback(
        plan,
        signature_runner=_signed,
        wait_for_parent=lambda *args: True,
        installer_runner=lambda command: commands.append(command) or 0,
        restart_app=lambda exe: restarted.append(exe),
        notify=lambda *args, **kwargs: None,
    )

    assert code == 0
    assert commands and commands[0][0] == str(installer)
    assert restarted == [tmp_path / "app" / "IDM.exe"]
    assert destination.is_file()
    connection = sqlite3.connect(str(destination))
    try:
        assert connection.execute("SELECT value FROM sample").fetchone() == ("kept",)
    finally:
        connection.close()


def test_run_rollback_refuses_bad_signature(tmp_path, backup, monkeypatch):
    installer = _installer(tmp_path)
    plan = _ready_plan(tmp_path, backup, installer)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr(
        "idm.updater.updater.database_file", lambda: tmp_path / "idm.sqlite3"
    )
    commands: list[list[str]] = []

    def bad_signature(_path):
        return SignatureInfo(status="NotSigned")

    code = run_rollback(
        plan,
        signature_runner=bad_signature,
        wait_for_parent=lambda *args: True,
        installer_runner=lambda command: commands.append(command) or 0,
        restart_app=lambda exe: None,
        notify=lambda *args, **kwargs: None,
    )

    assert code == 4
    assert commands == []


def test_run_rollback_reports_installer_failure(tmp_path, backup, monkeypatch):
    installer = _installer(tmp_path)
    plan = _ready_plan(tmp_path, backup, installer)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr(
        "idm.updater.updater.database_file", lambda: tmp_path / "idm.sqlite3"
    )

    code = run_rollback(
        plan,
        signature_runner=_signed,
        wait_for_parent=lambda *args: True,
        installer_runner=lambda command: 1602,
        restart_app=lambda exe: None,
        notify=lambda *args, **kwargs: None,
    )

    assert code == 5
