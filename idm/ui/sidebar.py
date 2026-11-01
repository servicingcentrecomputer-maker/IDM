"""Workspace navigation and download category sidebar with live counts."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from ..constants import APP_VERSION
from . import icons
from .theme import ThemeManager

KEY_ROLE = Qt.ItemDataRole.UserRole
ICON_ROLE = Qt.ItemDataRole.UserRole + 1
COUNT_ROLE = Qt.ItemDataRole.UserRole + 2

_ITEM_HEIGHT = 28

_MAIN_ITEMS = (
    ("dashboard", "Dashboard", "layout"),
    ("video_downloads", "Video Downloads", "video"),
    ("all", "All Downloads", "grid"),
    ("downloading", "Downloading", "download"),
    ("completed", "Completed", "check_circle"),
)

_TOOL_ITEMS = (
    ("browser_integration", "Browser Integration", "globe"),
    ("analytics", "Download Analytics", "analytics"),
    ("performance", "Performance Monitor", "gauge"),
    ("notifications", "Notifications", "bell"),
    ("update_center", "Update Center", "arrow_up"),
    ("advanced_settings", "Advanced Settings", "options"),
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
        return QSize(0, _ITEM_HEIGHT)

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
                QRect(rect.left() + 1, rect.top() + 6, 3, rect.height() - 12),
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
        count_width = 34 if count_text else 0
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
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setObjectName("SidebarScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("SidebarContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 5, 0, 4)
        content_layout.setSpacing(0)

        content_layout.addWidget(self._section_label("WORKSPACE"))
        self._main_list = self._create_list(_MAIN_ITEMS)
        self._main_list.setFixedHeight(len(_MAIN_ITEMS) * _ITEM_HEIGHT + 4)
        content_layout.addWidget(self._main_list)

        content_layout.addSpacing(4)
        content_layout.addWidget(self._section_label("TOOLS"))
        self._tool_list = self._create_list(_TOOL_ITEMS)
        self._tool_list.setFixedHeight(len(_TOOL_ITEMS) * _ITEM_HEIGHT + 4)
        content_layout.addWidget(self._tool_list)

        content_layout.addSpacing(4)
        content_layout.addWidget(self._section_label("CATEGORIES"))
        self._category_list = self._create_list(_CATEGORY_ITEMS)
        self._category_list.setFixedHeight(len(_CATEGORY_ITEMS) * _ITEM_HEIGHT + 4)
        content_layout.addWidget(self._category_list)
        content_layout.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        footer = QLabel(f"IDM v{APP_VERSION}\nDashboard · Media · Analytics")
        footer.setObjectName("SidebarFooter")
        footer.setWordWrap(True)
        layout.addWidget(footer)

        for widget in self._lists():
            widget.itemClicked.connect(self._on_item_clicked)
        self.select("all")
        theme.changed.connect(self._repaint)
        self.set_counts({})

    def _lists(self) -> tuple[QListWidget, QListWidget, QListWidget]:
        return (self._main_list, self._tool_list, self._category_list)

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
            item.setSizeHint(QSize(0, _ITEM_HEIGHT))
            widget.addItem(item)
        return widget

    def set_counts(self, counts: dict[str, int]) -> None:
        for widget in self._lists():
            for row in range(widget.count()):
                item = widget.item(row)
                key = str(item.data(KEY_ROLE))
                if key in counts:
                    item.setData(COUNT_ROLE, int(counts.get(key, 0)))
                else:
                    item.setData(COUNT_ROLE, None)
        self._repaint()

    def _repaint(self) -> None:
        for widget in self._lists():
            widget.viewport().update()
            widget.update()

    def _on_item_clicked(self, clicked_item: QListWidgetItem) -> None:
        sender = self.sender()
        for widget in self._lists():
            if widget is not sender:
                widget.clearSelection()
                widget.setCurrentRow(-1)
        self._current_key = str(clicked_item.data(KEY_ROLE))
        self._repaint()
        self.filter_changed.emit(self._current_key)

    def select(self, key: str, emit_signal: bool = False) -> None:
        for widget in self._lists():
            for row in range(widget.count()):
                item = widget.item(row)
                if item.data(KEY_ROLE) == key:
                    for other in self._lists():
                        if other is not widget:
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
