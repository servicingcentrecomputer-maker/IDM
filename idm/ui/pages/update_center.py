"""Update Center: configuration, history and recovery tools."""

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
from ...updater.state import load_history, read_pending_update
from .. import icons
from ..theme import ThemeManager
from .common import Card, NoticeBanner, PageScroll

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
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._settings = settings
        self.setObjectName("PageArea")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        page = PageScroll(theme, self)
        root.addWidget(page)
        body = page.body

        self._notice = NoticeBanner(
            theme,
            f"IDM {APP_VERSION}",
            "Updates are checked over HTTPS every 24 hours, verified with a "
            "signed manifest and SHA-256, and installed only with your approval.",
            "info",
        )
        check = QPushButton("  Check for updates")
        check.setObjectName("PrimaryButton")
        check.setIcon(icons.icon("arrow_up", "#FFFFFF", 14))
        check.clicked.connect(self.check_requested)
        self._notice.add_action(check)
        body.addWidget(self._notice)

        status = Card(theme, "Update configuration", "The source IDM uses for release information")
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        self._version_label = QLabel()
        self._channel_label = QLabel()
        self._source_label = QLabel()
        self._publisher_label = QLabel()
        self._last_check_label = QLabel()
        self._last_success_label = QLabel()
        rows = (
            ("Installed version", self._version_label),
            ("Channel", self._channel_label),
            ("Manifest source", self._source_label),
            ("Trusted publisher", self._publisher_label),
            ("Last check", self._last_check_label),
            ("Last successful update", self._last_success_label),
        )
        for row, (title, value) in enumerate(rows):
            label = QLabel(title)
            label.setObjectName("StatLabel")
            value.setObjectName("PanelCaption")
            value.setWordWrap(True)
            grid.addWidget(label, row, 0)
            grid.addWidget(value, row, 1)
        grid.setColumnStretch(1, 1)
        status.add_layout(grid)
        settings_button = QPushButton("Update settings")
        settings_button.setObjectName("SubtleButton")
        settings_button.clicked.connect(self.options_requested)
        status.body.addWidget(settings_button, 0, Qt.AlignmentFlag.AlignLeft)
        body.addWidget(status)

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

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        s = self._settings
        self._version_label.setText(f"{APP_NAME} {APP_VERSION}")
        self._channel_label.setText(str(s.update_channel or "stable").title())
        self._source_label.setText(
            s.update_manifest_url or "Not configured in this build."
        )
        self._publisher_label.setText(
            s.update_publisher or "No publisher key configured."
        )
        self._last_check_label.setText(s.update_last_check or "Never")
        if s.update_last_success:
            self._last_success_label.setText(
                f"{s.update_last_success} (version {s.update_last_success_version or '—'})"
            )
        else:
            self._last_success_label.setText("No successful update recorded.")

        enabled = []
        if s.update_auto_check:
            enabled.append(f"automatic checks every {int(s.update_check_interval_hours)} h")
        if s.update_auto_download:
            enabled.append("download automatically")
        if s.update_ask_before_install:
            enabled.append("ask before installing")
        self._notice.set_message(
            f"IDM {APP_VERSION}",
            "Updates are checked over HTTPS and verified with a signed manifest "
            "and SHA-256."
            + (f" Currently: {', '.join(enabled)}." if enabled else
               " Automatic checks are disabled."),
            "info",
        )

        self._history.clear()
        pending = None
        try:
            pending = read_pending_update()
        except Exception:
            pending = None
        if pending is not None:
            item = QListWidgetItem(
                f"Update in progress — {pending.from_version} → "
                f"{pending.target_version}\nStarted {pending.started_at}"
            )
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

    def _open_file(self, path: Path) -> None:
        path = Path(path)
        if not path.exists():
            self.message.emit(f"Not found: {path.name}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
