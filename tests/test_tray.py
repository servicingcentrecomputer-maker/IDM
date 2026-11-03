"""Notification-area and start-up wiring for the main window.

The tray itself is a Windows shell feature that does not exist on the
offscreen Qt platform used here, so these tests install a recording double in
place of :class:`TrayController` and check how the window drives it.
"""

from __future__ import annotations

from typing import ClassVar

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QDialog

from idm.core.settings import AppSettings
from idm.models.download_item import DownloadStatus
from idm.ui import main_window as main_window_module
from idm.ui.main_window import MainWindow
from idm.ui.theme import ThemeManager


class FakeTray(QObject):
    """Records everything the window asks the notification area to do."""

    open_requested = Signal()
    pause_all_requested = Signal()
    resume_all_requested = Signal()
    quit_requested = Signal()

    available = True

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.summaries: list[str] = []
        self.notifications: list[tuple[str, str, bool]] = []
        self.actions_enabled: list[tuple[bool, bool]] = []
        self.enabled_calls: list[bool] = []
        self.hidden_called = False
        self.destroy_called = False

    def set_summary(self, text: str) -> None:
        self.summaries.append(text)

    def set_transfer_actions_enabled(self, pausable: bool, resumable: bool) -> None:
        self.actions_enabled.append((pausable, resumable))

    def notify(self, title: str, message: str, error: bool = False) -> bool:
        self.notifications.append((title, message, error))
        return True

    def set_enabled(self, enabled: bool) -> None:
        self.enabled_calls.append(enabled)

    def hide(self) -> None:
        self.hidden_called = True

    def destroy(self) -> None:
        self.destroy_called = True


@pytest.fixture
def fake_tray(monkeypatch):
    created: list[FakeTray] = []

    def factory(parent=None):
        tray = FakeTray(parent)
        created.append(tray)
        return tray

    monkeypatch.setattr(main_window_module, "TrayController", factory)
    yield created
    QApplication.instance().setQuitOnLastWindowClosed(True)


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    settings = AppSettings()
    settings.download_dir = str(tmp_path / "downloads")
    settings.show_completion_dialog = False
    yield settings
    settings.close()


@pytest.fixture
def make_window(qt_app, isolated_settings, fake_tray):
    windows = []

    def build(**changes) -> MainWindow:
        for key, value in changes.items():
            setattr(isolated_settings, key, value)
        theme = ThemeManager(qt_app)
        instance = MainWindow(isolated_settings, theme)
        instance.show()
        qt_app.processEvents()
        windows.append(instance)
        return instance

    yield build
    for instance in windows:
        instance._shutdown()
        instance.hide()
        instance.deleteLater()
    qt_app.processEvents()


def _queue_download(window, name="queued-file.bin"):
    return window._manager.add_download(
        "https://example.com/" + name,
        name,
        window._settings.download_dir,
        download_later=True,
    )


def test_tray_is_created_when_the_option_is_on(qt_app, make_window):
    window = make_window(tray_enabled=True)

    assert isinstance(window._tray, FakeTray)
    # Hiding the window must not end the session while the tray is the way back.
    assert qt_app.quitOnLastWindowClosed() is False
    assert window._tray.summaries[-1] == "No downloads in progress"


def test_no_tray_when_the_option_is_off(qt_app, make_window):
    window = make_window(tray_enabled=False)

    assert window._tray is None
    assert qt_app.quitOnLastWindowClosed() is True


def test_tray_commands_drive_the_window_and_manager(qt_app, make_window):
    window = make_window(tray_enabled=True)
    calls: list[str] = []
    window._pause_all = lambda: calls.append("pause")
    window._resume_all = lambda: calls.append("resume")

    window._tray.open_requested.emit()
    qt_app.processEvents()
    assert window.isVisible()

    window._tray.pause_all_requested.emit()
    window._tray.resume_all_requested.emit()
    assert calls == ["pause", "resume"]

    window._tray.quit_requested.emit()
    assert window._quitting is True


def test_tray_summary_follows_the_transfers(qt_app, make_window):
    window = make_window(tray_enabled=True)
    tray = window._tray

    item = _queue_download(window)
    window._refresh_tray_state()
    assert "waiting in queue" in tray.summaries[-1]

    item.status = DownloadStatus.DOWNLOADING
    window._refresh_tray_state()
    assert "in progress" in tray.summaries[-1]
    assert tray.actions_enabled[-1] == (True, False)

    item.status = DownloadStatus.PAUSED
    window._refresh_tray_state()
    assert "paused" in tray.summaries[-1]
    assert tray.actions_enabled[-1] == (False, True)

    window._manager.remove([item.id])
    window._refresh_tray_state()
    assert tray.summaries[-1] == "No downloads in progress"


def test_closing_hides_to_the_tray_and_quitting_ends_the_session(qt_app, make_window):
    window = make_window(tray_enabled=True, tray_on_close=True)
    tray = window._tray

    window.close()
    qt_app.processEvents()

    assert not window.isVisible()
    assert window._shutdown_done is False
    assert tray.notifications[0][0] == "IDM is still running"

    # The hint is only shown once, then the window returns from the tray.
    window.show()
    window.close()
    assert len(tray.notifications) == 1

    window._quit_application()
    assert window._shutdown_done is True


def test_close_without_tray_hide_still_shuts_down(qt_app, make_window):
    window = make_window(tray_enabled=True, tray_on_close=False)

    window.close()

    assert window._shutdown_done is True
    assert window._tray.hidden_called is True


def test_finished_transfers_are_reported_through_the_tray(qt_app, make_window):
    window = make_window(tray_enabled=True, native_notifications=True)
    item = _queue_download(window)

    window._on_download_completed(item)
    window._on_download_failed(item)

    titles = [entry[0] for entry in window._tray.notifications]
    assert titles == ["Download complete", "Download failed"]
    assert window._tray.notifications[1][2] is True


def test_notifications_stop_when_the_option_is_off(qt_app, make_window):
    window = make_window(tray_enabled=True, native_notifications=False)
    item = _queue_download(window)

    window._on_download_completed(item)

    assert window._tray.notifications == []


_OPTION_KEYS = (
    "start_with_windows",
    "tray_enabled",
    "tray_on_close",
    "native_notifications",
    "theme",
    "ui_animations",
)


def _choices(settings, **overrides) -> dict:
    values = {key: getattr(settings, key) for key in _OPTION_KEYS}
    values.update(overrides)
    return values


class _FakeOptionsDialog:
    DialogCode = QDialog.DialogCode
    choices: ClassVar[dict] = {}

    def __init__(
        self,
        settings,
        theme,
        parent=None,
        initial_tab=0,
        capacity_reader=None,
        measure_request=None,
    ) -> None:
        self.opened_tab = initial_tab

    def exec(self) -> int:
        return int(QDialog.DialogCode.Accepted)

    def values(self) -> dict:
        return dict(self.choices)

    def wants_update_check(self) -> bool:
        return False

    def deleteLater(self) -> None:
        return None


def test_options_apply_the_startup_and_tray_choices(qt_app, make_window, monkeypatch):
    window = make_window(tray_enabled=True)
    window._update_scheduler.tick = lambda: None
    live_startup = [False]
    applied: list[bool] = []
    monkeypatch.setattr(main_window_module, "OptionsDialog", _FakeOptionsDialog)
    monkeypatch.setattr(
        main_window_module.startup, "is_enabled", lambda: live_startup[0]
    )
    monkeypatch.setattr(
        main_window_module.startup,
        "set_enabled",
        lambda enabled, executable=None, on_error=None: applied.append(enabled) or enabled,
    )

    old_tray = window._tray
    _FakeOptionsDialog.choices = _choices(
        window._settings, start_with_windows=True, tray_enabled=False
    )
    window._open_options()
    qt_app.processEvents()

    assert applied == [True]
    assert old_tray.destroy_called is True
    assert window._tray is None
    assert qt_app.quitOnLastWindowClosed() is True

    # Turning the icon back on builds a fresh controller, and the start-up
    # choice is undone from the registry.
    live_startup[0] = True
    _FakeOptionsDialog.choices = _choices(
        window._settings, start_with_windows=False, tray_enabled=True
    )
    window._open_options()

    assert isinstance(window._tray, FakeTray)
    assert window._tray is not old_tray
    assert applied == [True, False]
    assert window._settings.start_with_windows is False


def test_startup_choice_keeps_the_value_windows_actually_applied(make_window, monkeypatch):
    window = make_window(tray_enabled=False)
    monkeypatch.setattr(
        main_window_module.startup,
        "set_enabled",
        lambda enabled, executable=None, on_error=None: False,
    )

    window._apply_startup_choice(True)

    assert window._settings.start_with_windows is False
