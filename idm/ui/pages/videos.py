"""Video Downloads workspace for authorised direct media files."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...core.settings import AppSettings
from ...engine.manager import DownloadManager
from ...models.download_item import DownloadItem, DownloadStatus
from ...models.video_model import (
    COLUMN_ETA,
    COLUMN_FILENAME,
    COLUMN_FORMAT,
    COLUMN_PROGRESS,
    COLUMN_SIZE,
    COLUMN_SOURCE,
    COLUMN_SPEED,
    COLUMN_STATUS,
    COLUMN_TITLE,
    VideoTableModel,
)
from .. import icons
from ..delegates import ProgressDelegate, StatusDelegate, TextDelegate, ValueDelegate
from ..theme import ThemeManager
from .common import Card, NoticeBanner, PageScroll


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
        self.setObjectName("PageArea")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

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
        layout.addWidget(banner)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self._add_button = QPushButton("  Add Video URL")
        self._add_button.setObjectName("PrimaryButton")
        self._add_button.setIcon(icons.icon("add", "#FFFFFF", 16))
        self._add_button.clicked.connect(self.add_requested)
        actions.addWidget(self._add_button)

        self._pause_button = QPushButton("Pause")
        self._pause_button.clicked.connect(self._pause_selected)
        self._resume_button = QPushButton("Resume")
        self._resume_button.clicked.connect(self._resume_selected)
        self._stop_button = QPushButton("Stop")
        self._stop_button.clicked.connect(self._stop_selected)
        self._file_button = QPushButton("Open File")
        self._file_button.clicked.connect(lambda: self._open_selected(mode="file"))
        self._folder_button = QPushButton("Open Folder")
        self._folder_button.clicked.connect(lambda: self._open_selected(mode="folder"))
        self._delete_button = QPushButton("Delete Record")
        self._delete_button.setObjectName("DangerButton")
        self._delete_button.clicked.connect(self._delete_selected)
        for button in (
            self._pause_button,
            self._resume_button,
            self._stop_button,
            self._file_button,
            self._folder_button,
            self._delete_button,
        ):
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)

        card = Card(theme)
        card.body.setContentsMargins(0, 0, 0, 0)
        self._stack = QStackedWidget()
        self._table = self._build_table()
        self._empty = self._build_empty()
        self._stack.addWidget(self._table)
        self._stack.addWidget(self._empty)
        card.add(self._stack, 1)
        layout.addWidget(card, 1)

        self._model = VideoTableModel(manager, self)
        self._table.setModel(self._model)
        self._configure_columns()
        self._table.selectionModel().selectionChanged.connect(self._update_actions)
        self._table.doubleClicked.connect(self._on_double_click)
        self._table.customContextMenuRequested.connect(self._show_menu)

        manager.download_added.connect(self._on_rows_changed)
        manager.download_updated.connect(self._update_actions)
        manager.download_removed.connect(self._on_rows_changed)
        theme.changed.connect(self._on_theme_changed)
        self._update_actions()

    def _build_table(self) -> QTableView:
        table = QTableView()
        table.setObjectName("VideoTable")
        table.setFrameShape(QFrame.Shape.NoFrame)
        table.setShowGrid(False)
        table.setAlternatingRowColors(False)
        table.setWordWrap(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(50)
        header = table.horizontalHeader()
        header.setFixedHeight(34)
        header.setHighlightSections(False)
        header.setSectionsClickable(False)
        header.setStretchLastSection(False)

        table.setItemDelegateForColumn(
            COLUMN_TITLE, TextDelegate(self._theme, table, strong=True)
        )
        table.setItemDelegateForColumn(
            COLUMN_FILENAME, TextDelegate(self._theme, table, muted=True)
        )
        table.setItemDelegateForColumn(
            COLUMN_FORMAT, TextDelegate(self._theme, table, muted=True)
        )
        table.setItemDelegateForColumn(COLUMN_PROGRESS, ProgressDelegate(self._theme, table))
        table.setItemDelegateForColumn(COLUMN_STATUS, StatusDelegate(self._theme, table))
        table.setItemDelegateForColumn(
            COLUMN_SOURCE, TextDelegate(self._theme, table, muted=True)
        )
        value = ValueDelegate(self._theme, table)
        for column in (COLUMN_SIZE, COLUMN_SPEED, COLUMN_ETA):
            table.setItemDelegateForColumn(column, value)
        return table

    def _configure_columns(self) -> None:
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(COLUMN_TITLE, QHeaderView.ResizeMode.Stretch)
        widths = {
            COLUMN_FILENAME: 168,
            COLUMN_FORMAT: 70,
            COLUMN_SIZE: 82,
            COLUMN_PROGRESS: 142,
            COLUMN_SPEED: 96,
            COLUMN_ETA: 82,
            COLUMN_STATUS: 108,
            COLUMN_SOURCE: 128,
        }
        for column, width in widths.items():
            self._table.setColumnWidth(column, width)
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)

    def _build_empty(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(8)
        layout.addStretch(1)
        icon = QLabel()
        icon.setPixmap(icons.logo_pixmap(56))
        icon.setFixedSize(56, 56)
        icon.setScaledContents(True)
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignHCenter)
        title = QLabel("No media downloads yet")
        title.setObjectName("EmptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        hint = QLabel(
            "Paste a direct MP4 or WebM link you are authorised to download. "
            "Restricted platform pages are opened in the browser instead."
        )
        hint.setObjectName("EmptyText")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        button = QPushButton("  Add Video URL")
        button.setObjectName("PrimaryButton")
        button.setIcon(icons.icon("add", "#FFFFFF", 16))
        button.clicked.connect(self.add_requested)
        layout.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
        return widget

    # ------------------------------------------------------------------ state
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._model.refresh()
        self._on_rows_changed()

    def _on_rows_changed(self, *_args) -> None:
        self._stack.setCurrentWidget(
            self._table if self._model.rowCount() else self._empty
        )
        self._update_actions()

    def _update_actions(self, *_args) -> None:
        items = self._selected_items()
        self._pause_button.setEnabled(any(item.can_pause for item in items))
        self._resume_button.setEnabled(any(item.can_resume for item in items))
        self._stop_button.setEnabled(any(item.can_stop for item in items))
        self._file_button.setEnabled(
            len(items) == 1 and items[0].status == DownloadStatus.COMPLETED
        )
        self._folder_button.setEnabled(bool(items))
        self._delete_button.setEnabled(bool(items))

    def _selected_items(self) -> list[DownloadItem]:
        selection = self._table.selectionModel()
        if selection is None:
            return []
        items = []
        seen = set()
        for index in selection.selectedRows():
            item = self._model.item_at(index.row())
            if item is not None and item.id not in seen:
                seen.add(item.id)
                items.append(item)
        return items

    # ------------------------------------------------------------------ actions
    def _pause_selected(self) -> None:
        items = self._selected_items()
        count = self._manager.pause([item.id for item in items])
        self.message.emit(
            f"Paused {count} media download{'s' if count != 1 else ''}."
            if count
            else "The selected downloads cannot be paused."
        )

    def _resume_selected(self) -> None:
        items = self._selected_items()
        count = self._manager.resume([item.id for item in items])
        self.message.emit(
            f"Resumed {count} media download{'s' if count != 1 else ''}."
            if count
            else "The selected downloads cannot be resumed."
        )

    def _stop_selected(self) -> None:
        items = self._selected_items()
        count = self._manager.stop([item.id for item in items])
        self.message.emit(
            f"Stopped {count} media download{'s' if count != 1 else ''}."
            if count
            else "The selected downloads cannot be stopped."
        )

    def _open_selected(self, mode: str) -> None:
        items = self._selected_items()
        if not items:
            return
        item = items[0]
        if mode == "file":
            path = Path(item.path)
            if path.is_file():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            else:
                self.message.emit("The completed file is no longer on disk.")
            return
        folder = Path(item.folder)
        if folder.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        else:
            self.message.emit("The download folder no longer exists.")

    def _delete_selected(self) -> None:
        items = self._selected_items()
        if not items:
            return
        removed = self._manager.remove([item.id for item in items], delete_files=False)
        self.message.emit(
            f"Removed {removed} media record{'s' if removed != 1 else ''}. "
            "Files on disk were kept."
        )

    def _on_double_click(self, index) -> None:
        item = self._model.item_at(index.row())
        if item is None:
            return
        if item.status == DownloadStatus.COMPLETED:
            self._open_selected(mode="file")
        else:
            self.item_activated.emit(item.id)

    def _show_menu(self, position) -> None:
        index = self._table.indexAt(position)
        if not index.isValid():
            return
        if not self._table.selectionModel().isSelected(index):
            self._table.selectRow(index.row())
        item = self._model.item_at(index.row())
        if item is None:
            return
        p = self._theme.palette
        menu = QMenu(self)
        progress = menu.addAction(
            icons.icon("download", p.text_muted, 16), "Download progress"
        )
        progress.triggered.connect(lambda: self.item_activated.emit(item.id))
        menu.addSeparator()
        pause = menu.addAction(icons.icon("pause", p.text_muted, 16), "Pause")
        pause.setEnabled(item.can_pause)
        pause.triggered.connect(self._pause_selected)
        resume = menu.addAction(icons.icon("resume", p.text_muted, 16), "Resume")
        resume.setEnabled(item.can_resume)
        resume.triggered.connect(self._resume_selected)
        stop = menu.addAction(icons.icon("stop", p.text_muted, 16), "Stop")
        stop.setEnabled(item.can_stop)
        stop.triggered.connect(self._stop_selected)
        menu.addSeparator()
        open_file = menu.addAction(
            icons.icon("play", p.text_muted, 16), "Open file"
        )
        open_file.setEnabled(item.status == DownloadStatus.COMPLETED and Path(item.path).is_file())
        open_file.triggered.connect(lambda: self._open_selected(mode="file"))
        open_folder = menu.addAction(
            icons.icon("folder_open", p.text_muted, 16), "Open folder"
        )
        open_folder.triggered.connect(lambda: self._open_selected(mode="folder"))
        copy = menu.addAction(icons.icon("copy", p.text_muted, 16), "Copy link")
        copy.triggered.connect(lambda: self._copy(item))
        menu.addSeparator()
        remove = menu.addAction(
            icons.icon("delete", p.danger, 16), "Delete record (keep file)"
        )
        remove.triggered.connect(self._delete_selected)
        menu.exec(self._table.viewport().mapToGlobal(position))

    def _copy(self, item: DownloadItem) -> None:
        QGuiApplication.clipboard().setText(item.url)
        self.message.emit("Video link copied to the clipboard.")

    def _on_theme_changed(self) -> None:
        self._table.viewport().update()
        self._table.update()
