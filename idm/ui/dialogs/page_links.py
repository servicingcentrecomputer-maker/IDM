"""Confirm the links a browser captured from a page before IDM queues them."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from ..theme import ThemeManager
from .common import (
    BaseDialog,
    make_divider,
    make_header,
    primary_button,
    secondary_button,
)

_NAME_WIDTH = 46


def _describe(link: dict) -> str:
    filename = str(link.get("filename") or "").strip()
    url = str(link.get("url") or "")
    if filename:
        return f"{filename[:_NAME_WIDTH]}  \u2013  {url}"
    return url[: 120]


class PageLinksDialog(BaseDialog):
    """A checkable list of the links captured from one browser page."""

    def __init__(self, payload: dict, theme: ThemeManager, parent=None) -> None:
        super().__init__(theme, parent)
        self._links = [
            dict(link)
            for link in (payload.get("links") or [])
            if isinstance(link, dict) and link.get("url")
        ]
        self._page = str(payload.get("page_title") or payload.get("page_url") or "")
        self.setWindowTitle("Links found on this page")
        self.setMinimumSize(660, 460)

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 20)
        root.setSpacing(12)
        root.addWidget(
            make_header(
                "Download links from this page",
                self._page
                or "Choose which links IDM should download.",
            )
        )

        self.list = QListWidget()
        for link in self._links:
            item = QListWidgetItem(_describe(link))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setToolTip(str(link.get("url") or ""))
            self.list.addItem(item)
        root.addWidget(self.list, 1)

        self.count_label = QLabel()
        self.count_label.setObjectName("DialogSubtitle")
        root.addWidget(self.count_label)

        toolbar = QHBoxLayout()
        select_all = secondary_button("Select all")
        select_all.clicked.connect(lambda: self._set_all(Qt.CheckState.Checked))
        select_none = secondary_button("Select none")
        select_none.clicked.connect(lambda: self._set_all(Qt.CheckState.Unchecked))
        toolbar.addWidget(select_all)
        toolbar.addWidget(select_none)
        toolbar.addStretch(1)
        root.addLayout(toolbar)

        root.addWidget(make_divider())

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = secondary_button("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        self.download_button = primary_button("Download Selected")
        self.download_button.clicked.connect(self.accept)
        self.download_button.setEnabled(False)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.download_button)
        root.addLayout(buttons)

        self.list.itemChanged.connect(self._refresh)
        self._refresh()

    def _set_all(self, state: Qt.CheckState) -> None:
        # Suppress the per-item signal so a hundred links refresh once.
        self.list.blockSignals(True)
        for index in range(self.list.count()):
            self.list.item(index).setCheckState(state)
        self.list.blockSignals(False)
        self._refresh()

    def _refresh(self) -> None:
        count = len(self.selected())
        self.count_label.setText(f"{count} of {len(self._links)} links selected")
        self.download_button.setEnabled(count > 0)

    def selected(self) -> list[dict]:
        chosen: list[dict] = []
        for index in range(self.list.count()):
            if self.list.item(index).checkState() == Qt.CheckState.Checked:
                chosen.append(self._links[index])
        return chosen
