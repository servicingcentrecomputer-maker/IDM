"""“Download Later” hold semantics and queue persistence tests."""

from __future__ import annotations

import time

import pytest

from idm.core.settings import AppSettings
from idm.engine.manager import DownloadManager
from idm.models.download_item import DownloadStatus
from idm.ui.dialogs.queue import QueueDialog
from idm.ui.theme import ThemeManager
from tests.http_server import payload


def wait_until(app, predicate, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return bool(predicate())


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    instance = AppSettings()
    instance.download_dir = str(tmp_path / "Downloads")
    instance.max_concurrent = 1
    yield instance
    instance.close()


@pytest.fixture
def manager(qt_app, settings):
    instance = DownloadManager(settings)
    yield instance
    instance.shutdown()


def test_download_later_creates_a_held_queue_entry(
    manager, settings, server, tmp_path
) -> None:
    item = manager.add_download(
        server.url("/file/4096"),
        "held.bin",
        str(tmp_path / "Downloads"),
        description="Read this tomorrow",
        download_later=True,
        start_immediately=False,
    )
    assert item.status == DownloadStatus.QUEUED
    assert item.queued_later is True
    assert item.description == "Read this tomorrow"
    assert manager._workers == {}
    assert manager.active_count == 0

    record = settings.database.load_downloads()[0]
    assert record["start_later"] == 1
    assert record["description"] == "Read this tomorrow"
    assert record["status"] == DownloadStatus.QUEUED.value


def test_held_entry_does_not_take_a_queue_slot(
    qt_app, manager, settings, server, tmp_path
) -> None:
    folder = tmp_path / "Downloads"
    held = manager.add_download(
        server.url("/file/2048"),
        "held.bin",
        str(folder),
        download_later=True,
        start_immediately=False,
    )
    active = manager.add_download(
        server.url("/file/1024"),
        "active.bin",
        str(folder),
        start_immediately=True,
    )
    assert wait_until(
        qt_app,
        lambda: active.status == DownloadStatus.COMPLETED and not manager._workers,
    ), (active.status, active.error)
    assert active.path.read_bytes() == payload(1024)
    assert held.status == DownloadStatus.QUEUED
    assert held.queued_later is True


def test_held_entry_survives_restart_and_can_be_started(
    qt_app, settings, server, tmp_path
) -> None:
    folder = tmp_path / "Downloads"
    manager = DownloadManager(settings)
    item = manager.add_download(
        server.url("/file/3072"),
        "later.bin",
        str(folder),
        description="Saved for later",
        download_later=True,
        start_immediately=False,
    )
    download_id = item.id
    manager.shutdown()
    settings.close()

    restored_settings = AppSettings()
    restored = DownloadManager(restored_settings)
    try:
        carried = restored.get(download_id)
        assert carried is not None
        assert carried.status == DownloadStatus.QUEUED
        assert carried.queued_later is True
        assert carried.description == "Saved for later"
        assert restored._workers == {}

        assert restored.start_queued([download_id]) == 1
        assert wait_until(
            qt_app,
            lambda: carried.status == DownloadStatus.COMPLETED and not restored._workers,
        ), (carried.status, carried.error)
        assert carried.path.read_bytes() == payload(3072)
        assert not (folder / "later.bin.idm.part").exists()

        record = restored_settings.database.load_downloads()[0]
        assert record["start_later"] == 0
    finally:
        restored.shutdown()
        restored_settings.close()


def test_start_queued_ignores_waiting_or_unknown_items(
    manager, settings, server, tmp_path
) -> None:
    waiting = manager.add_download(
        server.url("/file/1024"),
        "waiting.bin",
        str(tmp_path / "Downloads"),
        start_immediately=False,
    )
    assert manager.start_queued([waiting.id]) == 0
    assert manager.start_queued(["missing"]) == 0
    assert waiting.status == DownloadStatus.PAUSED


def test_queue_dialog_marks_and_starts_held_entries(
    qt_app, manager, settings, server, tmp_path
) -> None:
    folder = tmp_path / "Downloads"
    held = manager.add_download(
        server.url("/file/1024"),
        "queued-later.bin",
        str(folder),
        download_later=True,
        start_immediately=False,
    )
    waiting = manager.add_download(
        server.url("/file/1024?other=1"),
        "waiting.bin",
        str(folder),
        start_immediately=False,
    )
    waiting.status = DownloadStatus.QUEUED
    manager.queue_changed.emit()

    theme = ThemeManager(qt_app)
    dialog = QueueDialog(manager, theme)
    try:
        assert dialog._table.rowCount() == 2
        states = {
            dialog._table.item(row, 1).text(): dialog._table.item(row, 3).text()
            for row in range(2)
        }
        assert states == {"queued-later.bin": "Later", "waiting.bin": "Waiting"}
        assert "1 set for later" in dialog._info.text()

        for row in range(dialog._table.rowCount()):
            if dialog._table.item(row, 1).text() == "queued-later.bin":
                dialog._table.selectRow(row)
                break
        qt_app.processEvents()
        assert dialog._start_button.isEnabled()

        dialog._start_now()
        assert held.queued_later is False
        assert manager.start_queued([held.id]) == 0
    finally:
        dialog.deleteLater()
