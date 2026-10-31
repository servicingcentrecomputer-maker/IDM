"""Application options dialog with live theme previews."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QRadioButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from downloads.location_manager import (
    MODE_ASK,
    MODE_DEFAULT,
    MODE_TYPE,
    DownloadLocationConfig,
    LocationError,
    LocationRule,
    default_rules_for,
    ensure_folder,
    validate_folder_path,
)

from ...constants import MAX_SPEED_LIMIT_KBPS
from ...core.paths import default_download_dir
from ...core.settings import AppSettings
from .. import icons
from ..theme import PALETTES, THEME_LABELS, THEME_ORDER, ThemeManager
from .common import (
    BaseDialog,
    make_divider,
    make_header,
    make_label,
    primary_button,
    secondary_button,
)
from .location_rule import LocationRuleDialog

_THEME_DESCRIPTIONS = {
    "classic": "Light grey chrome with the classic blue progress bars.",
    "light": "Clean white panels and rounded modern controls.",
    "dark": "A low-light palette for comfortable night use.",
}


class _ThemePreview(QWidget):
    def __init__(self, mode: str, parent=None) -> None:
        super().__init__(parent)
        self._palette = PALETTES[mode]
        self.setFixedHeight(74)

    def paintEvent(self, event) -> None:
        p = self._palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor(p.border), 1))
        painter.setBrush(QColor(p.bg))
        painter.drawRoundedRect(rect, 4, 4)

        toolbar = QRectF(rect.left() + 1, rect.top() + 1, rect.width() - 2, 13)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(p.surface_alt if p.toolbar_background.startswith("#") else p.surface))
        painter.drawRect(toolbar)
        for index in range(5):
            painter.setBrush(QColor(p.accent if index < 2 else p.text_faint))
            painter.drawEllipse(
                QRectF(toolbar.left() + 6 + index * 10, toolbar.top() + 4, 5, 5)
            )

        sidebar = QRectF(rect.left() + 1, toolbar.bottom(), 34, rect.height() - 14)
        painter.setBrush(QColor(p.surface))
        painter.drawRect(sidebar)
        painter.setBrush(QColor(p.accent_soft))
        painter.drawRoundedRect(
            QRectF(sidebar.left() + 4, sidebar.top() + 7, 26, 8), 2, 2
        )
        for index in range(2):
            painter.setBrush(QColor(p.text_faint))
            painter.drawRoundedRect(
                QRectF(sidebar.left() + 6, sidebar.top() + 22 + index * 9, 21, 4),
                2,
                2,
            )

        content_left = sidebar.right() + 8
        content_width = rect.right() - content_left - 6
        for index in range(3):
            top = toolbar.bottom() + 7 + index * 15
            painter.setBrush(QColor(p.surface))
            painter.drawRoundedRect(QRectF(content_left, top, content_width, 11), 2, 2)
            painter.setBrush(QColor(p.track))
            painter.drawRoundedRect(
                QRectF(content_left + 4, top + 7, content_width - 34, 2.5), 1.2, 1.2
            )
            fraction = (0.75, 0.45, 1.0)[index]
            painter.setBrush(QColor(p.accent))
            painter.drawRoundedRect(
                QRectF(
                    content_left + 4,
                    top + 7,
                    (content_width - 34) * fraction,
                    2.5,
                ),
                1.2,
                1.2,
            )

        painter.setBrush(QColor(p.sidebar_active))
        painter.drawRoundedRect(QRectF(sidebar.left() + 4, sidebar.top() + 7, 2.5, 8), 1, 1)
        painter.end()


class ThemeCard(QFrame):
    clicked = Signal(str)

    def __init__(self, mode: str, selected: bool, parent=None) -> None:
        super().__init__(parent)
        self.mode = mode
        self.setObjectName("ThemeCard")
        self.setProperty("selected", "true" if selected else "false")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(_ThemePreview(mode, self))

        title = QLabel(THEME_LABELS[mode])
        title.setObjectName("ThemeTitle")
        title_font = QFont(title.font())
        title_font.setWeight(QFont.Weight.DemiBold)
        title.setFont(title_font)
        layout.addWidget(title)

        description = QLabel(_THEME_DESCRIPTIONS[mode])
        description.setObjectName("ThemeDescription")
        description.setWordWrap(True)
        layout.addWidget(description)
        layout.addStretch(1)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", "true" if selected else "false")
        style = self.style()
        style.unpolish(self)
        style.polish(self)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.mode)
        super().mouseReleaseEvent(event)


class OptionsDialog(BaseDialog):
    def __init__(
        self,
        settings: AppSettings,
        theme: ThemeManager,
        parent=None,
        initial_tab: int = 0,
    ) -> None:
        super().__init__(theme, parent)
        self._settings = settings
        self._values: dict | None = None
        self._original_theme = theme.mode
        self._preview_mode = theme.mode

        self.setWindowTitle("IDM Options")
        self.setMinimumSize(700, 540)
        self.setSizeGripEnabled(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(12)

        root.addWidget(
            make_header(
                "IDM Options",
                "Configure downloads, folders, connections and the interface.",
            )
        )

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_general_tab(), "General")
        self._tabs.addTab(self._build_downloads_tab(), "Download Settings")
        self._tabs.addTab(self._build_save_to_tab(), "Save To")
        self._tabs.addTab(self._build_connections_tab(), "Connection Settings")
        self._tabs.addTab(self._build_interface_tab(), "User Interface")
        self._tabs.addTab(self._build_theme_tab(), "Themes")
        self._tabs.addTab(self._build_updates_tab(), "Updates")
        self._tabs.setCurrentIndex(
            max(0, min(int(initial_tab), self._tabs.count() - 1))
        )
        root.addWidget(self._tabs, 1)

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
        save = primary_button("OK")
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self._save)
        footer.addWidget(cancel)
        footer.addWidget(save)
        root.addLayout(footer)

    # ------------------------------------------------------------------ pages
    def _page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("TabPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(7)
        return page

    def _build_general_tab(self) -> QWidget:
        page = self._page()
        layout = page.layout()

        layout.addWidget(make_label("STARTUP", "FieldLabel"))
        self.start_checkbox = QCheckBox(
            "Start downloads immediately when they are added"
        )
        self.start_checkbox.setChecked(self._settings.start_immediately)
        layout.addWidget(self.start_checkbox)
        self.restore_checkbox = QCheckBox(
            "Restore the download list the next time IDM starts"
        )
        self.restore_checkbox.setChecked(self._settings.restore_session)
        layout.addWidget(self.restore_checkbox)
        layout.addSpacing(10)

        layout.addWidget(make_label("CONFIRMATIONS", "FieldLabel"))
        self.confirm_checkbox = QCheckBox(
            "Ask before removing downloads from the list"
        )
        self.confirm_checkbox.setChecked(self._settings.confirm_delete)
        layout.addWidget(self.confirm_checkbox)
        layout.addSpacing(10)

        layout.addWidget(make_label("STORAGE", "FieldLabel"))
        hint = make_label(
            "Settings and download history are stored in a local SQLite database "
            "inside your Windows application-data folder.",
            "HintLabel",
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    def _build_downloads_tab(self) -> QWidget:
        page = self._page()
        layout = page.layout()

        layout.addWidget(make_label("AUTOMATIC RETRY", "FieldLabel"))
        self.retry_checkbox = QCheckBox(
            "Retry downloads after temporary network failures"
        )
        self.retry_checkbox.setChecked(self._settings.auto_retry)
        layout.addWidget(self.retry_checkbox)

        retry_row = QHBoxLayout()
        retry_row.setSpacing(10)
        retry_row.addWidget(make_label("Retry attempts:"))
        self.retry_spin = QSpinBox()
        self.retry_spin.setRange(0, 10)
        self.retry_spin.setValue(self._settings.max_retries)
        self.retry_spin.setEnabled(self._settings.auto_retry)
        retry_row.addWidget(self.retry_spin)
        retry_row.addStretch(1)
        layout.addLayout(retry_row)
        self.retry_checkbox.toggled.connect(self.retry_spin.setEnabled)

        hint = make_label(
            "Interrupted transfers resume from the last saved byte when the server "
            "supports HTTP Range requests.",
            "HintLabel",
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addSpacing(10)

        layout.addWidget(make_label("SPEED LIMIT", "FieldLabel"))
        speed_row = QHBoxLayout()
        speed_row.setSpacing(10)
        speed_row.addWidget(make_label("Maximum download speed:"))
        self.speed_spin = QSpinBox()
        self.speed_spin.setRange(0, MAX_SPEED_LIMIT_KBPS)
        self.speed_spin.setSingleStep(128)
        self.speed_spin.setValue(self._settings.speed_limit_kbps)
        self.speed_spin.setSpecialValueText("Unlimited")
        self.speed_spin.setSuffix(" KB/s")
        speed_row.addWidget(self.speed_spin)
        speed_row.addStretch(1)
        layout.addLayout(speed_row)
        hint = make_label(
            "Set 0 for unlimited bandwidth. The limit applies to all active downloads.",
            "HintLabel",
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    def _build_save_to_tab(self) -> QWidget:
        page = self._page()
        layout = page.layout()
        config = self._settings.location_config.normalized()
        self._rules: list[LocationRule] = list(config.rules)

        layout.addWidget(make_label("DEFAULT DOWNLOAD FOLDER", "FieldLabel"))
        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        self.folder_edit = QLineEdit(self._settings.download_dir)
        self.folder_edit.setMinimumHeight(30)
        self._browse_button = secondary_button("Browse…")
        self._browse_button.setIcon(
            icons.icon("folder", self._theme.palette.text_muted, 16)
        )
        self._browse_button.clicked.connect(self._browse_folder)
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(self._browse_button)
        layout.addLayout(folder_row)
        hint = make_label(
            "Downloads are saved here unless a file type rule below applies or "
            "you pick another folder in the Add Download dialog.",
            "HintLabel",
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addSpacing(10)

        layout.addWidget(make_label("LOCATION MODE", "FieldLabel"))
        self.mode_group = QButtonGroup(page)
        self.mode_default = QRadioButton("Use the default folder for every download")
        self.mode_ask = QRadioButton("Ask for a folder before each download")
        self.mode_type = QRadioButton("Choose the folder by file type")
        for radio, mode in (
            (self.mode_default, MODE_DEFAULT),
            (self.mode_ask, MODE_ASK),
            (self.mode_type, MODE_TYPE),
        ):
            radio.setProperty("mode", mode)
            self.mode_group.addButton(radio)
            layout.addWidget(radio)
        chosen = {
            MODE_ASK: self.mode_ask,
            MODE_TYPE: self.mode_type,
        }.get(config.mode, self.mode_default)
        chosen.setChecked(True)
        self.mode_group.buttonToggled.connect(
            lambda _button, checked: checked and self._update_mode_state()
        )

        self._mode_hint = make_label("", "HintLabel")
        self._mode_hint.setWordWrap(True)
        layout.addWidget(self._mode_hint)
        layout.addSpacing(8)

        rules_header = QHBoxLayout()
        rules_header.setSpacing(8)
        rules_header.addWidget(make_label("FILE TYPE RULES", "FieldLabel"))
        rules_header.addStretch(1)
        self._rule_add_button = secondary_button("Add rule…")
        self._rule_edit_button = secondary_button("Edit…")
        self._rule_remove_button = secondary_button("Remove")
        self._recommended_button = secondary_button("Recommended folders")
        for button in (
            self._rule_add_button,
            self._rule_edit_button,
            self._rule_remove_button,
            self._recommended_button,
        ):
            rules_header.addWidget(button)
        layout.addLayout(rules_header)

        self._rules_table = QTableWidget(0, 2)
        self._rules_table.setHorizontalHeaderLabels(["File extensions", "Folder"])
        self._rules_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._rules_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._rules_table.verticalHeader().setVisible(False)
        self._rules_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._rules_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._rules_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._rules_table.setMinimumHeight(150)
        self._rules_table.itemSelectionChanged.connect(self._update_rule_buttons)
        self._rules_table.itemDoubleClicked.connect(lambda _item: self._edit_rule())
        layout.addWidget(self._rules_table)

        self._rule_add_button.clicked.connect(self._add_rule)
        self._rule_edit_button.clicked.connect(self._edit_rule)
        self._rule_remove_button.clicked.connect(self._remove_rule)
        self._recommended_button.clicked.connect(self._use_recommended_rules)

        browser_hint = make_label(
            "Chrome, Edge and Firefox send downloads through the local IDM "
            "bridge and use these folder settings. IDM never receives browser "
            "passwords, cookies or authorisation tokens.",
            "HintLabel",
        )
        browser_hint.setWordWrap(True)
        layout.addWidget(browser_hint)
        layout.addStretch(1)

        self._refresh_rules()
        self._update_mode_state()
        return page

    # ------------------------------------------------------------------ location rules
    def _current_mode(self) -> str:
        button = self.mode_group.checkedButton()
        return str(button.property("mode")) if button is not None else MODE_DEFAULT

    def _update_mode_state(self) -> None:
        mode = self._current_mode()
        type_mode = mode == MODE_TYPE
        self._rules_table.setEnabled(type_mode)
        self._rule_add_button.setEnabled(type_mode)
        self._recommended_button.setEnabled(type_mode)
        self._update_rule_buttons()
        if mode == MODE_ASK:
            text = (
                "IDM opens a folder picker before each download. Browser "
                "downloads are only cancelled after a folder is chosen and IDM "
                "accepts the task."
            )
        elif mode == MODE_TYPE:
            text = (
                "The first matching rule wins. Unmatched files use the default "
                "folder. Use * as an extension for a catch-all rule."
            )
        else:
            text = "Every download is saved in the default folder."
        self._mode_hint.setText(text)

    def _refresh_rules(self) -> None:
        self._rules_table.setRowCount(0)
        for rule in self._rules:
            row = self._rules_table.rowCount()
            self._rules_table.insertRow(row)
            extensions = QTableWidgetItem(", ".join(rule.extensions))
            extensions.setToolTip("Matches: " + ", ".join(rule.extensions))
            folder = QTableWidgetItem(rule.folder)
            folder.setToolTip(rule.folder)
            self._rules_table.setItem(row, 0, extensions)
            self._rules_table.setItem(row, 1, folder)
        self._update_rule_buttons()

    def _selected_rule_index(self) -> int:
        rows = self._rules_table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def _update_rule_buttons(self) -> None:
        enabled = self._current_mode() == MODE_TYPE
        selected = enabled and self._selected_rule_index() >= 0
        self._rule_edit_button.setEnabled(selected)
        self._rule_remove_button.setEnabled(selected)

    def _add_rule(self) -> None:
        dialog = LocationRuleDialog(self._theme, parent=self)
        try:
            if dialog.exec() != LocationRuleDialog.DialogCode.Accepted:
                return
            rule = dialog.rule()
        finally:
            dialog.deleteLater()
        self._rules.append(rule)
        self._refresh_rules()
        self._rules_table.selectRow(len(self._rules) - 1)

    def _edit_rule(self) -> None:
        index = self._selected_rule_index()
        if index < 0:
            return
        dialog = LocationRuleDialog(self._theme, self._rules[index], self)
        try:
            if dialog.exec() != LocationRuleDialog.DialogCode.Accepted:
                return
            self._rules[index] = dialog.rule()
        finally:
            dialog.deleteLater()
        self._refresh_rules()
        self._rules_table.selectRow(index)

    def _remove_rule(self) -> None:
        index = self._selected_rule_index()
        if index < 0:
            return
        del self._rules[index]
        self._refresh_rules()

    def _use_recommended_rules(self) -> None:
        folder = self.folder_edit.text().strip() or str(default_download_dir())
        try:
            validate_folder_path(folder)
            rules = default_rules_for(folder)
        except LocationError as exc:
            self._show_error(str(exc))
            return
        if self._rules:
            answer = QMessageBox.question(
                self,
                "Replace file type rules",
                "Replace the current rules with recommended Archives, Software, "
                "Documents, Media and Images folders under the default folder?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._rules = rules
        self._refresh_rules()

    def _build_connections_tab(self) -> QWidget:
        page = self._page()
        layout = page.layout()

        layout.addWidget(make_label("SIMULTANEOUS DOWNLOADS", "FieldLabel"))
        concurrent_row = QHBoxLayout()
        concurrent_row.setSpacing(10)
        concurrent_row.addWidget(make_label("Maximum downloads at once:"))
        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setRange(1, 10)
        self.concurrent_spin.setValue(self._settings.max_concurrent)
        concurrent_row.addWidget(self.concurrent_spin)
        concurrent_row.addStretch(1)
        layout.addLayout(concurrent_row)
        hint = make_label(
            "Additional downloads wait in the queue until a slot becomes available.",
            "HintLabel",
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addSpacing(10)

        layout.addWidget(make_label("CONNECTIONS PER DOWNLOAD", "FieldLabel"))
        segments_row = QHBoxLayout()
        segments_row.setSpacing(10)
        segments_row.addWidget(make_label("Segmented connections:"))
        self.segments_spin = QSpinBox()
        self.segments_spin.setRange(1, 16)
        self.segments_spin.setValue(self._settings.connections_per_download)
        self.segments_spin.setToolTip(
            "Maximum parallel HTTP Range connections for one file."
        )
        segments_row.addWidget(self.segments_spin)
        segments_row.addStretch(1)
        layout.addLayout(segments_row)

        note = QLabel(
            "Segmented downloading is used only when the server supports HTTP "
            "Range requests and the file is large enough for at least two "
            "segments. Otherwise IDM safely uses one connection."
        )
        note.setObjectName("HintLabel")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _build_interface_tab(self) -> QWidget:
        page = self._page()
        layout = page.layout()

        layout.addWidget(make_label("WINDOW ELEMENTS", "FieldLabel"))
        self.toolbar_check = QCheckBox("Show the toolbar")
        self.toolbar_check.setChecked(self._settings.show_toolbar)
        layout.addWidget(self.toolbar_check)
        self.sidebar_check = QCheckBox("Show the categories sidebar")
        self.sidebar_check.setChecked(self._settings.show_sidebar)
        layout.addWidget(self.sidebar_check)
        self.list_check = QCheckBox("Show the download list")
        self.list_check.setChecked(self._settings.show_download_list)
        layout.addWidget(self.list_check)
        self.status_check = QCheckBox("Show the status bar")
        self.status_check.setChecked(self._settings.show_status_bar)
        layout.addWidget(self.status_check)
        layout.addSpacing(10)

        hint = make_label(
            "The same switches are available from the View menu. The window "
            "position and size are remembered automatically.",
            "HintLabel",
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    def _build_updates_tab(self) -> QWidget:
        page = self._page()
        layout = page.layout()

        layout.addWidget(make_label("UPDATE SERVER", "FieldLabel"))
        self.update_url_edit = QLineEdit(self._settings.update_manifest_url)
        self.update_url_edit.setMinimumHeight(30)
        self.update_url_edit.setPlaceholderText(
            "https://example.com/idm/latest.json"
        )
        layout.addWidget(self.update_url_edit)
        url_hint = make_label(
            "HTTPS address of the release manifest. Leave blank to disable update "
            "checks. The IDM_UPDATE_MANIFEST_URL environment variable overrides "
            "this value.",
            "HintLabel",
        )
        url_hint.setWordWrap(True)
        layout.addWidget(url_hint)
        layout.addSpacing(12)

        layout.addWidget(make_label("UPDATE CHANNEL", "FieldLabel"))
        self.update_channel_combo = QComboBox()
        self.update_channel_combo.addItem("Stable releases", "stable")
        self.update_channel_combo.addItem("Beta releases", "beta")
        channel_index = self.update_channel_combo.findData(
            self._settings.update_channel
        )
        self.update_channel_combo.setCurrentIndex(max(0, channel_index))
        self.update_channel_combo.setMinimumHeight(30)
        layout.addWidget(self.update_channel_combo)
        channel_hint = make_label(
            "Stable accepts only stable manifests. Beta also accepts stable "
            "releases. The IDM_UPDATE_CHANNEL environment variable overrides "
            "this value.",
            "HintLabel",
        )
        channel_hint.setWordWrap(True)
        layout.addWidget(channel_hint)
        layout.addSpacing(12)

        layout.addWidget(make_label("TRUSTED PUBLISHER", "FieldLabel"))
        self.publisher_edit = QLineEdit(self._settings.update_publisher)
        self.publisher_edit.setMinimumHeight(30)
        self.publisher_edit.setPlaceholderText(
            "Exact Authenticode signer name, for example Your Company Ltd"
        )
        layout.addWidget(self.publisher_edit)
        publisher_hint = make_label(
            "Installers are only accepted when Windows Authenticode verifies them "
            "and the signer matches this name exactly. A publisher is required to "
            "install updates. The IDM_UPDATE_PUBLISHER environment variable "
            "overrides this value.",
            "HintLabel",
        )
        publisher_hint.setWordWrap(True)
        layout.addWidget(publisher_hint)
        layout.addSpacing(12)

        security_hint = make_label(
            "Downloads must use HTTPS, come from the manifest host or a configured "
            "trusted host, and match the SHA-256 hash in the manifest before "
            "installation. IDM never runs scripts received from the update server.",
            "HintLabel",
        )
        security_hint.setWordWrap(True)
        layout.addWidget(security_hint)
        layout.addStretch(1)
        return page

    def _build_theme_tab(self) -> QWidget:
        page = self._page()
        layout = page.layout()

        layout.addWidget(make_label("THEME", "FieldLabel"))
        cards = QHBoxLayout()
        cards.setSpacing(10)
        self.theme_cards: dict[str, ThemeCard] = {}
        for mode in THEME_ORDER:
            card = ThemeCard(mode, mode == self._settings.theme, page)
            card.clicked.connect(self._preview_theme)
            cards.addWidget(card, 1)
            self.theme_cards[mode] = card
        layout.addLayout(cards)
        layout.addSpacing(8)

        hint = make_label(
            "The selected theme is applied immediately so you can preview it. "
            "Choosing Cancel restores the previous theme.",
            "HintLabel",
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------ actions
    def _preview_theme(self, mode: str) -> None:
        self._preview_mode = mode
        for key, card in self.theme_cards.items():
            card.set_selected(key == mode)
        self._theme.set_mode(mode)
        self._browse_button.setIcon(
            icons.icon("folder", self._theme.palette.text_muted, 16)
        )

    def _browse_folder(self) -> None:
        start = self.folder_edit.text().strip() or str(default_download_dir())
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose default download folder", start
        )
        if chosen:
            self.folder_edit.setText(chosen)

    @staticmethod
    def _saving_approves_folder(_folder: str) -> bool:
        # Pressing OK with the path visible in this dialog is the user's
        # explicit approval to create it.  Browser requests use a separate
        # confirmation because the user may not have seen the folder.
        return True

    def _save(self) -> None:
        self.error_label.hide()
        folder = self.folder_edit.text().strip()
        if not folder:
            self._show_error("Choose a default download folder.")
            return
        try:
            folder = validate_folder_path(folder)
            folder = ensure_folder(
                folder, approve_create=self._saving_approves_folder
            )
        except LocationError as exc:
            self._show_error(str(exc))
            return

        config = DownloadLocationConfig(
            mode=self._current_mode(), rules=list(self._rules)
        )
        try:
            config.validate()
        except LocationError as exc:
            self._show_error(str(exc))
            return
        if config.mode == MODE_TYPE:
            for rule in config.rules:
                try:
                    ensure_folder(
                        rule.folder, approve_create=self._saving_approves_folder
                    )
                except LocationError as exc:
                    self._show_error(
                        f"Rule for {', '.join(rule.extensions)}: {exc}"
                    )
                    return

        update_url = self.update_url_edit.text().strip()
        if update_url:
            parsed = urlsplit(update_url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                self._show_error(
                    "The update manifest URL must be a plain HTTPS address "
                    "without embedded credentials."
                )
                return

        self._values = {
            "theme": self._preview_mode,
            "download_dir": folder,
            "max_concurrent": self.concurrent_spin.value(),
            "connections_per_download": self.segments_spin.value(),
            "auto_retry": self.retry_checkbox.isChecked(),
            "max_retries": self.retry_spin.value(),
            "speed_limit_kbps": self.speed_spin.value(),
            "confirm_delete": self.confirm_checkbox.isChecked(),
            "start_immediately": self.start_checkbox.isChecked(),
            "restore_session": self.restore_checkbox.isChecked(),
            "show_toolbar": self.toolbar_check.isChecked(),
            "show_sidebar": self.sidebar_check.isChecked(),
            "show_download_list": self.list_check.isChecked(),
            "show_status_bar": self.status_check.isChecked(),
            "update_manifest_url": update_url,
            "update_publisher": self.publisher_edit.text().strip(),
            "update_channel": self.update_channel_combo.currentData(),
            "location_config": config,
        }
        self.accept()

    def reject(self) -> None:
        if self._values is None and self._preview_mode != self._original_theme:
            self._theme.set_mode(self._original_theme)
        super().reject()

    def _show_error(self, text: str) -> None:
        self.error_label.setText(text)
        self.error_label.show()

    def values(self) -> dict:
        if self._values is None:
            raise RuntimeError("The dialog has not been accepted.")
        return dict(self._values)
