"""Classic application toolbar with the primary download actions."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout

from . import icons
from .theme import ThemeManager


class DownloadToolbar(QFrame):
    add_requested = Signal()
    resume_requested = Signal()
    resume_all_requested = Signal()
    pause_requested = Signal()
    stop_requested = Signal()
    delete_requested = Signal()
    options_requested = Signal()
    scheduler_requested = Signal()
    queue_requested = Signal()
    theme_toggled = Signal()

    def __init__(self, theme: ThemeManager, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setObjectName("Toolbar")
        self.setFixedHeight(64)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 6, 9, 6)
        layout.setSpacing(2)

        logo = QLabel()
        logo.setPixmap(icons.logo_pixmap(28))
        logo.setFixedSize(28, 28)
        logo.setScaledContents(True)

        brand_text = QVBoxLayout()
        brand_text.setContentsMargins(0, 0, 0, 0)
        brand_text.setSpacing(0)
        app_name = QLabel("IDM")
        app_name.setObjectName("BrandName")
        tagline = QLabel("DOWNLOAD MANAGER")
        tagline.setObjectName("BrandTagline")
        brand_text.addWidget(app_name)
        brand_text.addWidget(tagline)

        brand = QHBoxLayout()
        brand.setContentsMargins(2, 0, 8, 0)
        brand.setSpacing(7)
        brand.addWidget(logo, 0, Qt.AlignmentFlag.AlignVCenter)
        brand.addLayout(brand_text)
        layout.addLayout(brand)
        layout.addWidget(self._separator())

        self.buttons: dict[str, QToolButton] = {}
        self._add_button("add", "Add URL", "add_url", "Add a URL to download (Ctrl+N)", layout)
        layout.addWidget(self._separator())
        self._add_button("resume", "Resume", "resume", "Resume selected downloads (Ctrl+R)", layout)
        self._add_button(
            "resume_all",
            "Resume All",
            "resume_all",
            "Resume every paused download (Ctrl+Shift+R)",
            layout,
            width=74,
        )
        self._add_button("pause", "Pause", "pause", "Pause selected downloads (Ctrl+P)", layout)
        self._add_button("stop", "Stop", "stop", "Stop selected downloads (Ctrl+Shift+S)", layout)
        layout.addWidget(self._separator())
        self._add_button("delete", "Delete", "delete", "Remove selected downloads (Del)", layout)
        layout.addWidget(self._separator())
        self._add_button("options", "Options", "options", "IDM options (Ctrl+,)", layout)
        self._add_button(
            "scheduler",
            "Scheduler",
            "scheduler",
            "Schedule downloads (Ctrl+Shift+T)",
            layout,
            width=72,
        )
        self._add_button("queue", "Queue", "queue", "Manage the download queue (Ctrl+Shift+Q)", layout)

        layout.addStretch(1)

        self._theme_button = QToolButton()
        self._theme_button.setObjectName("ThemeButton")
        self._theme_button.setIconSize(QSize(19, 19))
        self._theme_button.setFixedSize(34, 34)
        self._theme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme_button.clicked.connect(self.theme_toggled)
        layout.addWidget(self._theme_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.buttons["add"].clicked.connect(self.add_requested)
        self.buttons["resume"].clicked.connect(self.resume_requested)
        self.buttons["resume_all"].clicked.connect(self.resume_all_requested)
        self.buttons["pause"].clicked.connect(self.pause_requested)
        self.buttons["stop"].clicked.connect(self.stop_requested)
        self.buttons["delete"].clicked.connect(self.delete_requested)
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
        separator.setFixedSize(1, 34)
        return separator

    def _add_button(
        self,
        key: str,
        text: str,
        icon_name: str,
        tooltip: str,
        layout: QHBoxLayout,
        width: int = 64,
    ) -> None:
        button = QToolButton()
        button.setObjectName("ToolbarButton")
        button.setText(text)
        button.setToolTip(tooltip)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        button.setIconSize(QSize(26, 26))
        button.setFixedSize(width, 50)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setProperty("icon_name", icon_name)
        layout.addWidget(button)
        self.buttons[key] = button

    def _refresh_icons(self) -> None:
        p = self._theme.palette
        for button in self.buttons.values():
            icon_name = button.property("icon_name")
            button.setIcon(icons.toolbar_icon(str(icon_name), 26))
        self._theme_button.setIcon(icons.icon("palette", p.text_muted, 18))
        self._theme_button.setToolTip(
            f"Theme: {self._theme.label} — click to change"
        )

    def update_actions(
        self,
        can_pause: bool,
        can_resume: bool,
        can_stop: bool,
        can_delete: bool,
        can_delete_completed: bool = False,
        can_resume_all: bool = False,
    ) -> None:
        del can_delete_completed
        self.buttons["pause"].setEnabled(can_pause)
        self.buttons["resume"].setEnabled(can_resume)
        self.buttons["resume_all"].setEnabled(can_resume_all)
        self.buttons["stop"].setEnabled(can_stop)
        self.buttons["delete"].setEnabled(can_delete)
