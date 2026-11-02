"""Download list card with a sortable table and empty state."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..models.table_model import (
    COLUMN_COUNT,
    COLUMN_DATE_ADDED,
    COLUMN_ETA,
    COLUMN_NAME,
    COLUMN_PROGRESS,
    COLUMN_SIZE,
    COLUMN_SPEED,
    COLUMN_STATUS,
)
from . import icons
from .delegates import (
    NameDelegate,
    ProgressDelegate,
    StatusDelegate,
    ValueDelegate,
)
from .theme import ThemeManager


class DownloadTable(QTableView):
    """Classic download list with click-to-sort column headers."""

    def __init__(self, theme: ThemeManager, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._sort_column = COLUMN_NAME
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._sorted = False
        self.setObjectName("DownloadTable")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setAlternatingRowColors(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setSortingEnabled(False)

        vertical = self.verticalHeader()
        vertical.setVisible(False)
        vertical.setDefaultSectionSize(64)
        vertical.setMinimumSectionSize(56)
        vertical.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)

        horizontal = self.horizontalHeader()
        horizontal.setFixedHeight(38)
        horizontal.setHighlightSections(False)
        horizontal.setSectionsClickable(True)
        horizontal.setSortIndicatorShown(False)
        horizontal.setMinimumSectionSize(56)
        horizontal.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        horizontal.setStretchLastSection(False)
        horizontal.sectionClicked.connect(self._on_header_clicked)

        self.setItemDelegateForColumn(COLUMN_NAME, NameDelegate(theme, self))
        self.setItemDelegateForColumn(COLUMN_STATUS, StatusDelegate(theme, self))
        self.setItemDelegateForColumn(COLUMN_PROGRESS, ProgressDelegate(theme, self))
        value_delegate = ValueDelegate(theme, self)
        for column in (
            COLUMN_SIZE,
            COLUMN_SPEED,
            COLUMN_ETA,
            COLUMN_DATE_ADDED,
        ):
            self.setItemDelegateForColumn(column, value_delegate)

        theme.changed.connect(self.viewport().update)

    def setModel(self, model) -> None:
        super().setModel(model)
        header = self.horizontalHeader()
        header.setSectionResizeMode(COLUMN_NAME, QHeaderView.ResizeMode.Stretch)
        widths = {
            COLUMN_SIZE: 88,
            COLUMN_STATUS: 116,
            COLUMN_PROGRESS: 112,
            COLUMN_SPEED: 100,
            COLUMN_ETA: 88,
            COLUMN_DATE_ADDED: 118,
        }
        for column, width in widths.items():
            self.setColumnWidth(column, width)
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
        if self._sorted and hasattr(model, "sort"):
            model.sort(self._sort_column, self._sort_order)

    def _on_header_clicked(self, column: int) -> None:
        if not 0 <= column < COLUMN_COUNT:
            return
        if self._sorted and column == self._sort_column:
            order = (
                Qt.SortOrder.DescendingOrder
                if self._sort_order == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
        else:
            order = Qt.SortOrder.AscendingOrder
        self._sort_column = column
        self._sort_order = order
        self._sorted = True
        header = self.horizontalHeader()
        header.setSortIndicatorShown(True)
        header.setSortIndicator(column, order)
        model = self.model()
        if model is not None and hasattr(model, "sort"):
            model.sort(column, order)

    def reset_sort(self) -> None:
        self._sorted = False
        self._sort_column = COLUMN_NAME
        self._sort_order = Qt.SortOrder.AscendingOrder
        self.horizontalHeader().setSortIndicatorShown(False)


class EmptyState(QWidget):
    add_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("EmptyState")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(0)
        layout.addStretch(1)

        logo = QLabel()
        logo.setPixmap(icons.logo_pixmap(72))
        logo.setFixedSize(72, 72)
        logo.setScaledContents(True)
        layout.addWidget(logo, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(18)

        self._title = QLabel("No downloads yet")
        self._title.setObjectName("EmptyTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._title)
        layout.addSpacing(6)

        self._text = QLabel(
            "Paste a direct link or click Add URL to start your first download."
        )
        self._text.setObjectName("EmptyText")
        self._text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._text.setWordWrap(True)
        layout.addWidget(self._text)
        layout.addSpacing(18)

        self._add_button = QPushButton("  Add URL")
        self._add_button.setObjectName("EmptyAddButton")
        self._add_button.setIcon(icons.icon("add", "#FFFFFF", 16))
        self._add_button.setIconSize(QSize(16, 16))
        self._add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_button.clicked.connect(self.add_requested)
        layout.addWidget(self._add_button, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(12)

        hint = QLabel("Supports HTTP and HTTPS links")
        hint.setObjectName("EmptyHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        layout.addStretch(1)

    def set_message(self, title: str, text: str) -> None:
        self._title.setText(title)
        self._text.setText(text)


class DownloadView(QFrame):
    add_requested = Signal()

    def __init__(self, theme: ThemeManager, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ContentCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.table = DownloadTable(theme, self)
        self.empty_state = EmptyState(self)
        self.empty_state.add_requested.connect(self.add_requested)

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self.table)
        self._stack.addWidget(self.empty_state)
        layout.addWidget(self._stack)

    def show_empty(
        self,
        visible: bool,
        title: str | None = None,
        text: str | None = None,
    ) -> None:
        if title is not None and text is not None:
            self.empty_state.set_message(title, text)
        self._stack.setCurrentWidget(self.empty_state if visible else self.table)
