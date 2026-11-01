"""Live performance monitor and transfer tuning."""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...core.settings import AppSettings
from ...core.url_utils import format_speed
from .. import icons
from ..theme import ThemeManager
from .common import Card, PageScroll, StatCard


class SpeedGraph(QWidget):
    """Sixty-second rolling transfer-rate graph."""

    SAMPLES = 60

    def __init__(self, theme: ThemeManager, manager, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._manager = manager
        self._points: deque[float] = deque([0.0] * self.SAMPLES, maxlen=self.SAMPLES)
        self.setMinimumHeight(170)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._sample)

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def reset(self) -> None:
        self._points = deque([0.0] * self.SAMPLES, maxlen=self.SAMPLES)
        self.update()

    def _sample(self) -> None:
        self._points.append(float(self._manager.total_speed))
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p = self._theme.palette
        rect = QRectF(self.rect().adjusted(8, 12, -8, -10))
        peak = max(self._points) if self._points else 0.0
        scale = max(64.0 * 1024, peak * 1.15)
        mid = rect.center().y()

        painter.setPen(QPen(QColor(p.border_soft), 1))
        painter.drawLine(int(rect.left()), int(rect.top()), int(rect.right()), int(rect.top()))
        painter.drawLine(int(rect.left()), int(mid), int(rect.right()), int(mid))
        painter.drawLine(
            int(rect.left()), int(rect.bottom()), int(rect.right()), int(rect.bottom())
        )

        painter.setFont(QFont(self.font().family(), max(7, self.font().pointSize() - 2)))
        painter.setPen(QColor(p.text_faint))
        painter.drawText(
            QRectF(rect.left(), rect.top() - 11, 120, 12),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
            f"peak {format_speed(peak)}",
        )

        if not any(self._points):
            painter.drawText(
                rect,
                int(Qt.AlignmentFlag.AlignCenter),
                "Waiting for transfer activity…",
            )
            return

        step = rect.width() / max(1, len(self._points) - 1)
        path = []
        for index, value in enumerate(self._points):
            x = rect.left() + step * index
            y = rect.bottom() - (value / scale) * rect.height()
            path.append(QPointF(x, y))

        area = QLinearGradient(0, rect.top(), 0, rect.bottom())
        accent = QColor(p.accent)
        area.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 90))
        area.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 5))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(area)
        polygon = QPolygonF(
            [QPointF(rect.left(), rect.bottom())]
            + path
            + [QPointF(rect.right(), rect.bottom())]
        )
        painter.drawPolygon(polygon)

        pen = QPen(QColor(p.accent), 2)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline(QPolygonF(path))


class PerformancePage(QWidget):
    message = Signal(str)
    settings_applied = Signal()
    options_requested = Signal()

    def __init__(
        self,
        theme: ThemeManager,
        manager,
        settings: AppSettings,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._manager = manager
        self._settings = settings
        self.setObjectName("PageArea")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        page = PageScroll(theme, self)
        root.addWidget(page)
        body = page.body

        stats = QGridLayout()
        stats.setHorizontalSpacing(10)
        stats.setVerticalSpacing(10)
        self._active_card = StatCard(theme, "Active transfers", "0")
        self._speed_card = StatCard(theme, "Combined speed", "0 B/s")
        self._queue_card = StatCard(theme, "Queued", "0")
        self._connection_card = StatCard(theme, "Connection slots", "0")
        self._active_card.set_accent(True)
        for column, card in enumerate(
            (self._active_card, self._speed_card, self._queue_card, self._connection_card)
        ):
            stats.addWidget(card, 0, column)
            stats.setColumnStretch(column, 1)
        body.addLayout(stats)

        graph_card = Card(
            theme,
            "Transfer rate",
            "Live combined throughput over the last 60 seconds",
        )
        self._graph = SpeedGraph(theme, manager)
        graph_card.add(self._graph)
        clear = QPushButton("Reset graph")
        clear.setObjectName("SubtleButton")
        clear.clicked.connect(self._graph.reset)
        graph_card.body.addWidget(clear, 0, Qt.AlignmentFlag.AlignRight)
        body.addWidget(graph_card)

        tuning = Card(theme, "Performance tuning", "Changes apply to new connections immediately")
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(9)

        self._concurrent_spin = QSpinBox()
        self._concurrent_spin.setRange(1, 10)
        self._concurrent_spin.setSuffix(" downloads")
        self._concurrent_spin.setToolTip("How many downloads may run at the same time.")
        self._connections_spin = QSpinBox()
        self._connections_spin.setRange(1, 16)
        self._connections_spin.setSuffix(" connections")
        self._connections_spin.setToolTip(
            "Parallel HTTP connections for servers that support byte ranges."
        )
        self._speed_spin = QSpinBox()
        self._speed_spin.setRange(0, 1024 * 1024)
        self._speed_spin.setSingleStep(64)
        self._speed_spin.setSuffix(" KB/s")
        self._speed_spin.setSpecialValueText("Unlimited")
        self._retry_check = QCheckBox("Retry transient failures automatically")
        self._network_check = QCheckBox("Resume automatically when the network returns")

        rows = (
            ("Simultaneous downloads", self._concurrent_spin, "1–10"),
            ("Connections per download", self._connections_spin, "1–16"),
            ("Global speed limit", self._speed_spin, "0 means unlimited"),
            ("Retry policy", self._retry_check, ""),
            ("Network recovery", self._network_check, ""),
        )
        for row, (title, widget, hint) in enumerate(rows):
            label = QLabel(title)
            label.setObjectName("SettingTitle")
            grid.addWidget(label, row, 0)
            if hint:
                detail = QLabel(hint)
                detail.setObjectName("SettingHint")
                grid.addWidget(detail, row, 1)
            grid.addWidget(widget, row, 2)
        grid.setColumnStretch(2, 1)
        tuning.add_layout(grid)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self._apply_button = QPushButton("Apply")
        self._apply_button.setObjectName("PrimaryButton")
        self._apply_button.clicked.connect(self._apply)
        buttons.addWidget(self._apply_button)
        self._reload_button = QPushButton("Reload")
        self._reload_button.setObjectName("SubtleButton")
        self._reload_button.clicked.connect(self._load)
        buttons.addWidget(self._reload_button)
        options = QPushButton("  Advanced options")
        options.setIcon(icons.icon("options", theme.palette.text_muted, 14))
        options.clicked.connect(self.options_requested)
        buttons.addWidget(options)
        buttons.addStretch(1)
        tuning.add_layout(buttons)
        body.addWidget(tuning)
        body.addStretch(1)

        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(600)
        self._stats_timer.timeout.connect(self._refresh_stats)
        manager.stats_changed.connect(self._refresh_stats)
        manager.queue_changed.connect(self._refresh_stats)
        manager.download_added.connect(self._on_manager_changed)
        manager.download_removed.connect(self._on_manager_changed)
        theme.changed.connect(self._graph.update)
        self._load()
        self._refresh_stats()

    # ------------------------------------------------------------------ lifecycle
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._load()
        self._refresh_stats()
        self._graph.start()
        self._stats_timer.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._graph.stop()
        self._stats_timer.stop()

    def _on_manager_changed(self, *_args) -> None:
        if self.isVisible():
            self._refresh_stats()

    def _load(self) -> None:
        self._concurrent_spin.setValue(int(self._settings.max_concurrent))
        self._connections_spin.setValue(int(self._settings.connections_per_download))
        self._speed_spin.setValue(int(self._settings.speed_limit_kbps))
        self._retry_check.setChecked(bool(self._settings.auto_retry))
        self._network_check.setChecked(bool(self._settings.auto_resume_on_network))

    def _apply(self) -> None:
        self._settings.max_concurrent = int(self._concurrent_spin.value())
        self._settings.connections_per_download = int(self._connections_spin.value())
        self._settings.speed_limit_kbps = int(self._speed_spin.value())
        self._settings.auto_retry = bool(self._retry_check.isChecked())
        self._settings.auto_resume_on_network = bool(self._network_check.isChecked())
        self._settings.save()
        self._manager.apply_settings()
        self._refresh_stats()
        self.settings_applied.emit()
        self.message.emit("Performance settings applied.")

    def _refresh_stats(self, *_args) -> None:
        active = self._manager.active_count
        speed = self._manager.total_speed
        queued = len(self._manager.queue_items())
        workers = len(getattr(self._manager, "_workers", {}))
        self._active_card.set_value(str(active), f"{workers} worker{'s' if workers != 1 else ''}")
        self._speed_card.set_value(format_speed(speed) if speed > 0 else "0 B/s")
        self._queue_card.set_value(str(queued), "Waiting for a slot")
        slots = int(self._manager.max_concurrent) * int(
            getattr(self._manager, "connections_per_download", 1)
        )
        self._connection_card.set_value(
            str(slots),
            f"{self._manager.max_concurrent} × "
            f"{getattr(self._manager, 'connections_per_download', 1)} connections",
        )
