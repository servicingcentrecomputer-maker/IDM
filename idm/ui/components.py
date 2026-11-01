"""Reusable interface components for the IDM 3.5 design system.

Everything here reads colours from :class:`idm.ui.theme.ThemeManager` and
metrics from :mod:`idm.ui.design`, so pages stay visually consistent.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QObject,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    Property,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import animations, design, icons
from .theme import ThemeManager


# ---------------------------------------------------------------------------
# Layout primitives
# ---------------------------------------------------------------------------

class PageScroll(QScrollArea):
    """Vertically scrolling page with a ready-to-use body layout."""

    def __init__(self, theme: ThemeManager, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setObjectName("PageScroll")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        body_widget = QWidget()
        body_widget.setObjectName("PageScrollBody")
        self.body = QVBoxLayout(body_widget)
        self.body.setContentsMargins(2, 2, 10, 8)
        self.body.setSpacing(design.SPACING["lg"])
        self.setWidget(body_widget)


def section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("SectionHeading")
    return label


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    return line


def icon_button(
    name: str,
    theme: ThemeManager,
    tooltip: str = "",
    size: int = design.ICON_SIZE["lg"],
    color: str | None = None,
) -> QToolButton:
    button = QToolButton()
    button.setObjectName("IconButton")
    button.setToolTip(tooltip)
    button.setAccessibleName(tooltip or name)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setIcon(icons.icon(name, color or theme.palette.text_muted, size))
    button.setIconSize(animations_size(size))
    button.setFixedSize(size + 16, size + 16)
    button.setProperty("icon_name", name)
    button.setProperty("icon_size", size)
    theme.changed.connect(lambda: _refresh_icon_button(button, theme))
    return button


def animations_size(size: int):
    from PySide6.QtCore import QSize

    return QSize(size, size)


def _refresh_icon_button(button: QToolButton, theme: ThemeManager) -> None:
    try:
        name = str(button.property("icon_name") or "file")
        size = int(button.property("icon_size") or design.ICON_SIZE["lg"])
        button.setIcon(icons.icon(name, theme.palette.text_muted, size))
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# Surfaces
# ---------------------------------------------------------------------------

class Card(QFrame):
    """Panel with an optional heading, supporting action widgets."""

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
        self._layout.setContentsMargins(
            design.SPACING["lg"], design.SPACING["md"],
            design.SPACING["lg"], design.SPACING["lg"],
        )
        self._layout.setSpacing(design.SPACING["sm"])

        self.title_label = None
        self.caption_label = None
        self.actions = QHBoxLayout()
        self.actions.setContentsMargins(0, 0, 0, 0)
        self.actions.setSpacing(design.SPACING["xs"])
        if title:
            header = QHBoxLayout()
            header.setContentsMargins(0, 0, 0, 0)
            header.setSpacing(design.SPACING["sm"])
            text_box = QVBoxLayout()
            text_box.setContentsMargins(0, 0, 0, 0)
            text_box.setSpacing(1)
            self.title_label = QLabel(title)
            self.title_label.setObjectName("PanelTitle")
            text_box.addWidget(self.title_label)
            self.caption_label = QLabel(caption)
            self.caption_label.setObjectName("PanelCaption")
            self.caption_label.setVisible(bool(caption))
            self.caption_label.setWordWrap(True)
            text_box.addWidget(self.caption_label)
            header.addLayout(text_box, 1)
            header.addLayout(self.actions)
            self._layout.addLayout(header)

        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(design.SPACING["sm"])
        self._layout.addLayout(self.body)

    def add(self, widget: QWidget, stretch: int = 0) -> None:
        self.body.addWidget(widget, stretch)

    def add_layout(self, layout) -> None:
        self.body.addLayout(layout)

    def add_action(self, widget: QWidget) -> None:
        self.actions.addWidget(widget)

    def set_caption(self, text: str) -> None:
        if self.caption_label is not None:
            self.caption_label.setText(text)
            self.caption_label.setVisible(bool(text))


class StatCard(QFrame):
    """Headline figure with an icon, supporting detail and accent state."""

    def __init__(
        self,
        theme: ThemeManager,
        label: str,
        value: str = "—",
        detail: str = "",
        icon_name: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._icon_name = icon_name
        self.setObjectName("StatCard")
        self.setProperty("accent", "false")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(108)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            design.SPACING["lg"], design.SPACING["lg"],
            design.SPACING["lg"], design.SPACING["lg"],
        )
        layout.setSpacing(design.SPACING["xs"])

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(design.SPACING["sm"])
        self._label = QLabel(label.upper())
        self._label.setObjectName("StatLabel")
        top.addWidget(self._label, 1)
        self._icon = QLabel()
        self._icon.setFixedSize(32, 32)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon.setVisible(bool(icon_name))
        top.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)

        self._value = QLabel(value)
        self._value.setObjectName("StatValue")
        layout.addWidget(self._value)

        self._detail = QLabel(detail)
        self._detail.setObjectName("StatDetail")
        self._detail.setWordWrap(True)
        self._detail.setVisible(bool(detail))
        layout.addWidget(self._detail)

        theme.changed.connect(self._refresh_icon)
        self._refresh_icon()

    def _refresh_icon(self) -> None:
        if not self._icon_name:
            return
        p = self._theme.palette
        color = p.accent if self.property("accent") == "true" else p.text_faint
        self._icon.setPixmap(icons.icon(self._icon_name, color, 20).pixmap(20, 20))
        self._icon.setStyleSheet(
            f"background-color: {p.accent_soft if self.property('accent') == 'true' else p.chip_bg};"
            f" border-radius: 10px;"
        )

    def set_value(self, value: str, detail: str | None = None) -> None:
        self._value.setText(value)
        if detail is not None:
            self._detail.setText(detail)
            self._detail.setVisible(bool(detail))

    def set_accent(self, accent: bool) -> None:
        self.setProperty("accent", "true" if accent else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self._refresh_icon()


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
        layout.setContentsMargins(
            design.SPACING["md"], design.SPACING["sm"],
            design.SPACING["md"], design.SPACING["sm"],
        )
        layout.setSpacing(design.SPACING["md"])

        self._marker = QLabel()
        self._marker.setFixedSize(4, 30)
        layout.addWidget(self._marker, 0, Qt.AlignmentFlag.AlignTop)

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
        self._actions.setSpacing(design.SPACING["xs"])
        layout.addLayout(self._actions)
        theme.changed.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        p = self._theme.palette
        kind = str(self.property("kind") or "info")
        color = {
            "warning": p.warning,
            "danger": p.danger,
            "success": p.success,
        }.get(kind, p.accent)
        self._marker.setStyleSheet(f"background-color: {color}; border-radius: 2px;")

    def add_action(self, widget: QWidget) -> None:
        self._actions.addWidget(widget)

    def set_message(self, title: str, text: str, kind: str | None = None) -> None:
        self.title_label.setText(title)
        self.text_label.setText(text)
        if kind is not None:
            self.setProperty("kind", kind)
            self.style().unpolish(self)
            self.style().polish(self)
            self._refresh()


class InfoTile(QFrame):
    """Compact icon + label + value tile used in overview grids."""

    def __init__(
        self,
        theme: ThemeManager,
        title: str,
        value: str = "",
        icon_name: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("InfoTile")
        self._theme = theme
        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            design.SPACING["md"], design.SPACING["sm"],
            design.SPACING["md"], design.SPACING["sm"],
        )
        layout.setSpacing(design.SPACING["sm"])
        self._icon_name = icon_name
        self._icon = QLabel()
        self._icon.setFixedSize(24, 24)
        self._icon.setVisible(bool(icon_name))
        layout.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignVCenter)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(0)
        self._title = QLabel(title)
        self._title.setObjectName("InfoTileTitle")
        self._value = QLabel(value)
        self._value.setObjectName("InfoTileText")
        self._value.setWordWrap(True)
        text.addWidget(self._title)
        text.addWidget(self._value)
        layout.addLayout(text, 1)
        theme.changed.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        if self._icon_name:
            self._icon.setPixmap(
                icons.icon(self._icon_name, self._theme.palette.accent, 16).pixmap(16, 16)
            )

    def set_value(self, text: str) -> None:
        self._value.setText(text)


# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------

class ToggleSwitch(QAbstractButton):
    """Fluent-style animated switch used by the settings pages."""

    def __init__(self, theme: ThemeManager, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._offset = 0.0
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(46, 26)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, checked: bool) -> None:
        ms = design.duration("fast")
        self._anim.stop()
        if ms <= 0:
            self.set_offset(1.0 if checked else 0.0)
            return
        self._anim.setDuration(ms)
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def _get_offset(self) -> float:
        return self._offset

    def _set_offset(self, value: float) -> None:
        self._offset = float(value)
        self.update()

    offset = Property(float, _get_offset, _set_offset)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p = self._theme.palette
        rect = QRectF(self.rect()).adjusted(1, 2, -1, -2)
        radius = rect.height() / 2

        off = QColor(p.track)
        on = QColor(p.accent)
        t = self._offset
        track = QColor(
            int(off.red() + (on.red() - off.red()) * t),
            int(off.green() + (on.green() - off.green()) * t),
            int(off.blue() + (on.blue() - off.blue()) * t),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(rect, radius, radius)

        knob = rect.height() - 4
        x = rect.left() + 2 + (rect.width() - knob - 4) * t
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QRectF(x, rect.top() + 2, knob, knob))

        if self.hasFocus():
            pen = QPen(QColor(p.focus_ring), 2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, radius, radius)

    def sizeHint(self):
        from PySide6.QtCore import QSize

        return QSize(46, 26)


class ProgressRing(QWidget):
    """Donut used for the storage overview."""

    def __init__(self, theme: ThemeManager, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._value = 0.0
        self.setMinimumSize(120, 120)
        theme.changed.connect(self.update)

    def set_value(self, value: float) -> None:
        self._value = max(0.0, min(1.0, float(value)))
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p = self._theme.palette
        side = min(self.width(), self.height()) - 16
        rect = QRectF(
            (self.width() - side) / 2, (self.height() - side) / 2, side, side
        )
        thickness = max(9.0, side * 0.10)
        arc = rect.adjusted(thickness / 2, thickness / 2, -thickness / 2, -thickness / 2)
        painter.setPen(QPen(QColor(p.track), thickness, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(arc, 0, 360 * 16)

        if self._value > 0:
            gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
            gradient.setColorAt(0.0, QColor(p.accent_hover))
            gradient.setColorAt(1.0, QColor(p.accent_pressed))
            pen = QPen(QBrush(gradient), thickness, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawArc(arc, 90 * 16, -int(360 * 16 * self._value))

        label = QFont(self.font())
        label.setPointSizeF(max(11.0, self.font().pointSizeF() + 2.2))
        label.setWeight(QFont.Weight.Bold)
        painter.setFont(label)
        painter.setPen(QColor(p.text))
        percent = f"{round(self._value * 100)}%"
        center = QRectF(rect.left(), rect.top() + 2, rect.width(), rect.height())
        painter.drawText(center, int(Qt.AlignmentFlag.AlignCenter), percent)


class ActivityChart(QWidget):
    """Stacked daily bars: completed, failed and other records."""

    def __init__(self, theme: ThemeManager, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._data: list[dict] = []
        self.setMinimumHeight(208)

    def set_data(self, data: list[dict]) -> None:
        self._data = list(data)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p = self._theme.palette
        rect = self.rect().adjusted(6, 12, -6, -6)

        if not self._data:
            painter.setPen(QColor(p.text_faint))
            painter.drawText(
                rect,
                int(Qt.AlignmentFlag.AlignCenter),
                "No activity recorded for this period.",
            )
            return

        label_font = QFont(self.font())
        label_font.setPointSizeF(max(7.5, self.font().pointSizeF() - 1.2))
        painter.setFont(label_font)
        metrics = painter.fontMetrics()
        label_height = metrics.height() + 4
        chart = QRectF(
            rect.left() + 6,
            rect.top() + 6,
            rect.width() - 12,
            rect.height() - label_height - 12,
        )
        maximum = max(1, max(int(entry.get("total") or 0) for entry in self._data))
        slot = chart.width() / len(self._data)
        bar_width = max(4.0, min(24.0, slot * 0.50))
        baseline = chart.bottom()

        painter.setPen(QPen(QColor(p.border_soft), 1, Qt.PenStyle.DotLine))
        for fraction in (0.25, 0.5, 0.75, 1.0):
            y = baseline - chart.height() * fraction
            painter.drawLine(int(chart.left()), int(y), int(chart.right()), int(y))

        step = max(1, len(self._data) // 10)
        for index, entry in enumerate(self._data):
            total = int(entry.get("total") or 0)
            completed = int(entry.get("completed") or 0)
            failed = int(entry.get("failed") or 0)
            other = max(0, total - completed - failed)
            center = chart.left() + slot * (index + 0.5)
            left = center - bar_width / 2
            bottom = baseline

            for value, color in (
                (other, QColor(p.text_faint)),
                (failed, QColor(p.danger)),
                (completed, QColor(p.success)),
            ):
                if value <= 0:
                    continue
                height = chart.height() * value / maximum
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawRoundedRect(
                    QRectF(left, bottom - height, bar_width, max(2.0, height)),
                    4,
                    4,
                )
                bottom -= height

            if index % step == 0 or index == len(self._data) - 1:
                painter.setPen(QColor(p.text_faint))
                label = str(entry.get("day") or "")[5:]
                painter.drawText(
                    QRectF(center - slot, baseline + 3, slot * 2, label_height),
                    int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
                    label,
                )

        painter.setPen(QColor(p.text_faint))
        painter.drawText(
            QRectF(chart.left(), chart.top() - 2, 80, label_height),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
            f"peak {maximum}",
        )


# ---------------------------------------------------------------------------
# Toasts
# ---------------------------------------------------------------------------

class Toast(QFrame):
    def __init__(
        self,
        theme: ThemeManager,
        title: str,
        text: str = "",
        kind: str = "info",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setProperty("kind", kind)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            design.SPACING["md"], design.SPACING["sm"],
            design.SPACING["md"], design.SPACING["sm"],
        )
        layout.setSpacing(design.SPACING["sm"])

        icon_name = {
            "success": "check_circle",
            "warning": "info",
            "error": "info",
        }.get(kind, "info")
        color = {
            "success": theme.palette.success,
            "warning": theme.palette.warning,
            "error": theme.palette.danger,
        }.get(kind, theme.palette.accent)
        icon = QLabel()
        icon.setPixmap(icons.icon(icon_name, color, 18).pixmap(18, 18))
        icon.setFixedSize(20, 20)
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(1)
        title_label = QLabel(title)
        title_label.setObjectName("ToastTitle")
        text_box.addWidget(title_label)
        if text:
            body = QLabel(text)
            body.setObjectName("ToastText")
            body.setWordWrap(True)
            body.setMaximumWidth(320)
            text_box.addWidget(body)
        layout.addLayout(text_box, 1)
        self.setFixedWidth(380)


class ToastHost(QObject):
    """Bottom-right notification stack that never steals focus."""

    def __init__(self, parent: QWidget, theme: ThemeManager, max_visible: int = 3) -> None:
        super().__init__(parent)
        self._parent = parent
        self._theme = theme
        self._max = max_visible
        self._toasts: list[QFrame] = []
        parent.installEventFilter(self)

    def show(
        self,
        title: str,
        text: str = "",
        kind: str = "info",
        timeout_ms: int = 4200,
    ) -> None:
        toast = Toast(self._theme, title, text, kind, self._parent)
        toast.show()
        toast.adjustSize()
        self._toasts.append(toast)
        while len(self._toasts) > self._max:
            oldest = self._toasts.pop(0)
            oldest.deleteLater()
        self._reposition()
        animations.fade_in(toast, design.duration("normal"))
        if timeout_ms > 0:
            QTimer.singleShot(timeout_ms, toast, lambda: self._dismiss(toast))

    def _dismiss(self, toast: QFrame) -> None:
        if toast not in self._toasts:
            return
        self._toasts.remove(toast)
        effect = QGraphicsOpacityEffect(toast)
        toast.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", toast)
        animation.setDuration(design.duration("fast"))
        animation.setStartValue(1.0)
        animation.setEndValue(0.0)
        animation.finished.connect(toast.deleteLater)
        animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        QTimer.singleShot(design.duration("fast") + 80, self._reposition)

    def _reposition(self) -> None:
        if not self._toasts:
            return
        margin = design.SPACING["xl"]
        y = self._parent.height() - margin
        for toast in reversed(self._toasts):
            toast.adjustSize()
            y -= toast.height()
            toast.move(self._parent.width() - toast.width() - margin, y)
            y -= design.SPACING["sm"]

    def eventFilter(self, watched, event) -> bool:
        if watched is self._parent and event.type() == QEvent.Type.Resize:
            self._reposition()
        return False


__all__ = [
    "ActivityChart",
    "Card",
    "InfoTile",
    "NoticeBanner",
    "PageScroll",
    "ProgressRing",
    "StatCard",
    "Toast",
    "ToastHost",
    "ToggleSwitch",
    "divider",
    "icon_button",
    "section_label",
]
