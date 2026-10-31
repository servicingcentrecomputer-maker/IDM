"""Classic download category sidebar with live counts."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
)

from ..constants import APP_VERSION
from . import icons
from .theme import ThemeManager

KEY_ROLE = Qt.ItemDataRole.UserRole
ICON_ROLE = Qt.ItemDataRole.UserRole + 1
COUNT_ROLE = Qt.ItemDataRole.UserRole + 2

_MAIN_ITEMS = (
    ("all", "All Downloads", "grid"),
    ("downloading", "Downloading", "download"),
    ("completed", "Completed", "check_circle"),
)

_CATEGORY_ITEMS = (
    ("documents", "Documents", "file_text"),
    ("music", "Music", "music"),
    ("videos", "Videos", "video"),
    ("programs", "Programs", "app"),
    ("compressed", "Compressed Files", "archive"),
)


class _SidebarDelegate(QStyledItemDelegate):
    def __init__(self, theme: ThemeManager, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme

    def sizeHint(self, option, index) -> QSize:
        return QSize(0, 30)

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p = self._theme.palette
        rect = option.rect.adjusted(6, 1, -6, -1)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(p.sidebar_active))
            painter.drawRoundedRect(rect, 3, 3)
            painter.setBrush(QColor(p.accent))
            painter.drawRoundedRect(
                QRect(rect.left() + 1, rect.top() + 7, 3, rect.height() - 14),
                1.5,
                1.5,
            )
        elif hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(p.surface_alt))
            painter.drawRoundedRect(rect, 3, 3)

        text_color = QColor(p.accent if selected else (p.text if hovered else p.text_muted))
        icon_name = str(index.data(ICON_ROLE) or "file")
        icon = icons.icon(icon_name, text_color.name(), 16)
        icon_rect = QRect(rect.left() + 11, rect.center().y() - 8, 16, 16)
        icon.paint(
            painter,
            icon_rect,
            Qt.AlignmentFlag.AlignCenter,
            icons.QIcon.Mode.Normal,
            icons.QIcon.State.Off,
        )

        font = QFont(option.font)
        font.setPointSizeF(max(8.5, option.font.pointSizeF() + 0.2))
        font.setWeight(QFont.Weight.DemiBold if selected else QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(text_color)

        count = index.data(COUNT_ROLE)
        count_text = str(count) if count is not None else ""
        count_width = 32 if count_text else 0
        text_rect = QRect(
            rect.left() + 35,
            rect.top(),
            max(10, rect.width() - 45 - count_width),
            rect.height(),
        )
        metrics = QFontMetrics(font)
        label = metrics.elidedText(
            str(index.data(Qt.ItemDataRole.DisplayRole) or ""),
            Qt.TextElideMode.ElideRight,
            text_rect.width(),
        )
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            label,
        )

        if count_text:
            count_font = QFont(option.font)
            count_font.setPointSizeF(max(8.0, option.font.pointSizeF() - 0.4))
            painter.setFont(count_font)
            painter.setPen(QColor(p.accent if selected else p.text_faint))
            count_rect = QRect(
                rect.right() - count_width - 4,
                rect.top(),
                count_width,
                rect.height(),
            )
            painter.drawText(
                count_rect,
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                count_text,
            )
        painter.restore()


class Sidebar(QFrame):
    filter_changed = Signal(str)

    def __init__(self, theme: ThemeManager, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._current_key = "all"
        self.setObjectName("Sidebar")
        self.setFixedWidth(208)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 5, 0, 10)
        layout.setSpacing(0)

        layout.addWidget(self._section_label("DOWNLOADS"))
        self._main_list = self._create_list(_MAIN_ITEMS)
        self._main_list.setFixedHeight(len(_MAIN_ITEMS) * 30 + 5)
        layout.addWidget(self._main_list)

        layout.addSpacing(6)
        layout.addWidget(self._section_label("CATEGORIES"))
        self._category_list = self._create_list(_CATEGORY_ITEMS)
        self._category_list.setFixedHeight(len(_CATEGORY_ITEMS) * 30 + 5)
        layout.addWidget(self._category_list)

        layout.addStretch(1)

        footer = QLabel(f"IDM v{APP_VERSION}\nHTTP · HTTPS downloads")
        footer.setObjectName("SidebarFooter")
        footer.setWordWrap(True)
        layout.addWidget(footer)

        self._main_list.itemClicked.connect(self._on_item_clicked)
        self._category_list.itemClicked.connect(self._on_item_clicked)
        self._main_list.setCurrentRow(0)
        theme.changed.connect(self._repaint)

        self.set_counts({})

    @staticmethod
    def _section_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SidebarSection")
        return label

    def _create_list(self, entries) -> QListWidget:
        widget = QListWidget()
        widget.setObjectName("SidebarList")
        widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        widget.setMouseTracking(True)
        widget.viewport().setMouseTracking(True)
        widget.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        widget.setItemDelegate(_SidebarDelegate(self._theme, widget))
        for key, text, icon_name in entries:
            item = QListWidgetItem(text)
            item.setData(KEY_ROLE, key)
            item.setData(ICON_ROLE, icon_name)
            item.setSizeHint(QSize(0, 30))
            widget.addItem(item)
        return widget

    def set_counts(self, counts: dict[str, int]) -> None:
        for widget in (self._main_list, self._category_list):
            for row in range(widget.count()):
                item = widget.item(row)
                key = str(item.data(KEY_ROLE))
                item.setData(COUNT_ROLE, int(counts.get(key, 0)))
        self._repaint()

    def _repaint(self) -> None:
        for widget in (self._main_list, self._category_list):
            widget.viewport().update()
            widget.update()

    def _on_item_clicked(self, clicked_item: QListWidgetItem) -> None:
        sender = self.sender()
        if sender is self._main_list:
            self._category_list.clearSelection()
            self._category_list.setCurrentRow(-1)
        else:
            self._main_list.clearSelection()
            self._main_list.setCurrentRow(-1)
        self._current_key = str(clicked_item.data(KEY_ROLE))
        self._repaint()
        self.filter_changed.emit(self._current_key)

    def select(self, key: str, emit_signal: bool = False) -> None:
        for widget in (self._main_list, self._category_list):
            for row in range(widget.count()):
                item = widget.item(row)
                if item.data(KEY_ROLE) == key:
                    other = (
                        self._category_list
                        if widget is self._main_list
                        else self._main_list
                    )
                    other.clearSelection()
                    other.setCurrentRow(-1)
                    widget.setCurrentRow(row)
                    self._current_key = key
                    self._repaint()
                    if emit_signal:
                        self.filter_changed.emit(key)
                    return

    @property
    def current_key(self) -> str:
        return self._current_key
