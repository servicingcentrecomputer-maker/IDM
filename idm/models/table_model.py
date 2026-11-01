"""Table model and filter proxy for the download list."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
)
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from ..constants import CATEGORY_FILTER_KEYS
from ..core.url_utils import format_eta, format_last_try, format_size, format_speed
from .download_item import DownloadItem, DownloadStatus

if TYPE_CHECKING:
    from ..engine.manager import DownloadManager

logger = logging.getLogger(__name__)

COLUMN_NAME = 0
COLUMN_SIZE = 1
COLUMN_CATEGORY = 2
COLUMN_STATUS = 3
COLUMN_ETA = 4
COLUMN_SPEED = 5
COLUMN_LAST_TRY = 6
COLUMN_COUNT = 7

HEADERS = (
    "File Name",
    "Size",
    "Category",
    "Status",
    "Time Left",
    "Transfer Rate",
    "Last Try",
)

ITEM_ROLE = Qt.ItemDataRole.UserRole + 1
STATUS_ROLE = Qt.ItemDataRole.UserRole + 2
PROGRESS_ROLE = Qt.ItemDataRole.UserRole + 3
SORT_ROLE = Qt.ItemDataRole.UserRole + 4

_DOWNLOADING_FILTER_STATUSES = {
    DownloadStatus.QUEUED,
    DownloadStatus.CONNECTING,
    DownloadStatus.DOWNLOADING,
    DownloadStatus.RETRYING,
    DownloadStatus.PAUSING,
    DownloadStatus.STOPPING,
}

_HISTORY_FILTER_STATUSES = {
    DownloadStatus.COMPLETED,
    DownloadStatus.FAILED,
    DownloadStatus.STOPPED,
}

_STATUS_SORT_ORDER = {
    DownloadStatus.CONNECTING: 0,
    DownloadStatus.DOWNLOADING: 1,
    DownloadStatus.RETRYING: 2,
    DownloadStatus.QUEUED: 3,
    DownloadStatus.PAUSING: 4,
    DownloadStatus.PAUSED: 5,
    DownloadStatus.STOPPING: 6,
    DownloadStatus.STOPPED: 7,
    DownloadStatus.FAILED: 8,
    DownloadStatus.COMPLETED: 9,
}


class DownloadTableModel(QAbstractTableModel):
    def __init__(self, manager: DownloadManager, parent=None) -> None:
        super().__init__(parent)
        self._manager = manager
        self._items: list[DownloadItem] = list(manager.items())
        manager.download_added.connect(self._on_added)
        manager.download_updated.connect(self._on_updated)
        manager.download_removed.connect(self._on_removed)

    def rowCount(self, parent=None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self._items)

    def columnCount(self, parent=None) -> int:
        return 0 if parent is not None and parent.isValid() else COLUMN_COUNT

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal:
            if role == Qt.ItemDataRole.DisplayRole and 0 <= section < len(HEADERS):
                return HEADERS[section]
            if role == Qt.ItemDataRole.TextAlignmentRole and section in {
                COLUMN_SIZE,
                COLUMN_ETA,
                COLUMN_SPEED,
                COLUMN_LAST_TRY,
            }:
                return int(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        item = self._items[index.row()]
        column = index.column()

        if role == ITEM_ROLE:
            return item
        if role == STATUS_ROLE:
            return item.status
        if role == PROGRESS_ROLE:
            return item.progress
        if role == SORT_ROLE:
            return _sort_value(item, column)

        if role == Qt.ItemDataRole.DisplayRole:
            if column == COLUMN_NAME:
                return item.filename
            if column == COLUMN_SIZE:
                return format_size(item.total_bytes) if item.total_bytes is not None else "—"
            if column == COLUMN_CATEGORY:
                return item.category or "Other"
            if column == COLUMN_STATUS:
                return item.status.value
            if column == COLUMN_ETA:
                if item.status == DownloadStatus.COMPLETED:
                    return "—"
                return format_eta(item.eta) if item.is_active else "—"
            if column == COLUMN_SPEED:
                return format_speed(item.speed) if item.is_active else "—"
            if column == COLUMN_LAST_TRY:
                return format_last_try(item.last_try)
            return None

        if role == Qt.ItemDataRole.ToolTipRole:
            lines = [
                f"<b>{item.filename}</b>",
                f"Category: {item.category}",
                f"From: {item.url}",
                f"To: {item.path}",
            ]
            if item.source_browser:
                lines.append(f"Source: {item.source_browser.capitalize()}")
            if item.referrer:
                lines.append(f"Referrer: {item.referrer}")
            if item.total_bytes:
                lines.append(
                    f"Size: {format_size(item.downloaded_bytes)} of {format_size(item.total_bytes)}"
                )
            if item.last_try:
                lines.append(f"Last try: {item.last_try:%Y-%m-%d %H:%M:%S}")
            if item.error:
                lines.append(f"<span style='color:#f87171'>{item.error}</span>")
            return "<br>".join(lines)

        if role == Qt.ItemDataRole.TextAlignmentRole and column in {
            COLUMN_SIZE,
            COLUMN_ETA,
            COLUMN_SPEED,
        }:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        if role == Qt.ItemDataRole.ForegroundRole and column in {
            COLUMN_SIZE,
            COLUMN_CATEGORY,
            COLUMN_ETA,
            COLUMN_SPEED,
            COLUMN_LAST_TRY,
        }:
            palette = QApplication.palette()
            return palette.color(QPalette.ColorRole.PlaceholderText)

        if role == Qt.ItemDataRole.ForegroundRole and column == COLUMN_STATUS:
            if item.status == DownloadStatus.FAILED:
                return QColor("#c94b4b")
            return None

        return None

    def item_at(self, row: int) -> DownloadItem | None:
        if 0 <= row < len(self._items):
            return self._items[row]
        return None

    def row_for_id(self, download_id: str) -> int:
        for row, item in enumerate(self._items):
            if item.id == download_id:
                return row
        return -1

    def _on_added(self, item: DownloadItem) -> None:
        row = len(self._items)
        self.beginInsertRows(QModelIndex(), row, row)
        self._items.append(item)
        self.endInsertRows()

    def _on_updated(self, item: DownloadItem) -> None:
        row = self.row_for_id(item.id)
        if row < 0:
            return
        self._items[row] = item
        top = self.index(row, 0)
        bottom = self.index(row, COLUMN_COUNT - 1)
        self.dataChanged.emit(
            top,
            bottom,
            [
                Qt.ItemDataRole.DisplayRole,
                Qt.ItemDataRole.ToolTipRole,
                Qt.ItemDataRole.ForegroundRole,
                ITEM_ROLE,
                STATUS_ROLE,
                PROGRESS_ROLE,
                SORT_ROLE,
            ],
        )

    def _on_removed(self, download_id: str) -> None:
        row = self.row_for_id(download_id)
        if row < 0:
            return
        self.beginRemoveRows(QModelIndex(), row, row)
        del self._items[row]
        self.endRemoveRows()


def _sort_value(item: DownloadItem, column: int) -> Any:
    if column == COLUMN_NAME:
        return item.filename.casefold()
    if column == COLUMN_SIZE:
        return item.total_bytes if item.total_bytes is not None else -1
    if column == COLUMN_CATEGORY:
        return (item.category or "").casefold()
    if column == COLUMN_STATUS:
        return _STATUS_SORT_ORDER.get(item.status, 99)
    if column == COLUMN_ETA:
        if item.eta is None:
            return float("inf")
        return item.eta
    if column == COLUMN_SPEED:
        return item.speed
    if column == COLUMN_LAST_TRY:
        return item.last_try.timestamp() if item.last_try else 0.0
    return ""


class DownloadFilterProxyModel(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._filter_key = "all"
        self._search = ""
        self.setDynamicSortFilter(True)
        self.setSortRole(SORT_ROLE)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def set_filter_key(self, key: str) -> None:
        if key != self._filter_key:
            self._filter_key = key
            self.beginFilterChange()
            self.endFilterChange()

    def set_search(self, text: str) -> None:
        search = text.strip().lower()
        if search != self._search:
            self._search = search
            self.beginFilterChange()
            self.endFilterChange()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        source = self.sourceModel()
        if not isinstance(source, DownloadTableModel):
            return True
        item = source.item_at(source_row)
        if item is None:
            return False

        if self._filter_key == "downloading":
            if item.status not in _DOWNLOADING_FILTER_STATUSES:
                return False
        elif self._filter_key == "completed":
            if item.status != DownloadStatus.COMPLETED:
                return False
        elif self._filter_key == "queued":
            if item.status != DownloadStatus.QUEUED:
                return False
        elif self._filter_key == "paused":
            if item.status not in {DownloadStatus.PAUSED, DownloadStatus.STOPPED}:
                return False
        elif self._filter_key == "history":
            if item.status not in _HISTORY_FILTER_STATUSES:
                return False
        elif (
            self._filter_key in CATEGORY_FILTER_KEYS
            and item.category != CATEGORY_FILTER_KEYS[self._filter_key]
        ):
            return False

        if self._search:
            haystack = "\n".join(
                (
                    item.filename,
                    item.url,
                    item.category or "",
                    item.source_domain or "",
                )
            ).lower()
            if self._search not in haystack:
                return False
        return True

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        left_value = left.data(SORT_ROLE)
        right_value = right.data(SORT_ROLE)
        if left_value is None:
            return True
        if right_value is None:
            return False
        try:
            return left_value < right_value
        except TypeError:
            return str(left_value) < str(right_value)
