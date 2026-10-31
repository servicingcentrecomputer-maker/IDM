"""Shared dialog helpers."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import icons
from ..theme import ThemeManager


class BaseDialog(QDialog):
    def __init__(self, theme: ThemeManager, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setModal(True)
        self.setWindowIcon(icons.app_icon())
        theme.changed.connect(self._sync_chrome)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._theme.apply_window_chrome(self)

    def _sync_chrome(self) -> None:
        if self.isVisible():
            self._theme.apply_window_chrome(self)


def make_header(title: str, subtitle: str) -> QWidget:
    header = QWidget()
    layout = QVBoxLayout(header)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(3)
    title_label = QLabel(title)
    title_label.setObjectName("DialogTitle")
    subtitle_label = QLabel(subtitle)
    subtitle_label.setObjectName("DialogSubtitle")
    subtitle_label.setWordWrap(True)
    layout.addWidget(title_label)
    layout.addWidget(subtitle_label)
    return header


def make_label(text: str, object_name: str = "FieldLabel") -> QLabel:
    label = QLabel(text)
    label.setObjectName(object_name)
    return label


def make_divider() -> QFrame:
    divider = QFrame()
    divider.setObjectName("Divider")
    divider.setFixedHeight(1)
    return divider


def primary_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("PrimaryButton")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setAutoDefault(True)
    button.setDefault(True)
    return button


def secondary_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setAutoDefault(False)
    return button
