"""Non-intrusive “update available” notification window."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from ...core.url_utils import format_size
from ...updater.manifest_validator import UpdateManifest
from ...updater.release_notes import categorize_notes
from ...updater.update_checker import UpdateCheckResult
from ...version import APP_NAME
from .. import icons
from ..theme import ThemeManager
from .common import (
    BaseDialog,
    make_divider,
    make_label,
    primary_button,
    secondary_button,
)

_ON_OPEN_MODES = {"install", "download", "notes"}


class UpdateNotificationDialog(BaseDialog):
    def __init__(
        self,
        theme: ThemeManager,
        result: UpdateCheckResult,
        settings,
        on_open_update,
        parent=None,
    ) -> None:
        super().__init__(theme, parent)
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self._result = result
        self._settings = settings
        self._on_open_update = on_open_update

        self.setWindowTitle(f"{APP_NAME} Update")
        self.setMinimumWidth(560)
        self.setMaximumWidth(660)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 16)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(icons.logo_pixmap(52))
        logo.setFixedSize(52, 52)
        logo.setScaledContents(True)
        header.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel("A new version of IDM is available")
        title.setObjectName("DialogTitle")
        subtitle = QLabel(
            f"IDM {result.latest_version} is ready. You are using "
            f"{result.current_version}."
        )
        subtitle.setObjectName("DialogSubtitle")
        subtitle.setWordWrap(True)
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles, 1)
        root.addLayout(header)

        if result.mandatory:
            required = QLabel(
                "This update is recommended because your installed version is "
                "no longer supported."
            )
            required.setObjectName("UpdateMandatory")
            required.setWordWrap(True)
            root.addWidget(required)

        root.addWidget(make_divider())

        facts = QHBoxLayout()
        facts.setSpacing(18)
        facts.addWidget(self._fact("INSTALLED", str(result.current_version)))
        facts.addWidget(self._fact("AVAILABLE", str(result.latest_version)))
        facts.addWidget(self._fact("RELEASED", result.manifest.release_date))
        facts.addWidget(self._fact("SIZE", _package_size_text(result.manifest)))
        facts.addStretch(1)
        root.addLayout(facts)

        root.addWidget(make_label("WHAT'S NEW", "FieldLabel"))
        notes = QPlainTextEdit()
        notes.setObjectName("ReleaseNotes")
        notes.setReadOnly(True)
        notes.setPlainText(_notes_text(result.manifest))
        notes.setMinimumHeight(150)
        notes.setMaximumHeight(210)
        root.addWidget(notes)

        root.addWidget(make_divider())
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        remind = secondary_button("Remind Me Later")
        remind.clicked.connect(self._remind_later)
        buttons.addWidget(remind)

        view = secondary_button("View Release Notes")
        view.clicked.connect(lambda: self._open("notes"))
        buttons.addWidget(view)

        buttons.addStretch(1)

        download = secondary_button("Download Update")
        download.clicked.connect(lambda: self._open("download"))
        buttons.addWidget(download)

        install = primary_button("Install Now")
        install.clicked.connect(lambda: self._open("install"))
        buttons.addWidget(install)
        root.addLayout(buttons)

        self._theme.changed.connect(self._sync_icons)

    def _fact(self, caption: str, value: str) -> QLabel:
        label = QLabel(f"{caption}\n{value}")
        label.setObjectName("HintLabel")
        label.setWordWrap(True)
        return label

    def _open(self, mode: str) -> None:
        if mode not in _ON_OPEN_MODES:
            return
        callback = self._on_open_update
        result = self._result
        self.accept()
        QTimer.singleShot(0, lambda: callback(result, mode))

    def _remind_later(self) -> None:
        try:
            self._settings.remind_later(str(self._result.latest_version), 24)
        except Exception:
            pass
        self.accept()

    def _sync_icons(self) -> None:
        self.setWindowIcon(icons.app_icon())


def _package_size_text(manifest: UpdateManifest) -> str:
    size = getattr(manifest, "package_size", None)
    return format_size(int(size)) if size else "Shown at download"


def _notes_text(manifest: UpdateManifest) -> str:
    sections = categorize_notes(manifest.release_notes)
    if not sections:
        return "No release notes were provided."
    blocks: list[str] = []
    for title, entries in sections:
        blocks.append(title.upper())
        blocks.extend(f"  •  {entry}" for entry in entries)
        blocks.append("")
    return "\n".join(blocks).strip()


__all__ = ["UpdateNotificationDialog"]
