"""Modeless download progress window."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSpinBox,
    QVBoxLayout,
)

from integrations.browser_detector import browser_display_name

from ...constants import MAX_SPEED_LIMIT_KBPS
from ...core.url_utils import format_eta, format_size, format_speed
from ...engine.manager import DownloadManager
from ...models.download_item import DownloadItem, DownloadStatus
from .. import icons
from ..theme import ThemeManager
from .common import (
    BaseDialog,
    make_divider,
    make_label,
    secondary_button,
)


class DownloadProgressDialog(BaseDialog):
    """Live view of one download, prepared for multi-connection statistics."""

    closed = Signal(str)

    def __init__(
        self,
        manager: DownloadManager,
        item_id: str,
        theme: ThemeManager,
        parent=None,
    ) -> None:
        super().__init__(theme, parent)
        self._manager = manager
        self._item_id = item_id
        self._closing = False
        self.setModal(False)
        self.setWindowTitle("Download Progress")
        self.setMinimumWidth(520)
        self.setSizeGripEnabled(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(12)
        self._icon = QLabel()
        self._icon.setFixedSize(40, 40)
        self._icon.setScaledContents(True)
        header.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)

        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(2)
        self._name = QLabel()
        self._name.setObjectName("ProgressFile")
        self._name.setWordWrap(True)
        self._url = QLabel()
        self._url.setObjectName("ProgressMeta")
        self._url.setWordWrap(True)
        title_box.addWidget(self._name)
        title_box.addWidget(self._url)
        header.addLayout(title_box, 1)
        root.addLayout(header)

        self._percent = QLabel("—")
        self._percent.setObjectName("ProgressPercent")
        self._percent.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(self._percent)

        self._progress = QProgressBar()
        self._progress.setObjectName("DownloadProgress")
        self._progress.setTextVisible(False)
        self._progress.setRange(0, 100)
        root.addWidget(self._progress)

        stats = QGridLayout()
        stats.setHorizontalSpacing(22)
        stats.setVerticalSpacing(4)
        self._size_value = self._stat(stats, 0, 0, "Size")
        self._downloaded_value = self._stat(stats, 0, 1, "Downloaded")
        self._rate_value = self._stat(stats, 1, 0, "Transfer rate")
        self._eta_value = self._stat(stats, 1, 1, "Time left")
        self._status_value = self._stat(stats, 2, 0, "Status")
        self._last_try_value = self._stat(stats, 2, 1, "Last try")
        self._source_value = self._stat(stats, 3, 0, "Source")
        self._referrer_value = self._stat(stats, 3, 1, "Referrer")
        root.addLayout(stats)

        self._error = QLabel()
        self._error.setObjectName("ErrorLabel")
        self._error.setWordWrap(True)
        self._error.hide()
        root.addWidget(self._error)

        root.addWidget(make_label("CONNECTIONS", "FieldLabel"))
        self._connections_container = QFrame()
        self._connections_container.setObjectName("ConnectionRow")
        self._connections_layout = QVBoxLayout(self._connections_container)
        self._connections_layout.setContentsMargins(10, 7, 10, 7)
        self._connections_layout.setSpacing(5)
        self._connection_rows: list[dict] = []
        root.addWidget(self._connections_container)

        self._connections_note = QLabel()
        self._connections_note.setObjectName("ProgressMeta")
        self._connections_note.setWordWrap(True)
        root.addWidget(self._connections_note)

        root.addWidget(make_label("DOWNLOAD SPEED LIMIT", "FieldLabel"))
        limit_row = QHBoxLayout()
        limit_row.setSpacing(8)
        self._limit_spin = QSpinBox()
        self._limit_spin.setRange(0, MAX_SPEED_LIMIT_KBPS)
        self._limit_spin.setSingleStep(128)
        self._limit_spin.setSpecialValueText("Unlimited")
        self._limit_spin.setSuffix(" KB/s")
        limit_row.addWidget(self._limit_spin)
        self._limit_button = secondary_button("Apply limit")
        self._limit_button.clicked.connect(self._apply_limit)
        limit_row.addWidget(self._limit_button)
        limit_row.addStretch(1)
        root.addLayout(limit_row)

        root.addWidget(make_divider())
        footer = QHBoxLayout()
        footer.setSpacing(8)
        self._folder_button = secondary_button("Open Folder")
        self._folder_button.setIcon(
            icons.icon("folder", self._theme.palette.text_muted, 16)
        )
        self._folder_button.clicked.connect(self._open_folder)
        footer.addWidget(self._folder_button)
        footer.addStretch(1)
        self._pause_button = secondary_button("Pause")
        self._pause_button.clicked.connect(self._toggle_pause)
        footer.addWidget(self._pause_button)
        self._cancel_button = secondary_button("Cancel")
        self._cancel_button.clicked.connect(self._cancel)
        footer.addWidget(self._cancel_button)
        root.addLayout(footer)

        manager.download_updated.connect(self._on_updated)
        manager.download_removed.connect(self._on_removed)
        self._timer = QTimer(self)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        theme.changed.connect(self._refresh)
        self._refresh()

    # ------------------------------------------------------------------ widgets
    @staticmethod
    def _stat(layout: QGridLayout, row: int, column: int, title: str) -> QLabel:
        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        key = QLabel(title)
        key.setObjectName("ProgressKey")
        value = QLabel("—")
        value.setObjectName("ProgressValue")
        box.addWidget(key)
        box.addWidget(value)
        layout.addLayout(box, row, column)
        return value

    # ------------------------------------------------------------------ events
    def _on_updated(self, item: DownloadItem) -> None:
        if item.id == self._item_id and not self._closing:
            self._apply(item)

    def _on_removed(self, download_id: str) -> None:
        if download_id == self._item_id:
            self.close()

    def _refresh(self) -> None:
        if self._closing:
            return
        item = self._manager.get(self._item_id)
        if item is None:
            self.close()
            return
        self._apply(item)

    def _apply(self, item: DownloadItem) -> None:
        p = self._theme.palette
        self._name.setText(item.filename)
        self._url.setText(item.url)
        self._url.setToolTip(item.url)
        self._icon.setPixmap(icons.category_icon(item.category, size=36).pixmap(36, 36))

        fraction = item.progress
        if item.status == DownloadStatus.COMPLETED:
            fraction = 1.0
        percent = round((fraction or 0.0) * 100)
        if fraction is None and item.status in {
            DownloadStatus.CONNECTING,
            DownloadStatus.DOWNLOADING,
            DownloadStatus.RETRYING,
        }:
            self._progress.setRange(0, 0)
            self._percent.setText("Downloading…")
        else:
            self._progress.setRange(0, 100)
            self._progress.setValue(percent)
            self._percent.setText(f"{percent}%")

        self._size_value.setText(
            format_size(item.total_bytes) if item.total_bytes else "Unknown"
        )
        downloaded_text = format_size(item.downloaded_bytes)
        if item.total_bytes:
            downloaded_text += f" of {format_size(item.total_bytes)}"
        self._downloaded_value.setText(downloaded_text)
        self._rate_value.setText(format_speed(item.speed) if item.speed > 0 else "—")
        self._eta_value.setText(
            format_eta(item.eta) if item.eta is not None and item.is_active else "—"
        )
        self._status_value.setText(item.status.value)
        self._last_try_value.setText(
            item.last_try.strftime("%Y-%m-%d %H:%M") if item.last_try else "—"
        )
        self._source_value.setText(
            browser_display_name(item.source_browser) if item.source_browser else "IDM"
        )
        self._referrer_value.setText(_referrer_label(item.referrer))
        self._referrer_value.setToolTip(item.referrer or "Added directly in IDM")

        if item.status == DownloadStatus.FAILED and item.error:
            self._error.setText(item.error)
            self._error.show()
        else:
            self._error.hide()

        if item.status == DownloadStatus.COMPLETED:
            self._pause_button.setText("Completed")
            self._pause_button.setEnabled(False)
            self._cancel_button.setText("Close")
        elif item.can_resume:
            self._pause_button.setText("Resume")
            self._pause_button.setIcon(icons.icon("resume", p.text, 16))
            self._pause_button.setEnabled(True)
            self._cancel_button.setText("Cancel")
        elif item.can_pause:
            self._pause_button.setText("Pause")
            self._pause_button.setIcon(icons.icon("pause", p.text, 16))
            self._pause_button.setEnabled(True)
            self._cancel_button.setText("Cancel")
        else:
            self._pause_button.setText("Pause")
            self._pause_button.setEnabled(False)
            self._cancel_button.setText("Cancel")

        completed = item.status == DownloadStatus.COMPLETED
        self._folder_button.setVisible(completed)
        self._folder_button.setEnabled(completed)
        self._update_connections(item, percent)
        self._update_limit(item, completed)

    # ------------------------------------------------------------------ connections
    def _update_connections(self, item: DownloadItem, percent: int) -> None:
        p = self._theme.palette
        segments = item.segments
        if segments:
            self._ensure_connection_rows(len(segments))
            for row, segment in zip(self._connection_rows, segments):
                length = int(segment.get("length") or 0)
                downloaded = int(segment.get("downloaded") or 0)
                fraction = (downloaded / length) if length > 0 else 0.0
                status = str(segment.get("status") or "active")
                row["name"].setText(
                    f"Connection {int(segment.get('index', 0)) + 1}"
                )
                row["bar"].setRange(0, 100)
                row["bar"].setValue(round(max(0.0, min(1.0, fraction)) * 100))
                row["meta"].setText(
                    f"{format_size(downloaded)} of {format_size(length)}   ·   "
                    f"{status.capitalize()}"
                )
                if status == "complete":
                    color = p.success
                elif status == "paused":
                    color = p.text_faint
                elif item.is_active:
                    color = p.accent
                else:
                    color = p.text_faint
                row["dot"].setStyleSheet(
                    f"background-color: {color}; border-radius: 3px;"
                )
            self._connections_note.setText(
                f"Segmented transfer · {len(segments)} HTTP Range connections · "
                f"{item.status.value}"
            )
            return

        self._ensure_connection_rows(1)
        row = self._connection_rows[0]
        row["name"].setText("Connection 1")
        if item.status in {
            DownloadStatus.CONNECTING,
            DownloadStatus.DOWNLOADING,
            DownloadStatus.RETRYING,
        } and item.progress is None:
            row["bar"].setRange(0, 0)
        else:
            row["bar"].setRange(0, 100)
            row["bar"].setValue(percent)
        row["meta"].setText(
            "Complete"
            if item.status == DownloadStatus.COMPLETED
            else ("Active" if item.is_active else "Idle")
        )
        if item.status == DownloadStatus.COMPLETED:
            color = p.success
        elif item.is_active:
            color = p.accent
        else:
            color = p.text_faint
        row["dot"].setStyleSheet(f"background-color: {color}; border-radius: 3px;")
        if item.status == DownloadStatus.COMPLETED:
            note = "Completed with a single HTTP connection."
        elif item.range_supported is False:
            note = (
                "Single connection: the server does not support HTTP Range "
                "requests, so segmented downloading is not safe for this file."
            )
        elif item.connections > 1:
            note = (
                f"Single connection in use. Up to {item.connections} connections "
                "are attempted when the server proves Range support and the file "
                "is large enough."
            )
        else:
            note = "Single connection (segmented downloading is disabled by settings)."
        self._connections_note.setText(note)

    def _ensure_connection_rows(self, count: int) -> None:
        while len(self._connection_rows) > count:
            row = self._connection_rows.pop()
            row["frame"].deleteLater()
        while len(self._connection_rows) < count:
            frame = QFrame()
            layout = QHBoxLayout(frame)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(10)
            dot = QLabel()
            dot.setFixedSize(7, 7)
            layout.addWidget(dot)
            name = QLabel()
            name.setObjectName("ConnectionName")
            name.setMinimumWidth(88)
            layout.addWidget(name)
            bar = QProgressBar()
            bar.setObjectName("DownloadProgress")
            bar.setFixedHeight(10)
            bar.setTextVisible(False)
            bar.setRange(0, 100)
            layout.addWidget(bar, 1)
            meta = QLabel()
            meta.setObjectName("ProgressMeta")
            layout.addWidget(meta)
            self._connections_layout.addWidget(frame)
            self._connection_rows.append(
                {"frame": frame, "dot": dot, "name": name, "bar": bar, "meta": meta}
            )

    # ------------------------------------------------------------------ speed limit
    def _update_limit(self, item: DownloadItem, completed: bool) -> None:
        if not self._limit_spin.hasFocus():
            self._limit_spin.setValue(int(item.speed_limit_kbps))
        self._limit_button.setEnabled(not completed)
        self._limit_spin.setEnabled(not completed)

    def _apply_limit(self) -> None:
        item = self._manager.get(self._item_id)
        if item is None:
            return
        self._manager.set_speed_limit(item.id, self._limit_spin.value())
        self._apply(item)

    # ------------------------------------------------------------------ actions
    def _toggle_pause(self) -> None:
        item = self._manager.get(self._item_id)
        if item is None:
            return
        if item.can_pause:
            self._manager.pause([item.id])
        elif item.can_resume:
            self._manager.resume([item.id])
        self._refresh()

    def _cancel(self) -> None:
        item = self._manager.get(self._item_id)
        if item is not None and item.status != DownloadStatus.COMPLETED:
            self._manager.stop([item.id])
        self.close()

    def _open_folder(self) -> None:
        item = self._manager.get(self._item_id)
        if item is None:
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(item.folder))

    def closeEvent(self, event) -> None:
        if not self._closing:
            self._closing = True
            self._timer.stop()
            try:
                self._manager.download_updated.disconnect(self._on_updated)
                self._manager.download_removed.disconnect(self._on_removed)
            except (RuntimeError, TypeError):
                pass
            self.closed.emit(self._item_id)
        super().closeEvent(event)


def _referrer_label(referrer: str) -> str:
    if not referrer:
        return "—"
    try:
        host = QUrl(referrer).host()
    except Exception:
        host = ""
    return host or referrer[:48]
