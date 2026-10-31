"""Queue management dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.url_utils import format_size
from ...engine.manager import DownloadManager
from .. import icons
from ..theme import ThemeManager
from .common import (
    BaseDialog,
    make_divider,
    make_header,
    primary_button,
    secondary_button,
)


class QueueDialog(BaseDialog):
    def __init__(self, manager: DownloadManager, theme: ThemeManager, parent=None) -> None:
        super().__init__(theme, parent)
        self._manager = manager
        self.setWindowTitle("Download queue")
        self.setMinimumSize(680, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 20)
        root.setSpacing(12)

        root.addWidget(
            make_header(
                "Download queue",
                "Downloads start automatically when a slot is free. Up to "
                f"{manager.max_concurrent} run at once; raise a file to start it sooner.",
            )
        )

        self._info = QLabel()
        self._info.setObjectName("HintLabel")
        root.addWidget(self._info)

        self._table = QTableWidget(0, 4)
        self._table.setObjectName("DialogTable")
        self._table.setHorizontalHeaderLabels(("#", "File name", "Size", "Added"))
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setShowGrid(False)
        self._table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._table.verticalHeader().setDefaultSectionSize(44)
        self._table.horizontalHeader().setFixedHeight(38)
        self._table.horizontalHeader().setHighlightSections(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 46)
        self._table.setColumnWidth(2, 105)
        self._table.setColumnWidth(3, 140)
        self._table.itemSelectionChanged.connect(self._update_buttons)

        self._empty = self._build_empty_state()
        self._stack = QStackedWidget()
        self._stack.addWidget(self._table)
        self._stack.addWidget(self._empty)
        root.addWidget(self._stack, 1)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(8)
        self._up_button = secondary_button("Move up")
        self._up_button.setIcon(icons.icon("arrow_up", theme.palette.text_muted, 16))
        self._down_button = secondary_button("Move down")
        self._down_button.setIcon(icons.icon("arrow_down", theme.palette.text_muted, 16))
        self._up_button.clicked.connect(lambda: self._move(-1))
        self._down_button.clicked.connect(lambda: self._move(1))
        actions_row.addWidget(self._up_button)
        actions_row.addWidget(self._down_button)
        actions_row.addStretch(1)
        root.addLayout(actions_row)

        root.addWidget(make_divider())
        footer = QHBoxLayout()
        footer.addStretch(1)
        close_button = primary_button("Close")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        root.addLayout(footer)

        manager.queue_changed.connect(self._refresh)
        manager.download_added.connect(self._refresh)
        manager.download_removed.connect(self._refresh)
        self._refresh()

    def _build_empty_state(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.addStretch(1)
        icon = QLabel()
        icon.setPixmap(icons.icon("queue", self._theme.palette.text_faint, 34).pixmap(34, 34))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)
        layout.addSpacing(12)
        title = QLabel("The queue is empty")
        title.setObjectName("EmptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        hint = QLabel("Downloads you add or resume will wait here for a free slot.")
        hint.setObjectName("EmptyText")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return widget

    def _refresh(self) -> None:
        queued = self._manager.queue_items()
        selected_id = self._selected_id()
        self._info.setText(f"{len(queued)} waiting   ·   up to {self._manager.max_concurrent} active at once")

        self._table.setUpdatesEnabled(False)
        self._table.setRowCount(len(queued))
        selected_row = -1
        for row, item in enumerate(queued):
            number = QTableWidgetItem(str(row + 1))
            number.setData(Qt.ItemDataRole.UserRole, item.id)
            number.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            name = QTableWidgetItem(item.filename)
            name.setToolTip(item.url)
            size = QTableWidgetItem(format_size(item.total_bytes) if item.total_bytes else "—")
            size.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            added = QTableWidgetItem(item.created_at.strftime("%b %d, %H:%M"))
            added.setForeground(QColor(self._theme.palette.text_faint))
            for column, cell in enumerate((number, name, size, added)):
                self._table.setItem(row, column, cell)
            if item.id == selected_id:
                selected_row = row
        self._table.setUpdatesEnabled(True)

        if selected_row >= 0:
            self._table.selectRow(selected_row)
        self._stack.setCurrentWidget(self._table if queued else self._empty)
        self._update_buttons()

    def _selected_id(self) -> str | None:
        selection = self._table.selectionModel()
        if selection is None or not selection.hasSelection():
            return None
        row = self._table.currentRow()
        if row < 0:
            return None
        cell = self._table.item(row, 0)
        return str(cell.data(Qt.ItemDataRole.UserRole)) if cell else None

    def _update_buttons(self) -> None:
        row = self._table.currentRow()
        count = self._table.rowCount()
        has_selection = self._selected_id() is not None
        self._up_button.setEnabled(has_selection and 0 < row < count)
        self._down_button.setEnabled(has_selection and 0 <= row < count - 1)

    def _move(self, delta: int) -> None:
        download_id = self._selected_id()
        if not download_id:
            return
        self._manager.move_in_queue(download_id, delta)
        self._refresh()
