"""UI behaviour tests and offscreen screenshots."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PySide6.QtCore import QDateTime
from PySide6.QtWidgets import QDialog

from idm.constants import custom_category_key
from idm.core.scheduler import SCHEDULE_ACTIONS
from idm.core.settings import AppSettings
from idm.core.url_utils import format_size
from idm.models.download_item import DownloadItem, DownloadStatus
from idm.models.table_model import (
    COLUMN_DATE_ADDED,
    COLUMN_DOWNLOADED,
    COLUMN_ETA,
    COLUMN_NAME,
    COLUMN_SPEED,
    ITEM_ROLE,
)
from idm.ui import main_window as main_window_module
from idm.ui.dialogs.about import AboutDialog
from idm.ui.dialogs.add_download import AddDownloadDialog
from idm.ui.dialogs.complete import DownloadCompleteDialog
from idm.ui.dialogs.options import OptionsDialog
from idm.ui.dialogs.progress import DownloadProgressDialog
from idm.ui.dialogs.queue import QueueDialog
from idm.ui.dialogs.scheduler import SchedulerDialog
from idm.ui.main_window import MainWindow, _parse_download_list, _sidebar_counts
from idm.ui.theme import ThemeManager
from idm.ui.toolbar import DownloadToolbar

ARTIFACTS = Path(__file__).resolve().parents[1] / "build" / "ui-check"


def wait_until(app, predicate, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return bool(predicate())


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    settings = AppSettings()
    settings.theme = "dark"
    settings.download_dir = str(tmp_path / "downloads")
    settings.max_concurrent = 3
    yield settings
    settings.close()


@pytest.fixture
def window(qt_app, isolated_settings):
    theme = ThemeManager(qt_app)
    theme.set_mode("dark")
    instance = MainWindow(isolated_settings, theme)
    instance.resize(1240, 770)
    instance.show()
    qt_app.processEvents()
    yield instance
    instance._shutdown()
    instance.hide()
    instance.deleteLater()
    qt_app.processEvents()


def test_main_window_shell_and_theme_toggle(qt_app, window):
    assert window.isVisible()
    assert window.windowTitle() == "IDM 3.6.2 – Internet Download Manager"
    assert set(window._toolbar.buttons) == {
        "add",
        "resume",
        "resume_all",
        "pause",
        "stop",
        "stop_all",
        "delete",
        "delete_completed",
        "refresh",
        "options",
        "scheduler",
        "queue",
    }
    assert window._toolbar.buttons["add"].text() == "Add URL"
    assert {"view_show_toolbar", "view_show_sidebar", "view_show_status_bar"}.issubset(
        window._actions
    )
    assert {
        "refresh",
        "import",
        "export",
        "pause_all",
        "stop_all",
        "delete_completed",
        "categories",
        "docs",
        "about",
        "check_updates",
    }.issubset(window._actions)
    assert window._download_view.empty_state.isVisible()
    assert window._page_title.text() == "All Downloads"

    window._focus_search()
    assert window._search.hasFocus()
    window._clear_search()

    assert window._theme.is_dark
    window._set_theme("light")
    qt_app.processEvents()
    assert not window._theme.is_dark
    assert window._settings.theme == "light"
    assert window._theme_actions["light"].isChecked()
    window._set_theme("dark")
    assert window._theme.is_dark
    assert window._theme_actions["dark"].isChecked()

    window._actions["view_show_toolbar"].setChecked(False)
    qt_app.processEvents()
    assert not window._toolbar.isVisible()
    assert window._settings.show_toolbar is False
    window._actions["view_show_toolbar"].setChecked(True)
    qt_app.processEvents()
    assert window._toolbar.isVisible()


def test_sort_control_refresh_and_other_files(qt_app, window, tmp_path):
    big = window._manager.add_download(
        "https://example.com/big.zip",
        "big.zip",
        str(tmp_path),
        start_immediately=False,
    )
    small = window._manager.add_download(
        "https://example.com/small.zip",
        "small.zip",
        str(tmp_path),
        start_immediately=False,
    )
    big.total_bytes = 2048
    small.total_bytes = 1024
    assert window._actions["refresh"].shortcut().toString() == "F5"

    window._sort_combo.setCurrentIndex(2)  # Largest first
    qt_app.processEvents()
    first = window._proxy.index(0, COLUMN_NAME).data(ITEM_ROLE)
    assert first.filename == "big.zip"

    window._download_view.table._on_header_clicked(COLUMN_NAME)
    assert window._sort_combo.currentIndex() == 1

    window._sort_combo.setCurrentIndex(0)
    window._refresh_download_list()
    qt_app.processEvents()
    assert window._proxy.rowCount() == 2
    assert window._status_bar._message.text() == "Download list refreshed."

    window._sidebar.select("other", emit_signal=True)
    qt_app.processEvents()
    assert window._page_title.text() == "Other Files"
    assert window._proxy.rowCount() == 0


def test_download_views_filters_search_and_screenshots(qt_app, server, window, tmp_path):
    docs = window._manager.add_download(
        server.url("/file/65536"), "quarterly-report.pdf", str(tmp_path)
    )
    music = window._manager.add_download(
        server.url("/file/49152"), "summer-mix.mp3", str(tmp_path)
    )
    assert wait_until(
        qt_app,
        lambda: docs.status == DownloadStatus.COMPLETED
        and music.status == DownloadStatus.COMPLETED,
        15,
    )
    assert wait_until(qt_app, lambda: window._proxy.rowCount() == 2)
    assert docs.category == "Documents"
    assert music.category == "Music"
    assert not window._download_view.empty_state.isVisible()

    window._select_item(docs.id)
    qt_app.processEvents()
    assert len(window._selected_items()) == 1
    assert not window._toolbar.buttons["pause"].isEnabled()
    assert not window._toolbar.buttons["resume"].isEnabled()
    assert window._toolbar.buttons["delete"].isEnabled()
    assert window._actions["delete_completed"].isEnabled()

    window._sidebar.select("documents", emit_signal=True)
    qt_app.processEvents()
    assert window._proxy.rowCount() == 1
    assert window._page_title.text() == "Documents"

    window._sidebar.select("music", emit_signal=True)
    qt_app.processEvents()
    assert window._proxy.rowCount() == 1

    window._sidebar.select("downloading", emit_signal=True)
    qt_app.processEvents()
    assert window._proxy.rowCount() == 0
    assert window._download_view.empty_state.isVisible()

    window._sidebar.select("completed", emit_signal=True)
    qt_app.processEvents()
    assert window._proxy.rowCount() == 2

    window._sidebar.select("all", emit_signal=True)
    window._search.setText("song")
    qt_app.processEvents()
    assert window._proxy.rowCount() == 0
    assert window._download_view.empty_state._title.text() == "No matches"
    window._search.clear()
    qt_app.processEvents()
    assert window._proxy.rowCount() == 2

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    window._set_theme("classic")
    qt_app.processEvents()
    window.grab().save(str(ARTIFACTS / "main-classic.png"))
    window._set_theme("light")
    qt_app.processEvents()
    window.grab().save(str(ARTIFACTS / "main-light.png"))
    window._set_theme("dark")
    qt_app.processEvents()
    window.grab().save(str(ARTIFACTS / "main-dark.png"))
    assert (ARTIFACTS / "main-classic.png").stat().st_size > 10_000
    assert (ARTIFACTS / "main-light.png").stat().st_size > 10_000
    assert (ARTIFACTS / "main-dark.png").stat().st_size > 10_000


def test_toolbar_actions_follow_status(qt_app, server, window, tmp_path):
    item = window._manager.add_download(
        server.url("/slow/4194304"), "active-download.bin", str(tmp_path)
    )
    assert wait_until(
        qt_app,
        lambda: item.status == DownloadStatus.DOWNLOADING
        and item.downloaded_bytes > 0,
        10,
    )
    window._select_item(item.id)
    qt_app.processEvents()
    assert window._toolbar.buttons["pause"].isEnabled()
    assert window._toolbar.buttons["stop"].isEnabled()
    assert not window._toolbar.buttons["resume"].isEnabled()

    window._pause_selected()
    assert wait_until(
        qt_app, lambda: item.status == DownloadStatus.PAUSED and not window._manager._workers, 10
    )
    qt_app.processEvents()
    assert window._toolbar.buttons["resume"].isEnabled()
    assert window._toolbar.buttons["stop"].isEnabled()
    assert not window._toolbar.buttons["pause"].isEnabled()

    window._resume_selected()
    assert wait_until(qt_app, lambda: item.status == DownloadStatus.DOWNLOADING, 10)
    window._stop_selected()
    assert wait_until(
        qt_app, lambda: item.status == DownloadStatus.STOPPED and not window._manager._workers, 10
    )
    assert item.part_path.exists()
    window._manager.remove([item.id], delete_files=False)
    assert wait_until(qt_app, lambda: not window._manager._workers)


def test_add_dialog_probe_and_validation(qt_app, server, window, tmp_path):
    dialog = AddDownloadDialog(window._settings, window._theme, window)
    dialog.show()
    folder = tmp_path / "from-dialog"
    dialog.folder_edit.setText(str(folder))
    dialog.url_edit.setText(server.url("/disposition/65536?name=manual.pdf"))

    assert wait_until(
        qt_app, lambda: dialog.probe_label.property("state") == "ok", 10
    ), dialog.probe_label.text()
    assert dialog.filename_edit.text() == "manual.pdf"
    assert "64.0 KB" in dialog.probe_label.text()
    assert "Resumable" in dialog.probe_label.text()
    assert dialog.category_combo.currentData() == "Documents"
    assert dialog.start_button.text() == "Start Download"
    assert dialog.later_button.text() == "Download Later"
    assert dialog.start_button.isDefault()

    dialog._validate_and_accept(True)
    assert dialog.result() == QDialog.DialogCode.Accepted
    values = dialog.values()
    assert values["url"] == server.url("/disposition/65536?name=manual.pdf")
    assert values["filename"] == "manual.pdf"
    assert values["folder"] == str(folder)
    assert values["category"] == "Documents"
    assert values["start_immediately"] is True
    dialog.deleteLater()

    later = AddDownloadDialog(window._settings, window._theme, window)
    later.show()
    later.folder_edit.setText(str(folder))
    later.url_edit.setText(server.url("/disposition/65536?name=later.pdf"))
    assert wait_until(
        qt_app, lambda: later.probe_label.property("state") == "ok", 10
    )
    assert later.start_button.isDefault()

    window._settings.start_immediately = False
    paused_pref = AddDownloadDialog(window._settings, window._theme, window)
    assert paused_pref.later_button.isDefault()
    paused_pref.deleteLater()
    window._settings.start_immediately = True

    later._validate_and_accept(False)
    assert later.values()["start_immediately"] is False
    later.deleteLater()

    invalid = AddDownloadDialog(window._settings, window._theme, window)
    invalid.show()
    invalid.url_edit.setText("ftp://example.com/file.zip")
    invalid.filename_edit.setText("file.zip")
    invalid.folder_edit.setText(str(folder))
    invalid._validate_and_accept(True)
    qt_app.processEvents()
    assert invalid.result() != QDialog.DialogCode.Accepted
    assert invalid.error_label.isVisible()
    assert "HTTP" in invalid.error_label.text()
    invalid.reject()
    invalid.deleteLater()


def test_options_dialog_values(qt_app, window):
    dialog = OptionsDialog(window._settings, window._theme, window)
    dialog.show()
    dialog._preview_theme("classic")
    qt_app.processEvents()
    assert window._theme.mode == "classic"
    assert dialog.theme_cards["classic"].property("selected") == "true"
    dialog._preview_theme("light")
    dialog.concurrent_spin.setValue(4)
    dialog.retry_checkbox.setChecked(False)
    dialog.retry_spin.setValue(5)
    dialog.speed_spin.setValue(512)
    dialog.toolbar_check.setChecked(False)
    dialog.status_check.setChecked(False)
    dialog.update_url_edit.setText("https://updates.example.com/idm/latest.json")
    dialog.publisher_edit.setText("IDM")
    dialog._save()
    assert dialog.result() == QDialog.DialogCode.Accepted
    values = dialog.values()
    assert values["theme"] == "light"
    assert values["max_concurrent"] == 4
    assert values["auto_retry"] is False
    assert values["max_retries"] == 5
    assert values["speed_limit_kbps"] == 512
    assert values["show_toolbar"] is False
    assert values["show_status_bar"] is False
    assert values["update_manifest_url"] == "https://updates.example.com/idm/latest.json"
    assert values["update_publisher"] == "IDM"
    dialog.deleteLater()


def test_options_reject_insecure_update_endpoint(qt_app, window):
    dialog = OptionsDialog(window._settings, window._theme, window)
    dialog.show()
    dialog.update_url_edit.setText("http://updates.example.com/latest.json")
    dialog._save()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.error_label.isVisible()
    assert "HTTPS" in dialog.error_label.text()
    dialog.reject()
    dialog.deleteLater()


def test_options_cancel_restores_theme(qt_app, window):
    original = window._theme.mode
    dialog = OptionsDialog(window._settings, window._theme, window)
    dialog.show()
    other = "light" if original != "light" else "classic"
    dialog._preview_theme(other)
    qt_app.processEvents()
    assert window._theme.mode == other
    dialog.reject()
    qt_app.processEvents()
    assert window._theme.mode == original


def test_about_dialog(qt_app, window):
    dialog = AboutDialog(window._theme, window)
    dialog.show()
    qt_app.processEvents()
    assert "About IDM" in dialog.windowTitle()
    assert dialog.isVisible()
    dialog.accept()
    dialog.deleteLater()


def test_header_sorting(qt_app, window, tmp_path):
    manager = window._manager
    bravo = manager.add_download(
        "https://example.com/bravo.bin", "bravo.bin", str(tmp_path),
        start_immediately=False,
    )
    alpha = manager.add_download(
        "https://example.com/alpha.bin", "alpha.bin", str(tmp_path),
        start_immediately=False,
    )
    assert wait_until(qt_app, lambda: window._proxy.rowCount() == 2)
    table = window._download_view.table

    table._on_header_clicked(COLUMN_NAME)
    qt_app.processEvents()
    first = window._proxy.index(0, COLUMN_NAME).data(ITEM_ROLE)
    second = window._proxy.index(1, COLUMN_NAME).data(ITEM_ROLE)
    assert first.filename == "alpha.bin"
    assert second.filename == "bravo.bin"

    table._on_header_clicked(COLUMN_NAME)
    qt_app.processEvents()
    first = window._proxy.index(0, COLUMN_NAME).data(ITEM_ROLE)
    assert first.filename == "bravo.bin"
    table.reset_sort()
    manager.remove([alpha.id, bravo.id])


def test_progress_dialog_tracks_and_controls(qt_app, server, window, tmp_path):
    item = window._manager.add_download(
        server.url("/slow/4194304"), "progress.bin", str(tmp_path)
    )
    assert wait_until(
        qt_app,
        lambda: item.status == DownloadStatus.DOWNLOADING and item.downloaded_bytes > 0,
        10,
    )
    dialog = DownloadProgressDialog(
        window._manager, item.id, window._theme, window
    )
    dialog.show()
    qt_app.processEvents()
    assert dialog.isVisible()
    assert dialog._name.text() == "progress.bin"
    assert dialog._pause_button.text() == "Pause"
    assert dialog._progress.value() >= 0

    dialog._toggle_pause()
    assert wait_until(
        qt_app,
        lambda: item.status == DownloadStatus.PAUSED
        and not window._manager._workers,
        10,
    ), item.error
    assert dialog._pause_button.text() == "Resume"

    dialog._toggle_pause()
    assert wait_until(
        qt_app, lambda: item.status == DownloadStatus.DOWNLOADING, 10
    ), item.error

    dialog._cancel()
    assert wait_until(
        qt_app,
        lambda: item.status in {DownloadStatus.STOPPED, DownloadStatus.COMPLETED}
        and not window._manager._workers,
        10,
    ), item.error
    window._manager.remove([item.id], delete_files=False)
    assert wait_until(qt_app, lambda: not window._manager._workers)


def test_export_import_round_trip(qt_app, server, window, tmp_path, monkeypatch):
    manager = window._manager
    item = manager.add_download(
        server.url("/file/8192"),
        "exported.bin",
        str(tmp_path),
        start_immediately=False,
    )
    export_path = tmp_path / "downloads.json"

    class FakeFileDialog:
        save_path = export_path
        open_path = export_path

        @staticmethod
        def getSaveFileName(*_args, **_kwargs):
            return str(FakeFileDialog.save_path), "JSON files (*.json)"

        @staticmethod
        def getOpenFileName(*_args, **_kwargs):
            return str(FakeFileDialog.open_path), "JSON files (*.json)"

    monkeypatch.setattr(main_window_module, "QFileDialog", FakeFileDialog)
    window._export_downloads()
    assert export_path.is_file()
    payload = export_path.read_text(encoding="utf-8")
    assert "exported.bin" in payload
    assert "downloads" in payload

    manager.remove([item.id])
    qt_app.processEvents()
    assert manager.items() == []

    window._import_downloads()
    imported = manager.items()
    assert len(imported) == 1
    assert imported[0].filename == "exported.bin"
    assert imported[0].status == DownloadStatus.PAUSED
    manager.remove([imported[0].id])


def test_completion_dialog_reports_real_details(qt_app, window, tmp_path):
    item = DownloadItem(
        url="https://example.com/report.pdf",
        filename="report.pdf",
        folder=str(tmp_path),
        category="Documents",
        total_bytes=65536,
        downloaded_bytes=65536,
        status=DownloadStatus.COMPLETED,
        created_at=datetime.now() - timedelta(seconds=4),
        completed_at=datetime.now(),
    )
    item.path.write_bytes(b"0" * 65536)

    dialog = DownloadCompleteDialog(item, window._theme, window._settings, window)
    dialog.show()
    qt_app.processEvents()
    assert dialog.isVisible()
    assert dialog._name.text() == "report.pdf"
    assert dialog._size.text() == "64.0 KB"
    assert dialog._source.text() == "example.com"
    assert dialog._speed.text().endswith("/s")
    assert dialog._file_button.isEnabled()

    window._settings.show_completion_dialog = True
    dialog._remember.setChecked(False)
    assert window._settings.show_completion_dialog is False
    dialog.close()
    dialog.deleteLater()
    qt_app.processEvents()


def test_completion_event_opens_and_cleans_up_dialog(qt_app, window, tmp_path):
    item = DownloadItem(
        url="https://example.com/archive.zip",
        filename="archive.zip",
        folder=str(tmp_path),
        category="Compressed",
        total_bytes=4096,
        downloaded_bytes=4096,
        status=DownloadStatus.COMPLETED,
        completed_at=datetime.now(),
    )
    window._settings.show_completion_dialog = True
    window._on_download_completed(item)
    qt_app.processEvents()
    assert item.id in window._completion_dialogs
    dialog = window._completion_dialogs[item.id]
    dialog.close()
    qt_app.processEvents()
    assert item.id not in window._completion_dialogs

    window._settings.show_completion_dialog = False
    window._on_download_completed(item)
    qt_app.processEvents()
    assert item.id not in window._completion_dialogs


def test_custom_categories_appear_in_sidebar_and_filter(qt_app, window, tmp_path):
    window._settings.update(
        {"custom_categories": [{"name": "Books", "extensions": ["cbz"]}]}
    )
    window._refresh_custom_categories()
    item = window._manager.add_download(
        "https://example.com/novel.cbz",
        "novel.cbz",
        str(tmp_path),
        category="Books",
        start_immediately=False,
    )
    assert wait_until(qt_app, lambda: window._proxy.rowCount() == 1)

    key = custom_category_key("Books")
    assert "Books" in window._custom_names
    window._sidebar.select(key, emit_signal=True)
    qt_app.processEvents()
    assert window._proxy.rowCount() == 1
    assert window._page_title.text() == "Books"
    counts = _sidebar_counts(window._manager.items(), 0, window._custom_names)
    assert counts[key] == 1
    window._manager.remove([item.id])
    qt_app.processEvents()


def test_parse_download_list_formats():
    entries = _parse_download_list(
        "https://example.com/a.bin\n# comment\n\nhttps://example.com/b.bin\n"
    )
    assert entries == [
        {"url": "https://example.com/a.bin"},
        {"url": "https://example.com/b.bin"},
    ]
    entries = _parse_download_list(
        '{"downloads": [{"url": "https://example.com/c.bin"}]}'
    )
    assert entries == [{"url": "https://example.com/c.bin"}]
    assert _parse_download_list("   ") == []


def test_queued_download_is_not_completed(qt_app, server, window, tmp_path):
    manager = window._manager
    manager.max_concurrent = 1
    active = manager.add_download(
        server.url("/slow/4194304"), "active.bin", str(tmp_path)
    )
    assert wait_until(
        qt_app, lambda: active.status == DownloadStatus.DOWNLOADING, 10
    )
    queued_item = manager.add_download(
        server.url("/slow/262144"), "queued.bin", str(tmp_path)
    )
    assert wait_until(
        qt_app, lambda: queued_item.status == DownloadStatus.QUEUED, 10
    )
    manager._flush_persistence()
    records = window._settings.database.load_downloads()
    record = next(entry for entry in records if entry["id"] == queued_item.id)
    assert record["status"] == DownloadStatus.QUEUED.value
    assert queued_item.status != DownloadStatus.COMPLETED
    assert queued_item.downloaded_bytes == 0

    manager.stop([active.id, queued_item.id])
    assert wait_until(qt_app, lambda: not manager._workers, 10)
    manager.remove([active.id, queued_item.id], delete_files=False)


def test_scheduler_dialog_add_and_delete(qt_app, window):
    scheduler = window._scheduler
    dialog = SchedulerDialog(scheduler, window._theme, window)
    dialog.show()
    assert dialog._table.rowCount() == len(scheduler.entries())
    dialog._when.setDateTime(QDateTime.currentDateTime().addSecs(900))
    index = dialog._action.findData("pause_all")
    dialog._action.setCurrentIndex(index)
    dialog._add_schedule()
    qt_app.processEvents()
    entries = scheduler.entries()
    assert len(entries) == 1
    assert entries[0].action == "pause_all"
    assert dialog._table.rowCount() == 1
    assert dialog._stack.currentWidget() is dialog._table

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    dialog.grab().save(str(ARTIFACTS / "scheduler.png"))

    dialog._table.selectRow(0)
    qt_app.processEvents()
    dialog._delete_selected()
    qt_app.processEvents()
    assert scheduler.entries() == []
    assert dialog._stack.currentWidget() is dialog._empty
    dialog.accept()
    dialog.deleteLater()
    assert SCHEDULE_ACTIONS["pause_all"].startswith("Pause")


def test_queue_dialog_reorders(qt_app, server, window, tmp_path):
    manager = window._manager
    manager.max_concurrent = 1
    active = manager.add_download(
        server.url("/slow/4194304"), "front-of-queue.bin", str(tmp_path)
    )
    assert wait_until(qt_app, lambda: active.status == DownloadStatus.DOWNLOADING, 10)
    first = manager.add_download(
        server.url("/slow/262144"), "queued-one.bin", str(tmp_path)
    )
    second = manager.add_download(
        server.url("/slow/262144"), "queued-two.bin", str(tmp_path)
    )
    assert wait_until(qt_app, lambda: second.status == DownloadStatus.QUEUED)
    assert manager.queue_items()[0].id == first.id

    dialog = QueueDialog(manager, window._theme, window)
    dialog.show()
    qt_app.processEvents()
    assert dialog._table.rowCount() == 2
    assert dialog._stack.currentWidget() is dialog._table
    dialog._table.selectRow(1)
    qt_app.processEvents()

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    dialog.grab().save(str(ARTIFACTS / "queue.png"))

    dialog._move(-1)
    qt_app.processEvents()
    assert manager.queue_items()[0].id == second.id
    dialog.accept()
    dialog.deleteLater()


def test_dashboard_screenshot_with_active_download(qt_app, server, window, tmp_path):
    completed = window._manager.add_download(
        server.url("/file/131072"), "brand-guidelines.pdf", str(tmp_path)
    )
    active = window._manager.add_download(
        server.url("/slow/2097152"), "launch-video.mp4", str(tmp_path)
    )
    queued = window._manager.add_download(
        server.url("/slow/524288"), "photo-pack.zip", str(tmp_path)
    )
    assert wait_until(
        qt_app,
        lambda: completed.status == DownloadStatus.COMPLETED
        and active.downloaded_bytes > 0,
        15,
    )
    qt_app.processEvents()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    window._theme.set_mode("dark")
    qt_app.processEvents()
    window.grab().save(str(ARTIFACTS / "dashboard-dark.png"))
    window._theme.set_mode("light")
    qt_app.processEvents()
    window.grab().save(str(ARTIFACTS / "dashboard-light.png"))
    window._manager.pause([active.id, queued.id])
    assert wait_until(
        qt_app,
        lambda: active.status in {DownloadStatus.PAUSED, DownloadStatus.COMPLETED},
        10,
    )


def test_dashboard_reports_total_downloads_and_total_data(qt_app, window, tmp_path):
    window._sidebar.select("dashboard", emit_signal=True)
    qt_app.processEvents()
    dashboard = window._dashboard_page
    assert dashboard._total_card._value.text() == "0"
    assert dashboard._total_card._detail.text() == "No transfers recorded"

    queued = window._manager.add_download(
        "https://example.com/one.zip",
        "one.zip",
        str(tmp_path),
        download_later=True,
    )
    window._manager.add_download(
        "https://example.com/two.zip",
        "two.zip",
        str(tmp_path),
        download_later=True,
    )
    dashboard.refresh()
    assert dashboard._total_card._value.text() == "2"
    assert dashboard._active_card._value.text() == "0"
    assert "2 queued" in dashboard._active_card._detail.text()
    assert dashboard._completed_card._value.text() == "0"
    assert dashboard._data_card._value.text() == "0 B"
    assert dashboard._hero_speed.accessibleName() == "Current speed"
    assert dashboard._hero_active.text() == "0"

    queued.status = DownloadStatus.COMPLETED
    queued.total_bytes = 2048
    queued.downloaded_bytes = 2048
    dashboard.refresh()
    assert dashboard._completed_card._value.text() == "1"
    assert dashboard._data_card._value.text() == format_size(2048)


def test_refresh_shows_loading_and_restores_the_table(qt_app, window, tmp_path):
    window._manager.add_download(
        "https://example.com/one.zip",
        "one.zip",
        str(tmp_path),
        start_immediately=False,
    )
    window._sidebar.select("all", emit_signal=True)
    qt_app.processEvents()
    seen: list[bool] = []
    original = window._model.reload

    def reload():
        seen.append(window._download_view.is_loading)
        original()

    window._model.reload = reload
    window._refresh_download_list()
    assert seen == [True]
    assert not window._download_view.is_loading
    assert window._download_view.table.isVisible()
    assert window._status_bar._message.text() == "Download list refreshed."


def test_toolbar_overflow_on_narrow_windows(qt_app, window):
    toolbar = window._toolbar
    window.resize(1040, 700)
    qt_app.processEvents()
    assert toolbar._overflow
    assert not toolbar.buttons["options"].isVisible()
    assert toolbar._overflow_button.isVisible()
    assert [
        action.text() for action in toolbar._overflow_menu.actions()
    ] == ["Queue", "Scheduler", "Options"]

    window.resize(1280, 700)
    qt_app.processEvents()
    assert not toolbar._overflow
    assert toolbar.buttons["options"].isVisible()
    assert not toolbar._overflow_button.isVisible()

    standalone = DownloadToolbar(window._theme)
    standalone.set_overflow(True)
    fired: list[str] = []
    standalone.options_requested.connect(lambda: fired.append("options"))
    standalone.queue_requested.connect(lambda: fired.append("queue"))
    standalone._overflow_actions["options"].trigger()
    standalone._overflow_actions["queue"].trigger()
    assert fired == ["options", "queue"]
    standalone.deleteLater()


def test_narrow_table_hides_low_priority_columns(qt_app, window, tmp_path):
    window._manager.add_download(
        "https://example.com/one.zip",
        "one.zip",
        str(tmp_path),
        start_immediately=False,
    )
    window._sidebar.select("all", emit_signal=True)
    window.resize(1366, 768)
    qt_app.processEvents()
    table = window._download_view.table
    assert table.isVisible()
    assert not table.isColumnHidden(COLUMN_DATE_ADDED)
    assert not table.isColumnHidden(COLUMN_ETA)

    window.resize(1040, 720)
    qt_app.processEvents()
    assert table.isColumnHidden(COLUMN_DATE_ADDED)
    assert table.isColumnHidden(COLUMN_ETA)
    assert table.isColumnHidden(COLUMN_DOWNLOADED)
    assert table.isColumnHidden(COLUMN_SPEED)
    assert table.columnWidth(COLUMN_NAME) >= 240

    window.resize(1280, 720)
    qt_app.processEvents()
    assert not table.isColumnHidden(COLUMN_DATE_ADDED)
