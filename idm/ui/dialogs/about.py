"""About IDM dialog with integrated update checking and installation."""

from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from ...constants import (
    APP_COPYRIGHT,
    APP_DESCRIPTION,
    APP_NAME,
    APP_VERSION,
)
from .. import icons
from ..theme import ThemeManager
from .common import BaseDialog, make_divider, primary_button
from .update import UpdatePanel


class AboutDialog(BaseDialog):
    def __init__(
        self,
        theme: ThemeManager,
        parent=None,
        settings=None,
        on_install=None,
        initial_result=None,
        auto_action: str | None = None,
        active_download_count=None,
        pause_downloads=None,
    ) -> None:
        super().__init__(theme, parent)
        self._closed = False
        self.setWindowTitle(f"About {APP_NAME}")
        self.setMinimumWidth(620)
        self.setMinimumHeight(560)
        self.setSizeGripEnabled(False)

        if settings is None:
            settings = SimpleNamespace(
                update_manifest_url="", update_publisher=""
            )
        if on_install is None:
            on_install = lambda _request: (
                "Automatic installation is not available in this context."
            )

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 18)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(14)
        logo = QLabel()
        logo.setPixmap(icons.logo_pixmap(64))
        logo.setFixedSize(64, 64)
        logo.setScaledContents(True)
        header.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(2)
        name = QLabel(f"{APP_NAME} {APP_VERSION}")
        name.setObjectName("DialogTitle")
        tagline = QLabel(f"{APP_DESCRIPTION} for Windows")
        tagline.setObjectName("DialogSubtitle")
        text_box.addWidget(name)
        text_box.addWidget(tagline)
        text_box.addSpacing(4)
        description = QLabel(
            "A compact, classic download manager built with Python and Qt. "
            "HTTP and HTTPS links, resumable transfers, queues, schedules and "
            "three interface themes."
        )
        description.setWordWrap(True)
        description.setObjectName("HintLabel")
        text_box.addWidget(description)
        header.addLayout(text_box, 1)
        root.addLayout(header)

        root.addSpacing(4)
        root.addWidget(make_divider())

        details = QLabel(
            f"{APP_COPYRIGHT}\n"
            f"Developer: {APP_NAME}\n"
            "Storage: SQLite settings and download history in "
            "%APPDATA%\\IDM Download Manager"
        )
        details.setObjectName("HintLabel")
        details.setWordWrap(True)
        root.addWidget(details)
        root.addSpacing(2)

        self.update_panel = UpdatePanel(
            settings,
            theme,
            on_install,
            self,
            active_downloads=active_download_count,
            pause_downloads=pause_downloads,
        )
        self.update_panel.installation_started.connect(self.accept)
        root.addWidget(self.update_panel)
        root.addStretch(1)

        if initial_result is not None:
            self.update_panel.set_result(initial_result)
            if auto_action == "install":
                QTimer.singleShot(0, self.update_panel.start_install)
            elif auto_action == "download":
                QTimer.singleShot(0, self.update_panel.start_download)

        footer = QHBoxLayout()
        footer.addStretch(1)
        close = primary_button("Close")
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        root.addLayout(footer)

    def check_now(self) -> None:
        self.update_panel.check_for_updates()

    def accept(self) -> None:
        self._shutdown_panel()
        super().accept()

    def reject(self) -> None:
        self._shutdown_panel()
        super().reject()

    def closeEvent(self, event) -> None:
        self._shutdown_panel()
        super().closeEvent(event)

    def _shutdown_panel(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.update_panel.shutdown()
