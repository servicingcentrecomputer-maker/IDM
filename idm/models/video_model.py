"""Table model for the Video Downloads workspace."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from ..core.url_utils import format_eta, format_size, format_speed
from .download_item import DownloadItem, DownloadStatus
from .table_model import ITEM_ROLE

if TYPE_CHECKING:
    from ..engine.manager import DownloadManager

COLUMN_TITLE = 0
COLUMN_FILENAME = 1
COLUMN_FORMAT = 2
COLUMN_SIZE = 3
COLUMN_PROGRESS = 4
COLUMN_SPEED = 5
COLUMN_ETA = 6
COLUMN_STATUS = 7
COLUMN_SOURCE = 8
COLUMN_COUNT = 9

HEADERS = (
    "Title",
    "File Name",
    "Format",
    "Size",
    "Progress",
    "Speed",
    "Time Left",
    "Status",
    "Source",
)


class VideoTableModel(QAbstractTableModel):
    """Live view of every video download known to the manager."""

    def __init__(self, manager: DownloadManager, parent=None) -> None:
        super().__init__(parent)
        self._manager = manager
        self._items: list[DownloadItem] = [
            item for item in manager.items() if item.is_video
        ]
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
                COLUMN_SPEED,
                COLUMN_ETA,
            }:
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        item = self._items[index.row()]
        column = index.column()

        if role == ITEM_ROLE:
            return item

        if role == Qt.ItemDataRole.DisplayRole:
            if column == COLUMN_TITLE:
                return item.page_title or item.filename
            if column == COLUMN_FILENAME:
                return item.filename
            if column == COLUMN_FORMAT:
                return item.media_label
            if column == COLUMN_SIZE:
                return (
                    format_size(item.total_bytes)
                    if item.total_bytes is not None
                    else "—"
                )
            if column == COLUMN_PROGRESS:
                if item.status == DownloadStatus.COMPLETED:
                    return "100%"
                if item.status == DownloadStatus.QUEUED:
                    return "Queued"
                progress = item.progress
                return f"{round((progress or 0.0) * 100)}%" if progress is not None else "—"
            if column == COLUMN_SPEED:
                return format_speed(item.speed) if item.is_active else "—"
            if column == COLUMN_ETA:
                if item.status == DownloadStatus.COMPLETED:
                    return "—"
                return format_eta(item.eta) if item.is_active and item.eta else "—"
            if column == COLUMN_STATUS:
                return item.status.value
            if column == COLUMN_SOURCE:
                return item.source_domain or "—"
            return None

        if role == Qt.ItemDataRole.ToolTipRole:
            lines = [f"<b>{item.page_title or item.filename}</b>", f"URL: {item.url}"]
            if item.page_url:
                lines.append(f"Page: {item.page_url}")
            lines.append(f"Saved to: {item.path}")
            if item.media_kind:
                lines.append(f"Media: {item.media_kind} ({item.media_label})")
            if item.integrity_label:
                lines.append(f"Integrity: {item.integrity_label}")
            return "<br>".join(lines)

        if role == Qt.ItemDataRole.TextAlignmentRole and column in {
            COLUMN_SIZE,
            COLUMN_SPEED,
            COLUMN_ETA,
        }:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

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

    def refresh(self) -> None:
        self.beginResetModel()
        self._items = [item for item in self._manager.items() if item.is_video]
        self.endResetModel()

    def _on_added(self, item: DownloadItem) -> None:
        if not item.is_video:
            return
        row = len(self._items)
        self.beginInsertRows(QModelIndex(), row, row)
        self._items.append(item)
        self.endInsertRows()

    def _on_updated(self, item: DownloadItem) -> None:
        row = self.row_for_id(item.id)
        if row < 0:
            if item.is_video:
                self._on_added(item)
            return
        if not item.is_video:
            self.beginRemoveRows(QModelIndex(), row, row)
            del self._items[row]
            self.endRemoveRows()
            return
        self._items[row] = item
        self.dataChanged.emit(
            self.index(row, 0),
            self.index(row, COLUMN_COUNT - 1),
            [
                Qt.ItemDataRole.DisplayRole,
                Qt.ItemDataRole.ToolTipRole,
                ITEM_ROLE,
            ],
        )

    def _on_removed(self, download_id: str) -> None:
        row = self.row_for_id(download_id)
        if row < 0:
            return
        self.beginRemoveRows(QModelIndex(), row, row)
        del self._items[row]
        self.endRemoveRows()
