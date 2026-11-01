"""Manage user-defined categories and remembered save folders."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...constants import EXTENSION_TO_CATEGORY
from ...core.categories import (
    category_names,
    normalize_category_name,
    normalize_extensions,
)
from ...core.settings import AppSettings
from ..theme import ThemeManager
from .common import (
    BaseDialog,
    make_divider,
    make_header,
    make_label,
    primary_button,
    secondary_button,
)


class CategoryEntryDialog(BaseDialog):
    """Create or rename a custom category with its extension list."""

    def __init__(
        self,
        theme: ThemeManager,
        *,
        name: str = "",
        extensions: list[str] | tuple[str, ...] = (),
        other_categories: list[dict] | None = None,
        parent=None,
    ) -> None:
        super().__init__(theme, parent)
        self._result: dict | None = None
        self._other = list(other_categories or [])

        self.setWindowTitle("Custom Category")
        self.setMinimumWidth(460)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(10)
        root.addWidget(
            make_header(
                "Custom category",
                "Choose a name and the file extensions that belong to it.",
            )
        )

        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.setColumnStretch(1, 1)

        form.addWidget(make_label("Name"), 0, 0)
        self.name_edit = QLineEdit(name)
        self.name_edit.setPlaceholderText("For example: Design assets")
        self.name_edit.setMaxLength(32)
        self.name_edit.setMinimumHeight(32)
        form.addWidget(self.name_edit, 0, 1)

        form.addWidget(make_label("Extensions"), 1, 0)
        self.extensions_edit = QLineEdit(", ".join(extensions))
        self.extensions_edit.setPlaceholderText("psd, ai, sketch")
        self.extensions_edit.setMinimumHeight(32)
        form.addWidget(self.extensions_edit, 1, 1)
        hint = QLabel(
            "Separate extensions with commas. Built-in extensions keep their "
            "original category."
        )
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        form.addWidget(hint, 2, 1)
        root.addLayout(form)

        self.error_label = QLabel()
        self.error_label.setObjectName("ErrorLabel")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        root.addWidget(self.error_label)

        root.addWidget(make_divider())
        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addStretch(1)
        cancel = secondary_button("Cancel")
        save = primary_button("Save Category")
        footer.addWidget(cancel)
        footer.addWidget(save)
        root.addLayout(footer)

        cancel.clicked.connect(self.reject)
        save.clicked.connect(self._save)
        self.name_edit.returnPressed.connect(self._save)
        self.extensions_edit.returnPressed.connect(self._save)
        self.name_edit.setFocus()

    def values(self) -> dict:
        if self._result is None:
            raise RuntimeError("The dialog has not been accepted.")
        return dict(self._result)

    def _save(self) -> None:
        self.error_label.hide()
        name = normalize_category_name(self.name_edit.text())
        if not name:
            self._show_error("Enter a category name without special characters.")
            return
        known = {
            str(entry.get("name") or "").casefold()
            for entry in self._other
            if str(entry.get("name") or "").casefold() != name.casefold()
        }
        from ...constants import _BUILTIN_CATEGORY_NAMES

        if name.casefold() in _BUILTIN_CATEGORY_NAMES or name.casefold() in known:
            self._show_error("That category name is already in use.")
            return

        raw = self.extensions_edit.text().replace(";", ",").split(",")
        extensions = normalize_extensions(raw)
        if not extensions:
            self._show_error("Add at least one extension, for example “psd”.")
            return

        used_by_builtin = {
            extension
            for extension in extensions
            if extension in EXTENSION_TO_CATEGORY
        }
        if used_by_builtin:
            self._show_error(
                "These extensions already belong to a built-in category: "
                + ", ".join(sorted(used_by_builtin))
            )
            return
        used_elsewhere = {
            extension
            for entry in self._other
            if str(entry.get("name") or "").casefold() != name.casefold()
            for extension in normalize_extensions(entry.get("extensions") or ())
            if extension in extensions
        }
        if used_elsewhere:
            self._show_error(
                "These extensions already belong to another category: "
                + ", ".join(sorted(used_elsewhere))
            )
            return

        self._result = {"name": name, "extensions": list(extensions)}
        self.accept()

    def _show_error(self, text: str) -> None:
        self.error_label.setText(text)
        self.error_label.show()


class CategoryManagerDialog(BaseDialog):
    """Review built-in categories, custom categories and remembered folders."""

    def __init__(
        self, settings: AppSettings, theme: ThemeManager, parent=None
    ) -> None:
        super().__init__(theme, parent)
        self._settings = settings
        self._custom = [
            dict(entry) for entry in settings.custom_categories
        ]

        self.setWindowTitle("Categories and Save Folders")
        self.setMinimumSize(660, 460)
        self.setSizeGripEnabled(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(10)
        root.addWidget(
            make_header(
                "Categories and save folders",
                "Built-in categories keep their extensions. Add your own and "
                "remember a folder for any category.",
            )
        )

        self.table = QTableWidget(0, 3)
        self.table.setObjectName("DialogTable")
        self.table.setHorizontalHeaderLabels(
            ["Category", "Extensions", "Remembered folder"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        root.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self._add_button = secondary_button("Add Category…")
        self._edit_button = secondary_button("Edit…")
        self._remove_button = secondary_button("Remove")
        self._folder_button = secondary_button("Set Remembered Folder…")
        self._forget_button = secondary_button("Forget Folder")
        for button in (
            self._add_button,
            self._edit_button,
            self._remove_button,
            self._folder_button,
            self._forget_button,
        ):
            buttons.addWidget(button)
        buttons.addStretch(1)
        root.addLayout(buttons)

        self._add_button.clicked.connect(self._add_category)
        self._edit_button.clicked.connect(self._edit_category)
        self._remove_button.clicked.connect(self._remove_category)
        self._folder_button.clicked.connect(self._set_folder)
        self._forget_button.clicked.connect(self._forget_folder)

        root.addWidget(make_divider())
        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addWidget(
            QLabel(
                "Remembered folders are used by the Download File Info dialog "
                "and can be changed at any time."
            ),
            1,
        )
        close = primary_button("Done")
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        root.addLayout(footer)

        self._refresh()

    # ------------------------------------------------------------------ helpers
    def _selected_name(self) -> str:
        row = self.table.currentRow()
        if row < 0:
            return ""
        item = self.table.item(row, 0)
        return item.text() if item is not None else ""

    def _is_custom(self, name: str) -> bool:
        return any(
            str(entry.get("name") or "").casefold() == name.casefold()
            for entry in self._custom
        )

    def _custom_entry(self, name: str) -> dict | None:
        for entry in self._custom:
            if str(entry.get("name") or "").casefold() == name.casefold():
                return entry
        return None

    def _extensions_label(self, name: str) -> str:
        entry = self._custom_entry(name)
        if entry is not None:
            extensions = normalize_extensions(entry.get("extensions") or ())
        else:
            extensions = tuple(
                sorted(
                    extension
                    for extension, category in EXTENSION_TO_CATEGORY.items()
                    if category == name
                )
            )
        return ", ".join(f".{extension}" for extension in extensions) or "—"

    def _refresh(self, select: str = "") -> None:
        remembered = self._settings.category_paths
        names = category_names(self._custom)
        self.table.blockSignals(True)
        self.table.setRowCount(len(names))
        for row, name in enumerate(names):
            name_item = QTableWidgetItem(name)
            name_item.setData(Qt.ItemDataRole.UserRole, name)
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QTableWidgetItem(self._extensions_label(name)))
            folder = remembered.get(name) or "—"
            self.table.setItem(row, 2, QTableWidgetItem(folder))
        self.table.blockSignals(False)
        if select:
            for row in range(self.table.rowCount()):
                if self.table.item(row, 0).text().casefold() == select.casefold():
                    self.table.selectRow(row)
                    break
        if self.table.currentRow() < 0 and self.table.rowCount():
            self.table.selectRow(0)
        self._update_buttons()

    def _update_buttons(self) -> None:
        name = self._selected_name()
        custom = self._is_custom(name)
        self._edit_button.setEnabled(custom)
        self._remove_button.setEnabled(custom)
        self._folder_button.setEnabled(bool(name))
        self._forget_button.setEnabled(
            bool(name) and bool(self._settings.category_paths.get(name))
        )

    def _persist_custom(self) -> None:
        self._settings.update({"custom_categories": self._custom})
        self._settings.save()

    # ------------------------------------------------------------------ actions
    def _add_category(self) -> None:
        dialog = CategoryEntryDialog(
            self._theme, other_categories=self._custom, parent=self
        )
        try:
            if dialog.exec() != CategoryEntryDialog.DialogCode.Accepted:
                return
            entry = dialog.values()
        finally:
            dialog.deleteLater()
        self._custom.append(entry)
        self._persist_custom()
        self._refresh(entry["name"])

    def _edit_category(self) -> None:
        name = self._selected_name()
        entry = self._custom_entry(name)
        if entry is None:
            return
        dialog = CategoryEntryDialog(
            self._theme,
            name=entry["name"],
            extensions=list(entry.get("extensions") or ()),
            other_categories=self._custom,
            parent=self,
        )
        try:
            if dialog.exec() != CategoryEntryDialog.DialogCode.Accepted:
                return
            updated = dialog.values()
        finally:
            dialog.deleteLater()
        replaced_ok = False
        new_custom: list[dict] = []
        for item in self._custom:
            if item is entry:
                new_custom.append(updated)
                replaced_ok = True
            else:
                new_custom.append(item)
        if not replaced_ok:
            return
        if updated["name"] != entry["name"] and entry["name"] in self._settings.category_paths:
            self._settings.remember_category_folder(
                updated["name"], self._settings.category_paths[entry["name"]]
            )
            self._settings.forget_category_folder(entry["name"])
        self._custom = new_custom
        self._persist_custom()
        self._refresh(updated["name"])

    def _remove_category(self) -> None:
        name = self._selected_name()
        entry = self._custom_entry(name)
        if entry is None:
            return
        self._custom = [
            item for item in self._custom if str(item.get("name")) != name
        ]
        self._settings.forget_category_folder(name)
        self._persist_custom()
        self._refresh()

    def _set_folder(self) -> None:
        name = self._selected_name()
        if not name:
            return
        start = self._settings.category_paths.get(name) or self._settings.download_dir
        chosen = QFileDialog.getExistingDirectory(
            self, f"Remembered folder for {name}", start
        )
        if not chosen:
            return
        self._settings.remember_category_folder(name, chosen)
        self._refresh(name)

    def _forget_folder(self) -> None:
        name = self._selected_name()
        if not name:
            return
        self._settings.forget_category_folder(name)
        self._refresh(name)


__all__ = ["CategoryEntryDialog", "CategoryManagerDialog"]
