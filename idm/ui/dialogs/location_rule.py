"""Dialog for a single file-type download location rule."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from downloads.location_manager import (
    LocationError,
    LocationRule,
    normalize_extensions,
    validate_folder_path,
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


class LocationRuleDialog(BaseDialog):
    def __init__(
        self,
        theme: ThemeManager,
        rule: LocationRule | None = None,
        parent=None,
    ) -> None:
        super().__init__(theme, parent)
        self._rule: LocationRule | None = None
        self.setWindowTitle("File type rule")
        self.setMinimumWidth(520)
        self.setSizeGripEnabled(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(10)
        root.addWidget(
            make_header(
                "File type rule",
                "Files with these extensions are saved in the selected folder "
                "when File type based locations is enabled.",
            )
        )

        root.addWidget(make_label("FILE EXTENSIONS", "FieldLabel"))
        self.extensions_edit = QLineEdit(
            ", ".join(rule.extensions) if rule else ""
        )
        self.extensions_edit.setPlaceholderText("zip, rar, 7z")
        self.extensions_edit.setMinimumHeight(30)
        root.addWidget(self.extensions_edit)
        hint = QLabel("Separate extensions with commas. Use * for a catch-all rule.")
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

        root.addWidget(make_label("SAVE TO", "FieldLabel"))
        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        self.folder_edit = QLineEdit(rule.folder if rule else "")
        self.folder_edit.setPlaceholderText(r"C:\Users\You\Downloads\Archives")
        self.folder_edit.setMinimumHeight(30)
        browse = secondary_button("Browse…")
        browse.setIcon(icons.icon("folder", self._theme.palette.text_muted, 16))
        browse.clicked.connect(self._browse)
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(browse)
        root.addLayout(folder_row)

        self.error_label = QLabel()
        self.error_label.setObjectName("ErrorLabel")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        root.addWidget(self.error_label)

        root.addWidget(make_divider())
        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel = secondary_button("Cancel")
        save = primary_button("OK")
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self._save)
        footer.addWidget(cancel)
        footer.addWidget(save)
        root.addLayout(footer)

    def _browse(self) -> None:
        start = self.folder_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose folder for this file type", start
        )
        if chosen:
            self.folder_edit.setText(chosen)

    def _show_error(self, text: str) -> None:
        self.error_label.setText(text)
        self.error_label.show()

    def _save(self) -> None:
        self.error_label.hide()
        try:
            extensions = normalize_extensions(
                self.extensions_edit.text().replace(";", ",").split(",")
            )
            if not extensions:
                raise LocationError("Enter at least one file extension.")
            folder = validate_folder_path(self.folder_edit.text())
        except LocationError as exc:
            self._show_error(str(exc))
            return
        self._rule = LocationRule(folder=folder, extensions=extensions)
        self.accept()

    def rule(self) -> LocationRule:
        if self._rule is None:
            raise RuntimeError("The dialog has not been accepted.")
        return self._rule
