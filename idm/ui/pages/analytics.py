"""Download analytics with a self-drawn activity chart."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import QDateTime, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.settings import AppSettings
from ...core.url_utils import format_size
from .. import icons
from ..theme import ThemeManager
from .common import Card, NoticeBanner, PageScroll, StatCard

_PERIODS = (
    ("Last 7 days", 7),
    ("Last 14 days", 14),
    ("Last 30 days", 30),
    ("Last 90 days", 90),
)

_EVENT_LABELS = {
    "added": "Added to the queue",
    "started": "Started",
    "paused": "Paused",
    "resumed": "Resumed",
    "stopped": "Stopped",
    "completed": "Completed",
    "failed": "Failed",
    "removed": "Removed",
    "network-wait": "Waiting for the network",
    "network-restored": "Connection restored",
    "integrity-verified": "Integrity verified",
    "integrity-mismatch": "Checksum mismatch",
}


class ActivityChart(QWidget):
    """Stacked daily bars: completed, failed and other records."""

    def __init__(self, theme: ThemeManager, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._data: list[dict] = []
        self.setMinimumHeight(215)

    def set_data(self, data: list[dict]) -> None:
        self._data = list(data)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p = self._theme.palette
        rect = self.rect().adjusted(6, 10, -6, -6)

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
            rect.top() + 4,
            rect.width() - 12,
            rect.height() - label_height - 10,
        )
        maximum = max(1, max(int(entry.get("total") or 0) for entry in self._data))
        slot = chart.width() / len(self._data)
        bar_width = max(3.0, min(28.0, slot * 0.55))
        baseline = chart.bottom()

        painter.setPen(QPen(QColor(p.border_soft), 1))
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
                    QRectF(left, bottom - height, bar_width, max(1.5, height)),
                    2,
                    2,
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
            QRectF(chart.left(), chart.top() - 2, 60, label_height),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
            f"max {maximum}",
        )


class AnalyticsPage(QWidget):
    def __init__(
        self,
        theme: ThemeManager,
        settings: AppSettings,
        manager,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._settings = settings
        self._manager = manager
        self.setObjectName("PageArea")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        page = PageScroll(theme, self)
        root.addWidget(page)
        body = page.body

        self._notice = NoticeBanner(
            theme,
            "Local analytics",
            "Figures are calculated from the download history stored on this "
            "computer. Nothing is uploaded anywhere.",
            "info",
        )
        body.addWidget(self._notice)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        toolbar.addWidget(QLabel("Period"))
        self._period = QComboBox()
        self._period.setObjectName("PeriodCombo")
        for label, days in _PERIODS:
            self._period.addItem(label, days)
        self._period.setCurrentIndex(1)
        self._period.currentIndexChanged.connect(self.refresh)
        toolbar.addWidget(self._period)
        self._refresh_button = QPushButton("  Refresh")
        self._refresh_button.setIcon(icons.icon("refresh", theme.palette.text_muted, 14))
        self._refresh_button.clicked.connect(self.refresh)
        toolbar.addWidget(self._refresh_button)
        toolbar.addStretch(1)
        body.addLayout(toolbar)

        stats = QGridLayout()
        stats.setHorizontalSpacing(10)
        stats.setVerticalSpacing(10)
        self._total_card = StatCard(theme, "Total records", "0")
        self._completed_card = StatCard(theme, "Completed", "0")
        self._failed_card = StatCard(theme, "Failed", "0")
        self._bytes_card = StatCard(theme, "Data completed", "0 B")
        for column, card in enumerate(
            (self._total_card, self._completed_card, self._failed_card, self._bytes_card)
        ):
            stats.addWidget(card, 0, column)
            stats.setColumnStretch(column, 1)
        body.addLayout(stats)

        chart_card = Card(theme, "Daily activity", "Downloads created or completed per day")
        self._chart = ActivityChart(theme)
        chart_card.add(self._chart)
        self._chart_caption = QLabel()
        self._chart_caption.setObjectName("PanelCaption")
        chart_card.add(self._chart_caption)
        body.addWidget(chart_card)

        events_card = Card(theme, "Recent events", "The latest engine activity")
        self._events = QListWidget()
        self._events.setObjectName("ActivityList")
        self._events.setMinimumHeight(160)
        events_card.add(self._events, 1)
        body.addWidget(events_card)
        body.addStretch(1)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(600)
        self._refresh_timer.timeout.connect(self.refresh)
        manager.download_added.connect(self._schedule_refresh)
        manager.download_updated.connect(self._schedule_refresh)
        manager.download_removed.connect(self._schedule_refresh)
        theme.changed.connect(self._on_theme)
        self.refresh()

    def _schedule_refresh(self, *_args) -> None:
        if self.isVisible():
            self._refresh_timer.start()

    def _on_theme(self) -> None:
        self._chart.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def refresh(self, *_args) -> None:
        database = getattr(self._settings, "database", None)
        if database is None:
            self._chart.set_data([])
            self._events.clear()
            self._notice.set_message(
                "History unavailable",
                "The download history database is not available in this session.",
                "warning",
            )
            return
        try:
            summary = database.download_summary()
            days = int(self._period.currentData() or 14)
            rows = database.daily_activity(days)
            events = database.load_download_events(60)
        except Exception:
            self._chart.set_data([])
            self._events.clear()
            self._notice.set_message(
                "History unavailable",
                "The download history could not be read. See the log for details.",
                "danger",
            )
            return

        self._notice.set_message(
            "Local analytics",
            "Figures are calculated from the download history stored on this "
            "computer. Nothing is uploaded anywhere.",
            "info",
        )
        total = int(summary.get("total") or 0)
        completed = int(summary.get("completed") or 0)
        failed = int(summary.get("failed") or 0)
        active = int(summary.get("active") or 0)
        bytes_done = int(summary.get("completed_bytes") or 0)
        rate = (completed / total * 100) if total else 0.0
        self._total_card.set_value(str(total), f"{active} active now")
        self._completed_card.set_value(str(completed), f"{rate:.0f}% success rate")
        self._failed_card.set_value(str(failed), "Retry from the download list")
        self._bytes_card.set_value(format_size(bytes_done), "Completed files only")

        series = self._series(rows, days)
        self._chart.set_data(series)
        period_total = sum(int(entry["total"]) for entry in series)
        period_completed = sum(int(entry["completed"]) for entry in series)
        self._chart_caption.setText(
            f"{period_total} record{'s' if period_total != 1 else ''} in this period "
            f"· {period_completed} completed"
        )

        items = {item.id: item for item in self._manager.items()}
        self._events.clear()
        if not events:
            placeholder = QListWidgetItem("No download events recorded yet.")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._events.addItem(placeholder)
        known_events = set(_EVENT_LABELS)
        for record in events:
            event = str(record.get("event") or "")
            label = _EVENT_LABELS.get(event, event.replace("-", " ").title())
            if event not in known_events and not label:
                continue
            item = items.get(str(record.get("download_id") or ""))
            name = item.filename if item is not None else "Download"
            byte_count = int(record.get("bytes") or 0)
            suffix = f" · {format_size(byte_count)}" if byte_count else ""
            when = _friendly_time(str(record.get("created_at") or ""))
            self._events.addItem(
                QListWidgetItem(f"{label} — {name}{suffix}\n{when}")
            )

    @staticmethod
    def _series(rows: list[dict], days: int) -> list[dict]:
        values = {str(row.get("day") or ""): row for row in rows}
        today = date.today()
        series = []
        for offset in range(days - 1, -1, -1):
            day = (today - timedelta(days=offset)).isoformat()
            row = values.get(day, {})
            series.append(
                {
                    "day": day,
                    "total": int(row.get("total") or 0),
                    "completed": int(row.get("completed") or 0),
                    "failed": int(row.get("failed") or 0),
                    "bytes": int(row.get("bytes") or 0),
                }
            )
        return series


def _friendly_time(value: str) -> str:
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return value
    delta = QDateTime.currentDateTime().toPython() - moment
    if delta.total_seconds() < 90:
        return "Just now"
    if delta.total_seconds() < 3600:
        return f"{int(delta.total_seconds() // 60)} min ago"
    if delta.total_seconds() < 86400:
        return f"{int(delta.total_seconds() // 3600)} h ago"
    return moment.strftime("%d %b %Y, %H:%M")
