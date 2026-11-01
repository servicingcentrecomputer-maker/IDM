"""Settings workspace with fourteen searchable, persisted sections."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...constants import APP_NAME, APP_VERSION, MAX_SPEED_LIMIT_KBPS
from ...core.paths import (
    app_data_dir,
    database_backup_dir,
    ensure_download_dir,
    log_file,
    project_root,
    schedules_file,
)
from ...core.settings import AppSettings
from .. import design, icons
from ..components import Card, PageScroll
from ..theme import THEME_LABELS, THEME_ORDER, ThemeManager
from .common import NoticeBanner

_DIRECT_MEDIA_TYPES = (
    "MP4", "WebM", "M4V", "MOV", "MKV", "AVI",
    "MP3", "M4A", "AAC", "OGG", "WAV", "FLAC",
)
_CATEGORY_TYPES = {
    "Documents": "PDF, DOCX, XLSX, PPTX, TXT, EPUB",
    "Programs": "EXE, MSI, ZIP installers, APK",
    "Music": "MP3, FLAC, WAV, M4A, OGG",
    "Compressed": "ZIP, RAR, 7Z, TAR, GZ",
    "Videos": "MP4, MKV, WebM, MOV, AVI",
}


class SettingsSection(Card):
    """Card that can hide individual rows when the settings search changes."""

    def __init__(
        self, theme: ThemeManager, title: str, caption: str = "", parent=None
    ) -> None:
        super().__init__(theme, title, caption, parent)
        self.section_title = title
        self.section_caption = caption
        self._entries: list[tuple[QWidget, str]] = []

    def add_row(
        self, title: str, control: QWidget, caption: str = ""
    ) -> QWidget:
        row = QFrame()
        row.setObjectName("SettingRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 9, 0, 9)
        layout.setSpacing(16)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        label = QLabel(title)
        label.setObjectName("SettingTitle")
        label.setWordWrap(True)
        text.addWidget(label)
        if caption:
            hint = QLabel(caption)
            hint.setObjectName("SettingHint")
            hint.setWordWrap(True)
            text.addWidget(hint)
        layout.addLayout(text, 1)
        layout.addWidget(control, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.body.addWidget(row)
        self._entries.append((row, f"{title} {caption}".lower()))
        return row

    def add_value(self, title: str, value: QLabel, caption: str = "") -> QWidget:
        row = QFrame()
        row.setObjectName("SettingRow")
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 9, 0, 9)
        layout.setSpacing(3)
        label = QLabel(title)
        label.setObjectName("SettingTitle")
        layout.addWidget(label)
        value.setObjectName("PanelCaption")
        value.setWordWrap(True)
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(value)
        if caption:
            hint = QLabel(caption)
            hint.setObjectName("SettingHint")
            hint.setWordWrap(True)
            layout.addWidget(hint)
        self.body.addWidget(row)
        self._entries.append((row, f"{title} {caption}".lower()))
        return row

    def add_buttons(
        self, title: str, buttons: list[QWidget], caption: str = ""
    ) -> QWidget:
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for button in buttons:
            layout.addWidget(button)
        return self.add_row(title, holder, caption)

    def apply_search(self, query: str) -> bool:
        if not query:
            for row, _text in self._entries:
                row.setVisible(True)
            self.setVisible(True)
            return True
        header = f"{self.section_title} {self.section_caption}".lower()
        header_match = query in header
        any_visible = header_match
        for row, text in self._entries:
            visible = header_match or query in self._searchable(row) or query in text
            row.setVisible(visible)
            any_visible = any_visible or visible
        shown = any_visible and (bool(self._entries) or header_match)
        self.setVisible(shown)
        return shown

    def _searchable(self, row: QWidget) -> str:
        return " ".join(
            widget.text()
            for widget in row.findChildren(QLabel)
            if hasattr(widget, "text")
        ).lower()


class AdvancedSettingsPage(QWidget):
    settings_applied = Signal()
    options_requested = Signal()
    options_tab_requested = Signal(int)
    import_requested = Signal()
    export_requested = Signal()
    scheduler_requested = Signal()
    queue_requested = Signal()
    navigate_requested = Signal(str)
    check_requested = Signal()
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
        self._sections: list[SettingsSection] = []
        self.setObjectName("PageArea")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        command_bar = QFrame()
        command_bar.setObjectName("SettingsCommandBar")
        command_layout = QHBoxLayout(command_bar)
        command_layout.setContentsMargins(12, 10, 12, 10)
        command_layout.setSpacing(10)
        self._search = QLineEdit()
        self._search.setObjectName("SearchBox")
        self._search.setPlaceholderText("Search settings…")
        self._search.setClearButtonEnabled(True)
        self._search_action = self._search.addAction(
            icons.icon("search", self._theme.palette.text_faint, 16),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self._search.textChanged.connect(self._apply_search)
        command_layout.addWidget(self._search, 1)
        self._apply_button = QPushButton("Apply settings")
        self._apply_button.setObjectName("PrimaryButton")
        self._apply_button.clicked.connect(self._apply)
        command_layout.addWidget(self._apply_button)
        self._reload_button = QPushButton("Discard changes")
        self._reload_button.setObjectName("SubtleButton")
        self._reload_button.clicked.connect(self._load)
        command_layout.addWidget(self._reload_button)
        root.addWidget(command_bar)

        page = PageScroll(theme, self)
        root.addWidget(page, 1)
        body = page.body
        self._body = body

        self._no_results = QLabel("No settings match this search.")
        self._no_results.setObjectName("MutedCaption")
        self._no_results.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_results.setVisible(False)

        self._build_general(body)
        self._build_downloads(body)
        self._build_connections(body)
        self._build_browser(body)
        self._build_video(body)
        self._build_file_types(body)
        self._build_scheduler(body)
        self._build_notifications(body)
        self._build_appearance(body)
        self._build_storage(body)
        self._build_backup(body)
        self._build_updates(body)
        self._build_security(body)
        self._build_about(body)
        body.addWidget(self._no_results)
        body.addStretch(1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addWidget(self._apply_footer_button())
        footer.addStretch(1)
        body.addLayout(footer)

        theme.changed.connect(self._on_theme_changed)
        self._load()
        self._refresh_runtime_info()

    # ------------------------------------------------------------------ sections
    def _section(self, body, title: str, caption: str) -> SettingsSection:
        section = SettingsSection(self._theme, title, caption, self)
        self._sections.append(section)
        body.addWidget(section)
        return section

    def _build_general(self, body) -> None:
        section = self._section(
            body, "General", "Everyday behaviour when IDM starts and downloads finish."
        )
        self._start_check = QCheckBox()
        section.add_row(
            "Start downloads immediately",
            self._start_check,
            "Begin transferring as soon as a link is added instead of queueing it.",
        )
        self._restore_check = QCheckBox()
        section.add_row(
            "Restore the download list at startup",
            self._restore_check,
            "Reload saved transfers so progress resumes where it stopped.",
        )
        self._confirm_check = QCheckBox()
        section.add_row(
            "Ask before removing downloads",
            self._confirm_check,
            "Removing a record never deletes the file on disk.",
        )
        section.add_buttons(
            "Transfer tools",
            [
                self._button("Import downloads…", self.import_requested, "import"),
                self._button("Export downloads…", self.export_requested, "export"),
            ],
            "Move download records between installations.",
        )

    def _build_downloads(self, body) -> None:
        section = self._section(
            body, "Downloads", "Retry policy and automatic recovery."
        )
        self._retry_check = QCheckBox()
        section.add_row(
            "Retry transient network failures",
            self._retry_check,
            "Retried attempts keep the bytes already received.",
        )
        self._max_retries = self._spin(0, 10)
        section.add_row(
            "Retries per download", self._max_retries, "Zero disables automatic retries."
        )
        self._network_check = QCheckBox()
        section.add_row(
            "Resume automatically when the connection returns",
            self._network_check,
        )
        section.add_buttons(
            "Queue",
            [self._button("Open queue manager", self.queue_requested, "queue")],
            "Change the order of waiting downloads.",
        )

    def _build_connections(self, body) -> None:
        section = self._section(
            body, "Connections", "Limits applied to the segmented download engine."
        )
        self._concurrent = self._spin(1, 10)
        section.add_row(
            "Simultaneous downloads",
            self._concurrent,
            "Active transfers allowed at the same time.",
        )
        self._connections = self._spin(1, 16)
        section.add_row(
            "Connections per download",
            self._connections,
            "Parallel segments used for a single file.",
        )
        self._speed = QSpinBox()
        self._speed.setRange(0, MAX_SPEED_LIMIT_KBPS)
        self._speed.setSingleStep(64)
        self._speed.setSuffix(" KB/s")
        self._speed.setSpecialValueText("Unlimited")
        section.add_row(
            "Global speed limit", self._speed, "Zero means no limit."
        )

    def _build_browser(self, body) -> None:
        section = self._section(
            body,
            "Browser Integration",
            "The IDM Video Assistant extension and its local native messaging bridge.",
        )
        self._browser_status = QLabel()
        section.add_value("Desktop bridge", self._browser_status)
        self._browser_version = QLabel()
        section.add_value("Extension", self._browser_version)
        self._browser_connections = QLabel()
        section.add_value("Browser connection", self._browser_connections)
        section.add_buttons(
            "Assistant",
            [
                self._button(
                    "Open Browser Assistant",
                    lambda: self.navigate_requested.emit("browser_integration"),
                    "globe",
                )
            ],
            "Register Chrome or Edge, review honest connection status and copy instructions.",
        )

    def _build_video(self, body) -> None:
        section = self._section(
            body,
            "Video Downloads",
            "Direct media links you are authorised to download.",
        )
        notice = NoticeBanner(
            self._theme,
            "No DRM or platform bypass",
            "IDM recognises YouTube and other platform links only to open the "
            "official page. It never extracts protected streams, deciphers "
            "signatures or scans restricted pages.",
            "info",
        )
        section.body.addWidget(notice)
        types = QLabel(
            "Supported direct media types: " + ", ".join(_DIRECT_MEDIA_TYPES) + "."
        )
        types.setObjectName("HintLabel")
        types.setWordWrap(True)
        section.body.addWidget(types)
        section.add_buttons(
            "Library",
            [
                self._button(
                    "Open Video Downloads",
                    lambda: self.navigate_requested.emit("video_downloads"),
                    "video",
                )
            ],
        )
        self._video_notice = notice

    def _build_file_types(self, body) -> None:
        section = self._section(
            body,
            "File Types",
            "How IDM categorises files and where automatic save rules are managed.",
        )
        summary = QLabel(
            "\n".join(f"{name}: {types}" for name, types in _CATEGORY_TYPES.items())
        )
        summary.setObjectName("HintLabel")
        summary.setWordWrap(True)
        section.body.addWidget(summary)
        self._rules_summary = QLabel()
        section.add_value("Location rules", self._rules_summary)
        section.add_buttons(
            "Save locations",
            [
                self._button(
                    "Manage file type rules…",
                    lambda: self.options_tab_requested.emit(2),
                    "folder",
                ),
                self._button(
                    "All options…",
                    self.options_requested,
                    "options",
                ),
            ],
        )

    def _build_scheduler(self, body) -> None:
        section = self._section(
            body,
            "Scheduler",
            "Timed pause and resume actions stored on this computer.",
        )
        self._schedule_summary = QLabel()
        section.add_value("Saved schedules", self._schedule_summary)
        section.add_buttons(
            "Manage",
            [self._button("Open scheduler", self.scheduler_requested, "scheduler")],
            "Create, review or remove timed actions.",
        )

    def _build_notifications(self, body) -> None:
        section = self._section(
            body,
            "Notifications",
            "Completion, failure and update notices stored locally.",
        )
        self._notify_update = QCheckBox()
        section.add_row(
            "Notify me about new updates",
            self._notify_update,
            "Update notices can always be checked manually in Update Center.",
        )
        self._notification_count = QLabel()
        section.add_value("Stored notifications", self._notification_count)
        section.add_buttons(
            "Inbox",
            [
                self._button(
                    "Open notification center",
                    lambda: self.navigate_requested.emit("notifications"),
                    "bell",
                )
            ],
        )

    def _build_appearance(self, body) -> None:
        section = self._section(
            body, "Appearance", "Theme, motion and workspace visibility."
        )
        self._theme_combo = QComboBox()
        for mode in THEME_ORDER:
            self._theme_combo.addItem(THEME_LABELS[mode], mode)
        section.add_row(
            "Colour theme", self._theme_combo, "Light, dark, classic or follow Windows."
        )
        self._animations_check = QCheckBox()
        section.add_row(
            "Interface animations",
            self._animations_check,
            "Reduced-motion preferences reported by Windows are always respected.",
        )
        self._sidebar_collapsed_check = QCheckBox()
        section.add_row(
            "Collapse the sidebar",
            self._sidebar_collapsed_check,
            "Keep navigation as an icon rail.",
        )
        self._toolbar_check = QCheckBox()
        section.add_row("Show the toolbar", self._toolbar_check)
        self._sidebar_check = QCheckBox()
        section.add_row("Show the navigation sidebar", self._sidebar_check)
        self._list_check = QCheckBox()
        section.add_row("Show the download list", self._list_check)
        self._status_check = QCheckBox()
        section.add_row("Show the status bar", self._status_check)
        section.add_buttons(
            "Advanced",
            [self._button("All interface options…", self.options_requested, "options")],
        )

    def _build_storage(self, body) -> None:
        section = self._section(
            body, "Storage", "Where new downloads and partial files are stored."
        )
        self._folder_edit = QLineEdit()
        self._folder_edit.setMinimumWidth(220)
        browse = QPushButton("Browse…")
        browse.setObjectName("SubtleButton")
        browse.setIcon(icons.icon("folder", self._theme.palette.text_muted, 14))
        browse.clicked.connect(self._browse)
        holder = QWidget()
        holder_layout = QHBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.setSpacing(6)
        holder_layout.addWidget(self._folder_edit)
        holder_layout.addWidget(browse)
        section.add_row("Download folder", holder)
        self._storage_usage = QLabel()
        section.add_value("Disk usage", self._storage_usage)
        section.add_buttons(
            "Folder",
            [self._button("Open download folder", self._open_download_folder, "folder_open")],
        )

    def _build_backup(self, body) -> None:
        section = self._section(
            body,
            "Backup and Restore",
            "Consistent snapshots of the SQLite database.",
        )
        self._backup_summary = QLabel()
        section.add_value(
            "Latest backup",
            self._backup_summary,
            "Automatic pre-update backups are kept separately by the verified updater.",
        )
        section.add_buttons(
            "Backups",
            [
                self._button("Create backup now", self._create_backup, "database"),
                self._button(
                    "Open backup folder",
                    lambda: self._open_path(database_backup_dir()),
                    "folder_open",
                ),
            ],
            "Restoring a database copy is performed by the verified updater rollback, "
            "never by overwriting the live database.",
        )

    def _build_updates(self, body) -> None:
        section = self._section(
            body,
            "Automatic Updates",
            "Signed release checks. Installation always requires explicit approval.",
        )
        self._update_auto = QCheckBox()
        section.add_row("Check for updates automatically", self._update_auto)
        self._update_interval = self._spin(1, 168)
        self._update_interval.setSuffix(" h")
        section.add_row("Check interval", self._update_interval)
        self._update_download = QCheckBox()
        section.add_row("Download new versions automatically", self._update_download)
        self._update_ask = QCheckBox()
        section.add_row("Ask before installing", self._update_ask)
        self._update_channel = QComboBox()
        self._update_channel.addItem("Stable", "stable")
        self._update_channel.addItem("Beta", "beta")
        section.add_row("Release channel", self._update_channel)
        self._update_url = QLineEdit()
        self._update_url.setMinimumWidth(260)
        self._update_url.setPlaceholderText("https://…/latest.json")
        section.add_row(
            "Signed manifest URL", self._update_url, "Plain HTTPS address only."
        )
        self._update_publisher = QLineEdit()
        self._update_publisher.setMinimumWidth(200)
        section.add_row("Trusted publisher", self._update_publisher)
        section.add_buttons(
            "Update Center",
            [
                self._button("Check for updates", self.check_requested, "refresh"),
                self._button(
                    "Open Update Center",
                    lambda: self.navigate_requested.emit("update_center"),
                    "arrow_up",
                ),
            ],
        )

    def _build_security(self, body) -> None:
        section = self._section(
            body, "Security", "Verification rules enforced by the updater."
        )
        for title, value in (
            ("Manifest signature", "Ed25519 signature required"),
            ("Payload integrity", "SHA-256 verified before installation"),
            ("Transport", "HTTPS only; credentials in URLs are rejected"),
            ("Native messaging", "Strict size limits and a command allowlist"),
            ("Browser permissions", "No browsing-history collection"),
        ):
            label = QLabel(value)
            section.add_value(title, label)
        section.add_buttons(
            "Audit",
            [
                self._button(
                    "Open update log", lambda: self._open_path(log_file()), "file_text"
                )
            ],
        )

    def _build_about(self, body) -> None:
        section = self._section(body, "About IDM", "Build and local data locations.")
        version = QLabel(f"{APP_NAME} {APP_VERSION}")
        section.add_value("Version", version)
        data = QLabel(str(app_data_dir()))
        section.add_value("Application data", data)
        extension = QLabel("Not found")
        section.add_value("Browser extension", extension)
        self._about_extension = extension
        section.add_buttons(
            "Details",
            [
                self._button("Open data folder", lambda: self._open_path(app_data_dir()), "folder_open"),
                self._button(
                    "Release notes",
                    lambda: self._open_path(project_root() / "ReleaseNotes.md"),
                    "file_text",
                ),
            ],
        )

    # ------------------------------------------------------------------ helpers
    def _button(self, text: str, callback, icon_name: str) -> QPushButton:
        button = QPushButton(f"  {text}")
        button.setObjectName("SubtleButton")
        button.setIcon(icons.icon(icon_name, self._theme.palette.text_muted, 14))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda _checked=False: callback())
        button.setProperty("icon_name", icon_name)
        return button

    def _spin(self, low: int, high: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(low, high)
        return spin

    def _apply_footer_button(self) -> QPushButton:
        button = QPushButton("Apply settings")
        button.setObjectName("PrimaryButton")
        button.clicked.connect(self._apply)
        return button

    # ------------------------------------------------------------------ data
    def _load_theme(self) -> None:
        index = self._theme_combo.findData(self._settings.theme)
        if index >= 0:
            self._theme_combo.setCurrentIndex(index)

    def _load(self) -> None:
        s = self._settings
        self._theme_combo.blockSignals(True)
        self._load_theme()
        self._theme_combo.blockSignals(False)
        self._folder_edit.setText(s.download_dir)
        self._concurrent.setValue(int(s.max_concurrent))
        self._connections.setValue(int(s.connections_per_download))
        self._speed.setValue(int(s.speed_limit_kbps))
        self._start_check.setChecked(bool(s.start_immediately))
        self._restore_check.setChecked(bool(s.restore_session))
        self._retry_check.setChecked(bool(s.auto_retry))
        self._max_retries.setValue(int(s.max_retries))
        self._network_check.setChecked(bool(s.auto_resume_on_network))
        self._confirm_check.setChecked(bool(s.confirm_delete))
        self._toolbar_check.setChecked(bool(s.show_toolbar))
        self._sidebar_check.setChecked(bool(s.show_sidebar))
        self._list_check.setChecked(bool(s.show_download_list))
        self._status_check.setChecked(bool(s.show_status_bar))
        self._sidebar_collapsed_check.setChecked(bool(s.sidebar_collapsed))
        self._animations_check.setChecked(bool(s.ui_animations))
        self._notify_update.setChecked(bool(s.update_notify))
        self._update_auto.setChecked(bool(s.update_auto_check))
        self._update_interval.setValue(int(s.update_check_interval_hours))
        self._update_download.setChecked(bool(s.update_auto_download))
        self._update_ask.setChecked(bool(s.update_ask_before_install))
        channel = self._update_channel.findData(s.update_channel)
        self._update_channel.setCurrentIndex(channel if channel >= 0 else 0)
        self._update_url.setText(s.update_manifest_url)
        self._update_publisher.setText(s.update_publisher)
        self._rules_summary.setText(self._rules_text())

    def _rules_text(self) -> str:
        config = self._settings.location_config.normalized()
        if not config.rules:
            return "No file type rules saved. The default folder is used."
        lines = []
        for rule in config.rules:
            extensions = ", ".join(rule.extensions)
            lines.append(f"{extensions} → {rule.folder}")
        return "\n".join(lines)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._load()
        self._refresh_runtime_info()

    def _refresh_runtime_info(self) -> None:
        database = getattr(self._settings, "database", None)
        if database is not None:
            try:
                self._storage_usage.setText(self._disk_usage_text())
            except OSError:
                self._storage_usage.setText("Storage information is unavailable.")
            try:
                unread = database.unread_notification_count()
                total = len(database.load_notifications(limit=1000))
                self._notification_count.setText(
                    f"{total} stored · {unread} unread"
                )
            except Exception:
                self._notification_count.setText("Notification store unavailable.")
        self._schedule_summary.setText(self._schedule_text())
        self._backup_summary.setText(self._backup_text())
        self._refresh_browser_summary()

    def _disk_usage_text(self) -> str:
        usage = shutil.disk_usage(self._settings.download_dir)
        from ...core.url_utils import format_size

        return (
            f"{format_size(usage.free)} free of {format_size(usage.total)} "
            f"in {self._settings.download_dir}"
        )

    def _schedule_text(self) -> str:
        path = schedules_file()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return "No schedules saved."
        if not isinstance(raw, list):
            return "No schedules saved."
        return f"{len(raw)} saved schedule{'s' if len(raw) != 1 else ''}."

    def _backup_text(self) -> str:
        try:
            backups = sorted(
                database_backup_dir().glob("*.sqlite3"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return "Backup folder unavailable."
        if not backups:
            return "No database backup has been created yet."
        latest = backups[0]
        moment = datetime.fromtimestamp(latest.stat().st_mtime)
        return f"{latest.name} · {moment:%Y-%m-%d %H:%M} · {len(backups)} backup(s)"

    def _refresh_browser_summary(self) -> None:
        bridge = None
        service = getattr(self.window(), "_browser", None)
        if service is not None:
            bridge = getattr(service, "bridge", None)
        listening = bool(getattr(service, "is_listening", False)) if service else False
        connections = int(getattr(bridge, "connection_count", 0) or 0) if bridge else 0
        if listening:
            port = getattr(bridge, "port", None)
            self._browser_status.setText(
                f"Listening on 127.0.0.1:{port}" if port else "Listening"
            )
            self._browser_connections.setText(
                f"{connections} active browser connection"
                f"{'s' if connections != 1 else ''}"
                if connections
                else "No browser is connected yet."
            )
        else:
            self._browser_status.setText(
                "The bridge is not running. Open Browser Assistant to restart it."
            )
            self._browser_connections.setText("Not connected.")

        folder = self._extension_dir()
        manifest = folder / "manifest.json"
        version = ""
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            version = str(data.get("version") or "")
        except (OSError, ValueError):
            version = ""
        text = f"Version {version} · {folder}" if version else "Extension files not found."
        self._browser_version.setText(text)
        self._about_extension.setText(text)

    def _extension_dir(self) -> Path:
        try:
            from integrations import registration

            return registration.extension_dir()
        except Exception:
            return project_root() / "BrowserExtension" / "IDMVideoAssistant"

    # ------------------------------------------------------------------ actions
    def _apply_search(self, text: str) -> None:
        query = text.strip().lower()
        any_visible = False
        for section in self._sections:
            any_visible = section.apply_search(query) or any_visible
        self._no_results.setVisible(bool(query) and not any_visible)

    def _browse(self) -> None:
        start = self._folder_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose download folder", start
        )
        if chosen:
            self._folder_edit.setText(chosen)

    def _open_download_folder(self) -> None:
        try:
            folder = ensure_download_dir(self._settings.download_dir)
        except OSError as exc:
            self.message.emit(f"The download folder could not be opened: {exc}")
            return
        self._open_path(folder)

    def _open_path(self, path: Path) -> None:
        path = Path(path)
        if not path.exists():
            self.message.emit(f"Not found: {path.name}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _create_backup(self) -> None:
        database = getattr(self._settings, "database", None)
        if database is None:
            self.message.emit("The database is unavailable.")
            return
        destination = (
            database_backup_dir()
            / f"IDM-backup-{datetime.now():%Y%m%d-%H%M%S}.sqlite3"
        )
        try:
            database.backup(destination)
        except Exception as exc:
            QMessageBox.warning(
                self, "Backup", f"The database backup could not be created:\n\n{exc}"
            )
            return
        self._backup_summary.setText(self._backup_text())
        self.message.emit(f"Backup created: {destination.name}")

    def _apply(self) -> None:
        folder_text = self._folder_edit.text().strip()
        if not folder_text:
            QMessageBox.warning(
                self, "Download folder", "Choose a folder for new downloads."
            )
            return
        try:
            folder = ensure_download_dir(folder_text)
        except OSError as exc:
            QMessageBox.warning(
                self, "Download folder", f"Could not use that folder:\n\n{exc}"
            )
            return

        selected_theme = str(self._theme_combo.currentData() or self._settings.theme)
        values = {
            "download_dir": str(folder),
            "max_concurrent": int(self._concurrent.value()),
            "connections_per_download": int(self._connections.value()),
            "speed_limit_kbps": int(self._speed.value()),
            "start_immediately": self._start_check.isChecked(),
            "restore_session": self._restore_check.isChecked(),
            "auto_retry": self._retry_check.isChecked(),
            "max_retries": int(self._max_retries.value()),
            "auto_resume_on_network": self._network_check.isChecked(),
            "confirm_delete": self._confirm_check.isChecked(),
            "show_toolbar": self._toolbar_check.isChecked(),
            "show_sidebar": self._sidebar_check.isChecked(),
            "show_download_list": self._list_check.isChecked(),
            "show_status_bar": self._status_check.isChecked(),
            "sidebar_collapsed": self._sidebar_collapsed_check.isChecked(),
            "ui_animations": self._animations_check.isChecked(),
            "update_notify": self._notify_update.isChecked(),
            "update_auto_check": self._update_auto.isChecked(),
            "update_check_interval_hours": int(self._update_interval.value()),
            "update_auto_download": self._update_download.isChecked(),
            "update_ask_before_install": self._update_ask.isChecked(),
            "update_channel": str(self._update_channel.currentData() or "stable"),
            "update_manifest_url": self._update_url.text().strip(),
            "update_publisher": self._update_publisher.text().strip(),
            "theme": selected_theme,
        }
        self._settings.update(values)
        self._settings.save()
        design.set_animations_enabled(bool(self._settings.ui_animations))
        self._theme.set_mode(selected_theme)
        self._rules_summary.setText(self._rules_text())
        self._refresh_runtime_info()
        self.settings_applied.emit()
        self.message.emit("Settings saved.")

    def _on_theme_changed(self) -> None:
        self._search_action.setIcon(
            icons.icon("search", self._theme.palette.text_faint, 16)
        )
        for button in self.findChildren(QPushButton):
            name = str(button.property("icon_name") or "")
            if not name:
                continue
            button.setIcon(
                icons.icon(name, self._theme.palette.text_muted, design.ICON_SIZE["sm"])
            )
        self._load_theme()
