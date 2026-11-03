"""Batch link entry: paste a list of URLs and queue them in one action."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
)

from ..theme import ThemeManager
from .common import (
    BaseDialog,
    make_divider,
    make_header,
    make_label,
    primary_button,
    secondary_button,
)

MAX_BATCH_LINKS = 500


def parse_url_lines(text: str) -> list[str]:
    """Return the unique links in ``text``, one per line, in the given order."""
    seen: set[str] = set()
    links: list[str] = []
    for raw in (text or "").splitlines():
        url = raw.strip()
        if not url or url.startswith("#"):
            continue
        key = url.casefold()
        if key in seen:
            continue
        seen.add(key)
        links.append(url)
        if len(links) >= MAX_BATCH_LINKS:
            break
    return links


class BatchUrlsDialog(BaseDialog):
    def __init__(self, settings, theme: ThemeManager, parent=None) -> None:
        super().__init__(theme, parent)
        self._settings = settings
        self.setWindowTitle("Add batch downloads")
        self.setMinimumSize(620, 460)

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 20)
        root.setSpacing(12)
        root.addWidget(
            make_header(
                "Add a batch of links",
                "Paste one link per line. Empty lines and duplicates are ignored.",
            )
        )

        self.urls_edit = QPlainTextEdit()
        self.urls_edit.setPlaceholderText(
            "https://example.com/files/report.pdf\nhttps://example.com/files/archive.zip"
        )
        self.urls_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.urls_edit.textChanged.connect(self._refresh_count)
        root.addWidget(self.urls_edit, 1)

        self.count_label = QLabel("0 links")
        self.count_label.setObjectName("DialogSubtitle")
        root.addWidget(self.count_label)

        root.addWidget(make_divider())
        root.addWidget(make_label("Save to"))
        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit(str(getattr(settings, "download_dir", "") or ""))
        self.folder_edit.setReadOnly(True)
        browse = secondary_button("Browse…")
        browse.clicked.connect(self._browse)
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(browse)
        root.addLayout(folder_row)

        self.start_check = QCheckBox("Start downloads immediately")
        self.start_check.setChecked(bool(getattr(settings, "start_immediately", True)))
        root.addWidget(self.start_check)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = secondary_button("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        self.add_button = primary_button("Add Downloads")
        self.add_button.clicked.connect(self._accept)
        self.add_button.setEnabled(False)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.add_button)
        root.addLayout(buttons)

        self._refresh_count()

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choose a download folder", self.folder_edit.text() or str(Path.home())
        )
        if folder:
            self.folder_edit.setText(folder)

    def _accept(self) -> None:
        if not self.urls():
            return
        self.accept()

    def _refresh_count(self) -> None:
        count = len(self.urls())
        suffix = f" (showing the first {MAX_BATCH_LINKS})" if count >= MAX_BATCH_LINKS else ""
        self.count_label.setText(f"{count} link{'' if count == 1 else 's'}{suffix}")
        self.add_button.setEnabled(count > 0)

    def urls(self) -> list[str]:
        return parse_url_lines(self.urls_edit.toPlainText())

    def values(self) -> dict:
        return {
            "urls": self.urls(),
            "folder": self.folder_edit.text().strip(),
            "start_immediately": self.start_check.isChecked(),
        }
