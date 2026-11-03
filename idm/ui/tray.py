"""Notification-area (system tray) presence for IDM.

The tray is optional: a session without one (a headless test run, a kiosk with
no shell notifier) must not lose the main window or break quit, so every entry
point here degrades to "not available" and the window behaves normally.
"""

from __future__ import annotations

import ctypes
import logging
import sys

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from . import icons

logger = logging.getLogger("idm.ui.tray")

# Windows attributes a toast to the process identity set here.  Without it a
# source checkout reports its notifications as "python.exe" and groups them
# under the interpreter rather than under IDM.  This is the same identity
# main.py gives the process, so taskbar grouping and toasts stay consistent.
APP_USER_MODEL_ID = "IDM.DownloadManager.1"

_TOOLTIP = "IDM Internet Download Manager"


def _set_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            APP_USER_MODEL_ID
        )
    except Exception:
        # A shell that refuses the identity still shows the notice; only the
        # friendly source label is lost.
        logger.debug("Could not set the Windows app user model ID", exc_info=True)


class TrayController(QObject):
    """A tray icon with the few commands that matter while IDM is hidden."""

    open_requested = Signal()
    pause_all_requested = Signal()
    resume_all_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._icon = QSystemTrayIcon(icons.app_icon(), parent)
        self._icon.setToolTip(_TOOLTIP)
        self._menu = QMenu(parent)
        self._available = QSystemTrayIcon.isSystemTrayAvailable()

        self.open_action = QAction("Open IDM", self._menu)
        self.open_action.triggered.connect(self.open_requested)
        self.pause_action = QAction("Pause all downloads", self._menu)
        self.pause_action.triggered.connect(self.pause_all_requested)
        self.resume_action = QAction("Resume all downloads", self._menu)
        self.resume_action.triggered.connect(self.resume_all_requested)
        self.quit_action = QAction("Quit IDM", self._menu)
        self.quit_action.triggered.connect(self.quit_requested)

        self._menu.addAction(self.open_action)
        self._menu.addSeparator()
        self._menu.addAction(self.pause_action)
        self._menu.addAction(self.resume_action)
        self._menu.addSeparator()
        self._menu.addAction(self.quit_action)
        self._icon.setContextMenu(self._menu)
        self._icon.activated.connect(self._on_activated)

        if self._available:
            _set_app_user_model_id()
            self._icon.show()
        else:
            logger.info("No system tray is available; IDM stays window-only")

    @property
    def available(self) -> bool:
        return self._available

    def _on_activated(self, reason) -> None:
        # Clicking the icon is how people return to a hidden IDM.
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.open_requested.emit()

    def set_summary(self, text: str) -> None:
        """Show what IDM is doing without opening the window."""
        self._icon.setToolTip(f"{_TOOLTIP}\n{text}" if text else _TOOLTIP)

    def set_transfer_actions_enabled(self, pausable: bool, resumable: bool) -> None:
        self.pause_action.setEnabled(pausable)
        self.resume_action.setEnabled(resumable)

    def notify(self, title: str, message: str, error: bool = False) -> bool:
        """Publish a native notification; report whether the shell accepted it."""
        if not self._available or not QSystemTrayIcon.supportsMessages():
            return False
        kind = (
            QSystemTrayIcon.MessageIcon.Critical
            if error
            else QSystemTrayIcon.MessageIcon.Information
        )
        self._icon.showMessage(title, message, kind, 6000)
        return True

    def set_enabled(self, enabled: bool) -> None:
        """Show or hide the icon without destroying the controller."""
        if not self._available:
            return
        if enabled:
            _set_app_user_model_id()
            self._icon.show()
        else:
            self._icon.hide()

    def hide(self) -> None:
        if self._available:
            self._icon.hide()

    def destroy(self) -> None:
        self.hide()
        self._menu.deleteLater()
        self._icon.deleteLater()


__all__ = ["APP_USER_MODEL_ID", "TrayController"]
