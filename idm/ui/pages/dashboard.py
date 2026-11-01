"""Next-generation dashboard with live figures and quick actions."""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
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

from ...constants import APP_VERSION
from ...core.settings import AppSettings
from ...core.url_utils import format_size, format_speed
from ...engine.manager import DownloadManager
from ...models.download_item import DownloadItem, DownloadStatus
from .. import icons
from ..theme import ThemeManager
from .common import Card, NoticeBanner, PageScroll, StatCard, section_label


class DashboardPage(QWidget):
    add_requested = Signal()
    navigate_requested = Signal(str)
    item_activated = Signal(str)

    def __init__(
        self,
        theme: ThemeManager,
        manager: DownloadManager,
        settings: AppSettings,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._manager = manager
        self._settings = settings
        self.setObjectName("PageArea")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        page = PageScroll(theme, self)
        root.addWidget(page)
        body = page.body

        banner = NoticeBanner(
            theme,
            f"IDM {APP_VERSION} · Ready to download",
            "Direct HTTP and HTTPS transfers, resumable segments and verified "
            "media downloads. Restricted platform pages can be opened in your "
            "browser instead.",
            "info",
        )
        body.addWidget(banner)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self._add_button = QPushButton("  Add URL")
        self._add_button.setObjectName("PrimaryButton")
        self._add_button.setIcon(icons.icon("add", "#FFFFFF", 16))
        self._add_button.clicked.connect(self.add_requested)
        self._resume_button = QPushButton("Resume All")
        self._resume_button.clicked.connect(self._resume_all)
        self._pause_button = QPushButton("Pause All")
        self._pause_button.clicked.connect(self._pause_all)
        self._folder_button = QPushButton("Open Downloads Folder")
        self._folder_button.clicked.connect(self._open_folder)
        self._videos_button = QPushButton("Video Downloads")
        self._videos_button.clicked.connect(
            lambda: self.navigate_requested.emit("video_downloads")
        )
        for button in (
            self._add_button,
            self._resume_button,
            self._pause_button,
            self._folder_button,
            self._videos_button,
        ):
            actions.addWidget(button)
        actions.addStretch(1)
        body.addLayout(actions)

        stats = QGridLayout()
        stats.setHorizontalSpacing(10)
        stats.setVerticalSpacing(10)
        self._active_card = StatCard(theme, "Active now", "0", "No transfers running")
        self._queue_card = StatCard(theme, "Queued", "0", "Waiting for a slot")
        self._completed_card = StatCard(theme, "Completed", "0", "Stored in your library")
        self._data_card = StatCard(theme, "Downloaded", "0 B", "Across completed files")
        self._active_card.set_accent(True)
        for column, card in enumerate(
            (self._active_card, self._queue_card, self._completed_card, self._data_card)
        ):
            stats.addWidget(card, 0, column)
            stats.setColumnStretch(column, 1)
        body.addLayout(stats)

        columns = QHBoxLayout()
        columns.setSpacing(10)

        self._active_card_panel = Card(theme, "In progress", "Live transfers and the queue")
        self._activity_list = QListWidget()
        self._activity_list.setObjectName("ActivityList")
        self._activity_list.setMinimumHeight(168)
        self._activity_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._activity_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._activity_list.itemDoubleClicked.connect(self._on_activity_activated)
        self._active_card_panel.add(self._activity_list, 1)
        manage = QPushButton("Manage all downloads")
        manage.setObjectName("SubtleButton")
        manage.clicked.connect(lambda: self.navigate_requested.emit("all"))
        self._active_card_panel.body.addWidget(manage, 0, Qt.AlignmentFlag.AlignLeft)
        columns.addWidget(self._active_card_panel, 3)

        self._recent_card = Card(theme, "Recent activity", "The newest notifications")
        self._recent_list = QListWidget()
        self._recent_list.setObjectName("ActivityList")
        self._recent_list.setMinimumHeight(168)
        self._recent_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._recent_card.add(self._recent_list, 1)
        recent_button = QPushButton("Open notifications")
        recent_button.setObjectName("SubtleButton")
        recent_button.clicked.connect(
            lambda: self.navigate_requested.emit("notifications")
        )
        self._recent_card.body.addWidget(recent_button, 0, Qt.AlignmentFlag.AlignLeft)
        columns.addWidget(self._recent_card, 2)
        body.addLayout(columns)

        system_card = Card(theme, "System", "Storage and transfer configuration")
        system_layout = QGridLayout()
        system_layout.setHorizontalSpacing(18)
        system_layout.setVerticalSpacing(5)
        self._folder_label = QLabel()
        self._folder_label.setObjectName("StatDetail")
        self._space_label = QLabel()
        self._space_label.setObjectName("StatDetail")
        self._speed_label = QLabel()
        self._speed_label.setObjectName("StatDetail")
        self._connection_label = QLabel()
        self._connection_label.setObjectName("StatDetail")
        for row, (title, widget) in enumerate(
            (
                ("Download folder", self._folder_label),
                ("Free space", self._space_label),
                ("Speed limit", self._speed_label),
                ("Connections per download", self._connection_label),
            )
        ):
            label = QLabel(title)
            label.setObjectName("StatLabel")
            system_layout.addWidget(label, row, 0)
            system_layout.addWidget(widget, row, 1)
        system_layout.setColumnStretch(1, 1)
        system_card.add_layout(system_layout)
        body.addWidget(section_label("Overview"))
        body.addWidget(system_card)
        body.addStretch(1)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(350)
        self._refresh_timer.timeout.connect(self.refresh)

        manager.download_added.connect(self._schedule_refresh)
        manager.download_updated.connect(self._schedule_refresh)
        manager.download_removed.connect(self._schedule_refresh)
        manager.stats_changed.connect(self._schedule_refresh)
        manager.queue_changed.connect(self._schedule_refresh)
        theme.changed.connect(self.refresh)
        self.refresh()

    # ------------------------------------------------------------------ actions
    def _resume_all(self) -> None:
        count = self._manager.resume_all()
        self._show_result(
            f"Resumed {count} download{'s' if count != 1 else ''}."
            if count
            else "There are no paused downloads to resume."
        )

    def _pause_all(self) -> None:
        count = self._manager.pause_all()
        self._show_result(
            f"Paused {count} download{'s' if count != 1 else ''}."
            if count
            else "There are no active downloads to pause."
        )

    def _open_folder(self) -> None:
        folder = Path(self._settings.download_dir)
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            self._show_result("The download folder could not be opened.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _show_result(self, message: str) -> None:
        parent = self.window()
        status_bar = getattr(parent, "_status_bar", None)
        if status_bar is not None:
            status_bar.show_message(message)

    def _on_activity_activated(self, item: QListWidgetItem) -> None:
        download_id = item.data(Qt.ItemDataRole.UserRole)
        if download_id:
            self.item_activated.emit(str(download_id))

    # ------------------------------------------------------------------ data
    def _schedule_refresh(self, *_args) -> None:
        if self.isVisible():
            self._refresh_timer.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def refresh(self, *_args) -> None:
        items = self._manager.items()
        active = [item for item in items if item.is_active]
        queued = [item for item in items if item.status == DownloadStatus.QUEUED]
        completed = [item for item in items if item.status == DownloadStatus.COMPLETED]
        total_bytes = sum(
            int(item.total_bytes or item.downloaded_bytes)
            for item in completed
        )
        speed = self._manager.total_speed

        self._active_card.set_value(
            str(len(active)),
            f"{format_speed(speed)} total" if speed > 0 else "Idle",
        )
        self._queue_card.set_value(str(len(queued)), "Waiting for a slot")
        self._completed_card.set_value(str(len(completed)), "Files are kept on disk")
        self._data_card.set_value(
            format_size(total_bytes) if total_bytes else "0 B",
            f"{len(items)} download{'s' if len(items) != 1 else ''} recorded",
        )
        self._resume_button.setEnabled(
            any(item.can_resume for item in items)
        )
        self._pause_button.setEnabled(any(item.can_pause for item in items))

        self._activity_list.clear()
        running = sorted(
            [item for item in items if item.is_in_progress],
            key=lambda item: (item.status != DownloadStatus.DOWNLOADING, item.filename.lower()),
        )[:8]
        if not running:
            placeholder = QListWidgetItem(
                "No active transfers. Add a URL or resume a paused download."
            )
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._activity_list.addItem(placeholder)
        for item in running:
            progress = item.progress
            if item.status == DownloadStatus.QUEUED:
                detail = "Queued"
            elif progress is None:
                detail = item.status.value
            else:
                detail = f"{round(progress * 100)}% · {format_speed(item.speed)}"
            entry = QListWidgetItem(f"{item.filename}\n{item.status.value}   ·   {detail}")
            entry.setData(Qt.ItemDataRole.UserRole, item.id)
            entry.setToolTip(self._tooltip(item))
            self._activity_list.addItem(entry)

        self._recent_list.clear()
        notifications = []
        database = getattr(self._settings, "database", None)
        if database is not None:
            try:
                notifications = database.load_notifications(limit=6)
            except Exception:
                notifications = []
        if not notifications:
            placeholder = QListWidgetItem("Completed and failed transfers appear here.")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._recent_list.addItem(placeholder)
        for record in notifications:
            prefix = "" if record.get("read_at") else "●  "
            text = f"{prefix}{record.get('title', '')}"
            if record.get("message"):
                text += f"\n{record['message']}"
            self._recent_list.addItem(QListWidgetItem(text))

        self._folder_label.setText(self._settings.download_dir)
        self._folder_label.setToolTip(self._settings.download_dir)
        try:
            usage = shutil.disk_usage(self._settings.download_dir)
            self._space_label.setText(
                f"{format_size(usage.free)} free of {format_size(usage.total)}"
            )
        except OSError:
            self._space_label.setText("Unavailable")
        limit = int(self._settings.speed_limit_kbps)
        self._speed_label.setText(
            f"{limit} KB/s" if limit else "Unlimited"
        )
        self._connection_label.setText(
            f"{int(self._settings.connections_per_download)} per download"
        )

    @staticmethod
    def _tooltip(item: DownloadItem) -> str:
        lines = [item.url]
        if item.page_url:
            lines.append(f"From: {item.page_url}")
        lines.append(str(item.path))
        return "\n".join(lines)
