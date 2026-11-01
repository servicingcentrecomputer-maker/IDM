"""Update Center: verified updates, release notes and recovery tools."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...constants import APP_NAME, APP_VERSION
from ...core.paths import (
    project_root,
    update_backups_dir,
    updater_log_file,
)
from ...core.settings import AppSettings
from ...core.url_utils import format_size
from ...updater.state import load_history, read_pending_update
from .. import icons
from ..dialogs.update import UpdatePanel
from ..theme import ThemeManager
from ..update_service import config_from_settings
from .common import Card, NoticeBanner, PageScroll, StatCard

_EVENT_TITLES = {
    "started": "Update started",
    "success": "Update installed",
    "failure": "Update did not finish",
    "rollback": "Previous version restored",
}


class UpdateCenterPage(QWidget):
    check_requested = Signal()
    options_requested = Signal()
    message = Signal(str)

    def __init__(
        self,
        theme: ThemeManager,
        settings: AppSettings,
        on_install=None,
        active_downloads=None,
        pause_downloads=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._settings = settings
        self._result = None
        self._error = ""
        self.setObjectName("PageArea")

        if on_install is None:
            on_install = lambda _request: (
                "Automatic installation is not available in this context."
            )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        page = PageScroll(theme, self)
        root.addWidget(page)
        body = page.body

        self._notice = NoticeBanner(
            theme,
            f"IDM {APP_VERSION}",
            "Updates are checked over HTTPS and verified with an Ed25519-signed "
            "manifest and SHA-256 before anything is installed.",
            "info",
        )
        check = QPushButton("  Check for updates")
        check.setObjectName("PrimaryButton")
        check.setIcon(icons.icon("arrow_up", "#FFFFFF", 14))
        check.clicked.connect(self.check_now)
        self._notice.add_action(check)
        self._check_button = check
        settings_button = QPushButton("Update settings")
        settings_button.setObjectName("SubtleButton")
        settings_button.clicked.connect(self.options_requested)
        self._notice.add_action(settings_button)
        body.addWidget(self._notice)

        summary = Card(theme, "Release status", "Read from the configured channel")
        stats = QGridLayout()
        stats.setHorizontalSpacing(10)
        stats.setVerticalSpacing(10)
        self._installed_card = StatCard(
            theme, "Installed", APP_VERSION, "Current build", "check_circle"
        )
        self._latest_card = StatCard(
            theme, "Latest", "—", "Not checked yet", "download"
        )
        self._status_card = StatCard(
            theme, "Status", "Not checked", "Run a check to compare versions", "refresh"
        )
        for column, card in enumerate(
            (self._installed_card, self._latest_card, self._status_card)
        ):
            stats.addWidget(card, 0, column)
            stats.setColumnStretch(column, 1)
        summary.add_layout(stats)
        self._last_check_label = QLabel()
        self._last_check_label.setObjectName("PanelCaption")
        self._last_check_label.setWordWrap(True)
        summary.add(self._last_check_label)
        body.addWidget(summary)

        self._panel = UpdatePanel(
            settings,
            theme,
            on_install,
            self,
            active_downloads=active_downloads,
            pause_downloads=pause_downloads,
        )
        self._panel.result_changed.connect(self._on_panel_result)
        self._panel.check_failed.connect(self.set_check_failed)
        self._panel.installation_started.connect(self._on_installation_started)
        body.addWidget(self._panel)

        verification = Card(
            theme,
            "Verification and safety",
            "What is checked before an update can run on this computer",
        )
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        self._source_label = QLabel()
        self._publisher_label = QLabel()
        self._manifest_label = QLabel()
        self._integrity_label = QLabel()
        self._data_label = QLabel()
        self._success_label = QLabel()
        rows = (
            ("Manifest source", self._source_label),
            ("Release signature", self._manifest_label),
            ("Installer integrity", self._integrity_label),
            ("Trusted publisher", self._publisher_label),
            ("Your data", self._data_label),
            ("Last successful update", self._success_label),
        )
        for row, (title, value) in enumerate(rows):
            label = QLabel(title)
            label.setObjectName("StatLabel")
            value.setObjectName("PanelCaption")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(label, row, 0)
            grid.addWidget(value, row, 1)
        grid.setColumnStretch(1, 1)
        verification.add_layout(grid)
        body.addWidget(verification)

        history = Card(theme, "Update history", "Recorded by the verified updater")
        self._history = QListWidget()
        self._history.setObjectName("ActivityList")
        self._history.setMinimumHeight(150)
        history.add(self._history, 1)
        body.addWidget(history)

        tools = Card(theme, "Maintenance", "Inspect logs, backups and release notes")
        tools_row = QHBoxLayout()
        tools_row.setSpacing(8)
        log_button = QPushButton("  Open update log")
        log_button.setIcon(icons.icon("file_text", theme.palette.text_muted, 14))
        log_button.clicked.connect(lambda: self._open_file(updater_log_file()))
        backup_button = QPushButton("  Open backups")
        backup_button.setIcon(icons.icon("archive", theme.palette.text_muted, 14))
        backup_button.clicked.connect(lambda: self._open_file(update_backups_dir()))
        notes_button = QPushButton("  Release notes")
        notes_button.setIcon(icons.icon("info", theme.palette.text_muted, 14))
        notes_button.clicked.connect(
            lambda: self._open_file(project_root() / "ReleaseNotes.md")
        )
        for button in (log_button, backup_button, notes_button):
            tools_row.addWidget(button)
        tools_row.addStretch(1)
        tools.add_layout(tools_row)
        body.addWidget(tools)
        body.addStretch(1)

        theme.changed.connect(self.refresh)
        self.refresh()

    # ------------------------------------------------------------------ public
    def check_now(self) -> None:
        self._panel.check_for_updates()

    def set_update_result(self, result) -> None:
        self._result = result
        self._error = ""
        self._apply_result()
        self._panel.blockSignals(True)
        try:
            self._panel.set_result(result)
        finally:
            self._panel.blockSignals(False)
        self._refresh_settings_labels()

    def _on_panel_result(self, result) -> None:
        self._result = result
        self._error = ""
        self._apply_result()
        self._refresh_settings_labels()

    def set_check_failed(self, message: str) -> None:
        self._error = str(message or "").strip()
        self._status_card.set_value(
            "Check failed",
            self._error.splitlines()[0][:90] if self._error else "See the log",
        )
        self._latest_card.set_value("—", "The last check did not complete")
        self._status_card.set_accent(False)
        self._notice.set_message(
            "Update check failed",
            "IDM could not reach the update server. Your installed version is "
            "unchanged; see the update log for details.",
            "danger",
        )
        self._refresh_settings_labels()

    def refresh(self) -> None:
        channel = str(self._settings.update_channel or "stable").title()
        self._installed_card.set_value(APP_VERSION, f"{channel} channel")
        self._apply_result()
        self._refresh_settings_labels()
        self._refresh_history()
        self._refresh_verification()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    # ------------------------------------------------------------------ render
    def _apply_result(self) -> None:
        result = self._result
        settings = self._settings
        if result is None:
            if self._error:
                self._status_card.set_value("Check failed", "See the log")
            elif settings.update_last_check:
                self._status_card.set_value(
                    "Not checked", "Run a check to compare versions"
                )
            else:
                self._status_card.set_value(
                    "Not checked", "No update check has been recorded"
                )
            self._latest_card.set_value("—", "Not checked yet")
            self._status_card.set_accent(False)
            self._notice.set_message(
                f"IDM {APP_VERSION}",
                "Updates are checked over HTTPS and verified with an "
                "Ed25519-signed manifest and SHA-256 before anything is installed.",
                "info",
            )
            return

        manifest = result.manifest
        detail = f"Released {manifest.release_date}" if manifest.release_date else ""
        if getattr(manifest, "package_size", None):
            size = format_size(int(manifest.package_size))
            detail = f"{detail} · {size}" if detail else size
        self._latest_card.set_value(str(result.latest_version), detail)

        if result.update_available:
            self._status_card.set_value(
                "Update ready",
                "Review the notes, then install when you are ready.",
            )
            self._status_card.set_accent(True)
            self._notice.set_message(
                f"IDM {result.latest_version} is available",
                "The signed release manifest was verified over HTTPS. The "
                "installer SHA-256 is checked again before installation, and "
                "your downloads and history are kept."
                + (" This release is marked as required." if result.mandatory else ""),
                "warning" if not result.mandatory else "danger",
            )
        elif result.installed_is_newer:
            self._status_card.set_value(
                "Up to date", "The installed build is newer than the published release."
            )
            self._status_card.set_accent(False)
            self._notice.set_message(
                f"IDM {APP_VERSION}",
                "You are using a build newer than the latest published release.",
                "success",
            )
        else:
            self._status_card.set_value(
                "Up to date", f"IDM {result.latest_version} is the latest release."
            )
            self._status_card.set_accent(False)
            self._notice.set_message(
                "IDM is up to date",
                f"IDM {result.latest_version} is installed and no newer release "
                "is published on this channel.",
                "success",
            )

    def _refresh_settings_labels(self) -> None:
        s = self._settings
        self._installed_card.set_value(
            APP_VERSION, f"{str(s.update_channel or 'stable').title()} channel"
        )
        last = s.update_last_check or "Never"
        self._last_check_label.setText(f"Last check: {last}")
        if s.update_last_success:
            self._success_label.setText(
                f"{s.update_last_success} (version {s.update_last_success_version or '—'})"
            )
        else:
            self._success_label.setText("No successful update recorded.")

    def _refresh_verification(self) -> None:
        s = self._settings
        try:
            config = config_from_settings(s)
        except Exception:
            config = None
        source = ""
        if config is not None:
            source = config.manifest_url
        self._source_label.setText(
            source or s.update_manifest_url or "Not configured in this build."
        )
        if config is not None and config.signature_required:
            self._manifest_label.setText(
                "Ed25519 signature is required for every manifest."
            )
        elif config is not None and config.expected_publisher:
            self._manifest_label.setText(
                "Checked with the trusted Authenticode publisher before install."
            )
        else:
            self._manifest_label.setText(
                "No signing key is configured; automatic installation is disabled."
            )
        self._integrity_label.setText(
            "The installer SHA-256 must match the release manifest."
        )
        self._publisher_label.setText(
            s.update_publisher
            or "Not set — the signed manifest and SHA-256 are required instead."
        )
        self._data_label.setText(
            "A verified backup and rollback plan are recorded before installation."
        )

    def _refresh_history(self) -> None:
        self._history.clear()
        pending = None
        try:
            pending = read_pending_update()
        except Exception:
            pending = None
        if pending is not None:
            title = (
                f"Reinstall in progress — {pending.target_version}"
                if pending.reinstall
                else f"Update in progress — {pending.from_version} → "
                f"{pending.target_version}"
            )
            item = QListWidgetItem(f"{title}\nStarted {pending.started_at}")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._history.addItem(item)
        try:
            entries = load_history()
        except Exception:
            entries = []
        if not entries:
            placeholder = QListWidgetItem("No update attempts recorded yet.")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._history.addItem(placeholder)
        for entry in entries:
            event = str(entry.get("event") or "")
            title = _EVENT_TITLES.get(event, event.replace("-", " ").title())
            line = (
                f"{title} — {entry.get('from_version', '')} → "
                f"{entry.get('target_version', '')}"
            )
            detail = str(entry.get("message") or "")
            if detail:
                line += f"\n{detail}"
            line += f"\n{entry.get('at', '')}"
            self._history.addItem(QListWidgetItem(line))

    def _on_installation_started(self) -> None:
        self._status_card.set_value(
            "Installing", "The verified installer is running. IDM will restart."
        )
        self._status_card.set_accent(True)
        self._notice.set_message(
            "Installing the verified update",
            "IDM is closing so the signed installer can replace the program "
            "files. Your downloads, settings and history are kept.",
            "info",
        )

    def _open_file(self, path: Path) -> None:
        path = Path(path)
        if not path.exists():
            self.message.emit(f"Not found: {path.name}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
