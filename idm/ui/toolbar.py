"""Modern application toolbar for IDM 3.5."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import design, icons
from .theme import ThemeManager


class NotificationButton(QToolButton):
    """Bell button that paints an unread badge without extra widgets."""

    def __init__(self, theme: ThemeManager, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._count = 0
        self.setObjectName("IconButton")
        self.setIconSize(QSize(21, 21))
        self.setFixedSize(40, 40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Notifications")
        self.setAccessibleName("Notifications")

    def set_count(self, count: int) -> None:
        self._count = max(0, int(count))
        self.setToolTip(
            "Notifications" if not self._count else f"Notifications ({self._count})"
        )
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._count <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p = self._theme.palette
        text = "99+" if self._count > 99 else str(self._count)
        width = max(16, 10 + 6 * len(text))
        badge = self.rect().adjusted(self.width() - width - 3, 2, -3, -self.height() + 18)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(p.danger))
        painter.drawRoundedRect(badge, 8, 8)
        painter.setPen(QColor("#FFFFFF"))
        font = painter.font()
        font.setPointSizeF(7.0)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(badge, int(Qt.AlignmentFlag.AlignCenter), text)


class DownloadToolbar(QFrame):
    add_requested = Signal()
    resume_requested = Signal()
    resume_all_requested = Signal()
    pause_requested = Signal()
    stop_requested = Signal()
    stop_all_requested = Signal()
    delete_requested = Signal()
    delete_completed_requested = Signal()
    options_requested = Signal()
    scheduler_requested = Signal()
    queue_requested = Signal()
    theme_toggled = Signal()
    notifications_requested = Signal()
    settings_requested = Signal()
    sidebar_toggled = Signal()

    def __init__(self, theme: ThemeManager, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setObjectName("Toolbar")
        self.setFixedHeight(design.SURFACE.toolbar_height)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 9, 16, 9)
        layout.setSpacing(4)

        self._sidebar_button = QToolButton()
        self._sidebar_button.setObjectName("IconButton")
        self._sidebar_button.setToolTip("Collapse or expand the sidebar (Ctrl+B)")
        self._sidebar_button.setAccessibleName("Toggle sidebar")
        self._sidebar_button.setFixedSize(40, 40)
        self._sidebar_button.setIconSize(QSize(21, 21))
        self._sidebar_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sidebar_button.clicked.connect(self.sidebar_toggled)
        layout.addWidget(self._sidebar_button)

        logo = QLabel()
        logo.setPixmap(icons.logo_pixmap(34))
        logo.setFixedSize(34, 34)
        logo.setScaledContents(True)

        brand_text = QVBoxLayout()
        brand_text.setContentsMargins(0, 0, 0, 0)
        brand_text.setSpacing(0)
        self._brand_name = QLabel("IDM")
        self._brand_name.setObjectName("BrandName")
        self._brand_tagline = QLabel("DOWNLOAD MANAGER")
        self._brand_tagline.setObjectName("BrandTagline")
        brand_text.addWidget(self._brand_name)
        brand_text.addWidget(self._brand_tagline)

        brand = QHBoxLayout()
        brand.setContentsMargins(4, 0, 14, 0)
        brand.setSpacing(10)
        brand.addWidget(logo, 0, Qt.AlignmentFlag.AlignVCenter)
        brand.addLayout(brand_text)
        layout.addLayout(brand)
        layout.addWidget(self._separator())

        self.buttons: dict[str, QToolButton] = {}
        self._add_button(
            "add",
            "Add URL",
            "add_url",
            "Add a URL to download (Ctrl+N)",
            layout,
            primary=True,
        )
        layout.addSpacing(4)
        self._add_button("resume", "Resume", "resume", "Resume selected downloads (Ctrl+R)", layout)
        self._add_button(
            "resume_all",
            "Resume All",
            "resume_all",
            "Resume every paused download (Ctrl+Shift+R)",
            layout,
        )
        self._add_button("pause", "Pause", "pause", "Pause selected downloads (Ctrl+P)", layout)
        self._add_button("stop", "Stop", "stop", "Stop selected downloads (Ctrl+Shift+S)", layout)
        self._add_button(
            "stop_all",
            "Stop All",
            "stop_all",
            "Stop every active download",
            layout,
        )
        self._add_button("delete", "Delete", "delete", "Remove selected downloads (Del)", layout)
        self._add_button(
            "delete_completed",
            "Delete Completed",
            "delete_completed",
            "Clear completed downloads from the list (Ctrl+Shift+Delete)",
            layout,
        )
        layout.addWidget(self._separator())
        self._add_button("queue", "Queue", "queue", "Manage the download queue (Ctrl+Shift+Q)", layout)
        self._add_button(
            "scheduler",
            "Scheduler",
            "scheduler",
            "Schedule downloads (Ctrl+Shift+T)",
            layout,
        )
        self._add_button("options", "Options", "options", "IDM options (Ctrl+,)", layout)

        layout.addStretch(1)

        self.search_field = QLineEdit()
        self.search_field.setObjectName("SearchBox")
        self.search_field.setPlaceholderText("Search downloads…")
        self.search_field.setClearButtonEnabled(True)
        self.search_field.setFixedWidth(260)
        self.search_field.setMinimumHeight(38)
        self.search_field.setAccessibleName("Search downloads")
        self.search_action = self.search_field.addAction(
            icons.icon("search", theme.palette.text_faint, 16),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        layout.addWidget(self.search_field, 0, Qt.AlignmentFlag.AlignVCenter)

        self._theme_button = QToolButton()
        self._theme_button.setObjectName("ThemeButton")
        self._theme_button.setIconSize(QSize(20, 20))
        self._theme_button.setFixedSize(40, 40)
        self._theme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme_button.clicked.connect(self.theme_toggled)
        layout.addWidget(self._theme_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.notifications_button = NotificationButton(theme, self)
        self.notifications_button.clicked.connect(self.notifications_requested)
        layout.addWidget(self.notifications_button)

        self.settings_button = QToolButton()
        self.settings_button.setObjectName("IconButton")
        self.settings_button.setToolTip("Settings")
        self.settings_button.setAccessibleName("Settings")
        self.settings_button.setFixedSize(40, 40)
        self.settings_button.setIconSize(QSize(21, 21))
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_button.clicked.connect(self.settings_requested)
        layout.addWidget(self.settings_button)

        self.buttons["add"].clicked.connect(self.add_requested)
        self.buttons["resume"].clicked.connect(self.resume_requested)
        self.buttons["resume_all"].clicked.connect(self.resume_all_requested)
        self.buttons["pause"].clicked.connect(self.pause_requested)
        self.buttons["stop"].clicked.connect(self.stop_requested)
        self.buttons["stop_all"].clicked.connect(self.stop_all_requested)
        self.buttons["delete"].clicked.connect(self.delete_requested)
        self.buttons["delete_completed"].clicked.connect(
            self.delete_completed_requested
        )
        self.buttons["options"].clicked.connect(self.options_requested)
        self.buttons["scheduler"].clicked.connect(self.scheduler_requested)
        self.buttons["queue"].clicked.connect(self.queue_requested)

        self._refresh_icons()
        theme.changed.connect(self._refresh_icons)
        self.update_actions(False, False, False, False, False)

    @staticmethod
    def _separator() -> QFrame:
        separator = QFrame()
        separator.setObjectName("ToolbarSeparator")
        separator.setFixedSize(1, 32)
        return separator

    def _add_button(
        self,
        key: str,
        text: str,
        icon_name: str,
        tooltip: str,
        layout: QHBoxLayout,
        primary: bool = False,
    ) -> None:
        button = QToolButton()
        button.setObjectName("ToolbarButton")
        button.setText(text)
        button.setToolTip(tooltip)
        button.setAccessibleName(text)
        button.setProperty("icon_name", icon_name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if primary:
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setProperty("accent", "true")
            button.setIconSize(QSize(21, 21))
            button.setFixedSize(126, 40)
        else:
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.setIconSize(QSize(21, 21))
            button.setFixedSize(40, 40)
        layout.addWidget(button)
        self.buttons[key] = button

    def _refresh_icons(self) -> None:
        p = self._theme.palette
        for key, button in self.buttons.items():
            icon_name = str(button.property("icon_name"))
            if key == "add":
                button.setIcon(icons.icon("add", "#FFFFFF", 20))
            else:
                button.setIcon(icons.icon(icon_name, p.text_muted, 20))
        self._theme_button.setIcon(icons.icon("palette", p.text_muted, 19))
        self._theme_button.setToolTip(
            f"Theme: {self._theme.label} — click to change"
        )
        self._sidebar_button.setIcon(icons.icon("sidebar", p.text_muted, 21))
        self.settings_button.setIcon(icons.icon("options", p.text_muted, 21))
        self.search_action.setIcon(icons.icon("search", p.text_faint, 17))
        self.notifications_button.setIcon(icons.icon("bell", p.text_muted, 21))

    def set_sidebar_collapsed(self, collapsed: bool) -> None:
        self._sidebar_button.setToolTip(
            "Expand the sidebar (Ctrl+B)" if collapsed else "Collapse the sidebar (Ctrl+B)"
        )

    def set_notifications(self, count: int) -> None:
        self.notifications_button.set_count(count)

    def set_compact(self, compact: bool) -> None:
        self._brand_tagline.setVisible(not compact)
        self.search_field.setFixedWidth(200 if compact else 260)

    def update_actions(
        self,
        can_pause: bool,
        can_resume: bool,
        can_stop: bool,
        can_delete: bool,
        can_delete_completed: bool = False,
        can_resume_all: bool = False,
        can_stop_all: bool = False,
    ) -> None:
        self.buttons["pause"].setEnabled(can_pause)
        self.buttons["resume"].setEnabled(can_resume)
        self.buttons["resume_all"].setEnabled(can_resume_all)
        self.buttons["stop"].setEnabled(can_stop)
        self.buttons["stop_all"].setEnabled(can_stop_all)
        self.buttons["delete"].setEnabled(can_delete)
        self.buttons["delete_completed"].setEnabled(can_delete_completed)
