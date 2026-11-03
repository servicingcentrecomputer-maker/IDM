"""Read-only properties for one download, with the file tools it links to."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core.url_utils import (
    format_eta,
    format_relative_time,
    format_size,
    format_speed,
    host_of,
)
from ...models.download_item import DownloadItem, DownloadStatus
from .. import design
from ..theme import ThemeManager
from .common import BaseDialog, make_divider, make_label, secondary_button


class DownloadPropertiesDialog(BaseDialog):
    """Everything IDM knows about one download, without duplicating storage.

    The dialog reports what it finds on disk rather than what the record says,
    so a moved or deleted file is visible instead of being hidden behind the
    numbers captured when the transfer finished.
    """

    open_file_requested = Signal(str)
    open_folder_requested = Signal(str)
    copy_link_requested = Signal(str)

    def __init__(
        self, item: DownloadItem, theme: ThemeManager, parent=None
    ) -> None:
        super().__init__(theme, parent)
        self._item = item
        self.setWindowTitle("Download Properties")
        self.setMinimumWidth(560)
        self.setMinimumHeight(520)
        self.setSizeGripEnabled(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(
            design.SPACING["xl"],
            design.SPACING["xl"],
            design.SPACING["xl"],
            design.SPACING["lg"],
        )
        root.setSpacing(design.SPACING["md"])

        title = QLabel(item.filename)
        title.setObjectName("DialogTitle")
        title.setWordWrap(True)
        subtitle = QLabel(f"{self._size_text()}  ·  {item.status.value}")
        subtitle.setObjectName("DialogSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)
        root.addWidget(make_divider())

        root.addWidget(self._scrollable(self._build_groups()), 1)
        root.addLayout(self._build_actions())

    # ------------------------------------------------------------------ content
    def _build_groups(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(design.SPACING["md"])
        for heading, rows in (
            ("General", self._general_rows()),
            ("Transfer", self._transfer_rows()),
            ("Integrity", self._integrity_rows()),
            ("Source", self._source_rows()),
        ):
            if not rows:
                continue
            layout.addWidget(self._card(heading, rows))
        error = self._item.error
        if error:
            layout.addWidget(self._card("Last error", [("Error", error)]))
        return container

    def _card(self, heading: str, rows: list[tuple[str, str]]) -> QFrame:
        card = QFrame()
        card.setObjectName("OptionsCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(
            design.SPACING["lg"],
            design.SPACING["md"],
            design.SPACING["lg"],
            design.SPACING["md"],
        )
        layout.setSpacing(design.SPACING["sm"])

        label = QLabel(heading.upper())
        label.setObjectName("CardTitle")
        layout.addWidget(label)

        grid = QGridLayout()
        grid.setHorizontalSpacing(design.SPACING["xl"])
        grid.setVerticalSpacing(design.SPACING["xs"])
        grid.setColumnMinimumWidth(0, 132)
        grid.setColumnStretch(1, 1)
        for row, (key, value) in enumerate(rows):
            grid.addWidget(make_label(key.upper(), "FileInfoKey"), row, 0)
            value_label = QLabel(value)
            value_label.setObjectName("FileInfoValue")
            value_label.setWordWrap(True)
            # A URL or a SHA-256 has no breakable word in it, so the label's own
            # minimum width would push the whole card past the dialog edge.
            value_label.setMinimumWidth(1)
            value_label.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )
            value_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            grid.addWidget(value_label, row, 1)
        layout.addLayout(grid)
        return card

    def _scrollable(self, widget: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(widget)
        return area

    def _general_rows(self) -> list[tuple[str, str]]:
        item = self._item
        rows = [
            ("Name", item.filename),
            ("Type", item.file_format or self._content_type_text()),
            ("Status", item.status.value),
            ("Category", item.category),
            ("Saved in", item.folder),
            ("On disk", self._on_disk_text()),
            ("Added", format_relative_time(item.created_at)),
        ]
        if item.completed_at is not None:
            rows.append(("Completed", format_relative_time(item.completed_at)))
        return rows

    def _transfer_rows(self) -> list[tuple[str, str]]:
        item = self._item
        rows = [
            (
                "Downloaded",
                f"{format_size(item.downloaded_bytes)} of {format_size(item.total_bytes)}",
            ),
            ("Connections", str(item.connections)),
            ("Segments", self._segments_text()),
        ]
        if item.is_active:
            rows.append(("Speed", format_speed(item.speed)))
            rows.append(("Time left", format_eta(item.eta)))
        elif item.status is DownloadStatus.COMPLETED:
            rows.append(("Average speed", self._average_speed_text()))
        rows.append(("Retries", str(item.retry_count)))
        if item.speed_limit_kbps:
            rows.append(
                ("Limit", format_speed(item.speed_limit_kbps * 1024.0))
            )
        if item.last_try is not None:
            rows.append(("Last attempt", format_relative_time(item.last_try)))
        rows.append(("Resume support", self._range_text()))
        return rows

    def _integrity_rows(self) -> list[tuple[str, str]]:
        item = self._item
        rows = [("Verification", item.integrity_label or "Not requested")]
        if item.expected_sha256:
            rows.append(("Expected SHA-256", item.expected_sha256))
        if item.integrity_verified_at:
            rows.append(("Verified at", item.integrity_verified_at))
        return rows

    def _source_rows(self) -> list[tuple[str, str]]:
        item = self._item
        rows = [("Link", item.url)]
        try:
            rows.append(("Host", host_of(item.url)))
        except ValueError:
            pass
        if item.source_browser:
            rows.append(("From", item.source_browser.title()))
        if item.referrer:
            rows.append(("Referrer", item.referrer))
        if item.page_url:
            rows.append(("Page", item.page_url))
        if item.page_title:
            rows.append(("Page title", item.page_title))
        if item.description:
            rows.append(("Description", item.description))
        return rows

    # ------------------------------------------------------------------ derived text
    def _size_text(self) -> str:
        item = self._item
        if item.total_bytes:
            return format_size(item.total_bytes)
        on_disk = self._disk_size()
        if on_disk is not None:
            return format_size(on_disk)
        return format_size(item.downloaded_bytes)

    def _disk_size(self) -> int | None:
        try:
            path = Path(self._item.path)
            return path.stat().st_size if path.is_file() else None
        except OSError:
            return None

    def _on_disk_text(self) -> str:
        size = self._disk_size()
        if size is None:
            return "Not found at the saved location"
        return f"{format_size(size)} in {self._item.path.name}"

    def _content_type_text(self) -> str:
        return self._item.content_type or "Unknown"

    def _segments_text(self) -> str:
        segments = self._item.segments
        if not segments:
            return "—"
        done = sum(
            1 for entry in segments if entry.get("done") or entry.get("complete")
        )
        return f"{done} of {len(segments)} finished"

    def _range_text(self) -> str:
        match self._item.range_supported:
            case True:
                return "Accepted by the server"
            case False:
                return "Not offered by the server"
            case _:
                return "Not probed"

    def _average_speed_text(self) -> str:
        created, completed = self._item.created_at, self._item.completed_at
        if created is None or completed is None:
            return "—"
        seconds = (completed - created).total_seconds()
        if seconds <= 0:
            return "—"
        size = self._disk_size()
        bytes_moved = size if size is not None else self._item.downloaded_bytes
        return format_speed(bytes_moved / seconds)

    # ------------------------------------------------------------------ actions
    def _build_actions(self) -> QHBoxLayout:
        actions = QHBoxLayout()
        actions.setSpacing(design.SPACING["sm"])
        actions.addStretch(1)

        copy = secondary_button("Copy Link")
        copy.setObjectName("GhostButton")
        copy.setMinimumHeight(34)
        copy.clicked.connect(lambda: self.copy_link_requested.emit(self._item.id))
        actions.addWidget(copy)

        folder = secondary_button("Open Folder")
        folder.setObjectName("GhostButton")
        folder.setMinimumHeight(34)
        folder.clicked.connect(
            lambda: self.open_folder_requested.emit(self._item.id)
        )
        actions.addWidget(folder)

        open_file = secondary_button("Open")
        open_file.setObjectName("PrimaryButton")
        open_file.setAutoDefault(False)
        open_file.setDefault(False)
        open_file.setMinimumHeight(34)
        open_file.setEnabled(self._item.path.is_file())
        open_file.clicked.connect(lambda: self.open_file_requested.emit(self._item.id))
        actions.addWidget(open_file)

        close = secondary_button("Close")
        close.setObjectName("GhostButton")
        close.setMinimumHeight(34)
        close.clicked.connect(self.accept)
        actions.addWidget(close)
        return actions


__all__ = ["DownloadPropertiesDialog"]
