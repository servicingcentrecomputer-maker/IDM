"""Verified pre-update backup tests."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from idm.updater.backup import (
    DATABASE_NAME,
    MANIFEST_NAME,
    BackupError,
    create_pre_update_backup,
    prune_backups,
    restore_database,
    sha256_file,
    verify_backup,
)


class FakeDatabase:
    def __init__(self, path: Path, *, fail: bool = False) -> None:
        self.path = path
        self.fail = fail

    def backup(self, destination: Path) -> Path:
        if self.fail:
            raise OSError("disk full")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.path, destination)
        return destination

    def load_queue(self) -> list[dict]:
        return [{"position": 0, "download_id": "abc"}]

    def load_downloads(self) -> list[dict]:
        return [{"id": "abc", "filename": "file.zip"}]

    def schema_version(self) -> int:
        return 7


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "live.sqlite3"
    connection = sqlite3.connect(str(path))
    try:
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('hello')")
        connection.commit()
    finally:
        connection.close()
    return FakeDatabase(path)


@pytest.fixture
def browser_dir(tmp_path):
    directory = tmp_path / "native"
    directory.mkdir()
    (directory / "com.idm.native.chrome.json").write_text("{}", encoding="utf-8")
    return directory


def _make_backup(database, tmp_path, browser_dir, *, now=None, keep=5):
    return create_pre_update_backup(
        database=database,
        from_version="1.0.0",
        target_version="1.1.0",
        settings_snapshot={"theme": "dark", "max_concurrent": 4},
        update_config={"channel": "stable"},
        manifest=None,
        browser_manifest_dir=browser_dir,
        base_dir=tmp_path / "backups",
        keep=keep,
        now=now,
    )


def test_backup_contains_verified_user_data(database, tmp_path, browser_dir):
    backup = _make_backup(database, tmp_path, browser_dir)

    assert backup.directory.is_dir()
    assert backup.database.is_file()
    assert backup.database.name == DATABASE_NAME
    assert (backup.directory / "settings.json").is_file()
    assert (backup.directory / "queue.json").is_file()
    assert (backup.directory / "downloads.json").is_file()
    assert (backup.directory / "browser-integration" / "com.idm.native.chrome.json").is_file()
    verify_backup(backup.directory)

    payload = json.loads((backup.directory / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert payload["from_version"] == "1.0.0"
    assert payload["target_version"] == "1.1.0"
    assert DATABASE_NAME in payload["files"]
    assert payload["files"][DATABASE_NAME]["sha256"] == sha256_file(backup.database)


def test_tampered_backup_fails_verification(database, tmp_path, browser_dir):
    backup = _make_backup(database, tmp_path, browser_dir)
    target = backup.directory / "settings.json"
    target.write_text('{"theme": "light"}', encoding="utf-8")
    with pytest.raises(BackupError):
        verify_backup(backup.directory)


def test_missing_backup_file_fails_verification(database, tmp_path, browser_dir):
    backup = _make_backup(database, tmp_path, browser_dir)
    (backup.directory / "queue.json").unlink()
    with pytest.raises(BackupError):
        verify_backup(backup.directory)


def test_unsafe_manifest_path_is_rejected(database, tmp_path, browser_dir):
    backup = _make_backup(database, tmp_path, browser_dir)
    manifest_path = backup.directory / MANIFEST_NAME
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["files"]["../outside.json"] = {"sha256": "0" * 64, "size": 0}
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BackupError):
        verify_backup(backup.directory)


def test_restore_database_uses_verified_copy(database, tmp_path, browser_dir):
    backup = _make_backup(database, tmp_path, browser_dir)
    destination = tmp_path / "restore" / "idm.sqlite3"
    destination.parent.mkdir()
    destination.write_bytes(b"broken")

    restored = restore_database(backup.directory, destination)

    assert restored == destination
    assert destination.read_bytes() == backup.database.read_bytes()
    connection = sqlite3.connect(str(destination))
    try:
        assert connection.execute("SELECT value FROM sample").fetchone() == ("hello",)
    finally:
        connection.close()


def test_backup_failure_cleans_partial_directory(tmp_path):
    database = FakeDatabase(tmp_path / "missing.sqlite3", fail=True)
    with pytest.raises(BackupError):
        create_pre_update_backup(
            database=database,
            from_version="1.0.0",
            target_version="1.1.0",
            settings_snapshot={},
            base_dir=tmp_path / "backups",
        )
    root = tmp_path / "backups"
    assert not root.exists() or not any(root.iterdir())


def test_prune_backups_keeps_newest_entries(tmp_path):
    root = tmp_path / "backups"
    root.mkdir()
    for index in range(12):
        entry = root / f"entry-{index}"
        entry.mkdir()
        moment = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=index)
        os.utime(entry, (moment.timestamp(), moment.timestamp()))

    removed = prune_backups(root, keep=3)

    assert removed == 9
    assert len(list(root.iterdir())) == 3
