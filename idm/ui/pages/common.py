"""Shared layout helpers for the IDM 3.0 workspace pages."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..theme import ThemeManager


class PageScroll(QScrollArea):
    """Vertical scrolling page with a ready-to-use body layout."""

    def __init__(self, theme: ThemeManager, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setObjectName("PageScroll")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        body = QWidget()
        body.setObjectName("PageScrollBody")
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(0, 0, 8, 4)
        self.body.setSpacing(12)
        self.setWidget(body)


class Card(QFrame):
    """Panel with an optional heading and a content layout."""

    def __init__(
        self,
        theme: ThemeManager,
        title: str = "",
        caption: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setObjectName("PanelCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(14, 12, 14, 12)
        self._layout.setSpacing(8)

        self.title_label = None
        self.caption_label = None
        if title:
            header = QVBoxLayout()
            header.setContentsMargins(0, 0, 0, 0)
            header.setSpacing(1)
            self.title_label = QLabel(title)
            self.title_label.setObjectName("PanelTitle")
            header.addWidget(self.title_label)
            self.caption_label = QLabel(caption)
            self.caption_label.setObjectName("PanelCaption")
            self.caption_label.setVisible(bool(caption))
            self.caption_label.setWordWrap(True)
            header.addWidget(self.caption_label)
            self._layout.addLayout(header)

        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(7)
        self._layout.addLayout(self.body)

    def add(self, widget: QWidget, stretch: int = 0) -> None:
        self.body.addWidget(widget, stretch)

    def add_layout(self, layout) -> None:
        self.body.addLayout(layout)

    def set_caption(self, text: str) -> None:
        if self.caption_label is not None:
            self.caption_label.setText(text)
            self.caption_label.setVisible(bool(text))


class StatCard(QFrame):
    """Compact headline figure with label and supporting detail."""

    def __init__(
        self,
        theme: ThemeManager,
        label: str,
        value: str = "—",
        detail: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setObjectName("StatCard")
        self.setProperty("accent", "false")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(84)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(2)

        self._label = QLabel(label.upper())
        self._label.setObjectName("StatLabel")
        self._value = QLabel(value)
        self._value.setObjectName("StatValue")
        self._detail = QLabel(detail)
        self._detail.setObjectName("StatDetail")
        self._detail.setWordWrap(True)
        self._detail.setVisible(bool(detail))

        layout.addWidget(self._label)
        layout.addWidget(self._value)
        layout.addWidget(self._detail)

    def set_value(self, value: str, detail: str | None = None) -> None:
        self._value.setText(value)
        if detail is not None:
            self._detail.setText(detail)
            self._detail.setVisible(bool(detail))

    def set_accent(self, accent: bool) -> None:
        self.setProperty("accent", "true" if accent else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class NoticeBanner(QFrame):
    """Inline policy or status notice with a title and explanation."""

    def __init__(
        self,
        theme: ThemeManager,
        title: str = "",
        text: str = "",
        kind: str = "info",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setObjectName("NoticeBanner")
        self.setProperty("kind", kind)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(10)

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("NoticeTitle")
        self.text_label = QLabel(text)
        self.text_label.setObjectName("NoticeText")
        self.text_label.setWordWrap(True)
        text_box.addWidget(self.title_label)
        text_box.addWidget(self.text_label)
        layout.addLayout(text_box, 1)
        self._actions = QHBoxLayout()
        self._actions.setContentsMargins(0, 0, 0, 0)
        self._actions.setSpacing(6)
        layout.addLayout(self._actions)

    def add_action(self, widget: QWidget) -> None:
        self._actions.addWidget(widget)

    def set_message(self, title: str, text: str, kind: str | None = None) -> None:
        self.title_label.setText(title)
        self.text_label.setText(text)
        if kind is not None:
            self.setProperty("kind", kind)
            self.style().unpolish(self)
            self.style().polish(self)


def section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("SectionHeading")
    return label
