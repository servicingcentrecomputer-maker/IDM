"""Update panel used by the About window and the Check for Updates action."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from PySide6.QtCore import QThread, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from ...core.settings import AppSettings
from ...core.url_utils import format_size, format_speed
from ...updater.config import UpdateConfig
from ...updater.download_metrics import describe_metrics
from ...updater.errors import UpdateConfigurationError
from ...updater.launcher import (
    InstallRequest,
    create_update_directory,
    safe_remove_update_dir,
    updater_executable,
)
from ...updater.update_checker import UpdateCheckResult
from ...updater.version_manager import Version, current_version
from ...version import APP_NAME
from .. import icons
from ..theme import ThemeManager
from ..update_service import (
    PreparedUpdate,
    UpdateCheckWorker,
    UpdateInstallWorker,
    config_from_settings,
)
from .common import (
    make_divider,
    make_label,
    primary_button,
    secondary_button,
)

logger = logging.getLogger(__name__)


class LinkLabel(QLabel):
    """A QLabel that behaves like a hyperlink without rendering remote HTML."""

    clicked = Signal()

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setObjectName("LinkLabel")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._enabled_link = False
        font = QFont(self.font())
        font.setUnderline(False)
        self.setFont(font)

    def set_link_enabled(self, enabled: bool) -> None:
        self._enabled_link = bool(enabled)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor
            if enabled
            else Qt.CursorShape.ArrowCursor
        )
        font = QFont(self.font())
        font.setUnderline(bool(enabled))
        self.setFont(font)

    def mouseReleaseEvent(self, event) -> None:
        if self._enabled_link and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if self._enabled_link and event.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
            Qt.Key.Key_Space,
        ):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class UpdatePanel(QWidget):
    installation_started = Signal()

    def __init__(
        self,
        settings: AppSettings,
        theme: ThemeManager,
        on_install,
        parent=None,
        active_downloads=None,
        pause_downloads=None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._theme = theme
        self._on_install = on_install
        self._active_downloads = active_downloads or (lambda: 0)
        self._pause_downloads = pause_downloads or (lambda: 0)
        self._config: UpdateConfig | None = None
        self._result: UpdateCheckResult | None = None
        self._prepared: PreparedUpdate | None = None
        self._update_dir: Path | None = None
        self._restart_requested = True
        self._busy = False
        self._handed_off = False
        self._closing = False
        self._last_action = "check"
        self._auto_install = False
        self._confirmed_install = False
        self._manual_download = False
        self._download_started_at = 0.0
        self._check_worker: UpdateCheckWorker | None = None
        self._install_worker: UpdateInstallWorker | None = None

        card = QFrame()
        card.setObjectName("DialogCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(7)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title = QLabel("Application Updates")
        title.setObjectName("SectionTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self._current_label = QLabel(
            f"Installed version: {current_version()} · "
            f"{getattr(self._settings, 'update_channel', 'stable') or 'stable'} channel"
        )
        self._current_label.setObjectName("HintLabel")
        title_row.addWidget(self._current_label)
        layout.addLayout(title_row)

        latest_row = QHBoxLayout()
        latest_row.setSpacing(8)
        latest_caption = QLabel("Latest version:")
        latest_caption.setObjectName("HintLabel")
        latest_row.addWidget(latest_caption)
        self._latest_value = LinkLabel("Not checked yet")
        latest_row.addWidget(self._latest_value)
        self._release_date = QLabel()
        self._release_date.setObjectName("HintLabel")
        latest_row.addWidget(self._release_date)
        latest_row.addStretch(1)
        layout.addLayout(latest_row)

        self._mandatory_label = QLabel("This update is required.")
        self._mandatory_label.setObjectName("UpdateMandatory")
        self._mandatory_label.hide()
        layout.addWidget(self._mandatory_label)

        self._status = QLabel("Not checked yet.")
        self._status.setObjectName("UpdateStatus")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._detail = QLabel()
        self._detail.setObjectName("ErrorLabel")
        self._detail.setWordWrap(True)
        self._detail.hide()
        layout.addWidget(self._detail)

        self._progress = QProgressBar()
        self._progress.setObjectName("DownloadProgress")
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFormat("%p%")
        self._progress.hide()
        layout.addWidget(self._progress)

        self._progress_text = QLabel()
        self._progress_text.setObjectName("ProgressMeta")
        self._progress_text.hide()
        layout.addWidget(self._progress_text)

        self._notes_label = make_label("RELEASE NOTES", "FieldLabel")
        self._notes_label.hide()
        layout.addWidget(self._notes_label)
        self._notes = QPlainTextEdit()
        self._notes.setObjectName("ReleaseNotes")
        self._notes.setReadOnly(True)
        self._notes.setMinimumHeight(100)
        self._notes.setMaximumHeight(150)
        self._notes.hide()
        layout.addWidget(self._notes)

        layout.addWidget(make_divider())
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self._check_button = secondary_button("Check for Updates")
        self._check_button.setIcon(
            icons.icon("arrow_up", self._theme.palette.text_muted, 16)
        )
        self._check_button.clicked.connect(self.check_for_updates)
        buttons.addWidget(self._check_button)
        buttons.addStretch(1)
        self._cancel_button = secondary_button("Cancel")
        self._cancel_button.hide()
        self._cancel_button.clicked.connect(self._cancel_download)
        buttons.addWidget(self._cancel_button)
        self._retry_button = secondary_button("Retry")
        self._retry_button.hide()
        self._retry_button.clicked.connect(self._retry)
        buttons.addWidget(self._retry_button)
        self._update_button = primary_button("Update Now")
        self._update_button.setIcon(icons.icon("download", "#FFFFFF", 16))
        self._update_button.hide()
        self._update_button.clicked.connect(self._update_action)
        buttons.addWidget(self._update_button)
        layout.addLayout(buttons)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(card)

        self._latest_value.clicked.connect(self._update_action)
        self._theme.changed.connect(self._sync_icons)

    # ------------------------------------------------------------------ public
    def set_result(self, result: UpdateCheckResult) -> None:
        """Show an already-completed check, for the notification window."""
        self._config = config_from_settings(self._settings)
        self._manual_download = (
            self._config.configured and not self._config.installation_supported
        )
        self._on_check_succeeded(result)

    def start_download(self) -> None:
        """Download and verify only; the user installs from this panel."""
        if self._busy or self._closing:
            return
        if self._manual_download:
            self._open_manual_download()
            return
        self._auto_install = False
        if self._preflight_install():
            self._begin_download()

    def start_install(self) -> None:
        """Download and install after the user clicked “Install Now”."""
        if self._busy or self._closing:
            return
        if self._manual_download:
            self._open_manual_download()
            return
        self._auto_install = True
        if not self._confirm_install_if_needed():
            return
        if self._preflight_install():
            self._begin_download()

    def install_prepared(self) -> None:
        if self._prepared is not None and self._guard_active_downloads():
            self._install_prepared()

    def check_for_updates(self) -> None:
        if self._busy or self._closing:
            return
        config = config_from_settings(self._settings)
        self._config = config
        self._manual_download = config.configured and not config.installation_supported
        try:
            config.require_endpoint()
        except UpdateConfigurationError as exc:
            self._result = None
            self._latest_value.setText("—")
            self._latest_value.set_link_enabled(False)
            self._release_date.clear()
            self._mandatory_label.hide()
            self._update_button.hide()
            self._retry_button.hide()
            self._progress.hide()
            self._progress_text.hide()
            self._show_message("Updates are not configured.", str(exc), "error")
            return

        self._busy = True
        self._last_action = "check"
        self._result = None
        self._prepared = None
        self._confirmed_install = False
        self._update_button.hide()
        self._retry_button.hide()
        self._cancel_button.hide()
        self._check_button.setEnabled(False)
        self._detail.hide()
        self._latest_value.setText("Checking…")
        self._latest_value.set_link_enabled(False)
        self._release_date.clear()
        self._mandatory_label.hide()
        self._progress.setRange(0, 0)
        self._progress.show()
        self._progress_text.setText("Contacting the update server…")
        self._progress_text.show()
        self._set_status("Checking for updates…", "busy")

        worker = UpdateCheckWorker(config, current_version(), self)
        worker.succeeded.connect(self._on_check_succeeded)
        worker.failed.connect(self._on_check_failed)
        worker.finished.connect(self._on_check_finished)
        self._check_worker = worker
        worker.start()

    def shutdown(self) -> None:
        self._closing = True
        self._stop_worker(self._check_worker, cancel=None)
        self._stop_worker(self._install_worker, cancel=lambda w: w.cancel())
        self._check_worker = None
        self._install_worker = None
        if self._update_dir is not None and not self._handed_off:
            safe_remove_update_dir(self._update_dir)
            self._update_dir = None

    # ------------------------------------------------------------------ check
    def _on_check_succeeded(self, result: UpdateCheckResult) -> None:
        self._busy = False
        self._check_button.setEnabled(True)
        self._progress.hide()
        self._progress_text.hide()
        self._detail.hide()
        self._result = result
        self._prepared = None
        self._confirmed_install = False
        manifest = result.manifest

        self._latest_value.setText(str(result.latest_version))
        release_text = f"Released {manifest.release_date}"
        if getattr(manifest, "package_size", None):
            release_text += f"  ·  {format_size(int(manifest.package_size))}"
        self._release_date.setText(release_text)
        self._update_button.setText("Update Now")
        self._mandatory_label.setVisible(result.update_available and result.mandatory)
        self._notes_label.setText(
            f"RELEASE NOTES — VERSION {result.latest_version}"
        )
        self._notes.setPlainText(
            manifest.release_notes or "No release notes were provided."
        )
        self._notes_label.show()
        self._notes.show()

        if result.update_available:
            self._latest_value.set_link_enabled(True)
            if self._manual_download:
                self._update_button.setText("Download Installer")
                self._set_status(
                    "New version available. Automatic installation is disabled.",
                    "warn",
                )
                self._detail.setText(
                    f"Download IDM {result.latest_version} from GitHub and run "
                    "the installer manually. Automatic installation requires a "
                    "build signed with a trusted code-signing certificate."
                )
                self._detail.show()
            else:
                self._set_status("New version available.", "warn")
                if result.mandatory:
                    self._detail.setText(
                        "This update is required because your installed version "
                        "is no longer supported. It is still installed only with "
                        "your consent."
                    )
                    self._detail.show()
            self._update_button.show()
            self._update_button.setEnabled(True)
            self._retry_button.hide()
            return

        self._latest_value.set_link_enabled(False)
        self._update_button.hide()
        self._retry_button.hide()
        if result.installed_is_newer:
            self._set_status("You are using the latest version of IDM.", "ok")
            self._detail.setText(
                "The installed version is newer than the latest published release."
            )
            self._detail.show()
        else:
            self._set_status("You are using the latest version of IDM.", "ok")

    def _on_check_failed(self, message: str) -> None:
        self._busy = False
        self._check_button.setEnabled(True)
        self._progress.hide()
        self._progress_text.hide()
        self._prepared = None
        self._confirmed_install = False
        self._update_button.hide()
        self._latest_value.setText("—")
        self._latest_value.set_link_enabled(False)
        self._release_date.clear()
        self._mandatory_label.hide()
        self._notes_label.hide()
        self._notes.hide()
        self._last_action = "check"
        self._show_message("Update failed.", message, "error")
        self._retry_button.show()

    def _on_check_finished(self) -> None:
        worker = self.sender()
        if isinstance(worker, QThread):
            worker.deleteLater()
        if worker is self._check_worker:
            self._check_worker = None

    # ------------------------------------------------------------------ install
    def _update_action(self) -> None:
        if self._manual_download:
            self._open_manual_download()
        else:
            self._prompt_install()

    def _open_manual_download(self) -> None:
        result = self._result
        if result is None:
            return
        url = QUrl(result.manifest.download_url)
        if url.scheme().lower() != "https" or not QDesktopServices.openUrl(url):
            self._show_message(
                "Could not open the download page.",
                "Open the IDM release page in your browser and download the "
                "installer manually.",
                "error",
            )
            return
        self._show_message(
            "Download opened in your browser.",
            f"Run the downloaded installer to update IDM to "
            f"{result.latest_version}. Automatic installation is disabled in "
            "this build.",
            "ok",
        )

    def _prompt_install(self) -> None:
        if self._busy or self._closing or self._result is None:
            return
        if self._manual_download:
            self._open_manual_download()
            return
        result = self._result
        if self._prepared is not None:
            if not self._confirm_install_if_needed():
                return
            self._install_prepared()
            return
        if not result.update_available:
            return
        if not self._confirm_install_if_needed():
            return
        self._auto_install = True
        if not self._preflight_install():
            return
        self._begin_download()

    def _confirm_install_if_needed(self) -> bool:
        if self._confirmed_install:
            return True
        if not bool(getattr(self._settings, "update_ask_before_install", True)):
            self._confirmed_install = True
            return self._guard_active_downloads()
        result = self._result
        if result is None:
            return False

        message = QMessageBox(self)
        message.setWindowTitle("Install IDM update")
        message.setIcon(QMessageBox.Icon.Question)
        message.setText(f"Install {APP_NAME} {result.latest_version} now?")
        details = (
            f"Current version: {result.current_version}\n"
            f"New version: {result.latest_version}\n"
            f"Release date: {result.manifest.release_date}\n\n"
            "IDM will back up your settings, download history and queue, then "
            "close while the verified installer runs."
        )
        if getattr(result.manifest, "package_size", None):
            details += (
                f"\nDownload size: {format_size(int(result.manifest.package_size))}"
            )
        if result.mandatory:
            details = "This is a required update.\n\n" + details
        active = int(self._active_downloads() or 0)
        if active:
            details += (
                f"\n\n{active} download{'s are' if active != 1 else ' is'} "
                "active. They will be paused before IDM closes; partial files "
                "are kept."
            )
        message.setInformativeText(details)
        restart_box = QCheckBox("Restart IDM when the installation finishes")
        restart_box.setChecked(True)
        message.setCheckBox(restart_box)
        message.setStandardButtons(
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok
        )
        message.button(QMessageBox.StandardButton.Ok).setText("Install")
        message.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if message.exec() != QMessageBox.StandardButton.Ok:
            return False

        self._restart_requested = restart_box.isChecked()
        self._confirmed_install = True
        return self._guard_active_downloads()

    def _guard_active_downloads(self) -> bool:
        count = int(self._active_downloads() or 0)
        if count <= 0:
            return True
        message = QMessageBox(self)
        message.setWindowTitle("Downloads are running")
        message.setIcon(QMessageBox.Icon.Question)
        message.setText(
            f"{count} download{'s are' if count != 1 else ' is'} still running."
        )
        message.setInformativeText(
            "The update needs IDM to close. Pause the active downloads and "
            "continue? Partial .idm.part files are kept and can be resumed "
            "after the update."
        )
        message.setStandardButtons(
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok
        )
        message.button(QMessageBox.StandardButton.Ok).setText(
            "Pause downloads and update"
        )
        message.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if message.exec() != QMessageBox.StandardButton.Ok:
            return False
        self._pause_downloads()
        return True

    def _preflight_install(self) -> bool:
        config = self._config or config_from_settings(self._settings)
        self._config = config
        try:
            config.require_publisher()
        except UpdateConfigurationError as exc:
            self._last_action = "check"
            self._show_message(
                "Automatic installation is not available.", str(exc), "error"
            )
            self._retry_button.hide()
            return False

        if updater_executable() is None:
            self._last_action = "check"
            self._show_message(
                "The Updater component is missing.",
                "Automatic installation requires the packaged IDM_Updater.exe "
                "next to IDM.exe. Build the application with "
                "build_windows.ps1 or reinstall IDM to repair the update system.",
                "error",
            )
            self._retry_button.hide()
            return False
        return True

    def _begin_download(self) -> None:
        if self._result is None:
            return
        config = self._config or config_from_settings(self._settings)
        if self._update_dir is None:
            self._update_dir = create_update_directory()

        self._prepared = None
        self._download_started_at = time.monotonic()
        self._busy = True
        self._last_action = "download"
        self._detail.hide()
        self._retry_button.hide()
        self._update_button.hide()
        self._check_button.setEnabled(False)
        self._cancel_button.show()
        self._cancel_button.setEnabled(True)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.show()
        self._progress_text.setText("0%")
        self._progress_text.show()
        self._set_status("Downloading update…", "busy")

        worker = UpdateInstallWorker(
            config, self._result.manifest, self._update_dir, self
        )
        worker.progress.connect(self._on_progress)
        worker.status.connect(self._on_download_status)
        worker.succeeded.connect(self._on_install_succeeded)
        worker.failed.connect(self._on_install_failed)
        worker.cancelled.connect(self._on_install_cancelled)
        worker.finished.connect(self._on_install_finished)
        self._install_worker = worker
        worker.start()

    def _on_progress(self, done: int, total: int) -> None:
        elapsed = max(0.0, time.monotonic() - self._download_started_at)
        if total > 0:
            percent = max(0, min(100, int(done * 100 / total)))
            self._progress.setRange(0, 100)
            self._progress.setValue(percent)
        else:
            self._progress.setRange(0, 0)
        self._progress_text.setText(
            describe_metrics(
                done,
                total if total > 0 else None,
                elapsed,
                format_size,
                format_speed,
            )
        )

    def _on_download_status(self, text: str) -> None:
        if text.startswith("Downloading"):
            self._set_status("Downloading update…", "busy")
        elif text.startswith("Verifying"):
            self._progress.setRange(0, 0)
            self._progress_text.setText("Checking SHA-256 and Authenticode signature…")
            self._set_status("Verifying update package…", "busy")
        elif text.startswith("Preparing"):
            self._progress.setRange(0, 0)
            self._progress_text.setText("Saving application state…")
            self._set_status("Preparing installation…", "busy")

    def _on_install_succeeded(self, prepared: PreparedUpdate) -> None:
        self._busy = False
        self._cancel_button.hide()
        self._check_button.setEnabled(True)
        self._progress.setRange(0, 100)
        self._progress.setValue(100)
        self._progress_text.hide()
        self._prepared = prepared

        if self._result is None or self._update_dir is None:
            self._on_install_failed("The update information is no longer available.")
            return
        if self._auto_install:
            self._set_status("Preparing installation…", "busy")
            self._install_prepared()
            return

        self._set_status("Update downloaded and verified.", "ok")
        self._detail.setText(
            "The signed installer passed SHA-256 and Windows Authenticode "
            "verification. Click Install Now when you are ready; IDM will "
            "close and install the update."
        )
        self._detail.show()
        self._update_button.setText("Install Now")
        self._update_button.show()
        self._update_button.setEnabled(True)
        self._retry_button.hide()

    def _install_prepared(self) -> None:
        prepared = self._prepared
        result = self._result
        if prepared is None or result is None or self._update_dir is None:
            self._on_install_failed("The update information is no longer available.")
            return
        if not self._guard_active_downloads():
            return

        request = InstallRequest(
            installer=prepared.downloaded.path,
            sha256=prepared.downloaded.sha256,
            publisher=prepared.publisher,
            target_version=result.manifest.latest_version,
            update_dir=self._update_dir,
            restart=self._restart_requested,
            manifest=result.manifest,
        )
        try:
            error = self._on_install(request)
        except Exception:
            logger.exception("The update handoff failed")
            error = "IDM could not start the updater. See the log for details."
        if error:
            self._on_install_failed(str(error))
            return

        self._handed_off = True
        self.installation_started.emit()

    def _on_install_failed(self, message: str) -> None:
        self._busy = False
        self._cancel_button.hide()
        self._check_button.setEnabled(True)
        self._progress.hide()
        self._progress_text.hide()
        if self._result is not None and self._result.update_available:
            self._update_button.setText(
                "Install Now" if self._prepared is not None else "Update Now"
            )
            self._update_button.show()
            self._update_button.setEnabled(True)
        self._last_action = "download"
        self._show_message("Update failed.", message, "error")
        self._retry_button.show()

    def _on_install_cancelled(self) -> None:
        self._busy = False
        self._cancel_button.hide()
        self._check_button.setEnabled(True)
        self._progress.hide()
        self._progress_text.hide()
        self._set_status("Download cancelled.", "warn")
        self._detail.hide()
        self._prepared = None
        self._cleanup_update_dir()
        if self._result is not None and self._result.update_available:
            self._update_button.setText("Update Now")
            self._update_button.show()
            self._update_button.setEnabled(True)
        self._retry_button.show()
        self._last_action = "download"

    def _on_install_finished(self) -> None:
        worker = self.sender()
        if isinstance(worker, QThread):
            worker.deleteLater()
        if worker is self._install_worker:
            self._install_worker = None

    def _cancel_download(self) -> None:
        if self._install_worker is not None:
            self._cancel_button.setEnabled(False)
            self._install_worker.cancel()

    def _retry(self) -> None:
        if self._busy or self._result is None:
            return
        if self._last_action == "check":
            self.check_for_updates()
            return
        if self._prepared is not None:
            self.install_prepared()
            return
        if not self._preflight_install():
            return
        self._begin_download()

    # ------------------------------------------------------------------ helpers
    def _set_status(self, text: str, state: str) -> None:
        self._status.setText(text)
        if self._status.property("state") != state:
            self._status.setProperty("state", state)
            style = self._status.style()
            style.unpolish(self._status)
            style.polish(self._status)
            self._status.update()

    def _show_message(self, status: str, detail: str, state: str) -> None:
        self._set_status(status, state)
        self._detail.setText(detail)
        self._detail.setVisible(bool(detail))

    def _cleanup_update_dir(self) -> None:
        if self._update_dir is not None and not self._handed_off:
            safe_remove_update_dir(self._update_dir)
            self._update_dir = None

    def _stop_worker(self, worker, cancel) -> None:
        if worker is None or not worker.isRunning():
            return
        if cancel is not None:
            cancel(worker)
        if not worker.wait(2500):
            logger.warning("Terminating an unresponsive update worker")
            worker.terminate()
            worker.wait(1000)

    def _sync_icons(self) -> None:
        self._check_button.setIcon(
            icons.icon("arrow_up", self._theme.palette.text_muted, 16)
        )
        self._update_button.setIcon(icons.icon("download", "#FFFFFF", 16))
