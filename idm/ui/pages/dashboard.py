"""Premium dashboard with live transfer data and local activity."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...constants import APP_VERSION
from ...core.settings import AppSettings
from ...core.url_utils import format_size, format_speed
from ...engine.manager import DownloadManager
from ...models.download_item import DownloadItem, DownloadStatus
from .. import design, icons
from ..components import (
    ActivityChart,
    Card,
    PageScroll,
    ProgressRing,
    StatCard,
    section_label,
)
from ..theme import ThemeManager


class HeroCard(QFrame):
    """Gradient hero with a soft light treatment painted behind its content."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        radius = design.RADIUS_PX["lg"]
        clip = QPainterPath()
        clip.addRoundedRect(
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius
        )
        painter.setClipPath(clip)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 18))
        painter.drawEllipse(QRectF(self.width() - 214, -128, 340, 340))
        painter.setBrush(QColor(255, 255, 255, 10))
        painter.drawEllipse(QRectF(self.width() - 58, 34, 190, 190))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 30), 1))
        painter.drawEllipse(QRectF(self.width() - 268, 10, 224, 224))


class TransferRow(QFrame):
    activated = Signal(str)

    def __init__(
        self, theme: ThemeManager, item: DownloadItem, parent=None
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._item = item
        self.setObjectName("TransferRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{item.url}\n{item.path}")
        self.setMinimumHeight(62)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(5)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)

        icon_label = QLabel()
        icon_label.setFixedSize(30, 30)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tint = icons.category_color(item.category)
        icon_label.setPixmap(
            icons.category_icon(item.category, tint, 17).pixmap(17, 17)
        )
        icon_label.setStyleSheet(
            f"background-color: {theme.palette.chip_bg}; border-radius: 9px;"
        )
        top.addWidget(icon_label)

        name = QLabel(item.filename)
        name.setObjectName("TransferName")
        name.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        top.addWidget(name, 1)

        self._state = QLabel()
        self._state.setObjectName("TransferMeta")
        top.addWidget(self._state)

        layout.addLayout(top)

        self._progress = QProgressBar()
        self._progress.setObjectName("MiniProgress")
        self._progress.setRange(0, 1000)
        self._progress.setFixedHeight(5)
        self._progress.setTextVisible(False)
        layout.addWidget(self._progress)

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        self._meta = QLabel()
        self._meta.setObjectName("TransferMeta")
        meta_row.addWidget(self._meta, 1)
        self._percent = QLabel()
        self._percent.setObjectName("TransferMeta")
        meta_row.addWidget(self._percent)
        layout.addLayout(meta_row)

        self.update_from(item)

    def update_from(self, item: DownloadItem) -> None:
        self._item = item
        p = self._theme.palette
        progress = 1.0 if item.status == DownloadStatus.COMPLETED else (item.progress or 0.0)
        self._progress.setValue(int(progress * 1000))
        self._state.setText(item.status.value)
        if item.is_active:
            state_color = p.accent
        elif item.status == DownloadStatus.COMPLETED:
            state_color = p.success
        elif item.status in (DownloadStatus.PAUSED, DownloadStatus.STOPPED):
            state_color = p.warning
        elif item.status == DownloadStatus.FAILED:
            state_color = p.danger
        else:
            state_color = p.text_faint
        self._state.setStyleSheet(f"color: {state_color}; font-weight: 600;")
        self._percent.setText(f"{round(progress * 100)}%")
        parts: list[str] = []
        if item.is_active:
            if item.speed > 0:
                parts.append(format_speed(item.speed))
            if item.eta is not None:
                parts.append(f"{format_eta_short(item.eta)} left")
        elif item.status == DownloadStatus.QUEUED:
            parts.append("Waiting for a download slot")
        elif item.status == DownloadStatus.PAUSED:
            parts.append("Paused")
        elif item.status == DownloadStatus.RETRYING:
            parts.append("Retrying")
        if item.total_bytes:
            parts.append(
                f"{format_size(item.downloaded_bytes)} of {format_size(item.total_bytes)}"
            )
        elif item.downloaded_bytes:
            parts.append(format_size(item.downloaded_bytes))
        self._meta.setText("   ·   ".join(parts) if parts else item.status.value)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.activated.emit(self._item.id)
        super().mouseReleaseEvent(event)


def format_eta_short(seconds: float) -> str:
    total = max(0, int(seconds))
    if total >= 3600:
        return f"{total // 3600}h {total % 3600 // 60:02d}m"
    if total >= 60:
        return f"{total // 60}m {total % 60:02d}s"
    return f"{total}s"


def compact_path(path: str, limit: int = 40) -> str:
    path = str(path)
    if len(path) <= limit:
        return path
    parsed = Path(path)
    name = parsed.name or path
    anchor = parsed.anchor
    tail = f"{anchor}…{os.sep}{name}" if anchor else f"…{os.sep}{name}"
    if len(tail) <= limit:
        return tail
    return f"…{path[-(limit - 1):]}"


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
        self._transfer_rows: dict[str, TransferRow] = {}
        self._last_static_refresh = 0.0
        self._columns_stacked: bool | None = None
        self.setObjectName("PageArea")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        page = PageScroll(theme, self)
        root.addWidget(page)
        body = page.body

        body.addWidget(self._build_hero())

        stats = QGridLayout()
        stats.setSpacing(design.SPACING["md"])
        self._stats_grid = stats
        self._stats_columns = 0
        self._active_card = StatCard(
            theme, "Downloading", "0", "No transfers running", icon_name="download"
        )
        self._queue_card = StatCard(
            theme, "Queued", "0", "Waiting for a slot", icon_name="queue"
        )
        self._completed_card = StatCard(
            theme, "Completed", "0", "Stored in your library", icon_name="check_circle"
        )
        self._data_card = StatCard(
            theme, "Downloaded", "0 B", "Across completed files", icon_name="database"
        )
        self._active_card.set_accent(True)
        self._stat_cards = (
            self._active_card,
            self._queue_card,
            self._completed_card,
            self._data_card,
        )
        self._layout_stat_cards(4)
        body.addLayout(stats)

        columns = QHBoxLayout()
        columns.setSpacing(design.SPACING["md"])
        self._columns = columns

        self._active_panel = Card(theme, "Active transfers", "Updated automatically")
        manage = QPushButton("View all")
        manage.setObjectName("SubtleButton")
        manage.clicked.connect(lambda: self.navigate_requested.emit("all"))
        self._active_panel.add_action(manage)
        self._rows_layout = QVBoxLayout()
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(2)
        self._transfer_placeholder = QLabel(
            "No active transfers. Add a URL or resume a paused download."
        )
        self._transfer_placeholder.setObjectName("MutedCaption")
        self._transfer_placeholder.setWordWrap(True)
        self._rows_layout.addWidget(self._transfer_placeholder)
        self._rows_layout.addStretch(1)
        self._active_panel.add_layout(self._rows_layout)
        columns.addWidget(self._active_panel, 3)

        side = QVBoxLayout()
        side.setSpacing(design.SPACING["md"])
        self._storage_panel = Card(theme, "Storage", "Download folder usage")
        storage_row = QHBoxLayout()
        storage_row.setContentsMargins(0, 0, 0, 0)
        storage_row.setSpacing(design.SPACING["lg"])
        self._storage_ring = ProgressRing(theme)
        self._storage_ring.setFixedSize(112, 112)
        storage_row.addWidget(self._storage_ring)
        storage_text = QVBoxLayout()
        storage_text.setContentsMargins(0, 0, 0, 0)
        storage_text.setSpacing(2)
        self._storage_value = QLabel("—")
        self._storage_value.setObjectName("StatValue")
        self._storage_detail = QLabel()
        self._storage_detail.setObjectName("MutedCaption")
        self._storage_detail.setWordWrap(True)
        self._folder_label = QLabel()
        self._folder_label.setObjectName("MutedCaption")
        self._folder_label.setWordWrap(False)
        self._folder_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        storage_text.addWidget(self._storage_value)
        storage_text.addWidget(self._storage_detail)
        storage_text.addSpacing(2)
        storage_text.addWidget(self._folder_label)
        storage_text.addStretch(1)
        storage_row.addLayout(storage_text, 1)
        self._storage_panel.add_layout(storage_row)
        side.addWidget(self._storage_panel)

        self._quick_panel = Card(theme, "Quick actions", "Common destinations")
        quick = QGridLayout()
        quick.setHorizontalSpacing(design.SPACING["xs"])
        quick.setVerticalSpacing(design.SPACING["xs"])
        self._quick_buttons = {
            "folder": self._quick_button("folder_open", "Open download folder", self._open_folder),
            "queue": self._quick_button(
                "queue", "Manage queue", lambda: self.navigate_requested.emit("queued")
            ),
            "scheduler": self._quick_button(
                "scheduler", "Scheduler", lambda: self.navigate_requested.emit("scheduler")
            ),
            "videos": self._quick_button(
                "video", "Video downloads", lambda: self.navigate_requested.emit("video_downloads")
            ),
            "browser": self._quick_button(
                "globe",
                "Browser Assistant",
                lambda: self.navigate_requested.emit("browser_integration"),
            ),
            "settings": self._quick_button(
                "options", "Settings", lambda: self.navigate_requested.emit("settings")
            ),
        }
        order = ("folder", "queue", "scheduler", "videos", "browser", "settings")
        for index, key in enumerate(order):
            quick.addWidget(self._quick_buttons[key], index // 2, index % 2)
        quick.setColumnStretch(0, 1)
        quick.setColumnStretch(1, 1)
        self._quick_panel.add_layout(quick)
        side.addWidget(self._quick_panel)
        side.addStretch(1)
        columns.addLayout(side, 2)
        body.addLayout(columns)

        bottom = QHBoxLayout()
        bottom.setSpacing(design.SPACING["md"])
        self._activity_panel = Card(
            theme, "Activity", "Downloads recorded over the last two weeks"
        )
        self._chart = ActivityChart(theme)
        self._activity_panel.add(self._chart, 1)
        bottom.addWidget(self._activity_panel, 3)

        self._recent_panel = Card(theme, "Recent activity", "Newest notifications")
        open_notifications = QPushButton("Open notifications")
        open_notifications.setObjectName("SubtleButton")
        open_notifications.clicked.connect(
            lambda: self.navigate_requested.emit("notifications")
        )
        self._recent_panel.add_action(open_notifications)
        self._recent_list = QListWidget()
        self._recent_list.setObjectName("ActivityList")
        self._recent_list.setMinimumHeight(150)
        self._recent_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._recent_panel.add(self._recent_list, 1)
        bottom.addWidget(self._recent_panel, 2)
        body.addLayout(bottom)
        body.addStretch(1)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(350)
        self._refresh_timer.timeout.connect(self.refresh)

        self._static_timer = QTimer(self)
        self._static_timer.setInterval(15_000)
        self._static_timer.timeout.connect(self._refresh_static)
        self._static_timer.start()

        manager.download_added.connect(self._schedule_refresh)
        manager.download_updated.connect(self._schedule_refresh)
        manager.download_removed.connect(self._schedule_refresh)
        manager.stats_changed.connect(self._schedule_refresh)
        manager.queue_changed.connect(self._schedule_refresh)
        theme.changed.connect(self._on_theme_changed)
        self.refresh()

    # ------------------------------------------------------------------ construction
    def _build_hero(self) -> QFrame:
        hero = HeroCard()
        hero.setObjectName("HeroCard")
        layout = QHBoxLayout(hero)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(design.SPACING["lg"])

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(3)
        eyebrow = QLabel(f"IDM {APP_VERSION}")
        eyebrow.setObjectName("HeroEyebrow")
        title = QLabel("Everything is ready.")
        title.setObjectName("HeroTitle")
        title.setWordWrap(True)
        self._hero_title = title
        subtitle = QLabel(
            "Add a direct link, resume a transfer or check the browser assistant."
        )
        subtitle.setObjectName("HeroText")
        subtitle.setWordWrap(True)
        subtitle.setMaximumWidth(560)
        text.addWidget(eyebrow)
        text.addWidget(title)
        text.addWidget(subtitle)
        layout.addLayout(text, 1)

        numbers = QHBoxLayout()
        numbers.setContentsMargins(0, 0, 0, 0)
        numbers.setSpacing(design.SPACING["xl"])
        self._hero_numbers = QWidget()
        self._hero_numbers.setLayout(numbers)
        self._hero_speed = QLabel("0 B/s")
        self._hero_speed.setObjectName("HeroStatValue")
        self._hero_active = QLabel("0 active")
        self._hero_active.setObjectName("HeroStatLabel")
        speed_box = QVBoxLayout()
        speed_box.setSpacing(0)
        speed_box.addWidget(self._hero_speed)
        speed_box.addWidget(self._hero_active)
        numbers.addLayout(speed_box)

        self._hero_limit = QLabel("Unlimited")
        self._hero_limit.setObjectName("HeroStatValue")
        limit_label = QLabel("SPEED LIMIT")
        limit_label.setObjectName("HeroStatLabel")
        limit_box = QVBoxLayout()
        limit_box.setSpacing(0)
        limit_box.addWidget(self._hero_limit)
        limit_box.addWidget(limit_label)
        numbers.addLayout(limit_box)
        layout.addWidget(self._hero_numbers)

        self._add_button = QPushButton("  Add URL")
        self._add_button.setObjectName("HeroPrimary")
        self._add_button.setIcon(icons.icon("add", self._theme.palette.accent_pressed, 16))
        self._add_button.setIconSize(QSize(16, 16))
        self._add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_button.clicked.connect(self.add_requested)
        layout.addWidget(self._add_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self._resume_button = QPushButton("Resume All")
        self._resume_button.setObjectName("HeroButton")
        self._resume_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._resume_button.clicked.connect(self._resume_all)
        layout.addWidget(self._resume_button, 0, Qt.AlignmentFlag.AlignVCenter)
        return hero

    def _quick_button(self, icon_name: str, text: str, callback) -> QPushButton:
        button = QPushButton(f"  {text}")
        button.setObjectName("QuickAction")
        button.setIcon(icons.icon(icon_name, self._theme.palette.text_muted, 16))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(callback)
        button.setProperty("icon_name", icon_name)
        return button

    def _refresh_hero_icons(self) -> None:
        from PySide6.QtCore import QSize

        p = self._theme.palette
        self._add_button.setIcon(
            icons.icon("add", p.accent_pressed, design.ICON_SIZE["md"])
        )
        self._add_button.setIconSize(QSize(design.ICON_SIZE["md"], design.ICON_SIZE["md"]))
        for button in self._quick_buttons.values():
            button.setIcon(
                icons.icon(str(button.property("icon_name")), p.text_muted, design.ICON_SIZE["md"])
            )

    # ------------------------------------------------------------------ actions
    def _resume_all(self) -> None:
        count = self._manager.resume_all()
        self._show_result(
            f"Resumed {count} download{'s' if count != 1 else ''}."
            if count
            else "There are no paused downloads to resume."
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

    def _on_transfer_activated(self, download_id: str) -> None:
        if download_id:
            self.item_activated.emit(download_id)

    # ------------------------------------------------------------------ data
    def _schedule_refresh(self, *_args) -> None:
        if self.isVisible():
            self._refresh_timer.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._last_static_refresh = 0.0
        self.refresh()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        width = self.width()
        self._hero_numbers.setVisible(width >= 940)
        self._resume_button.setVisible(width >= 880)
        self._layout_stat_cards(4 if width >= 800 else 2)
        self._layout_columns(stacked=width < 980)

    def _layout_stat_cards(self, columns: int) -> None:
        columns = max(1, min(4, columns))
        if columns == self._stats_columns:
            return
        self._stats_columns = columns
        for card in self._stat_cards:
            self._stats_grid.removeWidget(card)
        for index, card in enumerate(self._stat_cards):
            self._stats_grid.addWidget(card, index // columns, index % columns)
        for column in range(4):
            self._stats_grid.setColumnStretch(column, 1 if column < columns else 0)

    def _layout_columns(self, stacked: bool) -> None:
        if stacked == self._columns_stacked:
            return
        self._columns_stacked = stacked
        self._columns.setDirection(
            QBoxLayout.Direction.TopToBottom
            if stacked
            else QBoxLayout.Direction.LeftToRight
        )
        self._columns.setStretch(0, 0 if stacked else 3)
        self._columns.setStretch(1, 0 if stacked else 2)

    def refresh(self, *_args) -> None:
        items = self._manager.items()
        active = [item for item in items if item.is_active]
        queued = [item for item in items if item.status == DownloadStatus.QUEUED]
        completed = [item for item in items if item.status == DownloadStatus.COMPLETED]
        total_bytes = sum(
            int(item.total_bytes or item.downloaded_bytes) for item in completed
        )
        speed = self._manager.total_speed

        if active:
            self._hero_title.setText(
                f"{len(active)} transfer{'s' if len(active) != 1 else ''} in progress."
            )
        elif queued:
            self._hero_title.setText("Your queue is waiting.")
        elif items:
            self._hero_title.setText("Everything is up to date.")
        else:
            self._hero_title.setText("Everything is ready.")

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
        self._hero_speed.setText(format_speed(speed) if speed > 0 else "0 B/s")
        self._hero_active.setText(f"{len(active)} active")
        limit = int(self._settings.speed_limit_kbps)
        self._hero_limit.setText(f"{limit} KB/s" if limit else "Unlimited")
        self._resume_button.setEnabled(any(item.can_resume for item in items))
        self._rebuild_transfers(items, active, queued)
        if self.isVisible():
            self._refresh_static()

    def _rebuild_transfers(
        self,
        items: list[DownloadItem],
        active: list[DownloadItem],
        queued: list[DownloadItem],
    ) -> None:
        del items
        visible = list(
            sorted(
                active + queued,
                key=lambda item: (
                    item.status != DownloadStatus.DOWNLOADING,
                    item.filename.lower(),
                ),
            )[:6]
        )
        visible_ids = {item.id for item in visible}
        for download_id, row in list(self._transfer_rows.items()):
            if download_id not in visible_ids:
                self._rows_layout.removeWidget(row)
                row.deleteLater()
                del self._transfer_rows[download_id]

        self._transfer_placeholder.setVisible(not visible)
        for index, item in enumerate(visible):
            row = self._transfer_rows.get(item.id)
            if row is None:
                row = TransferRow(self._theme, item, self._active_panel)
                row.activated.connect(self._on_transfer_activated)
                self._transfer_rows[item.id] = row
                self._rows_layout.insertWidget(index + 1, row)
            else:
                row.update_from(item)
                if self._rows_layout.indexOf(row) != index + 1:
                    self._rows_layout.removeWidget(row)
                    self._rows_layout.insertWidget(index + 1, row)

    def _refresh_static(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_static_refresh < 5.0:
            return
        self._last_static_refresh = now
        database = getattr(self._settings, "database", None)
        if database is not None:
            try:
                activity = database.daily_activity(14)
            except Exception:
                activity = []
            self._chart.set_data(activity)
            try:
                notifications = database.load_notifications(limit=6)
            except Exception:
                notifications = []
        else:
            self._chart.set_data([])
            notifications = []

        self._recent_list.clear()
        if not notifications:
            placeholder = QListWidgetItem(
                "Completed and failed transfers appear here."
            )
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._recent_list.addItem(placeholder)
        for record in notifications:
            prefix = "" if record.get("read_at") else "●  "
            text = f"{prefix}{record.get('title', '')}"
            if record.get("message"):
                text += f"\n{record['message']}"
            self._recent_list.addItem(QListWidgetItem(text))

        self._folder_label.setText(compact_path(self._settings.download_dir))
        self._folder_label.setToolTip(self._settings.download_dir)
        try:
            usage = shutil.disk_usage(self._settings.download_dir)
        except OSError:
            self._storage_value.setText("—")
            self._storage_detail.setText("Storage information is unavailable.")
            self._storage_ring.set_value(0.0)
            return
        used_fraction = 0.0 if usage.total <= 0 else 1.0 - usage.free / usage.total
        self._storage_ring.set_value(used_fraction)
        self._storage_value.setText(f"{format_size(usage.free)} free")
        self._storage_detail.setText(
            f"{round(used_fraction * 100)}% of {format_size(usage.total)} is in use"
        )

    def _on_theme_changed(self) -> None:
        self._refresh_hero_icons()
        self.refresh()
