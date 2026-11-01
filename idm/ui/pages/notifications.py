"""Notification centre backed by the local SQLite history."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.settings import AppSettings
from .. import icons
from ..theme import ThemeManager
from .common import Card, NoticeBanner, PageScroll

_KIND_LABELS = {
    "completed": "Completed",
    "failed": "Failed",
    "network": "Connection",
    "integrity": "Integrity",
    "update": "Update",
    "info": "Info",
}


class NotificationsPage(QWidget):
    item_requested = Signal(str)
    message = Signal(str)

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
            "Download notifications",
            "Completion, failure and network notices are stored locally so you "
            "can review them after the fact.",
            "info",
        )
        body.addWidget(self._notice)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        toolbar.addWidget(QLabel("Show"))
        self._filter = QComboBox()
        self._filter.addItem("All notifications", False)
        self._filter.addItem("Unread only", True)
        self._filter.currentIndexChanged.connect(self.refresh)
        toolbar.addWidget(self._filter)
        toolbar.addStretch(1)
        self._read_button = QPushButton("Mark all read")
        self._read_button.clicked.connect(self._mark_all_read)
        self._delete_button = QPushButton("Delete selected")
        self._delete_button.clicked.connect(self._delete_selected)
        self._clear_button = QPushButton("Clear all")
        self._clear_button.setObjectName("DangerButton")
        self._clear_button.clicked.connect(self._clear_all)
        self._refresh_button = QPushButton("  Refresh")
        self._refresh_button.setIcon(icons.icon("refresh", theme.palette.text_muted, 14))
        self._refresh_button.clicked.connect(self.refresh)
        for button in (
            self._read_button,
            self._delete_button,
            self._clear_button,
            self._refresh_button,
        ):
            toolbar.addWidget(button)
        body.addLayout(toolbar)

        card = Card(theme)
        card.body.setContentsMargins(0, 0, 0, 0)
        self._list = QListWidget()
        self._list.setObjectName("NotificationList")
        self._list.setMinimumHeight(300)
        self._list.itemSelectionChanged.connect(self._update_actions)
        self._list.itemDoubleClicked.connect(self._open_item)
        card.add(self._list, 1)
        body.addWidget(card, 1)
        body.addStretch(1)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(400)
        self._refresh_timer.timeout.connect(self.refresh)
        manager.download_completed.connect(self._schedule_refresh)
        manager.download_failed.connect(self._schedule_refresh)
        theme.changed.connect(self.refresh)
        self._update_actions()
        self.refresh()

    def _schedule_refresh(self, *_args) -> None:
        if self.isVisible():
            self._refresh_timer.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def refresh(self, *_args) -> None:
        database = getattr(self._settings, "database", None)
        self._list.clear()
        self._notice.set_message(
            "Download notifications",
            "Completion, failure and network notices are stored locally so you "
            "can review them after the fact.",
            "info",
        )
        if database is None:
            self._notice.set_message(
                "Notifications unavailable",
                "The local history database is not available in this session.",
                "warning",
            )
            self._update_actions()
            return
        try:
            unread_only = bool(self._filter.currentData())
            records = database.load_notifications(limit=300, unread_only=unread_only)
            unread = database.unread_notification_count()
        except Exception:
            self._notice.set_message(
                "Notifications unavailable",
                "The notification history could not be read. See the log for details.",
                "danger",
            )
            self._update_actions()
            return
        if records:
            self._notice.set_message(
                "Download notifications",
                f"{unread} unread notification{'s' if unread != 1 else ''} · "
                f"{len(records)} shown",
                "info",
            )
        if not records:
            placeholder = QListWidgetItem(
                "No notifications yet. Completed and failed downloads will appear here."
            )
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(placeholder)
        for record in records:
            kind = str(record.get("kind") or "info")
            prefix = "" if record.get("read_at") else "●  "
            title = f"{prefix}{record.get('title', '')}"
            body_text = str(record.get("message") or "")
            when = _relative_time(str(record.get("created_at") or ""))
            meta = _KIND_LABELS.get(kind, kind.title())
            text = f"{title}\n{body_text}" if body_text else title
            text += f"\n{meta} · {when}"
            entry = QListWidgetItem(text)
            entry.setData(Qt.ItemDataRole.UserRole, int(record.get("id") or 0))
            entry.setData(
                Qt.ItemDataRole.UserRole + 1, str(record.get("download_id") or "")
            )
            if not record.get("read_at"):
                entry.setData(Qt.ItemDataRole.UserRole + 2, True)
            self._list.addItem(entry)
        self._update_actions()

    def _selected_entries(self) -> list[QListWidgetItem]:
        return [
            item
            for item in self._list.selectedItems()
            if item.data(Qt.ItemDataRole.UserRole)
        ]

    def _update_actions(self) -> None:
        entries = self._selected_entries()
        self._read_button.setEnabled(bool(self._list.count()))
        self._delete_button.setEnabled(bool(entries))
        self._clear_button.setEnabled(bool(self._list.count()))

    def _mark_all_read(self) -> None:
        database = getattr(self._settings, "database", None)
        if database is None:
            return
        try:
            count = database.mark_all_notifications_read()
        except Exception:
            self.message.emit("Notifications could not be updated.")
            return
        self.message.emit(
            f"Marked {count} notification{'s' if count != 1 else ''} as read."
            if count
            else "There are no unread notifications."
        )
        self.refresh()
        _refresh_badges(self.window())

    def _delete_selected(self) -> None:
        database = getattr(self._settings, "database", None)
        if database is None:
            return
        entries = self._selected_entries()
        if not entries:
            return
        try:
            for entry in entries:
                database.delete_notification(int(entry.data(Qt.ItemDataRole.UserRole)))
        except Exception:
            self.message.emit("The selected notifications could not be deleted.")
            return
        self.message.emit(
            f"Deleted {len(entries)} notification{'s' if len(entries) != 1 else ''}."
        )
        self.refresh()
        _refresh_badges(self.window())

    def _clear_all(self) -> None:
        database = getattr(self._settings, "database", None)
        if database is None:
            return
        try:
            count = database.clear_notifications()
        except Exception:
            self.message.emit("Notifications could not be cleared.")
            return
        self.message.emit(
            f"Cleared {count} notification{'s' if count != 1 else ''}."
            if count
            else "There are no notifications to clear."
        )
        self.refresh()
        _refresh_badges(self.window())

    def _open_item(self, item: QListWidgetItem) -> None:
        database = getattr(self._settings, "database", None)
        notification_id = int(item.data(Qt.ItemDataRole.UserRole) or 0)
        if database is not None and notification_id:
            try:
                database.mark_notification_read(notification_id)
            except Exception:
                pass
        download_id = str(item.data(Qt.ItemDataRole.UserRole + 1) or "")
        if download_id:
            self.refresh()
            _refresh_badges(self.window())
            self.item_requested.emit(download_id)
        else:
            self.refresh()
            _refresh_badges(self.window())


def _relative_time(value: str) -> str:
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return value
    delta = datetime.now() - moment
    if delta.total_seconds() < 90:
        return "just now"
    if delta.total_seconds() < 3600:
        return f"{int(delta.total_seconds() // 60)} min ago"
    if delta.total_seconds() < 86400:
        return f"{int(delta.total_seconds() // 3600)} h ago"
    return moment.strftime("%d %b %Y, %H:%M")


def _refresh_badges(window) -> None:
    refresh = getattr(window, "_refresh_sidebar_badges", None)
    if callable(refresh):
        refresh()
