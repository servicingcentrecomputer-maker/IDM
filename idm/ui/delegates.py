"""Custom table item delegates for the download list."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QLinearGradient,
    QPainter,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from ..models.download_item import DownloadStatus
from ..models.table_model import ITEM_ROLE
from . import icons
from .theme import Palette, ThemeManager


def status_color(status: DownloadStatus, palette: Palette) -> QColor:
    if status in {DownloadStatus.CONNECTING, DownloadStatus.DOWNLOADING}:
        return QColor(palette.accent)
    if status in {
        DownloadStatus.RETRYING,
        DownloadStatus.PAUSING,
        DownloadStatus.PAUSED,
    }:
        return QColor(palette.warning)
    if status == DownloadStatus.COMPLETED:
        return QColor(palette.success)
    if status == DownloadStatus.FAILED:
        return QColor(palette.danger)
    if status == DownloadStatus.QUEUED:
        return QColor(palette.text_faint)
    return QColor(palette.text_muted)


class _BaseDelegate(QStyledItemDelegate):
    def __init__(self, theme: ThemeManager, parent=None) -> None:
        super().__init__(parent)
        self._theme = theme

    def _paint_background(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        opt.icon = QIcon()
        style = option.widget.style() if option.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, option.widget)

    def _paint_separator(self, painter: QPainter, option: QStyleOptionViewItem) -> None:
        p = self._theme.palette
        painter.save()
        painter.setPen(QPen(QColor(p.border_soft), 1))
        y = option.rect.bottom()
        painter.drawLine(option.rect.left(), y, option.rect.right(), y)
        painter.restore()

    @staticmethod
    def _is_selected(option: QStyleOptionViewItem) -> bool:
        return bool(option.state & QStyle.StateFlag.State_Selected)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        size = super().sizeHint(option, index)
        return QSize(size.width(), 64)


class NameDelegate(_BaseDelegate):
    """File name cell with the download progress bar underneath."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        item = index.data(ITEM_ROLE)
        if item is None:
            super().paint(painter, option, index)
            return

        painter.save()
        self._paint_background(painter, option, index)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p = self._theme.palette

        outer = option.rect.adjusted(16, 0, -14, 0)
        icon_box = QRect(outer.left(), outer.center().y() - 19, 38, 38)
        tint = QColor(icons.category_color(item.category))
        tint.setAlpha(42 if self._is_selected(option) else 28)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(tint)
        painter.drawRoundedRect(QRectF(icon_box), 11, 11)

        cat_icon = icons.category_icon(item.category, size=20)
        cat_icon.paint(
            painter,
            icon_box.adjusted(9, 9, -9, -9),
            Qt.AlignmentFlag.AlignCenter,
            QIcon.Mode.Normal,
            QIcon.State.Off,
        )

        text_left = icon_box.right() + 13
        text_width = max(10, outer.right() - text_left)
        selected = self._is_selected(option)
        text_color = (
            option.palette.color(QPalette.ColorRole.HighlightedText)
            if selected
            else QColor(p.text)
        )
        muted_color = (
            option.palette.color(QPalette.ColorRole.HighlightedText)
            if selected
            else QColor(p.text_muted)
        )

        name_font = QFont(option.font)
        name_font.setPointSizeF(max(9.0, option.font.pointSizeF() + 0.6))
        name_font.setWeight(QFont.Weight.DemiBold)
        name_rect = QRect(text_left, icon_box.top() - 2, text_width, 22)
        painter.setFont(name_font)
        painter.setPen(text_color)
        name_metrics = QFontMetrics(name_font)
        elided_name = name_metrics.elidedText(
            item.filename, Qt.TextElideMode.ElideMiddle, text_width
        )
        painter.drawText(
            name_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            elided_name,
        )

        fraction = item.progress
        if item.status == DownloadStatus.COMPLETED:
            fraction = 1.0
        label = f"{round((fraction or 0.0) * 100)}%"
        if item.status == DownloadStatus.QUEUED:
            label = "Queued"
        elif item.status == DownloadStatus.COMPLETED:
            label = "100%"
        elif fraction is None and item.status in {
            DownloadStatus.DOWNLOADING,
            DownloadStatus.CONNECTING,
            DownloadStatus.RETRYING,
        }:
            label = "…"

        label_font = QFont(option.font)
        label_font.setPointSizeF(max(8.0, option.font.pointSizeF() - 0.8))
        label_metrics = QFontMetrics(label_font)
        label_width = max(
            label_metrics.horizontalAdvance("100%"),
            label_metrics.horizontalAdvance("Queued"),
        ) + 8
        bar_width = max(0, text_width - label_width - 10)
        bar_rect = QRect(text_left, icon_box.top() + 27, bar_width, 6)
        bar_color = QColor(p.track)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bar_color)
        painter.drawRoundedRect(QRectF(bar_rect), 3, 3)
        if fraction and fraction > 0:
            fill_width = max(0.0, bar_rect.width() * min(1.0, fraction))
            if fill_width >= 1:
                fill = QRectF(
                    bar_rect.left(), bar_rect.top(), fill_width, bar_rect.height()
                )
                if item.status == DownloadStatus.FAILED:
                    painter.setBrush(QColor(p.danger))
                elif item.status in {DownloadStatus.PAUSED, DownloadStatus.STOPPED}:
                    painter.setBrush(QColor(p.warning))
                else:
                    gradient = QLinearGradient(fill.topLeft(), fill.topRight())
                    gradient.setColorAt(0.0, QColor(p.accent_hover))
                    gradient.setColorAt(1.0, QColor(p.accent))
                    painter.setBrush(gradient)
                painter.drawRoundedRect(fill, 3, 3)

        painter.setFont(label_font)
        painter.setPen(muted_color)
        label_rect = QRect(bar_rect.right() + 8, bar_rect.top() - 6, label_width, 18)
        painter.drawText(
            label_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            label,
        )

        self._paint_separator(painter, option)
        painter.restore()


class StatusDelegate(_BaseDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        item = index.data(ITEM_ROLE)
        if item is None:
            super().paint(painter, option, index)
            return

        painter.save()
        self._paint_background(painter, option, index)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p = self._theme.palette
        color = status_color(item.status, p)

        font = QFont(option.font)
        font.setPointSizeF(max(8.5, option.font.pointSizeF() - 0.2))
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        label = item.status.value

        pill_width = min(
            max(48, option.rect.width() - 24),
            metrics.horizontalAdvance(label) + 30,
        )
        pill = QRect(
            option.rect.left() + 14,
            option.rect.center().y() - 11,
            pill_width,
            22,
        )
        fill = QColor(color)
        fill.setAlpha(46 if self._is_selected(option) else 32)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(pill, 11, 11)

        painter.setBrush(color)
        painter.drawEllipse(QRect(pill.left() + 9, pill.center().y() - 3, 6, 6))

        painter.setPen(color)
        text_rect = QRect(
            pill.left() + 19,
            pill.top(),
            pill.width() - 23,
            pill.height(),
        )
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            label,
        )

        self._paint_separator(painter, option)
        painter.restore()


class TextDelegate(_BaseDelegate):
    """Left-aligned text cell with an optional muted or emphasised style."""

    def __init__(self, theme: ThemeManager, parent=None, *, muted=False, strong=False) -> None:
        super().__init__(theme, parent)
        self._muted = muted
        self._strong = strong

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        self._paint_background(painter, option, index)
        p = self._theme.palette
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")

        font = QFont(option.font)
        if self._strong:
            font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        if self._is_selected(option):
            color = option.palette.color(QPalette.ColorRole.HighlightedText)
        elif self._muted:
            color = QColor(p.text_muted)
        else:
            color = QColor(p.text)
        painter.setPen(color)

        rect = option.rect.adjusted(16, 0, -12, 0)
        metrics = QFontMetrics(font)
        elided = metrics.elidedText(text, Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(
            rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            elided,
        )

        self._paint_separator(painter, option)
        painter.restore()


class ProgressDelegate(_BaseDelegate):
    """Progress bar with a percentage label, used by the video table."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        item = index.data(ITEM_ROLE)
        if item is None:
            super().paint(painter, option, index)
            return

        painter.save()
        self._paint_background(painter, option, index)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p = self._theme.palette

        fraction = 1.0 if item.status == DownloadStatus.COMPLETED else (item.progress or 0.0)
        if item.status == DownloadStatus.QUEUED:
            label = "Queued"
        else:
            label = f"{round(fraction * 100)}%"
        if self._is_selected(option):
            label_color = option.palette.color(QPalette.ColorRole.HighlightedText)
        else:
            label_color = QColor(p.text_muted)

        font = QFont(option.font)
        font.setPointSizeF(max(8.0, option.font.pointSizeF() - 0.5))
        painter.setFont(font)
        label_width = QFontMetrics(font).horizontalAdvance("100%") + 8
        bar = QRect(
            option.rect.left() + 16,
            option.rect.center().y() - 3,
            max(10, option.rect.width() - label_width - 30),
            6,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(p.track))
        painter.drawRoundedRect(QRectF(bar), 3, 3)

        if fraction > 0:
            width = max(0.0, bar.width() * min(1.0, fraction))
            if width >= 1:
                fill_rect = QRectF(bar.left(), bar.top(), width, bar.height())
                if item.status == DownloadStatus.FAILED:
                    painter.setBrush(QColor(p.danger))
                elif item.status in {DownloadStatus.PAUSED, DownloadStatus.STOPPED}:
                    painter.setBrush(QColor(p.warning))
                else:
                    gradient = QLinearGradient(fill_rect.topLeft(), fill_rect.topRight())
                    gradient.setColorAt(0.0, QColor(p.accent_hover))
                    gradient.setColorAt(1.0, QColor(p.accent))
                    painter.setBrush(gradient)
                painter.drawRoundedRect(fill_rect, 3, 3)

        painter.setPen(label_color)
        label_rect = QRect(
            bar.right() + 7,
            option.rect.top(),
            label_width,
            option.rect.height(),
        )
        painter.drawText(
            label_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            label,
        )

        self._paint_separator(painter, option)
        painter.restore()


class ValueDelegate(_BaseDelegate):
    """Right-aligned secondary values (size, time left, rate, last try)."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        self._paint_background(painter, option, index)
        p = self._theme.palette
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")

        font = QFont(option.font)
        font.setPointSizeF(max(8.0, option.font.pointSizeF() - 0.2))
        painter.setFont(font)
        if self._is_selected(option):
            color = option.palette.color(QPalette.ColorRole.HighlightedText)
        elif index.column() == 5:
            color = QColor(p.text_muted)
        else:
            color = QColor(p.text)
        painter.setPen(color)

        rect = option.rect.adjusted(8, 0, -16, 0)
        alignment = index.data(Qt.ItemDataRole.TextAlignmentRole)
        flags = Qt.AlignmentFlag(int(alignment)) if alignment else (
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        metrics = QFontMetrics(font)
        elided = metrics.elidedText(text, Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(rect, int(flags), elided)

        self._paint_separator(painter, option)
        painter.restore()
