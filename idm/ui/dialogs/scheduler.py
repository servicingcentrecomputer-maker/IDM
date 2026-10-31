"""Download scheduler dialog."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QDateTime, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateTimeEdit,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.scheduler import SCHEDULE_ACTIONS, DownloadScheduler
from .. import icons
from ..theme import ThemeManager
from .common import (
    BaseDialog,
    make_divider,
    make_header,
    make_label,
    primary_button,
    secondary_button,
)


class SchedulerDialog(BaseDialog):
    def __init__(
        self, scheduler: DownloadScheduler, theme: ThemeManager, parent=None
    ) -> None:
        super().__init__(theme, parent)
        self._scheduler = scheduler
        self.setWindowTitle("Scheduler")
        self.setMinimumSize(660, 540)

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 20)
        root.setSpacing(12)

        root.addWidget(
            make_header(
                "Scheduler",
                "Pause or resume the download queue at a chosen time. Schedules run while IDM is open.",
            )
        )

        card = QFrame()
        card.setObjectName("DialogCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(8)

        card_layout.addWidget(make_label("NEW SCHEDULE", "SectionTitle"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(5)
        grid.addWidget(make_label("Run at"), 0, 0)
        grid.addWidget(make_label("Action"), 0, 1)
        self._when = QDateTimeEdit()
        self._when.setCalendarPopup(True)
        self._when.setDisplayFormat("MMM d, yyyy   h:mm AP")
        self._when.setMinimumDateTime(QDateTime.currentDateTime())
        self._when.setDateTime(QDateTime.currentDateTime().addSecs(600))
        self._action = QComboBox()
        for key, label in SCHEDULE_ACTIONS.items():
            self._action.addItem(label, key)
        grid.addWidget(self._when, 1, 0)
        grid.addWidget(self._action, 1, 1)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        card_layout.addLayout(grid)

        add_row = QHBoxLayout()
        add_row.addStretch(1)
        add_button = primary_button("Add schedule")
        add_button.clicked.connect(self._add_schedule)
        add_row.addWidget(add_button)
        card_layout.addLayout(add_row)
        root.addWidget(card)

        self._error = QLabel()
        self._error.setObjectName("ErrorLabel")
        self._error.setWordWrap(True)
        self._error.hide()
        root.addWidget(self._error)

        self._info = QLabel()
        self._info.setObjectName("HintLabel")
        root.addWidget(self._info)

        self._table = QTableWidget(0, 2)
        self._table.setObjectName("DialogTable")
        self._table.setHorizontalHeaderLabels(("Date & time", "Action"))
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setDefaultSectionSize(42)
        self._table.horizontalHeader().setFixedHeight(38)
        self._table.horizontalHeader().setHighlightSections(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(1, 210)
        self._table.itemSelectionChanged.connect(self._update_buttons)

        self._empty = self._build_empty_state()
        self._stack = QStackedWidget()
        self._stack.addWidget(self._table)
        self._stack.addWidget(self._empty)
        root.addWidget(self._stack, 1)

        actions = QHBoxLayout()
        self._delete_button = secondary_button("Delete selected")
        self._delete_button.setIcon(icons.icon("delete", theme.palette.danger, 16))
        self._delete_button.clicked.connect(self._delete_selected)
        actions.addWidget(self._delete_button)
        actions.addStretch(1)
        root.addLayout(actions)

        root.addWidget(make_divider())
        footer = QHBoxLayout()
        footer.addStretch(1)
        close_button = primary_button("Close")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        root.addLayout(footer)

        scheduler.schedules_changed.connect(self._refresh)
        self._refresh()

    def _build_empty_state(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(30, 24, 30, 24)
        layout.addStretch(1)
        icon = QLabel()
        icon.setPixmap(icons.icon("scheduler", self._theme.palette.text_faint, 34).pixmap(34, 34))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)
        layout.addSpacing(10)
        title = QLabel("No schedules yet")
        title.setObjectName("EmptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        hint = QLabel("Add a time above to pause or resume your downloads automatically.")
        hint.setObjectName("EmptyText")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return widget

    def _refresh(self) -> None:
        entries = self._scheduler.entries()
        selected_id = self._selected_id()
        self._info.setText(f"{len(entries)} scheduled")
        self._table.setUpdatesEnabled(False)
        self._table.setRowCount(len(entries))
        selected_row = -1
        for row, entry in enumerate(entries):
            when = QTableWidgetItem(entry.run_at.strftime("%a, %b %d, %Y   ·   %I:%M %p"))
            when.setData(Qt.ItemDataRole.UserRole, entry.id)
            action = QTableWidgetItem(SCHEDULE_ACTIONS.get(entry.action, entry.action))
            action.setForeground(QColor(self._theme.palette.text_muted))
            self._table.setItem(row, 0, when)
            self._table.setItem(row, 1, action)
            if entry.id == selected_id:
                selected_row = row
        self._table.setUpdatesEnabled(True)
        if selected_row >= 0:
            self._table.selectRow(selected_row)
        self._stack.setCurrentWidget(self._table if entries else self._empty)
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
        self._delete_button.setEnabled(self._selected_id() is not None)

    def _add_schedule(self) -> None:
        self._error.hide()
        run_at: datetime = self._when.dateTime().toPython()
        action = str(self._action.currentData())
        try:
            self._scheduler.add(run_at, action)
        except ValueError as exc:
            self._error.setText(str(exc))
            self._error.show()
            return
        self._when.setDateTime(QDateTime.currentDateTime().addSecs(600))
        self._refresh()

    def _delete_selected(self) -> None:
        schedule_id = self._selected_id()
        if schedule_id:
            self._scheduler.remove(schedule_id)
            self._refresh()
