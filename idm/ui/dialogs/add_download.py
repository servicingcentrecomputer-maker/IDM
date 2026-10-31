"""Classic Add Download dialog with asynchronous link inspection."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from ...constants import CATEGORIES, PRIORITIES, PRIORITY_NORMAL
from ...core.paths import default_download_dir, ensure_download_dir
from ...core.probe import LinkProbe, ProbeResult
from ...core.settings import AppSettings
from ...core.url_utils import (
    InvalidUrlError,
    category_for_filename,
    format_size,
    guess_filename,
    is_valid_url,
    sanitize_filename,
    unique_filename,
    validate_url,
)
from .. import icons
from ..theme import ThemeManager
from .common import (
    BaseDialog,
    make_divider,
    make_header,
    make_label,
    primary_button,
    secondary_button,
)


class AddDownloadDialog(BaseDialog):
    def __init__(
        self, settings: AppSettings, theme: ThemeManager, parent=None
    ) -> None:
        super().__init__(theme, parent)
        self._settings = settings
        self._auto_filename = True
        self._auto_category = True
        self._last_probed_url = ""
        self._probe_result: ProbeResult | None = None
        self._result: dict | None = None

        self.setWindowTitle("Add Download")
        self.setMinimumWidth(620)
        self.setSizeGripEnabled(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(10)

        root.addWidget(
            make_header(
                "Add Download",
                "Enter the address of the file you want to download.",
            )
        )
        root.addSpacing(2)

        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.setColumnStretch(1, 1)

        form.addWidget(
            make_label("Download URL:"),
            0,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        )
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://example.com/file.zip")
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.setMinimumHeight(32)
        form.addWidget(self.url_edit, 0, 1, 1, 2)

        self.probe_label = QLabel("Paste a direct HTTP or HTTPS file link.")
        self.probe_label.setObjectName("ProbeLabel")
        self.probe_label.setProperty("state", "")
        self.probe_label.setWordWrap(True)
        form.addWidget(self.probe_label, 1, 1, 1, 2)

        form.addWidget(make_label("File Name:"), 2, 0)
        self.filename_edit = QLineEdit()
        self.filename_edit.setPlaceholderText("Detected automatically from the link")
        self.filename_edit.setMinimumHeight(32)
        form.addWidget(self.filename_edit, 2, 1, 1, 2)

        form.addWidget(make_label("Save To:"), 3, 0)
        self.folder_edit = QLineEdit(
            str(settings.download_dir or default_download_dir())
        )
        self.folder_edit.setMinimumHeight(32)
        form.addWidget(self.folder_edit, 3, 1)
        self.browse_button = secondary_button("Browse…")
        self.browse_button.setIcon(
            icons.icon("folder", self._theme.palette.text_muted, 16)
        )
        self.browse_button.clicked.connect(self._browse_folder)
        form.addWidget(self.browse_button, 3, 2)

        form.addWidget(make_label("Category:"), 4, 0)
        self.category_combo = QComboBox()
        for category in CATEGORIES:
            self.category_combo.addItem(category, category)
        form.addWidget(self.category_combo, 4, 1)

        form.addWidget(make_label("Priority:"), 5, 0)
        self.priority_combo = QComboBox()
        for name, value in PRIORITIES.items():
            self.priority_combo.addItem(name, value)
        self.priority_combo.setCurrentIndex(1)
        form.addWidget(self.priority_combo, 5, 1)
        form.setColumnMinimumWidth(2, 88)
        root.addLayout(form)

        self.hint_label = QLabel()
        self.hint_label.setObjectName("HintLabel")
        self.hint_label.setWordWrap(True)
        self.hint_label.hide()
        root.addWidget(self.hint_label)

        self.error_label = QLabel()
        self.error_label.setObjectName("ErrorLabel")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        root.addWidget(self.error_label)

        root.addSpacing(2)
        root.addWidget(make_divider())

        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addStretch(1)
        self.later_button = secondary_button("Download Later")
        self.start_button = primary_button("Start Download")
        self.cancel_button = secondary_button("Cancel")
        footer.addWidget(self.later_button)
        footer.addWidget(self.start_button)
        footer.addWidget(self.cancel_button)
        root.addLayout(footer)

        self._probe = LinkProbe(self)
        self._probe.finished.connect(self._on_probe_finished)
        self._probe.failed.connect(self._on_probe_failed)

        self._probe_timer = QTimer(self)
        self._probe_timer.setSingleShot(True)
        self._probe_timer.setInterval(650)
        self._probe_timer.timeout.connect(self._request_probe)

        self.url_edit.textChanged.connect(self._on_url_changed)
        self.url_edit.editingFinished.connect(self._request_probe)
        self.filename_edit.textEdited.connect(self._on_filename_edited)
        self.filename_edit.textChanged.connect(lambda _: self._update_hint())
        self.folder_edit.textChanged.connect(lambda _: self._update_hint())
        self.category_combo.activated.connect(
            lambda _: setattr(self, "_auto_category", False)
        )
        self.start_button.clicked.connect(lambda: self._validate_and_accept(True))
        self.later_button.clicked.connect(lambda: self._validate_and_accept(False))
        self.cancel_button.clicked.connect(self.reject)
        if settings.start_immediately:
            self.start_button.setDefault(True)
        else:
            self.later_button.setDefault(True)

        self.setTabOrder(self.url_edit, self.filename_edit)
        self.setTabOrder(self.filename_edit, self.folder_edit)
        self.setTabOrder(self.folder_edit, self.browse_button)
        self.setTabOrder(self.browse_button, self.category_combo)
        self.setTabOrder(self.category_combo, self.priority_combo)
        self.setTabOrder(self.priority_combo, self.start_button)
        self.setTabOrder(self.start_button, self.later_button)
        self.setTabOrder(self.later_button, self.cancel_button)

        self._select_category(CATEGORIES[-1])
        self.adjustSize()

    # ------------------------------------------------------------------ values
    def values(self) -> dict:
        if self._result is None:
            raise RuntimeError("The dialog has not been accepted.")
        return dict(self._result)

    # ------------------------------------------------------------------ UI events
    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self.url_edit.setFocus)

    def reject(self) -> None:
        self._probe_timer.stop()
        self._probe.abort()
        super().reject()

    def _browse_folder(self) -> None:
        start = self.folder_edit.text().strip() or str(default_download_dir())
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose download folder", start
        )
        if chosen:
            self.folder_edit.setText(chosen)
            self._update_hint()

    # ------------------------------------------------------------------ URL / probe
    def _on_url_changed(self, text: str) -> None:
        self._probe_timer.stop()
        self._probe.abort()
        self._last_probed_url = ""
        self._probe_result = None
        self._clear_error()
        self._set_probe("Paste a direct HTTP or HTTPS file link.", "")

        url = text.strip()
        if self._auto_filename:
            if url:
                guessed = guess_filename(url)
                self.filename_edit.setText(guessed)
                if self._auto_category:
                    self._select_category(category_for_filename(guessed))
            else:
                self.filename_edit.clear()
        self._update_hint()

        if url and is_valid_url(url):
            self._probe_timer.start()

    def _request_probe(self) -> None:
        url = self.url_edit.text().strip()
        if not url or url == self._last_probed_url:
            return
        try:
            validate_url(url)
        except InvalidUrlError:
            return
        self._last_probed_url = url
        self._set_probe("Inspecting link…", "pending")
        self._probe.start(url)

    def _on_probe_finished(self, result: ProbeResult) -> None:
        if self.url_edit.text().strip() != self._last_probed_url:
            return
        self._probe_result = result

        parts: list[str] = []
        if result.total_bytes is not None:
            parts.append(format_size(result.total_bytes))
        if result.range_supported:
            parts.append("Resumable")
        if result.content_type:
            parts.append(result.content_type)
        self._set_probe("   ·   ".join(parts) if parts else "Link ready.", "ok")

        if self._auto_filename and result.filename:
            self.filename_edit.setText(sanitize_filename(result.filename))
            if self._auto_category:
                self._select_category(category_for_filename(result.filename))
            self._update_hint()

    def _on_probe_failed(self, message: str) -> None:
        if self.url_edit.text().strip() != self._last_probed_url:
            return
        self._set_probe(f"{message} You can still add the link.", "warn")

    def _set_probe(self, text: str, state: str) -> None:
        self.probe_label.setText(text)
        self.probe_label.setProperty("state", state)
        style = self.probe_label.style()
        style.unpolish(self.probe_label)
        style.polish(self.probe_label)

    # ------------------------------------------------------------------ fields
    def _on_filename_edited(self, text: str) -> None:
        self._auto_filename = False
        self._clear_error()
        if self._auto_category:
            self._select_category(category_for_filename(text))
        self._update_hint()

    def _select_category(self, category: str) -> None:
        index = self.category_combo.findData(category)
        if index >= 0:
            with QSignalBlocker(self.category_combo):
                self.category_combo.setCurrentIndex(index)

    def _update_hint(self) -> None:
        filename = self.filename_edit.text().strip()
        folder = self.folder_edit.text().strip()
        if not filename or not folder:
            self.hint_label.hide()
            return
        try:
            folder_path = Path(folder).expanduser()
        except (OSError, ValueError):
            self.hint_label.hide()
            return
        try:
            taken = (folder_path / filename).exists() or (
                folder_path / f"{filename}.idm.part"
            ).exists()
            if not taken:
                self.hint_label.hide()
                return
            unique = unique_filename(folder_path, filename)
        except (OSError, RuntimeError, ValueError):
            self.hint_label.hide()
            return
        self.hint_label.setText(
            f"“{filename}” already exists in this folder. "
            f"It will be saved as “{unique}”."
        )
        self.hint_label.show()

    def _show_error(self, text: str) -> None:
        self.error_label.setText(text)
        self.error_label.show()

    def _clear_error(self) -> None:
        self.error_label.clear()
        self.error_label.hide()

    # ------------------------------------------------------------------ accept
    def _validate_and_accept(self, start_immediately: bool) -> None:
        self._clear_error()
        try:
            url = validate_url(self.url_edit.text())
        except InvalidUrlError as exc:
            self._show_error(str(exc))
            self.url_edit.setFocus()
            return

        raw_name = self.filename_edit.text().strip()
        if not raw_name:
            self._show_error("Enter a file name for the download.")
            self.filename_edit.setFocus()
            return
        filename = sanitize_filename(raw_name)

        folder_text = self.folder_edit.text().strip()
        if not folder_text:
            self._show_error("Choose a folder for the download.")
            self.folder_edit.setFocus()
            return
        try:
            folder_path = ensure_download_dir(folder_text)
        except OSError as exc:
            self._show_error(f"Could not use that folder: {exc}")
            self.folder_edit.setFocus()
            return

        try:
            filename = unique_filename(folder_path, filename)
        except (RuntimeError, OSError) as exc:
            self._show_error(str(exc))
            return

        self._result = {
            "url": url,
            "filename": filename,
            "folder": str(folder_path),
            "category": str(self.category_combo.currentData()),
            "priority": int(self.priority_combo.currentData() or PRIORITY_NORMAL),
            "start_immediately": start_immediately,
        }
        self._probe_timer.stop()
        self._probe.abort()
        self.accept()
