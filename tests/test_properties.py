"""Download properties and the user-initiated "open file" path."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton

from idm.core.settings import AppSettings
from idm.models.download_item import DownloadItem, DownloadStatus
from idm.ui import main_window as main_window_module
from idm.ui.dialogs.properties import DownloadPropertiesDialog
from idm.ui.main_window import MainWindow
from idm.ui.theme import ThemeManager


def wait_until(app, predicate, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    settings = AppSettings()
    settings.download_dir = str(tmp_path / "downloads")
    settings.show_completion_dialog = False
    Path(settings.download_dir).mkdir(parents=True, exist_ok=True)
    yield settings
    settings.close()


@pytest.fixture
def window(qt_app, isolated_settings):
    theme = ThemeManager(qt_app)
    instance = MainWindow(isolated_settings, theme)
    instance.show()
    qt_app.processEvents()
    yield instance
    instance._shutdown()
    instance.hide()
    instance.deleteLater()
    qt_app.processEvents()


def _record(folder: Path, filename: str, payload: bytes | None) -> DownloadItem:
    folder.mkdir(parents=True, exist_ok=True)
    if payload is not None:
        (folder / filename).write_bytes(payload)
    return DownloadItem(
        url=f"https://files.example.com/{filename}",
        filename=filename,
        folder=str(folder),
        category="General",
        status=DownloadStatus.COMPLETED,
    )


def test_properties_report_what_is_really_on_disk(qt_app, tmp_path):
    item = _record(tmp_path / "downloads", "report.pdf", b"%PDF" + b"x" * 2044)
    item.total_bytes = 999999
    item.downloaded_bytes = 999999
    item.connections = 8
    item.content_type = "application/pdf"

    dialog = DownloadPropertiesDialog(item, ThemeManager(qt_app))
    dialog.show()
    qt_app.processEvents()
    text = "\n".join(label.text() for label in dialog.findChildren(QLabel))

    assert "report.pdf" in text
    assert "2.0 KB" in text  # the file on disk, not the size the record claims
    assert "https://files.example.com/report.pdf" in text
    assert "General" in text
    dialog.deleteLater()


def test_properties_open_button_is_disabled_without_the_file(qt_app, tmp_path):
    item = _record(tmp_path, "lost.zip", None)
    dialog = DownloadPropertiesDialog(item, ThemeManager(qt_app))
    buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}

    assert buttons["Open"].isEnabled() is False
    assert buttons["Open Folder"].isEnabled() is True

    emitted: list[str] = []
    dialog.open_file_requested.connect(emitted.append)
    buttons["Open"].click()
    assert emitted == []
    dialog.deleteLater()


def test_properties_buttons_hand_back_the_download_id(qt_app, tmp_path):
    item = _record(tmp_path, "song.mp3", b"audio bytes")
    dialog = DownloadPropertiesDialog(item, ThemeManager(qt_app))
    seen: dict[str, str] = {}
    dialog.open_file_requested.connect(lambda value: seen.__setitem__("file", value))
    dialog.open_folder_requested.connect(
        lambda value: seen.__setitem__("folder", value)
    )
    dialog.copy_link_requested.connect(lambda value: seen.__setitem__("copy", value))

    wanted = {"Open", "Open Folder", "Copy Link"}
    for button in dialog.findChildren(QPushButton):
        if button.text() in wanted:
            button.click()

    assert seen == {
        "file": item.id,
        "folder": item.id,
        "copy": item.id,
    }
    dialog.deleteLater()


def test_properties_stays_usable_on_a_small_screen(qt_app, tmp_path):
    """A 64-char hash and a long link must not push the dialog off a laptop."""
    item = _record(tmp_path / "deep" / "nested" / "folder" / "path", "report.pdf", b"x")
    item.url = "https://files.example.com/" + "segment/" * 30 + "report.pdf"
    item.expected_sha256 = "7f3a" + "0" * 60

    dialog = DownloadPropertiesDialog(item, ThemeManager(qt_app))

    assert dialog.minimumSizeHint().width() <= 620
    dialog.deleteLater()


def test_open_file_hands_a_finished_document_to_the_shell(
    qt_app, window, tmp_path, monkeypatch
):
    opened: list[str] = []
    monkeypatch.setattr(
        main_window_module.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toString()) or True,
    )
    item = _record(tmp_path / "docs", "notes.txt", b"hello")

    window._open_file(item)

    assert len(opened) == 1
    assert opened[0].endswith("notes.txt")


def test_open_file_asks_before_running_a_program(
    qt_app, window, tmp_path, monkeypatch
):
    opened: list[str] = []
    monkeypatch.setattr(
        main_window_module.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toString()) or True,
    )
    questions: list[str] = []
    reply = {"answer": QMessageBox.StandardButton.No}

    def answer(_parent, title, _text, *_args):
        questions.append(title)
        return reply["answer"]

    monkeypatch.setattr(main_window_module.QMessageBox, "question", answer)
    item = _record(tmp_path / "programs", "setup.exe", b"MZ\x90\x00")

    window._open_file(item)

    assert opened == []
    assert questions == ["Open executable file"]
    assert "cancelled" in window._status_bar._message.text().lower()

    reply["answer"] = QMessageBox.StandardButton.Yes
    window._open_file(item)

    assert len(opened) == 1
    assert opened[0].endswith("setup.exe")


def test_open_file_says_so_when_the_file_disappeared(
    qt_app, window, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        main_window_module.QDesktopServices, "openUrl", lambda url: True
    )
    item = _record(tmp_path / "gone", "gone.bin", b"data")
    Path(item.path).unlink()

    window._open_file(item)

    assert "no longer" in window._status_bar._message.text()


def test_open_and_properties_actions_track_the_selection(
    qt_app, window, tmp_path
):
    assert window._actions["open_file"].isEnabled() is False
    assert window._actions["properties"].isEnabled() is False

    manager = window._manager
    item = manager.add_download(
        "https://files.example.com/archive.zip",
        "archive.zip",
        str(tmp_path),
        download_later=True,
    )
    assert wait_until(qt_app, lambda: bool(window._proxy.rowCount()))
    window._select_item(item.id)
    qt_app.processEvents()

    assert window._actions["properties"].isEnabled() is True
    assert window._actions["open_folder"].isEnabled() is True
    assert (
        window._actions["open_file"].isEnabled() is False
    )  # nothing has been written yet

    Path(item.path).write_bytes(b"not really a zip")
    window._update_actions()

    assert window._actions["open_file"].isEnabled() is True
