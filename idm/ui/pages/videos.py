"""Video Downloads workspace for authorised direct media files."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QRect, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core.settings import AppSettings
from ...core.url_utils import format_eta, format_size, format_speed
from ...engine.manager import DownloadManager
from ...models.download_item import DownloadItem, DownloadStatus
from .. import design, icons
from ..components import NoticeBanner, icon_button
from ..theme import ThemeManager

_FILTERS = (
    ("all", "All"),
    ("downloading", "Downloading"),
    ("completed", "Completed"),
    ("paused", "Paused"),
    ("failed", "Failed"),
)
_SORTS = (
    ("newest", "Newest first"),
    ("name", "Name"),
    ("size", "Largest first"),
    ("progress", "Progress"),
)
_IN_PROGRESS = {
    DownloadStatus.QUEUED,
    DownloadStatus.CONNECTING,
    DownloadStatus.DOWNLOADING,
    DownloadStatus.RETRYING,
    DownloadStatus.PAUSING,
    DownloadStatus.STOPPING,
}


def _format_duration(seconds: int | None) -> str:
    if not seconds or seconds <= 0:
        return ""
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _domain_of(item: DownloadItem) -> str:
    if item.source_domain:
        return item.source_domain
    try:
        return urlsplit(item.url).hostname or ""
    except ValueError:
        return ""


def _status_state(item: DownloadItem) -> str:
    if item.status == DownloadStatus.COMPLETED:
        return "ok"
    if item.status == DownloadStatus.FAILED:
        return "error"
    if item.status in {DownloadStatus.PAUSED, DownloadStatus.STOPPED}:
        return "warn"
    if item.status == DownloadStatus.QUEUED:
        return "idle"
    return "active"


class VideoThumb(QWidget):
    """Stylised media header; shows only metadata IDM actually knows."""

    def __init__(self, theme: ThemeManager, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._duration = ""
        self._quality = ""
        self.setMinimumHeight(128)
        self.setMaximumHeight(144)

    def set_info(self, duration: str, quality: str) -> None:
        if duration == self._duration and quality == self._quality:
            return
        self._duration = duration
        self._quality = quality
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p = self._theme.palette
        rect = QRectF(self.rect()).adjusted(0, 0, -1, -1)

        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        accent = QColor(p.accent)
        gradient.setColorAt(0.0, QColor("#1B3159"))
        gradient.setColorAt(0.55, QColor("#122344"))
        gradient.setColorAt(1.0, QColor("#0A1529"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawRoundedRect(rect, design.RADIUS_PX["md"], design.RADIUS_PX["md"])

        painter.setPen(Qt.PenStyle.NoPen)
        glow = QColor(accent)
        glow.setAlpha(58)
        painter.setBrush(glow)
        painter.drawEllipse(QRectF(rect.right() - 92, rect.top() - 54, 168, 168))
        painter.setBrush(QColor(80, 140, 255, 30))
        painter.drawEllipse(QRectF(rect.left() - 46, rect.bottom() - 70, 150, 150))

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 36), 1))
        painter.drawEllipse(QRectF(rect.right() - 130, rect.top() - 18, 180, 180))

        center = rect.center()
        disc = QRectF(center.x() - 24, center.y() - 24, 48, 48)
        disc_fill = QColor(accent)
        disc_fill.setAlpha(230)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(disc_fill)
        painter.drawEllipse(disc)
        painter.setBrush(QColor(255, 255, 255, 34))
        painter.drawEllipse(disc.adjusted(-6, -6, 6, 6))
        painter.setBrush(disc_fill)
        painter.drawEllipse(disc)

        icon = icons.icon("play", "#FFFFFF", 20)
        icon.paint(
            painter,
            QRect(int(disc.left()), int(disc.top()), int(disc.width()), int(disc.height())),
            Qt.AlignmentFlag.AlignCenter,
            icon.Mode.Normal,
            icon.State.Off,
        )

        font = QFont(self.font())
        font.setPointSizeF(max(7.5, self.font().pointSizeF() - 1.0))
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        metrics = QFontMetrics(font)

        if self._duration:
            width = metrics.horizontalAdvance(self._duration) + 14
            chip = QRectF(rect.right() - width - 10, rect.bottom() - 28, width, 19)
            painter.setBrush(QColor(0, 0, 0, 135))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(chip, 5, 5)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(
                chip, int(Qt.AlignmentFlag.AlignCenter), self._duration
            )

        if self._quality:
            width = metrics.horizontalAdvance(self._quality) + 14
            chip = QRectF(rect.left() + 10, rect.top() + 10, width, 19)
            painter.setBrush(QColor(0, 0, 0, 105))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(chip, 5, 5)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(
                chip, int(Qt.AlignmentFlag.AlignCenter), self._quality
            )


class VideoCard(QFrame):
    """One media download with real progress, metadata and actions."""

    action = Signal(str, str)
    activated = Signal(str)

    def __init__(self, theme: ThemeManager, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._item: DownloadItem | None = None
        self.setObjectName("VideoCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Video download")
        self.setMinimumWidth(250)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(9)

        self._thumb = VideoThumb(theme, self)
        layout.addWidget(self._thumb)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        self._title = QLabel()
        self._title.setObjectName("VideoTitle")
        self._title.setWordWrap(True)
        self._title.setMaximumHeight(38)
        title_row.addWidget(self._title, 1)
        self._badge = QLabel()
        self._badge.setObjectName("VideoBadge")
        title_row.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(title_row)

        self._domain = QLabel()
        self._domain.setObjectName("VideoMeta")
        self._domain.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self._domain)

        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(8)
        self._progress = QProgressBar()
        self._progress.setObjectName("MiniProgress")
        self._progress.setRange(0, 1000)
        self._progress.setTextVisible(False)
        progress_row.addWidget(self._progress, 1)
        self._percent = QLabel()
        self._percent.setObjectName("VideoMeta")
        self._percent.setMinimumWidth(34)
        self._percent.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        progress_row.addWidget(self._percent)
        layout.addLayout(progress_row)

        self._detail = QLabel()
        self._detail.setObjectName("VideoMeta")
        layout.addWidget(self._detail)
        self._transfer = QLabel()
        self._transfer.setObjectName("VideoMeta")
        layout.addWidget(self._transfer)

        layout.addStretch(1)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 2, 0, 0)
        actions.setSpacing(2)
        self._toggle = self._action_button("resume", "Resume download")
        self._toggle.clicked.connect(self._toggle_download)
        self._file = self._action_button("play", "Open downloaded file")
        self._file.clicked.connect(lambda: self._emit("open_file"))
        self._folder = self._action_button("folder_open", "Open download folder")
        self._folder.clicked.connect(lambda: self._emit("open_folder"))
        self._copy = self._action_button("copy", "Copy media link")
        self._copy.clicked.connect(lambda: self._emit("copy"))
        self._delete = self._action_button(
            "delete", "Remove record (keeps the file)", theme.palette.danger
        )
        self._delete.clicked.connect(lambda: self._emit("delete"))
        for button in (self._toggle, self._file, self._folder, self._copy):
            actions.addWidget(button)
        divider = QFrame()
        divider.setObjectName("ActionDivider")
        divider.setFixedSize(1, 16)
        actions.addSpacing(4)
        actions.addWidget(divider)
        actions.addSpacing(4)
        actions.addWidget(self._delete)
        actions.addStretch(1)
        layout.addLayout(actions)

    def _action_button(
        self, name: str, tooltip: str, color: str | None = None
    ) -> QToolButton:
        button = icon_button(
            name, self._theme, tooltip, design.ICON_SIZE["md"], color
        )
        button.setFixedSize(30, 30)
        button.setAccessibleName(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        return button

    @property
    def download_id(self) -> str:
        return self._item.id if self._item is not None else ""

    def update_from(self, item: DownloadItem, metadata: dict | None) -> None:
        self._item = item
        metadata = metadata or {}
        title = item.page_title or item.filename
        self._title.setText(title)
        self._title.setToolTip(f"{item.url}\n{item.path}")
        self.setAccessibleName(f"{title} — {item.status.value}")

        quality = str(metadata.get("quality_label") or item.media_label or "")
        duration = _format_duration(metadata.get("duration_seconds"))
        self._thumb.set_info(duration, quality)
        self._thumb.setToolTip(
            "\n".join(
                part
                for part in (
                    title,
                    f"Quality: {quality}" if quality else "",
                    f"Duration: {duration}" if duration else "",
                    _domain_of(item),
                )
                if part
            )
        )

        domain = _domain_of(item)
        self._domain.setText(domain or "Direct download")
        self._badge.setText(item.status.value)
        self._badge.setProperty("state", _status_state(item))
        self._badge.style().unpolish(self._badge)
        self._badge.style().polish(self._badge)

        fraction = 1.0 if item.status == DownloadStatus.COMPLETED else (item.progress or 0.0)
        self._progress.setValue(int(max(0.0, min(1.0, fraction)) * 1000))
        if item.status == DownloadStatus.COMPLETED:
            self._percent.setText("100%")
        elif fraction:
            self._percent.setText(f"{round(fraction * 100)}%")
        else:
            self._percent.setText("—")

        parts: list[str] = []
        if item.total_bytes:
            parts.append(f"{format_size(item.downloaded_bytes)} of {format_size(item.total_bytes)}")
        elif item.downloaded_bytes:
            parts.append(format_size(item.downloaded_bytes))
        if item.connections:
            parts.append(f"{item.connections} connections")
        self._detail.setText("  ·  ".join(parts) if parts else "Size not reported yet")

        transfer: list[str] = []
        if item.is_active:
            if item.speed > 0:
                transfer.append(format_speed(item.speed))
            if item.eta is not None:
                transfer.append(f"{format_eta(item.eta)} left")
        elif item.status == DownloadStatus.QUEUED:
            transfer.append("Waiting for a download slot")
        elif item.status == DownloadStatus.PAUSED:
            transfer.append("Paused")
        elif item.status == DownloadStatus.STOPPED:
            transfer.append("Stopped")
        elif item.status == DownloadStatus.FAILED:
            transfer.append(item.error or "Download failed")
        elif item.status == DownloadStatus.COMPLETED and item.completed_at:
            transfer.append(f"Completed {item.completed_at:%d %b %Y, %H:%M}")
        self._transfer.setText("  ·  ".join(transfer))
        self._transfer.setVisible(bool(transfer))

        self._file.setEnabled(
            item.status == DownloadStatus.COMPLETED and Path(item.path).is_file()
        )
        self._folder.setEnabled(True)
        if item.can_pause:
            self._toggle.setIcon(icons.icon("pause", self._theme.palette.text_muted, 15))
            self._toggle.setToolTip("Pause download")
            self._toggle.setProperty("action", "pause")
        else:
            self._toggle.setIcon(icons.icon("resume", self._theme.palette.text_muted, 15))
            self._toggle.setToolTip("Resume download")
            self._toggle.setProperty("action", "resume")
        self._toggle.setVisible(item.can_pause or item.can_resume)
        self._toggle.setEnabled(item.can_pause or item.can_resume)

    def _toggle_download(self) -> None:
        action = str(self._toggle.property("action") or "resume")
        self._emit(action)

    def _emit(self, action: str) -> None:
        if self._item is not None:
            self.action.emit(action, self._item.id)

    def mouseDoubleClickEvent(self, event) -> None:
        if self._item is not None and event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self._item.id)
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event) -> None:
        if self._item is not None and event.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
            Qt.Key.Key_Space,
        ):
            self.activated.emit(self._item.id)
            event.accept()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event) -> None:
        item = self._item
        if item is None:
            return
        p = self._theme.palette
        menu = QMenu(self)
        menu.addAction(
            icons.icon("download", p.text_muted, 16), "Open transfer details"
        ).triggered.connect(lambda: self.activated.emit(item.id))
        menu.addSeparator()
        pause = menu.addAction(icons.icon("pause", p.text_muted, 16), "Pause")
        pause.setEnabled(item.can_pause)
        pause.triggered.connect(lambda: self.action.emit("pause", item.id))
        resume = menu.addAction(icons.icon("resume", p.text_muted, 16), "Resume")
        resume.setEnabled(item.can_resume)
        resume.triggered.connect(lambda: self.action.emit("resume", item.id))
        stop = menu.addAction(icons.icon("stop", p.text_muted, 16), "Stop")
        stop.setEnabled(item.can_stop)
        stop.triggered.connect(lambda: self.action.emit("stop", item.id))
        menu.addSeparator()
        open_file = menu.addAction(icons.icon("play", p.text_muted, 16), "Open file")
        open_file.setEnabled(
            item.status == DownloadStatus.COMPLETED and Path(item.path).is_file()
        )
        open_file.triggered.connect(lambda: self.action.emit("open_file", item.id))
        menu.addAction(
            icons.icon("folder_open", p.text_muted, 16), "Open folder"
        ).triggered.connect(lambda: self.action.emit("open_folder", item.id))
        menu.addAction(
            icons.icon("copy", p.text_muted, 16), "Copy link"
        ).triggered.connect(lambda: self.action.emit("copy", item.id))
        menu.addSeparator()
        menu.addAction(
            icons.icon("delete", p.danger, 16), "Delete record (keep file)"
        ).triggered.connect(lambda: self.action.emit("delete", item.id))
        menu.exec(event.globalPos())


class VideoDownloadsPage(QWidget):
    add_requested = Signal()
    guide_requested = Signal()
    item_activated = Signal(str)
    message = Signal(str)

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
        self._cards: dict[str, VideoCard] = {}
        self._visible_ids: list[str] = []
        self._metadata: dict[str, dict] = {}
        self._columns = 0
        self._layout_signature: tuple | None = None
        self._filter = "all"
        self.setObjectName("PageArea")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        banner = NoticeBanner(
            theme,
            "Direct video files only",
            "MP4, WebM and other media links you are authorised to download are "
            "supported. Pages on streaming platforms are not media files: IDM "
            "opens them in your browser instead of bypassing access controls.",
            "info",
        )
        learn = QPushButton("Read policy")
        learn.setObjectName("SubtleButton")
        learn.clicked.connect(self.guide_requested)
        banner.add_action(learn)
        root.addWidget(banner)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self._search = QLineEdit()
        self._search.setObjectName("SearchBox")
        self._search.setPlaceholderText("Search videos by title, file name or source…")
        self._search.setClearButtonEnabled(True)
        self._search.setMinimumWidth(180)
        self._search_icon = self._search.addAction(
            icons.icon("search", theme.palette.text_faint, 16),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self._search.textChanged.connect(self._on_search_changed)
        controls.addWidget(self._search, 1)

        self._sort = QComboBox()
        for key, label in _SORTS:
            self._sort.addItem(label, key)
        self._sort.currentIndexChanged.connect(lambda _index: self._refresh_view())
        controls.addWidget(self._sort)

        self._add_button = QPushButton("  Add Video URL")
        self._add_button.setObjectName("PrimaryButton")
        self._add_button.setIcon(icons.icon("add", "#FFFFFF", 16))
        self._add_button.clicked.connect(self.add_requested)
        controls.addWidget(self._add_button)
        root.addLayout(controls)

        filters = QHBoxLayout()
        filters.setSpacing(6)
        self._chips: dict[str, QPushButton] = {}
        for key, text in _FILTERS:
            chip = QPushButton(text)
            chip.setObjectName("ChipButton")
            chip.setCheckable(True)
            chip.setChecked(key == self._filter)
            chip.clicked.connect(lambda _checked=False, name=key: self._set_filter(name))
            self._chips[key] = chip
            filters.addWidget(chip)
        filters.addStretch(1)
        root.addLayout(filters)

        self._count_label = QLabel()
        self._count_label.setObjectName("PageSubtitle")
        root.addWidget(self._count_label)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("PageScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget()
        container.setObjectName("PageScrollBody")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(2, 2, 10, 8)
        container_layout.setSpacing(design.SPACING["lg"])
        self._grid = QGridLayout()
        self._grid.setHorizontalSpacing(design.SPACING["md"])
        self._grid.setVerticalSpacing(design.SPACING["md"])
        self._grid.setContentsMargins(0, 0, 0, 0)
        container_layout.addLayout(self._grid)
        self._empty = self._build_empty()
        container_layout.addWidget(self._empty)
        container_layout.addStretch(1)
        self._scroll.setWidget(container)
        self._container = container
        root.addWidget(self._scroll, 1)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(250)
        self._refresh_timer.timeout.connect(self._refresh_view)

        manager.download_added.connect(self._schedule_refresh)
        manager.download_updated.connect(self._schedule_refresh)
        manager.download_removed.connect(self._schedule_refresh)
        theme.changed.connect(self._on_theme_changed)
        self._refresh_view()

    def _build_empty(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(24, 40, 24, 40)
        layout.setSpacing(8)
        layout.addStretch(1)
        icon = QLabel()
        icon.setPixmap(icons.logo_pixmap(56))
        icon.setFixedSize(56, 56)
        icon.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignHCenter)
        self._empty_title = QLabel("No media downloads yet")
        self._empty_title.setObjectName("EmptyTitle")
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty_title)
        self._empty_text = QLabel(
            "Paste a direct MP4 or WebM link you are authorised to download. "
            "Restricted platform pages are opened in the browser instead."
        )
        self._empty_text.setObjectName("EmptyText")
        self._empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_text.setWordWrap(True)
        layout.addWidget(self._empty_text)
        self._empty_button = QPushButton("  Add Video URL")
        self._empty_button.setObjectName("EmptyAddButton")
        self._empty_button.setIcon(icons.icon("add", "#FFFFFF", 16))
        self._empty_button.clicked.connect(self.add_requested)
        layout.addWidget(self._empty_button, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
        return widget

    # ------------------------------------------------------------------ filtering
    def _on_search_changed(self, _text: str) -> None:
        self._refresh_view()

    def _set_filter(self, key: str) -> None:
        self._filter = key
        for name, chip in self._chips.items():
            chip.setChecked(name == key)
        self._refresh_view()

    def _accepted(self, item: DownloadItem) -> bool:
        if self._filter == "downloading" and item.status not in _IN_PROGRESS:
            return False
        if self._filter == "completed" and item.status != DownloadStatus.COMPLETED:
            return False
        if self._filter == "paused" and item.status not in {
            DownloadStatus.PAUSED,
            DownloadStatus.STOPPED,
        }:
            return False
        if self._filter == "failed" and item.status != DownloadStatus.FAILED:
            return False
        search = self._search.text().strip().lower()
        if search:
            haystack = "\n".join(
                (
                    item.page_title,
                    item.filename,
                    item.url,
                    item.source_domain,
                )
            ).lower()
            if search not in haystack:
                return False
        return True

    def _sorted(self, items: list[DownloadItem]) -> list[DownloadItem]:
        key = str(self._sort.currentData() or "newest")
        if key == "name":
            return sorted(items, key=lambda item: (item.page_title or item.filename).casefold())
        if key == "size":
            return sorted(
                items,
                key=lambda item: item.total_bytes or item.downloaded_bytes or 0,
                reverse=True,
            )
        if key == "progress":
            return sorted(items, key=lambda item: item.progress or 0.0, reverse=True)
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    # ------------------------------------------------------------------ data
    def _schedule_refresh(self, *_args) -> None:
        if self.isVisible():
            self._refresh_timer.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh_view()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._arrange_cards()

    def _refresh_view(self) -> None:
        database = getattr(self._settings, "database", None)
        metadata: dict[str, dict] = {}
        if database is not None:
            try:
                metadata = database.load_all_media_metadata()
            except Exception:
                metadata = {}
        self._metadata = metadata

        videos = [item for item in self._manager.items() if item.is_video]
        for item in videos:
            card = self._cards.get(item.id)
            if card is None:
                card = VideoCard(self._theme, self._container)
                card.action.connect(self._on_action)
                card.activated.connect(self.item_activated)
                self._cards[item.id] = card
            card.update_from(item, metadata.get(item.id))

        accepted = [item for item in videos if self._accepted(item)]
        visible = self._sorted(accepted)
        self._visible_ids = [item.id for item in visible]

        self._count_label.setText(
            f"{len(visible)} of {len(videos)} video download"
            f"{'s' if len(videos) != 1 else ''}"
            if videos
            else "No media downloads yet"
        )
        self._empty.setVisible(not visible)
        if not visible:
            if not videos:
                self._empty_title.setText("No media downloads yet")
                self._empty_text.setText(
                    "Paste a direct MP4 or WebM link you are authorised to download. "
                    "Restricted platform pages are opened in the browser instead."
                )
            else:
                self._empty_title.setText("No videos match")
                self._empty_text.setText(
                    "Change the search text or choose a different status filter."
                )
        self._empty_button.setVisible(not videos)
        self._arrange_cards()

        known = {item.id for item in videos}
        for download_id, card in list(self._cards.items()):
            if download_id not in known:
                self._grid.removeWidget(card)
                card.deleteLater()
                del self._cards[download_id]

    def _columns_for_width(self) -> int:
        width = max(
            self._scroll.viewport().width() if self._scroll is not None else 0,
            self.width(),
        )
        return max(1, min(5, width // 310))

    def _arrange_cards(self) -> None:
        if not hasattr(self, "_grid"):
            return
        columns = self._columns_for_width()
        cards = [
            self._cards[download_id]
            for download_id in self._visible_ids
            if download_id in self._cards
        ]
        signature = (columns, tuple(self._visible_ids))
        if signature == self._layout_signature:
            return
        self._layout_signature = signature
        if columns != self._columns:
            self._columns = columns
            for index in range(5):
                self._grid.setColumnStretch(index, 1 if index < columns else 0)
        for card in self._cards.values():
            self._grid.removeWidget(card)
        for index, card in enumerate(cards):
            card.setVisible(True)
            self._grid.addWidget(card, index // columns, index % columns)
        for card in self._cards.values():
            if card not in cards:
                card.setVisible(False)

    # ------------------------------------------------------------------ actions
    def _on_action(self, action: str, download_id: str) -> None:
        item = self._manager.get(download_id)
        if item is None:
            return
        if action == "pause":
            count = self._manager.pause([download_id])
            self.message.emit(
                "Download paused." if count else "The download could not be paused."
            )
        elif action == "resume":
            count = self._manager.resume([download_id])
            self.message.emit(
                "Download resumed." if count else "The download could not be resumed."
            )
        elif action == "stop":
            count = self._manager.stop([download_id])
            self.message.emit(
                "Download stopped." if count else "The download could not be stopped."
            )
        elif action == "open_file":
            path = Path(item.path)
            if path.is_file():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            else:
                self.message.emit("The completed file is no longer on disk.")
        elif action == "open_folder":
            folder = Path(item.folder)
            if folder.is_dir():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
            else:
                self.message.emit("The download folder no longer exists.")
        elif action == "copy":
            QGuiApplication.clipboard().setText(item.url)
            self.message.emit("Video link copied to the clipboard.")
        elif action == "delete":
            removed = self._manager.remove([download_id], delete_files=False)
            self.message.emit(
                f"Removed {removed} media record{'s' if removed != 1 else ''}. "
                "Files on disk were kept."
                if removed
                else "The media record could not be removed."
            )
            self._refresh_view()

    def _on_theme_changed(self) -> None:
        self._search_icon.setIcon(
            icons.icon("search", self._theme.palette.text_faint, 16)
        )
        self._refresh_view()
