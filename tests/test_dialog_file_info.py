"""Download File Info dialog behaviour tests."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QScrollArea

from idm.core.settings import AppSettings
from idm.core.url_utils import format_progress_size
from idm.engine.manager import DownloadManager
from idm.models.download_item import DownloadItem, DownloadStatus
from idm.models.table_model import (
    COLUMN_DOWNLOADED,
    COLUMN_SIZE,
    DownloadTableModel,
)
from idm.ui.dialogs.download_file_info import AddDownloadDialog
from idm.ui.theme import ThemeManager


def wait_until(app, predicate, timeout: float = 12.0) -> bool:
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
    Path(instance.download_dir).mkdir(parents=True)
    yield instance
    instance.close()


@pytest.fixture
def theme(qt_app):
    return ThemeManager(qt_app)


@pytest.fixture
def manager(qt_app, settings):
    instance = DownloadManager(settings)
    yield instance
    instance.shutdown()


def test_remembered_folder_is_applied_and_stays_stored(
    qt_app, settings, theme, server, tmp_path
) -> None:
    docs = tmp_path / "Docs"
    docs.mkdir()
    settings.remember_category_folder("Documents", str(docs))

    dialog = AddDownloadDialog(
        settings, theme, initial_category="Documents"
    )
    try:
        assert dialog.folder_edit.text() == str(docs)
        assert dialog.remember_check.isChecked()
        assert "Documents" in dialog.remember_check.text()

        dialog.url_edit.setText(server.url("/disposition/1024?name=report.pdf"))
        assert wait_until(
            qt_app, lambda: dialog.probe_label.property("state") == "ok"
        ), dialog.probe_label.text()
        dialog.description_edit.setPlainText("Quarterly report")
        dialog._validate_and_accept(True)

        assert dialog.result() == QDialog.DialogCode.Accepted
        values = dialog.values()
        assert values["url"] == server.url("/disposition/1024?name=report.pdf")
        assert values["filename"] == "report.pdf"
        assert values["folder"] == str(docs)
        assert values["category"] == "Documents"
        assert values["description"] == "Quarterly report"
        assert values["start_immediately"] is True
        assert values["download_later"] is False
    finally:
        dialog.deleteLater()
    assert settings.remembered_folder("Documents") == str(docs)


def test_switching_category_applies_that_remembered_folder(
    qt_app, settings, theme, tmp_path
) -> None:
    docs = tmp_path / "Docs"
    music = tmp_path / "Music"
    docs.mkdir()
    music.mkdir()
    settings.remember_category_folder("Documents", str(docs))
    settings.remember_category_folder("Music", str(music))

    dialog = AddDownloadDialog(settings, theme, initial_category="Documents")
    try:
        index = dialog.category_combo.findData("Music")
        assert index >= 0
        dialog.category_combo.setCurrentIndex(index)
        dialog._on_category_activated(index)
        assert dialog.folder_edit.text() == str(music)
        assert dialog.remember_check.isChecked()

        index = dialog.category_combo.findData("Programs")
        dialog.category_combo.setCurrentIndex(index)
        dialog._on_category_activated(index)
        assert dialog.remember_check.isChecked() is False
        assert dialog.folder_edit.text() == str(music)
    finally:
        dialog.deleteLater()


def test_custom_category_is_listed_and_detected(
    qt_app, settings, theme, server
) -> None:
    settings.update(
        {"custom_categories": [{"name": "Books", "extensions": ["cbz"]}]}
    )
    dialog = AddDownloadDialog(settings, theme)
    try:
        assert dialog.category_combo.findData("Books") >= 0
        dialog.url_edit.setText(server.url("/disposition/2048?name=novel.cbz"))
        assert wait_until(
            qt_app, lambda: dialog.probe_label.property("state") == "ok"
        ), dialog.probe_label.text()
        assert dialog.filename_edit.text() == "novel.cbz"
        assert dialog.category_combo.currentData() == "Books"
        assert "Books" in dialog.file_type_label.text()
    finally:
        dialog.deleteLater()


def test_unsafe_filename_is_sanitised_inside_the_folder(
    qt_app, settings, theme, tmp_path
) -> None:
    folder = tmp_path / "Downloads"
    dialog = AddDownloadDialog(settings, theme)
    try:
        dialog.url_edit.setText("https://example.com/download")
        dialog.filename_edit.setText(r"..\..\evil.exe")
        dialog.folder_edit.setText(str(folder))
        dialog._validate_and_accept(True)
        assert dialog.result() == QDialog.DialogCode.Accepted
        values = dialog.values()
        assert Path(values["filename"]).name == values["filename"]
        assert "\\" not in values["filename"]
        assert "/" not in values["filename"]
        assert (Path(values["folder"]) / values["filename"]).resolve().parent == folder.resolve()
    finally:
        dialog.deleteLater()


def test_invalid_inputs_keep_the_dialog_open(qt_app, settings, theme) -> None:
    dialog = AddDownloadDialog(settings, theme)
    dialog.show()
    try:
        dialog.url_edit.setText("file:///C:/Windows/win.ini")
        dialog.filename_edit.setText("win.ini")
        dialog._validate_and_accept(True)
        assert dialog.result() != QDialog.DialogCode.Accepted
        assert "HTTP, HTTPS, FTP and FTPS" in dialog.error_label.text()

        dialog.url_edit.setText("https://example.com/file.zip")
        dialog.filename_edit.setText("")
        dialog._validate_and_accept(True)
        assert dialog.result() != QDialog.DialogCode.Accepted
        assert "file name" in dialog.error_label.text().lower()

        dialog.folder_edit.setText("")
        dialog.filename_edit.setText("file.zip")
        dialog._validate_and_accept(True)
        assert dialog.result() != QDialog.DialogCode.Accepted
        assert "folder" in dialog.error_label.text().lower()
    finally:
        dialog.reject()
        dialog.deleteLater()


def test_active_duplicate_url_is_rejected_before_creation(
    qt_app, settings, theme, manager, tmp_path
) -> None:
    folder = tmp_path / "Downloads"
    existing = manager.add_download(
        "http://127.0.0.1:1/duplicate.zip",
        "duplicate.zip",
        str(folder),
        start_immediately=False,
    )
    dialog = AddDownloadDialog(
        settings, theme, manager=manager, initial_url=existing.url
    )
    dialog.filename_edit.setText("second-copy.zip")
    dialog.folder_edit.setText(str(folder))
    try:
        dialog._validate_and_accept(True)
        assert dialog.result() != QDialog.DialogCode.Accepted
        assert "already being downloaded" in dialog.error_label.text()
        assert len(manager.items()) == 1
    finally:
        dialog.deleteLater()


def test_description_limit_and_download_later_flags(
    qt_app, settings, theme, tmp_path
) -> None:
    folder = tmp_path / "Downloads"
    dialog = AddDownloadDialog(settings, theme)
    try:
        dialog.url_edit.setText("https://example.com/archive.zip")
        dialog.filename_edit.setText("archive.zip")
        dialog.folder_edit.setText(str(folder))
        dialog.description_edit.setPlainText("x" * 2001)
        dialog._validate_and_accept(False)
        assert dialog.result() != QDialog.DialogCode.Accepted
        assert "2000" in dialog.error_label.text()

        dialog.description_edit.setPlainText("x" * 2000)
        dialog._validate_and_accept(False)
        assert dialog.result() == QDialog.DialogCode.Accepted
        values = dialog.values()
        assert values["start_immediately"] is False
        assert values["download_later"] is True
        assert len(values["description"]) == 2000
    finally:
        dialog.deleteLater()


def test_submit_callback_errors_keep_the_dialog_open(
    qt_app, settings, theme, tmp_path
) -> None:
    calls: list[dict] = []

    def failing_submit(values: dict):
        calls.append(values)
        raise ValueError("Could not create the download: disk full")

    dialog = AddDownloadDialog(settings, theme, submit_callback=failing_submit)
    dialog.show()
    try:
        dialog.url_edit.setText("https://example.com/file.zip")
        dialog.filename_edit.setText("file.zip")
        dialog.folder_edit.setText(str(tmp_path / "Downloads"))
        dialog._validate_and_accept(True)
        assert dialog.result() != QDialog.DialogCode.Accepted
        assert dialog.created_item is None
        assert "disk full" in dialog.error_label.text()
        assert calls and calls[0]["filename"] == "file.zip"
    finally:
        dialog.reject()
        dialog.deleteLater()


def test_submit_callback_creates_task_before_accepting(
    qt_app, settings, theme, manager, tmp_path
) -> None:
    folder = tmp_path / "Downloads"
    created: list = []

    def submit(values: dict):
        item = manager.add_download(**values)
        created.append(item)
        return item

    dialog = AddDownloadDialog(settings, theme, manager=manager, submit_callback=submit)
    try:
        dialog.url_edit.setText("https://example.com/new.bin")
        dialog.filename_edit.setText("new.bin")
        dialog.folder_edit.setText(str(folder))
        dialog.description_edit.setPlainText("Created atomically")
        dialog._validate_and_accept(False)
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.created_item is created[0]
        assert manager.get(created[0].id) is created[0]
        assert created[0].description == "Created atomically"
        assert created[0].queued_later is True
        assert created[0].status.value == "Queued"
    finally:
        dialog.deleteLater()


def test_probe_failure_leaves_editable_unknown_details(
    qt_app, settings, theme, tmp_path
) -> None:
    dialog = AddDownloadDialog(settings, theme)
    try:
        dialog.url_edit.setText("http://127.0.0.1:1/unreachable")
        dialog.filename_edit.setText("manual.bin")
        dialog.folder_edit.setText(str(tmp_path / "Downloads"))
        dialog._last_probed_url = dialog.url_edit.text().strip()
        dialog._on_probe_failed("The server refused the connection.")

        assert "still add the link" in dialog.probe_label.text()
        assert dialog._info_labels["size"].text() == "Unknown"
        assert dialog._info_labels["mime"].text() == "Unknown"
        assert dialog._info_labels["status"].text() == "Not available"

        dialog._validate_and_accept(True)
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.values()["filename"] == "manual.bin"
    finally:
        dialog.deleteLater()


def test_copy_button_copies_the_complete_long_url(qt_app, settings, theme) -> None:
    long_url = "https://example.com/download?token=" + "a" * 400 + "&name=file.bin"
    dialog = AddDownloadDialog(settings, theme)
    try:
        dialog.url_edit.setText(long_url)
        dialog._copy_url()
        assert QApplication.clipboard().text() == long_url
        assert "copied" in dialog.probe_label.text()
    finally:
        dialog.deleteLater()


def test_dialog_remains_usable_on_a_small_display(
    qt_app, settings, theme
) -> None:
    dialog = AddDownloadDialog(settings, theme)
    dialog.show()
    try:
        assert dialog.minimumWidth() <= 640
        assert dialog.minimumHeight() <= 560
        dialog.resize(640, 560)
        qt_app.processEvents()
        assert dialog.width() >= 640
        assert dialog.height() >= 560
        assert dialog.findChild(QScrollArea) is not None
        assert dialog.start_button.isVisible()
        assert dialog.later_button.isVisible()
        assert dialog.cancel_button.isVisible()
        assert dialog.layout().sizeHint().height() > 0
    finally:
        dialog.reject()
        dialog.deleteLater()


def test_restricted_platform_disables_actions(qt_app, settings, theme) -> None:
    dialog = AddDownloadDialog(settings, theme)
    dialog.show()
    try:
        dialog.url_edit.setText("https://www.youtube.com/watch?v=abcdefghijk")
        qt_app.processEvents()
        assert dialog.start_button.isEnabled() is False
        assert dialog.later_button.isEnabled() is False
        assert dialog.open_page_button.isVisible()
        assert dialog.probe_label.property("state") == "warn"
    finally:
        dialog.deleteLater()


def test_progress_size_formats_live_bytes() -> None:
    assert format_progress_size(8_738_133, 67_108_864) == "8.3 MB of 64.0 MB"
    assert (
        format_progress_size(8_738_133, 67_108_864, compact=True) == "8.3/64 MB"
    )
    assert format_progress_size(67_108_864, 67_108_864, compact=True) == "64 MB"
    assert format_progress_size(0, 67_108_864, compact=True) == "0/64 MB"
    assert format_progress_size(0, None) == ""
    assert format_progress_size(1536, None) == "1.5 KB"


def test_size_and_downloaded_columns(qt_app, settings, manager) -> None:
    item = DownloadItem(
        url="https://example.com/archive.rar",
        filename="archive.rar",
        folder=str(settings.download_dir),
        category="Compressed",
        status=DownloadStatus.DOWNLOADING,
        total_bytes=64 * 1024 * 1024,
        downloaded_bytes=8 * 1024 * 1024,
    )
    model = DownloadTableModel(manager)
    model._items = [item]
    size_index = model.index(0, COLUMN_SIZE)
    downloaded_index = model.index(0, COLUMN_DOWNLOADED)
    assert model.data(size_index, Qt.ItemDataRole.DisplayRole) == "64.0 MB"
    assert model.data(downloaded_index, Qt.ItemDataRole.DisplayRole) == "8.0 MB"
    item.downloaded_bytes = item.total_bytes
    item.status = DownloadStatus.COMPLETED
    assert model.data(downloaded_index, Qt.ItemDataRole.DisplayRole) == "64.0 MB"


def test_dialog_switches_to_live_progress_after_start(
    qt_app, settings, theme, manager, server
) -> None:
    item = manager.add_download(
        server.url("/slow/16777216"),
        "archive.rar",
        str(settings.download_dir),
        category="Compressed",
    )
    dialog = AddDownloadDialog(
        settings,
        theme,
        initial_url=item.url,
        initial_filename=item.filename,
        manager=manager,
    )
    dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    dialog.show()
    try:
        dialog.start_progress(item)
        assert dialog.progress_mode is True
        assert dialog._body_scroll.isHidden()
        assert dialog._progress_view.isVisible()
        assert dialog.start_button.isHidden()
        assert dialog.later_button.isHidden()

        assert wait_until(qt_app, lambda: item.downloaded_bytes > 0)
        dialog._apply_progress(item)
        assert "%" in dialog._progress_percent.text()
        assert "of" in dialog._progress_size.text()
        assert dialog.cancel_button.text() == "Cancel download"

        manager.stop([item.id])
        assert wait_until(qt_app, lambda: item.status == DownloadStatus.STOPPED)
        dialog._apply_progress(item)
        assert dialog._progress_state.text() == "Stopped"
        assert dialog.cancel_button.text() == "Close"
    finally:
        dialog.close()


def test_dialog_live_progress_completes_and_schedules_close(
    qt_app, settings, theme, manager, server
) -> None:
    item = manager.add_download(
        server.url("/file/4096"), "small.bin", str(settings.download_dir)
    )
    dialog = AddDownloadDialog(
        settings,
        theme,
        initial_url=item.url,
        initial_filename=item.filename,
        manager=manager,
    )
    dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    dialog.show()
    try:
        dialog.start_progress(item)
        assert wait_until(
            qt_app, lambda: item.status == DownloadStatus.COMPLETED
        )
        dialog._apply_progress(item)
        assert dialog._progress_percent.text() == "100%"
        assert dialog._progress_state.text() == "Completed"
        assert dialog.cancel_button.text() == "Close"
        assert dialog._progress_close_timer.isActive()
    finally:
        dialog.close()
