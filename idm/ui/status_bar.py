"""Bottom status bar: live counts, transfer rate and transient messages."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from ..constants import APP_VERSION
from ..core.url_utils import format_speed
from .theme import ThemeManager


class StatusBar(QFrame):
    def __init__(self, theme: ThemeManager, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._active = 0
        self._speed = 0.0
        self._queued = 0
        self.setObjectName("StatusBar")
        self.setFixedHeight(28)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(7)

        self._dot = QLabel()
        self._dot.setFixedSize(7, 7)
        layout.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)

        self._activity = QLabel("Ready")
        self._activity.setObjectName("StatusText")
        layout.addWidget(self._activity)

        self._speed_label = QLabel()
        self._speed_label.setObjectName("StatusValue")
        layout.addWidget(self._speed_label)

        layout.addStretch(1)

        self._message = QLabel()
        self._message.setObjectName("StatusMessage")
        layout.addWidget(self._message)

        divider = QFrame()
        divider.setObjectName("StatusDivider")
        divider.setFixedSize(1, 12)
        layout.addWidget(divider)

        version = QLabel(f"IDM {APP_VERSION}")
        version.setObjectName("StatusVersion")
        layout.addWidget(version)

        self._message_timer = QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.timeout.connect(self._clear_message)

        theme.changed.connect(self._refresh)
        self._refresh()

    def set_stats(self, active: int, speed: float, queued: int) -> None:
        self._active = active
        self._speed = speed
        self._queued = queued
        self._refresh()

    def _refresh(self) -> None:
        p = self._theme.palette
        if self._active > 0:
            dot_color = p.success
            text = f"{self._active} active"
            if self._queued:
                text += f"  ·  {self._queued} queued"
        elif self._queued > 0:
            dot_color = p.accent
            text = f"{self._queued} queued"
        else:
            dot_color = p.text_faint
            text = "Ready"
        self._dot.setStyleSheet(f"background-color: {dot_color}; border-radius: 3px;")
        self._activity.setText(text)
        if self._speed > 0:
            self._speed_label.setText(format_speed(self._speed))
            self._speed_label.show()
        else:
            self._speed_label.hide()

    def show_message(self, text: str, timeout_ms: int = 5000) -> None:
        self._message.setText(text)
        self._message_timer.stop()
        if timeout_ms > 0:
            self._message_timer.start(timeout_ms)

    def _clear_message(self) -> None:
        self._message.clear()
