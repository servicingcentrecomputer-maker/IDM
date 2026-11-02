"""Download complete dialog shown after a transfer finishes."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ...core.url_utils import format_relative_time, format_size, format_speed, host_of
from ...models.download_item import DownloadItem
from .. import design, icons
from ..theme import ThemeManager
from .common import (
    BaseDialog,
    make_divider,
    make_label,
    primary_button,
    secondary_button,
)


class DownloadCompleteDialog(BaseDialog):
    """Non-modal confirmation with real file details and quick actions."""

    closed = Signal(str)

    def __init__(
        self,
        item: DownloadItem,
        theme: ThemeManager,
        settings=None,
        parent=None,
    ) -> None:
        super().__init__(theme, parent)
        self._item = item
        self._settings = settings
        self._closed_emitted = False
        self.setModal(False)
        self.setWindowTitle("Download Complete")
        self.setMinimumWidth(540)
        self.setSizeGripEnabled(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(
            design.SPACING["xl"],
            design.SPACING["xl"],
            design.SPACING["xl"],
            design.SPACING["lg"],
        )
        root.setSpacing(design.SPACING["md"])

        root.addLayout(self._build_header())
        root.addWidget(make_divider())
        root.addWidget(self._build_details())

        self._hint = QLabel(
            "The file is ready. Open it now or jump straight to its folder."
        )
        self._hint.setObjectName("HintLabel")
        self._hint.setWordWrap(True)
        root.addWidget(self._hint)

        root.addLayout(self._build_actions())
        root.addWidget(self._build_remember())

        self._theme.changed.connect(self._refresh_icons)
        self._refresh_icons()

    # ------------------------------------------------------------------ construction
    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(design.SPACING["md"])

        self._badge = QLabel()
        self._badge.setObjectName("CompletionBadge")
        self._badge.setFixedSize(52, 52)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignTop)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(design.SPACING["xxs"])
        title = QLabel("Download complete")
        title.setObjectName("DialogTitle")
        self._name = QLabel(self._item.filename)
        self._name.setObjectName("CompletionFileName")
        self._name.setWordWrap(True)
        subtitle = QLabel(
            f"{format_size(self._file_size())} saved to {self._item.folder}"
        )
        subtitle.setObjectName("DialogSubtitle")
        subtitle.setWordWrap(True)
        text.addWidget(title)
        text.addWidget(self._name)
        text.addWidget(subtitle)
        header.addLayout(text, 1)
        return header

    def _build_details(self) -> QWidget:
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

        title = QLabel("File details")
        title.setObjectName("CardTitle")
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(design.SPACING["xl"])
        grid.setVerticalSpacing(design.SPACING["sm"])
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        self._speed = self._stat(grid, 0, 0, "Average speed", self._average_speed())
        self._completed = self._stat(
            grid, 0, 1, "Completed", format_relative_time(self._item.completed_at)
        )
        self._size = self._stat(grid, 1, 0, "Size", format_size(self._file_size()))
        self._source = self._stat(grid, 1, 1, "Source", self._source_text())

        integrity = self._item.integrity_label
        if integrity:
            self._stat(grid, 2, 0, "Integrity", integrity)

        layout.addLayout(grid)
        return card

    def _stat(
        self, grid: QGridLayout, row: int, column: int, label: str, value: str
    ) -> QLabel:
        grid.addWidget(
            make_label(label.upper(), "FileInfoKey"), row, column * 2
        )
        value_label = QLabel(value)
        value_label.setObjectName("FileInfoValue")
        value_label.setWordWrap(True)
        value_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        grid.addWidget(value_label, row, column * 2 + 1)
        return value_label

    def _build_actions(self) -> QHBoxLayout:
        actions = QHBoxLayout()
        actions.setSpacing(design.SPACING["sm"])
        actions.addStretch(1)

        self._folder_button = secondary_button("Open Folder")
        self._folder_button.setObjectName("SubtleButton")
        self._folder_button.setMinimumHeight(38)
        self._folder_button.clicked.connect(self._open_folder)
        actions.addWidget(self._folder_button)

        close = secondary_button("Close")
        close.setObjectName("GhostButton")
        close.setMinimumHeight(38)
        close.clicked.connect(self.close)
        actions.addWidget(close)

        self._file_button = primary_button("Open File")
        self._file_button.setMinimumHeight(38)
        self._file_button.setMinimumWidth(126)
        self._file_button.clicked.connect(self._open_file)
        self._file_button.setEnabled(self._item.path.exists())
        if not self._file_button.isEnabled():
            self._file_button.setToolTip(
                "The file is no longer at its saved location."
            )
        actions.addWidget(self._file_button)
        return actions

    def _build_remember(self) -> QCheckBox:
        self._remember = QCheckBox(
            "Show this window when a download completes"
        )
        self._remember.setCursor(Qt.CursorShape.PointingHandCursor)
        if self._settings is not None:
            self._remember.setChecked(
                bool(getattr(self._settings, "show_completion_dialog", True))
            )
            self._remember.toggled.connect(self._remember_choice)
        else:
            self._remember.setChecked(True)
            self._remember.setEnabled(False)
        return self._remember

    # ------------------------------------------------------------------ data
    def _file_size(self) -> int:
        if self._item.total_bytes and self._item.total_bytes > 0:
            return self._item.total_bytes
        return max(0, self._item.downloaded_bytes)

    def _elapsed(self) -> float | None:
        created = self._item.created_at
        completed = self._item.completed_at
        if not isinstance(created, datetime) or not isinstance(completed, datetime):
            return None
        seconds = (completed - created).total_seconds()
        return seconds if seconds > 0 else None

    def _average_speed(self) -> str:
        elapsed = self._elapsed()
        if not elapsed:
            return "—"
        return format_speed(self._file_size() / elapsed)

    def _source_text(self) -> str:
        try:
            host = host_of(self._item.url)
        except ValueError:
            host = ""
        return host or "—"

    # ------------------------------------------------------------------ actions
    def _open_file(self) -> None:
        path = self._item.path
        if not path.exists():
            self._hint.setText(
                "The file is no longer at its saved location. It may have "
                "been moved or deleted."
            )
            self._file_button.setEnabled(False)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_folder(self) -> None:
        folder = Path(self._item.folder)
        if not folder.exists():
            self._hint.setText("The download folder no longer exists.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _remember_choice(self, checked: bool) -> None:
        if self._settings is None:
            return
        self._settings.update({"show_completion_dialog": bool(checked)})
        self._settings.save()

    # ------------------------------------------------------------------ chrome
    def _refresh_icons(self) -> None:
        palette = self._theme.palette
        size = design.ICON_SIZE["hero"]
        self._badge.setPixmap(
            icons.icon("check_circle", palette.success, size).pixmap(size, size)
        )
        small = design.ICON_SIZE["sm"]
        self._folder_button.setIcon(
            icons.icon("folder_open", palette.text_muted, small)
        )
        self._file_button.setIcon(
            icons.icon("play", palette.on_accent, small)
        )

    def closeEvent(self, event) -> None:
        if not self._closed_emitted:
            self._closed_emitted = True
            self.closed.emit(self._item.id)
        super().closeEvent(event)


__all__ = ["DownloadCompleteDialog"]
