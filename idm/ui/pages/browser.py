"""Browser Integration workspace for the IDM Video Assistant extension."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.paths import project_root
from ...core.settings import AppSettings
from ...ui import icons
from ..theme import ThemeManager
from .common import Card, NoticeBanner, PageScroll

_BROWSERS = (
    ("chrome", "Google Chrome"),
    ("edge", "Microsoft Edge"),
    ("firefox", "Mozilla Firefox"),
    ("brave", "Brave"),
    ("opera", "Opera"),
)

_DIRECT_MEDIA_TYPES = (
    "MP4", "WebM", "M4V", "MOV", "MKV", "AVI",
    "MP3", "M4A", "AAC", "OGG", "WAV", "FLAC",
)


class _BrowserRow(QFrame):
    def __init__(self, theme: ThemeManager, browser: str, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("BrowserRow")
        self.browser = browser
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(10)

        icon = QLabel()
        icon.setPixmap(icons.icon("globe", theme.palette.accent, 18).pixmap(18, 18))
        icon.setFixedSize(20, 20)
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(1)
        name = QLabel(title)
        name.setObjectName("BrowserName")
        self.status = QLabel("Not checked")
        self.status.setObjectName("BrowserStatus")
        self.status.setWordWrap(True)
        text.addWidget(name)
        text.addWidget(self.status)
        layout.addLayout(text, 1)

        self.install_button = QPushButton("Enable")
        self.install_button.setObjectName("SubtleButton")
        self.install_button.setToolTip(
            "Register IDM's native messaging host for this browser"
        )
        self.remove_button = QPushButton("Disable")
        self.remove_button.setObjectName("DangerButton")
        self.remove_button.setToolTip("Remove IDM's native messaging registration")
        layout.addWidget(self.install_button)
        layout.addWidget(self.remove_button)

    def set_status(self, text: str, state: str = "") -> None:
        self.status.setText(text)
        self.status.setProperty("state", state)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)


class BrowserIntegrationPage(QWidget):
    message = Signal(str)
    guide_requested = Signal()

    def __init__(
        self,
        theme: ThemeManager,
        settings: AppSettings,
        service,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._settings = settings
        self._service = service
        self._checked = False
        self._last_activity = ""
        self.setObjectName("PageArea")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        page = PageScroll(theme, self)
        root.addWidget(page)
        body = page.body

        self._notice = NoticeBanner(
            theme,
            "IDM Video Assistant",
            "The Chromium extension detects direct media links and sends "
            "them to IDM through a local, validated native messaging connection. "
            "It does not read browsing history or download pages on its own.",
            "info",
        )
        guide = QPushButton("Integration guide")
        guide.setObjectName("SubtleButton")
        guide.clicked.connect(self.guide_requested)
        self._notice.add_action(guide)
        body.addWidget(self._notice)

        bridge = Card(
            theme,
            "Desktop bridge",
            "The extension reaches IDM through an authenticated connection on this computer.",
        )
        bridge_row = QHBoxLayout()
        bridge_row.setSpacing(10)
        self._bridge_status = QLabel("Checking…")
        self._bridge_status.setObjectName("BrowserStatus")
        bridge_row.addWidget(self._bridge_status, 1)
        self._restart_button = QPushButton("Restart bridge")
        self._restart_button.setObjectName("SubtleButton")
        self._restart_button.clicked.connect(self._restart_bridge)
        self._refresh_button = QPushButton("  Refresh status")
        self._refresh_button.setIcon(
            icons.icon("refresh", theme.palette.text_muted, 14)
        )
        self._refresh_button.clicked.connect(self.refresh)
        bridge_row.addWidget(self._restart_button)
        bridge_row.addWidget(self._refresh_button)
        bridge.add_layout(bridge_row)
        body.addWidget(bridge)

        browsers = Card(
            theme,
            "Registered browsers",
            "Native messaging is registered for the current Windows user. "
            "Chrome, Edge, Brave, Opera and Firefox must be restarted after "
            "a change.",
        )
        self._rows: dict[str, _BrowserRow] = {}
        for browser, title in _BROWSERS:
            row = _BrowserRow(theme, browser, title)
            row.install_button.clicked.connect(
                lambda _checked=False, key=browser: self._install(key)
            )
            row.remove_button.clicked.connect(
                lambda _checked=False, key=browser: self._remove(key)
            )
            row.install_button.setEnabled(False)
            row.remove_button.setEnabled(False)
            self._rows[browser] = row
            browsers.add(row)

        self._host_label = QLabel("Native host: not checked")
        self._host_label.setObjectName("PanelCaption")
        self._host_label.setWordWrap(True)
        browsers.add(self._host_label)
        body.addWidget(browsers)

        extension_card = Card(
            theme,
            "Extension folder",
            "Load the unpacked extension once in each browser. IDM never "
            "installs browser extensions silently.",
        )
        self._version_label = QLabel("Extension version: not found")
        self._version_label.setObjectName("PanelCaption")
        self._version_label.setWordWrap(True)
        extension_card.add(self._version_label)
        types = QLabel(
            "Supported direct media types: " + ", ".join(_DIRECT_MEDIA_TYPES)
            + ". Restricted platform pages are never scanned for streams."
        )
        types.setObjectName("HintLabel")
        types.setWordWrap(True)
        extension_card.add(types)
        extension_row = QHBoxLayout()
        extension_row.setSpacing(8)
        self._folder_label = QLabel()
        self._folder_label.setObjectName("PanelCaption")
        self._folder_label.setWordWrap(True)
        extension_row.addWidget(self._folder_label, 1)
        open_folder = QPushButton("Open folder")
        open_folder.setObjectName("SubtleButton")
        open_folder.clicked.connect(self._open_extension_folder)
        extension_row.addWidget(open_folder)
        extension_card.add_layout(extension_row)
        steps = QLabel(
            "Chrome: chrome://extensions → Developer mode → Load unpacked.  "
            "Edge: edge://extensions → Developer mode → Load unpacked.  "
            "Brave: brave://extensions → Developer mode → Load unpacked.  "
            "Opera: opera://extensions → Developer mode → Load unpacked.  "
            "Firefox: about:debugging → This Firefox → Load Temporary Add-on "
            "and pick extensions/firefox/manifest.json; a temporary add-on is "
            "unloaded on restart, so a signed add-on is needed for permanent "
            "integration."
        )
        steps.setObjectName("HintLabel")
        steps.setWordWrap(True)
        extension_card.add(steps)
        body.addWidget(extension_card)
        body.addStretch(1)

        theme.changed.connect(self._refresh_icons)
        self._refresh_icons()

        # The bridge reports every validated request, so an extension that
        # starts talking is visible without pressing Refresh.
        self._service.bridge_activity.connect(self._on_bridge_activity)
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(4000)
        self._status_timer.timeout.connect(self._refresh_bridge_status)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self.refresh)
        self._status_timer.start()

    def hideEvent(self, event) -> None:
        self._status_timer.stop()
        super().hideEvent(event)

    def _on_bridge_activity(self, request_type: str) -> None:
        self._last_activity = request_type
        self._refresh_bridge_status()

    # ------------------------------------------------------------------ helpers
    def _refresh_bridge_status(self) -> None:
        listening = bool(self._service.is_listening)
        bridge = self._service.bridge
        port = bridge.port
        connections = int(bridge.connection_count or 0)
        activity = (
            f" · last request: {self._last_activity.replace('_', ' ')}"
            if self._last_activity
            else ""
        )
        if listening:
            detail = (
                f"{connections} browser connection{'s' if connections != 1 else ''} active"
                if connections
                else "no browser connected yet"
            )
            location = f"127.0.0.1:{port}" if port else "local address"
            self._bridge_status.setText(
                f"Listening on {location} · {detail}{activity}"
            )
            self._bridge_status.setProperty("state", "ok")
        else:
            self._bridge_status.setText(
                "The bridge is not running. Restart it or check the log."
            )
            self._bridge_status.setProperty("state", "error")
        self._bridge_status.style().unpolish(self._bridge_status)
        self._bridge_status.style().polish(self._bridge_status)

    def _extension_dir(self) -> Path:
        try:
            from integrations import registration

            return registration.extension_dir()
        except Exception:
            return project_root() / "BrowserExtension" / "IDMVideoAssistant"

    def _refresh_icons(self) -> None:
        self._refresh_button.setIcon(
            icons.icon("refresh", self._theme.palette.text_muted, 14)
        )
        self._restart_button.setToolTip("Restart the local bridge connection")

    def _read_extension_version(self, folder: Path) -> str:
        manifest = folder / "manifest.json"
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""
        version = data.get("version")
        return str(version) if version else ""

    def refresh(self) -> None:
        self._checked = True
        self._refresh_bridge_status()

        folder = self._extension_dir()
        self._folder_label.setText(
            str(folder) if folder.is_dir() else
            "The extension files are not installed next to IDM."
        )
        version = self._read_extension_version(folder)
        self._version_label.setText(
            f"Extension version: {version}"
            if version
            else "Extension version: manifest.json was not found."
        )

        try:
            from integrations import registration
        except Exception:
            self._host_label.setText("Native host status is unavailable.")
            for row in self._rows.values():
                row.set_status("Not available on this platform.", "warn")
                row.install_button.setEnabled(False)
                row.remove_button.setEnabled(False)
            return

        host = None
        try:
            host = registration.find_host_path()
        except Exception:
            host = None
        self._host_label.setText(
            f"Native host: {host}" if host else
            "Native host: IDM_NativeHost.exe was not found. Install IDM with the "
            "V3 setup package to register browser integration."
        )
        if sys.platform != "win32":
            for row in self._rows.values():
                row.set_status("Windows only.", "warn")
                row.install_button.setEnabled(False)
                row.remove_button.setEnabled(False)
            return

        for browser, row in self._rows.items():
            try:
                status = registration.browser_status(browser)
            except Exception as exc:
                row.set_status(f"Status unavailable: {exc}", "error")
                row.install_button.setEnabled(bool(host))
                row.remove_button.setEnabled(False)
                continue
            problems = status.get("problems") or []
            registered = bool(status.get("registered_views"))
            if status.get("installed"):
                row.set_status(
                    "Registered for this user. Restart the browser to pick up changes.",
                    "ok",
                )
            elif registered:
                row.set_status(
                    "Registered, but needs attention: " + " ".join(problems),
                    "warn",
                )
            elif problems:
                row.set_status("Not registered. " + " ".join(problems), "warn")
            else:
                row.set_status("Not registered for this user.", "")
            row.install_button.setEnabled(bool(host))
            row.remove_button.setEnabled(registered)

    # ------------------------------------------------------------------ actions
    def _restart_bridge(self) -> None:
        try:
            self._service.stop()
            started = bool(self._service.start())
        except Exception:
            started = False
        if started:
            self.message.emit("Browser bridge restarted.")
        else:
            self.message.emit("The browser bridge could not be started.")
        self.refresh()

    def _install(self, browser: str) -> None:
        try:
            from integrations import registration

            host = registration.find_host_path()
            if host is None:
                QMessageBox.information(
                    self,
                    "Native host missing",
                    "IDM_NativeHost.exe was not found. Install IDM with the V3 "
                    "setup package, then try again.",
                )
                return
            result = registration.install_browser(browser, host)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Browser integration",
                f"The integration could not be installed:\n\n{exc}",
            )
            self.message.emit("Browser integration could not be installed.")
            return
        warnings = result.get("warnings") or []
        self.message.emit(
            f"Registered IDM for {browser.title()}."
            + (" Some registry views reported warnings." if warnings else "")
        )
        self.refresh()

    def _remove(self, browser: str) -> None:
        answer = QMessageBox.question(
            self,
            "Remove browser integration",
            f"Remove IDM's native messaging registration for {browser.title()}? "
            "The browser extension files are not deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            from integrations import registration

            result = registration.uninstall_browser(browser)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Browser integration",
                f"The registration could not be removed:\n\n{exc}",
            )
            return
        if result.get("ok"):
            self.message.emit(f"Removed IDM registration for {browser.title()}.")
        else:
            self.message.emit(
                "The registration could not be fully removed. "
                + " ".join(result.get("warnings") or [])
            )
        self.refresh()

    def _open_extension_folder(self) -> None:
        folder = self._extension_dir()
        if not folder.is_dir():
            QMessageBox.information(
                self,
                "Extension folder",
                "The IDM Video Assistant extension files were not found next to "
                "this installation.",
            )
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
