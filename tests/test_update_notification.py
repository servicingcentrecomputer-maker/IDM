"""Update notification window and main-window notification gating."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QPushButton

from idm.core.settings import AppSettings
from idm.ui.dialogs.update_notification import UpdateNotificationDialog
from idm.ui.main_window import MainWindow
from idm.ui.theme import ThemeManager
from idm.updater.update_checker import UpdateCheckResult
from idm.updater.version_manager import Version
from tests.update_helpers import installer_bytes, make_manifest


class FakeSettings:
    def __init__(self) -> None:
        self.reminders: list[tuple[str, int]] = []

    def remind_later(self, version: str, hours: int) -> None:
        self.reminders.append((str(version), int(hours)))


def _result() -> UpdateCheckResult:
    manifest = make_manifest(
        installer_bytes("1.1.0"),
        latest_version="1.1.0",
        release_notes=[
            "New: signed update manifests",
            "Performance: faster resume",
            "Security: pinned publisher",
            "Fix: queue ordering",
        ],
        package_size=7_340_032,
    )
    return UpdateCheckResult(
        manifest=manifest,
        current_version=Version.parse("1.0.0"),
        latest_version=Version.parse("1.1.0"),
        update_available=True,
        mandatory=False,
        below_minimum=False,
        installed_is_newer=False,
    )


def _button(dialog, text: str) -> QPushButton:
    for button in dialog.findChildren(QPushButton):
        if button.text() == text:
            return button
    raise AssertionError(f"No button labelled {text!r}")


def _notes(dialog) -> str:
    editors = dialog.findChildren(QPlainTextEdit)
    assert editors
    return editors[0].toPlainText()


@pytest.fixture
def theme(qt_app):
    manager = ThemeManager(qt_app)
    manager.set_mode("classic")
    yield manager
    manager.set_mode("classic")


def test_notification_shows_release_information(qt_app, theme):
    dialog = UpdateNotificationDialog(
        theme, _result(), FakeSettings(), lambda *args: None
    )
    dialog.show()
    qt_app.processEvents()
    try:
        labels = " ".join(label.text() for label in dialog.findChildren(QLabel))
        assert "1.1.0" in labels
        assert "RELEASED" in labels
        assert "7.0 MB" in labels
        notes = _notes(dialog)
        assert "NEW FEATURES" in notes
        assert "PERFORMANCE" in notes
        assert "SECURITY" in notes
        assert "BUG FIXES" in notes
    finally:
        dialog.deleteLater()
        qt_app.processEvents()


def test_install_now_opens_the_update_window(qt_app, theme):
    opened: list[tuple[UpdateCheckResult, str]] = []
    dialog = UpdateNotificationDialog(
        theme, _result(), FakeSettings(), lambda result, mode: opened.append((result, mode))
    )
    dialog.show()
    qt_app.processEvents()
    try:
        QTest.mouseClick(_button(dialog, "Install Now"), Qt.MouseButton.LeftButton)
        for _ in range(10):
            qt_app.processEvents()
        assert [mode for _result, mode in opened] == ["install"]
    finally:
        dialog.deleteLater()
        qt_app.processEvents()


def test_manual_mode_offers_download_only(qt_app, theme, monkeypatch):
    opened: list[str] = []

    class FakeDesktop:
        @staticmethod
        def openUrl(url):
            opened.append(url.toString())
            return True

    monkeypatch.setattr(
        "idm.ui.dialogs.update_notification.QDesktopServices", FakeDesktop
    )
    callbacks: list[tuple] = []
    dialog = UpdateNotificationDialog(
        theme,
        _result(),
        FakeSettings(),
        lambda *args: callbacks.append(args),
        manual_download=True,
    )
    dialog.show()
    qt_app.processEvents()
    try:
        texts = [button.text() for button in dialog.findChildren(QPushButton)]
        assert "Install Now" not in texts
        assert "Download Installer" in texts
        labels = " ".join(label.text() for label in dialog.findChildren(QLabel))
        assert "unsigned build" in labels
        QTest.mouseClick(
            _button(dialog, "Download Installer"), Qt.MouseButton.LeftButton
        )
        qt_app.processEvents()
        assert opened == [_result().manifest.download_url]
        assert callbacks == []
    finally:
        dialog.deleteLater()
        qt_app.processEvents()


def test_remind_me_later_stores_a_version_specific_reminder(qt_app, theme):
    settings = FakeSettings()
    dialog = UpdateNotificationDialog(theme, _result(), settings, lambda *args: None)
    dialog.show()
    qt_app.processEvents()
    try:
        QTest.mouseClick(_button(dialog, "Remind Me Later"), Qt.MouseButton.LeftButton)
        qt_app.processEvents()
        assert settings.reminders == [("1.1.0", 24)]
        assert not dialog.isVisible()
    finally:
        dialog.deleteLater()
        qt_app.processEvents()


def test_view_release_notes_opens_notes_mode(qt_app, theme):
    opened: list[str] = []
    dialog = UpdateNotificationDialog(
        theme, _result(), FakeSettings(), lambda _result, mode: opened.append(mode)
    )
    dialog.show()
    qt_app.processEvents()
    try:
        QTest.mouseClick(
            _button(dialog, "View Release Notes"), Qt.MouseButton.LeftButton
        )
        for _ in range(10):
            qt_app.processEvents()
        assert opened == ["notes"]
    finally:
        dialog.deleteLater()
        qt_app.processEvents()


# ---------------------------------------------------------------- main window
@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    settings = AppSettings()
    settings.download_dir = str(tmp_path / "downloads")
    yield settings
    settings.close()


@pytest.fixture
def window(qt_app, isolated_settings):
    theme = ThemeManager(qt_app)
    theme.set_mode("classic")
    instance = MainWindow(isolated_settings, theme)
    instance.show()
    qt_app.processEvents()
    yield instance
    instance._shutdown()
    instance.hide()
    instance.deleteLater()
    qt_app.processEvents()


def test_main_window_notifies_for_available_update(window, monkeypatch):
    shown: list[UpdateCheckResult] = []
    monkeypatch.setattr(window, "_show_update_notification", shown.append)
    window._on_update_available(_result())
    assert len(shown) == 1


def test_main_window_honours_the_reminder(window, monkeypatch):
    shown: list[UpdateCheckResult] = []
    monkeypatch.setattr(window, "_show_update_notification", shown.append)
    window._settings.remind_later("1.1.0", 24)
    window._on_update_available(_result())
    assert shown == []


def test_main_window_auto_download_option_opens_download_mode(window, monkeypatch):
    opened: list[tuple[object, str, bool]] = []
    monkeypatch.setattr(
        window,
        "_open_update_window",
        lambda result, mode="notes", modal=True: opened.append((result, mode, modal)),
    )
    window._settings.update_publisher = "IDM"
    window._settings.update_auto_download = True
    window._on_update_available(_result())
    assert len(opened) == 1
    assert opened[0][1] == "download"
    assert opened[0][2] is False


def test_main_window_manual_mode_skips_auto_download(window, monkeypatch):
    opened: list[object] = []
    shown: list[UpdateCheckResult] = []
    monkeypatch.setattr(
        window, "_open_update_window", lambda *args, **kwargs: opened.append(args)
    )
    monkeypatch.setattr(window, "_show_update_notification", shown.append)
    monkeypatch.setattr("config.MANIFEST_PUBLIC_KEY", "")
    window._settings.update_publisher = ""
    window._settings.update_auto_download = True
    window._on_update_available(_result())
    assert opened == []
    assert len(shown) == 1


def test_main_window_can_disable_notifications(window, monkeypatch):
    shown: list[UpdateCheckResult] = []
    monkeypatch.setattr(window, "_show_update_notification", shown.append)
    window._settings.update_notify = False
    window._on_update_available(_result())
    assert shown == []
