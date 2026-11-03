"""SQLite persistence and session restoration tests."""

from __future__ import annotations

from idm.core.settings import AppSettings
from idm.engine.manager import DownloadManager
from idm.models.download_item import DownloadStatus


def test_settings_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    settings = AppSettings()
    assert settings.theme == "light"
    settings.theme = "dark"
    settings.max_concurrent = 5
    settings.speed_limit_kbps = 256
    settings.show_sidebar = False
    settings.save()
    settings.close()

    restored = AppSettings()
    try:
        assert restored.theme == "dark"
        assert restored.max_concurrent == 5
        assert restored.speed_limit_kbps == 256
        assert restored.show_sidebar is False
    finally:
        restored.close()


def test_in_progress_downloads_restore_as_paused(
    qt_app, server, tmp_path, monkeypatch
):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    folder = tmp_path / "downloads"
    settings = AppSettings()
    manager = DownloadManager(settings)
    active = manager.add_download(
        server.url("/file/1024"),
        "restore-active.bin",
        str(folder),
        start_immediately=False,
    )
    queued = manager.add_download(
        server.url("/file/1024"),
        "restore-queued.bin",
        str(folder),
        start_immediately=False,
    )
    manager.shutdown()

    for item, status in (
        (active, DownloadStatus.DOWNLOADING),
        (queued, DownloadStatus.QUEUED),
    ):
        record = manager._record_for(item)
        record["status"] = status.value
        settings.database.save_download(record)
    settings.close()

    restored_settings = AppSettings()
    restored_manager = DownloadManager(restored_settings)
    try:
        restored_active = restored_manager.get(active.id)
        restored_queued = restored_manager.get(queued.id)
        assert restored_active is not None
        assert restored_queued is not None
        assert restored_active.status == DownloadStatus.PAUSED
        assert restored_queued.status == DownloadStatus.PAUSED
        assert restored_active.downloaded_bytes == 0
        assert restored_manager.active_count == 0
    finally:
        restored_manager.shutdown()
        restored_settings.close()
