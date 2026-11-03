"""Workspace navigation with live counts and a collapsible rail."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRect, QSize, Qt, Property, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from ..constants import APP_VERSION, custom_category_key
from ..core.url_utils import format_speed
from . import design, icons
from .theme import ThemeManager

KEY_ROLE = Qt.ItemDataRole.UserRole
ICON_ROLE = Qt.ItemDataRole.UserRole + 1
COUNT_ROLE = Qt.ItemDataRole.UserRole + 2

_ITEM_HEIGHT = 38
_COLLAPSED_WIDTH = design.SURFACE.sidebar_collapsed
_EXPANDED_WIDTH = design.SURFACE.sidebar_expanded

_WORKSPACE_ITEMS = (
    ("dashboard", "Dashboard", "layout"),
    ("all", "All Downloads", "grid"),
    ("downloading", "Downloading", "download"),
    ("completed", "Completed", "check_circle"),
    ("queued", "Queued", "queue"),
    ("paused", "Paused", "pause"),
)

_LIBRARY_ITEMS = (
    ("documents", "Documents", "file_text"),
    ("music", "Music", "music"),
    ("videos", "Videos", "video"),
    ("programs", "Programs", "app"),
    ("compressed", "Compressed Files", "archive"),
    ("images", "Images", "image"),
    ("general", "General", "file"),
    ("other", "Other Files", "file"),
)

_TOOL_ITEMS = (
    ("browser_integration", "Browser Assistant", "globe"),
    ("scheduler", "Scheduler", "scheduler"),
    ("history", "Download History", "database"),
    ("analytics", "Analytics", "analytics"),
    ("performance", "Performance", "gauge"),
    ("notifications", "Notifications", "bell"),
    ("update_center", "Update Center", "refresh"),
)


class _SidebarDelegate(QStyledItemDelegate):
    def __init__(self, theme: ThemeManager, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.collapsed = False

    def sizeHint(self, option, index) -> QSize:
        return QSize(0, _ITEM_HEIGHT)

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p = self._theme.palette
        rect = option.rect.adjusted(7, 2, -7, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(p.sidebar_active))
            painter.drawRoundedRect(rect, design.RADIUS_PX["md"], design.RADIUS_PX["md"])
            painter.setBrush(QColor(p.accent))
            painter.drawRoundedRect(
                QRect(rect.left() + 1, rect.top() + 10, 3, rect.height() - 20),
                1.5,
                1.5,
            )
        elif hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(p.nav_hover))
            painter.drawRoundedRect(rect, design.RADIUS_PX["md"], design.RADIUS_PX["md"])

        text_color = QColor(p.accent if selected else (p.text if hovered else p.text_muted))
        icon_name = str(index.data(ICON_ROLE) or "file")
        icon_size = 20
        if self.collapsed:
            icon_rect = QRect(
                rect.center().x() - icon_size // 2,
                rect.center().y() - icon_size // 2,
                icon_size,
                icon_size,
            )
        else:
            icon_rect = QRect(rect.left() + 14, rect.center().y() - icon_size // 2, icon_size, icon_size)
        icon = icons.icon(icon_name, text_color.name(), icon_size)
        icon.paint(
            painter,
            icon_rect,
            Qt.AlignmentFlag.AlignCenter,
            icons.QIcon.Mode.Normal,
            icons.QIcon.State.Off,
        )
        if self.collapsed:
            painter.restore()
            return

        font = QFont(option.font)
        font.setPointSizeF(max(9.0, option.font.pointSizeF() + 0.3))
        font.setWeight(QFont.Weight.DemiBold if selected else QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(text_color)

        count = index.data(COUNT_ROLE)
        count_text = _count_label(count)
        count_width = 30 if count_text else 0
        text_rect = QRect(
            rect.left() + 44,
            rect.top(),
            max(10, rect.width() - 58 - count_width),
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
            count_font.setPointSizeF(max(8.0, option.font.pointSizeF() - 0.5))
            count_font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(count_font)
            badge = QRect(rect.right() - count_width - 6, rect.center().y() - 9, count_width, 19)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(p.accent_soft if selected else p.chip_bg))
            painter.drawRoundedRect(badge, 9.5, 9.5)
            painter.setPen(QColor(p.accent if selected else p.text_faint))
            painter.drawText(
                badge,
                int(Qt.AlignmentFlag.AlignCenter),
                count_text,
            )
        painter.restore()


def _count_label(value) -> str:
    if value is None:
        return ""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return ""
    if number <= 0:
        return ""
    return "999+" if number > 999 else str(number)


class Sidebar(QFrame):
    filter_changed = Signal(str)
    collapsed_changed = Signal(bool)

    def __init__(self, theme: ThemeManager, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._current_key = "all"
        self._collapsed = False
        self._width = _EXPANDED_WIDTH
        self.setObjectName("Sidebar")
        self.setFixedWidth(_EXPANDED_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setMinimumWidth(_COLLAPSED_WIDTH)

        self._width_anim = QPropertyAnimation(self, b"railWidth", self)
        self._width_anim.setDuration(design.duration("normal"))
        self._width_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setObjectName("SidebarScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("SidebarContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 6, 0, 4)
        content_layout.setSpacing(0)

        self._section_labels: list[QLabel] = []

        content_layout.addWidget(self._add_section(content_layout, "WORKSPACE"))
        self._workspace_list = self._create_list(_WORKSPACE_ITEMS)
        content_layout.addWidget(self._workspace_list)

        content_layout.addWidget(self._add_section(content_layout, "LIBRARY"))
        self._library_list = self._create_list(_LIBRARY_ITEMS)
        content_layout.addWidget(self._library_list)

        self._custom_label = self._add_section(
            content_layout, "CUSTOM CATEGORIES"
        )
        self._custom_list = self._create_list(())
        content_layout.addWidget(self._custom_label)
        content_layout.addWidget(self._custom_list)

        content_layout.addWidget(self._add_section(content_layout, "TOOLS"))
        self._tool_list = self._create_list(_TOOL_ITEMS)
        content_layout.addWidget(self._tool_list)
        content_layout.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        footer = QFrame()
        footer.setObjectName("SidebarFooterBox")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(8, 6, 8, 2)
        footer_layout.setSpacing(3)
        self._settings_button = QPushButton("  Settings")
        self._settings_button.setObjectName("SidebarSettings")
        self._settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._settings_button.setIcon(icons.icon("options", theme.palette.text_muted, 18))
        self._settings_button.setIconSize(QSize(18, 18))
        self._settings_button.setToolTip("Open settings")
        self._settings_button.clicked.connect(self._on_settings_clicked)
        footer_layout.addWidget(self._settings_button)
        self._footer = QLabel(f"IDM {APP_VERSION}")
        self._footer.setObjectName("SidebarFooter")
        self._footer.setToolTip(f"Application version {APP_VERSION}")
        footer_layout.addWidget(self._footer)

        self._connection = QFrame()
        self._connection.setObjectName("SidebarConnection")
        self._connection.setFixedHeight(26)
        connection_layout = QHBoxLayout(self._connection)
        connection_layout.setContentsMargins(8, 0, 8, 0)
        connection_layout.setSpacing(6)
        self._connection_dot = QLabel()
        self._connection_dot.setFixedSize(8, 8)
        connection_layout.addWidget(
            self._connection_dot, 0, Qt.AlignmentFlag.AlignVCenter
        )
        self._connection_text = QLabel("Online")
        self._connection_text.setObjectName("SidebarConnectionText")
        connection_layout.addWidget(self._connection_text)
        connection_layout.addStretch(1)
        self._connection_speed = QLabel()
        self._connection_speed.setObjectName("SidebarConnectionSpeed")
        connection_layout.addWidget(self._connection_speed)
        footer_layout.addWidget(self._connection)

        self._online = True
        self._network_available = True
        self._speed = 0.0
        layout.addWidget(footer)

        for widget in self._lists():
            widget.itemClicked.connect(self._on_item_clicked)
            widget.itemActivated.connect(self._on_item_clicked)
        self.select("all")
        theme.changed.connect(self._repaint)
        theme.changed.connect(self._refresh_icons)
        theme.changed.connect(self._refresh_connection)
        self.set_counts({})
        self.set_custom_categories([])
        self._refresh_connection()

    def _lists(self) -> tuple[QListWidget, ...]:
        return (
            self._workspace_list,
            self._library_list,
            self._custom_list,
            self._tool_list,
        )

    def set_custom_categories(self, names) -> None:
        names = [str(name).strip() for name in names if str(name).strip()]
        self._custom_list.clear()
        for name in names:
            item = QListWidgetItem(name)
            item.setData(KEY_ROLE, custom_category_key(name))
            item.setData(ICON_ROLE, "folder")
            item.setSizeHint(QSize(0, _ITEM_HEIGHT))
            item.setToolTip(name)
            self._custom_list.addItem(item)
        has_categories = bool(names)
        self._custom_label.setVisible(has_categories)
        self._custom_list.setVisible(has_categories)
        self._custom_list.setFixedHeight(
            len(names) * _ITEM_HEIGHT + 6 if names else 0
        )
        self.set_counts({})
        if self._current_key.startswith("custom:"):
            keys = {
                str(self._custom_list.item(row).data(KEY_ROLE))
                for row in range(self._custom_list.count())
            }
            if self._current_key not in keys:
                self.select("all", emit_signal=True)

    def _add_section(self, layout: QVBoxLayout, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SidebarSection")
        self._section_labels.append(label)
        return label

    def _create_list(self, entries) -> QListWidget:
        widget = QListWidget()
        widget.setObjectName("SidebarList")
        widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
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
            item.setToolTip(text)
            widget.addItem(item)
        widget.setFixedHeight(len(entries) * _ITEM_HEIGHT + 6)
        return widget

    # ------------------------------------------------------------------ collapse
    @property
    def collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool, animate: bool = True) -> None:
        collapsed = bool(collapsed)
        self._collapsed = collapsed
        target = _COLLAPSED_WIDTH if collapsed else _EXPANDED_WIDTH
        for label in self._section_labels:
            label.setVisible(not collapsed)
        self._footer.setVisible(not collapsed)
        self._connection_text.setVisible(not collapsed)
        self._connection_speed.setVisible(not collapsed)
        self._settings_button.setText("" if collapsed else "  Settings")
        self._settings_button.setFixedHeight(38)
        if collapsed:
            self._settings_button.setToolTip("Open settings")
        for widget in self._lists():
            widget.itemDelegate().collapsed = collapsed
            widget.setFixedHeight(
                widget.count() * _ITEM_HEIGHT + 6
            )
        self._restyle_settings_button()
        if animate and design.duration("normal") > 0:
            self._width_anim.stop()
            self._width_anim.setStartValue(self.width())
            self._width_anim.setEndValue(target)
            self._width_anim.start()
        else:
            self._set_rail_width(target)
        self._repaint()
        self.collapsed_changed.emit(collapsed)

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)

    def _restyle_settings_button(self) -> None:
        if self._collapsed:
            self._settings_button.setStyleSheet(
                "text-align: center; padding-left: 0px;"
            )
        else:
            self._settings_button.setStyleSheet("")

    def _get_rail_width(self) -> int:
        return self._width

    def _set_rail_width(self, value: int) -> None:
        self._width = int(value)
        self.setFixedWidth(self._width)
        self.updateGeometry()

    railWidth = Property(int, _get_rail_width, _set_rail_width)

    # ------------------------------------------------------------------ items
    def set_counts(self, counts: dict[str, int]) -> None:
        for widget in self._lists():
            for row in range(widget.count()):
                item = widget.item(row)
                key = str(item.data(KEY_ROLE))
                item.setData(COUNT_ROLE, int(counts.get(key, 0)) if key in counts else None)
        self._repaint()

    def set_connection(
        self, online: bool, available: bool = True, speed: float = 0.0
    ) -> None:
        online = bool(online)
        available = bool(available)
        speed = max(0.0, float(speed))
        if (
            online == self._online
            and available == self._network_available
            and abs(speed - self._speed) < 1.0
        ):
            return
        self._online = online
        self._network_available = available
        self._speed = speed
        self._refresh_connection()

    def _refresh_connection(self) -> None:
        p = self._theme.palette
        if self._online:
            dot_color = p.success
            text = "Online"
            detail = "Network is reachable"
        else:
            dot_color = p.danger
            text = "Offline"
            detail = "Windows reports no network connection"
        if not self._network_available:
            dot_color = p.success if self._online else p.text_faint
            detail = (
                "Network monitoring is unavailable; IDM assumes the "
                "connection is available"
            )
        self._connection_dot.setStyleSheet(
            f"background-color: {dot_color}; border-radius: 4px;"
        )
        self._connection_text.setText(text)
        speed_text = (
            format_speed(self._speed)
            if self._online and self._speed > 0
            else ""
        )
        self._connection_speed.setText(speed_text)
        self._connection.setToolTip(f"{detail}. {speed_text}".strip())
        if self._collapsed:
            self._connection.setToolTip(f"Network: {text}")

    def _refresh_icons(self) -> None:
        self._settings_button.setIcon(
            icons.icon("options", self._theme.palette.text_muted, 18)
        )
        self._refresh_connection()
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
        self._set_settings_active(False)
        self._repaint()
        self.filter_changed.emit(self._current_key)

    def _on_settings_clicked(self) -> None:
        for widget in self._lists():
            widget.clearSelection()
            widget.setCurrentRow(-1)
        self._current_key = "settings"
        self._set_settings_active(True)
        self._repaint()
        self.filter_changed.emit("settings")

    def _set_settings_active(self, active: bool) -> None:
        self._settings_button.setProperty("active", "true" if active else "false")
        self._settings_button.style().unpolish(self._settings_button)
        self._settings_button.style().polish(self._settings_button)

    def select(self, key: str, emit_signal: bool = False) -> None:
        self._set_settings_active(key == "settings")
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
        for widget in self._lists():
            widget.clearSelection()
            widget.setCurrentRow(-1)
        self._current_key = key
        self._repaint()
        if emit_signal:
            self.filter_changed.emit(key)

    @property
    def current_key(self) -> str:
        return self._current_key
