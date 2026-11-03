"""Application options dialog with live theme previews."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
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
from ...core import network
from ...core.bandwidth import (
    MEASURE_WINDOW_SECONDS,
    MIN_SPEED_LIMIT_PERCENT,
    SPEED_LIMIT_FIXED,
    SPEED_LIMIT_PERCENT,
    SPEED_LIMIT_UNLIMITED,
)
from ...core.credentials import CredentialError
from ...core.paths import default_download_dir
from ...core.settings import AppSettings
from ...core.url_utils import format_size
from ...updater.schedule import parse_timestamp
from ...updater.version_manager import current_version
from .. import icons
from ..theme import THEME_LABELS, THEME_ORDER, ThemeManager, resolved_palette
from .common import (
    BaseDialog,
    make_divider,
    make_header,
    make_label,
    primary_button,
    secondary_button,
)
from .categories import CategoryManagerDialog
from .location_rule import LocationRuleDialog
from .site_auth import SiteAuthDialog

def _format_update_time(value: str) -> str:
    moment = parse_timestamp(value)
    if moment is None:
        return "Never"
    return moment.astimezone().strftime("%Y-%m-%d %H:%M")


_THEME_DESCRIPTIONS = {
    "classic": (
        "The original IDM look: compact grey chrome and classic blue meters. "
        "Kept for existing preferences."
    ),
    "light": "Bright Fluent surfaces, soft borders and azure accents.",
    "dark": "Layered charcoal surfaces with a brighter azure accent.",
    "system": "Automatically follows the Windows light or dark setting.",
}


class _ThemePreview(QWidget):
    def __init__(self, mode: str, parent=None) -> None:
        super().__init__(parent)
        self._palette = resolved_palette(mode)
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
        capacity_reader=None,
        measure_request=None,
    ) -> None:
        super().__init__(theme, parent)
        self._settings = settings
        # The live link measurement lives in the engine, not in settings, so the
        # dialog is handed readers instead of the manager itself.
        self._capacity_reader = capacity_reader or (lambda: 0)
        self._measure_request = measure_request or (lambda: False)
        self._values: dict | None = None
        self._check_requested = False
        self._original_theme = theme.mode
        self._preview_mode = theme.mode
        self._site_auth: list[dict] = [
            dict(entry) for entry in getattr(settings, "site_auth", [])
        ]
        self._original_site_auth = {
            entry["host"]: dict(entry) for entry in self._site_auth
        }
        self._pending_site_passwords: dict[str, tuple[str, str]] = {}
        self._removed_site_hosts: set[str] = set()
        self._proxy_has_password = bool(network.proxy_password(settings))
        self._proxy_password_removed = False

        self.setWindowTitle("IDM Options")
        self.setMinimumSize(700, 540)
        self.resize(940, 640)
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
        self._tabs.addTab(self._scrollable(self._build_general_tab()), "General")
        self._tabs.addTab(self._scrollable(self._build_downloads_tab()), "Download Settings")
        self._tabs.addTab(self._scrollable(self._build_save_to_tab()), "Save To")
        self._tabs.addTab(
            self._scrollable(self._build_connections_tab()), "Connection Settings"
        )
        self._tabs.addTab(self._scrollable(self._build_interface_tab()), "User Interface")
        self._tabs.addTab(self._scrollable(self._build_theme_tab()), "Themes")
        self._tabs.addTab(self._scrollable(self._build_updates_tab()), "Updates")
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

    @staticmethod
    def _scrollable(page: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("DialogScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        return scroll

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

        layout.addWidget(make_label("SYSTEM INTEGRATION", "FieldLabel"))
        self.startup_checkbox = QCheckBox(
            "Start IDM automatically when I sign in to Windows"
        )
        self.startup_checkbox.setChecked(self._settings.start_with_windows)
        self.startup_checkbox.setToolTip(
            "Writes IDM's own value under HKCU\\Software\\Microsoft\\Windows"
            "\\CurrentVersion\\Run for this user account only."
        )
        layout.addWidget(self.startup_checkbox)
        self.tray_checkbox = QCheckBox(
            "Show IDM in the notification area (system tray)"
        )
        self.tray_checkbox.setChecked(self._settings.tray_enabled)
        self.tray_checkbox.setToolTip(
            "Adds the tray icon with Open, Pause all, Resume all and Quit."
        )
        layout.addWidget(self.tray_checkbox)
        self.tray_close_checkbox = QCheckBox(
            "Hide IDM in the tray instead of closing it"
        )
        self.tray_close_checkbox.setChecked(self._settings.tray_on_close)
        self.tray_close_checkbox.setEnabled(self._settings.tray_enabled)
        self.tray_checkbox.toggled.connect(self.tray_close_checkbox.setEnabled)
        layout.addWidget(self.tray_close_checkbox)
        self.native_notify_checkbox = QCheckBox(
            "Show a Windows notification when a download finishes or fails"
        )
        self.native_notify_checkbox.setChecked(self._settings.native_notifications)
        self.native_notify_checkbox.setEnabled(self._settings.tray_enabled)
        self.tray_checkbox.toggled.connect(self.native_notify_checkbox.setEnabled)
        layout.addWidget(self.native_notify_checkbox)
        layout.addSpacing(10)

        layout.addWidget(make_label("CONFIRMATIONS", "FieldLabel"))
        self.confirm_checkbox = QCheckBox(
            "Ask before removing downloads from the list"
        )
        self.confirm_checkbox.setChecked(self._settings.confirm_delete)
        layout.addWidget(self.confirm_checkbox)
        self.completion_checkbox = QCheckBox(
            "Show the Download Complete window after a transfer finishes"
        )
        self.completion_checkbox.setChecked(self._settings.show_completion_dialog)
        layout.addWidget(self.completion_checkbox)
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

        layout.addWidget(make_label("BANDWIDTH LIMIT", "FieldLabel"))
        self.speed_unlimited = QRadioButton("No limit")
        self.speed_fixed = QRadioButton("Fixed maximum:")
        self.speed_percent = QRadioButton("Percentage of the measured link:")
        self._speed_group = QButtonGroup(self)
        layout.addWidget(self.speed_unlimited)

        fixed_row = QHBoxLayout()
        fixed_row.setSpacing(10)
        fixed_row.addSpacing(24)
        fixed_row.addWidget(self.speed_fixed)
        self.speed_spin = QSpinBox()
        self.speed_spin.setRange(0, MAX_SPEED_LIMIT_KBPS)
        self.speed_spin.setSingleStep(128)
        self.speed_spin.setValue(self._settings.speed_limit_kbps)
        self.speed_spin.setSpecialValueText("Unlimited")
        self.speed_spin.setSuffix(" KB/s")
        fixed_row.addWidget(self.speed_spin)
        fixed_row.addStretch(1)
        layout.addLayout(fixed_row)

        percent_row = QHBoxLayout()
        percent_row.setSpacing(10)
        percent_row.addSpacing(24)
        percent_row.addWidget(self.speed_percent)
        self.speed_percent_spin = QSpinBox()
        self.speed_percent_spin.setRange(MIN_SPEED_LIMIT_PERCENT, 100)
        self.speed_percent_spin.setSingleStep(5)
        self.speed_percent_spin.setValue(self._settings.speed_limit_percent)
        self.speed_percent_spin.setSuffix(" %")
        self.speed_percent_spin.valueChanged.connect(self._refresh_capacity_label)
        percent_row.addWidget(self.speed_percent_spin)
        percent_row.addStretch(1)
        layout.addLayout(percent_row)

        for index, button in enumerate(
            (self.speed_unlimited, self.speed_fixed, self.speed_percent)
        ):
            self._speed_group.addButton(button, index)

        mode = getattr(self._settings, "speed_limit_mode", SPEED_LIMIT_UNLIMITED)
        self.speed_unlimited.setChecked(mode == SPEED_LIMIT_UNLIMITED)
        self.speed_fixed.setChecked(mode == SPEED_LIMIT_FIXED)
        self.speed_percent.setChecked(mode == SPEED_LIMIT_PERCENT)
        if not any(
            button.isChecked()
            for button in (
                self.speed_unlimited,
                self.speed_fixed,
                self.speed_percent,
            )
        ):
            self.speed_unlimited.setChecked(True)
        self._speed_group.idToggled.connect(self._on_speed_mode_changed)

        self.capacity_label = make_label("", "HintLabel")
        self.capacity_label.setWordWrap(True)
        layout.addWidget(self.capacity_label)

        measure_row = QHBoxLayout()
        measure_row.setSpacing(10)
        measure_row.addSpacing(24)
        self.measure_button = QPushButton("Measure the link now")
        self.measure_button.setObjectName("SubtleButton")
        self.measure_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.measure_button.clicked.connect(self._measure_capacity)
        measure_row.addWidget(self.measure_button)
        measure_row.addStretch(1)
        layout.addLayout(measure_row)

        hint = make_label(
            "A percentage limit is taken from the speed IDM sees while downloads "
            "run, so it drops on its own when the connection slows down. A "
            "faster link stays hidden behind the limit, so use the button above "
            "to measure it when you move to a quicker network. Nothing can be "
            "measured while the link is idle: start a download first.",
            "HintLabel",
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self._sync_speed_limit_inputs()
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------ bandwidth
    def _on_speed_mode_changed(self, _button_id: int, checked: bool) -> None:
        if checked:
            self._sync_speed_limit_inputs()

    def _sync_speed_limit_inputs(self) -> None:
        self.speed_spin.setEnabled(self.speed_fixed.isChecked())
        self.speed_percent_spin.setEnabled(self.speed_percent.isChecked())
        self.measure_button.setEnabled(self.speed_percent.isChecked())
        self._refresh_capacity_label()

    def _speed_limit_mode(self) -> str:
        if self.speed_fixed.isChecked():
            return SPEED_LIMIT_FIXED
        if self.speed_percent.isChecked():
            return SPEED_LIMIT_PERCENT
        return SPEED_LIMIT_UNLIMITED

    def _refresh_capacity_label(self) -> None:
        kbps = max(0, int(self._capacity_reader() or 0))
        if not kbps:
            self.capacity_label.setText("Measured link: not measured yet.")
            return
        if self.speed_percent.isChecked():
            limit = kbps * self.speed_percent_spin.value() // 100
            self.capacity_label.setText(
                f"Measured link: {format_size(kbps * 1024)}/s. "
                f"{self.speed_percent_spin.value()} % of it is "
                f"{format_size(limit * 1024)}/s."
            )
        else:
            self.capacity_label.setText(
                f"Measured link: {format_size(kbps * 1024)}/s."
            )

    def _measure_capacity(self) -> None:
        if not self._measure_request():
            self.capacity_label.setText(
                "Nothing is downloading right now, so there is no traffic to "
                "measure. Start a download and try again."
            )
            return
        self.capacity_label.setText("Measuring the link for a few seconds…")
        QTimer.singleShot(
            int(MEASURE_WINDOW_SECONDS * 1000) + 500, self._refresh_capacity_label
        )

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

        category_row = QHBoxLayout()
        category_row.setSpacing(8)
        category_row.addWidget(
            make_label(
                "Categories remember a folder for each file type. They are "
                "offered in the Download File Info dialog.",
                "HintLabel",
            ),
            1,
        )
        self._categories_button = secondary_button("Categories & folders…")
        self._categories_button.clicked.connect(self._manage_categories)
        category_row.addWidget(self._categories_button)
        layout.addLayout(category_row)
        layout.addStretch(1)

        self._refresh_rules()
        self._update_mode_state()
        return page

    def _manage_categories(self) -> None:
        dialog = CategoryManagerDialog(self._settings, self._theme, self)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

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
        layout.addSpacing(14)

        layout.addWidget(make_label("PROXY SERVER", "FieldLabel"))
        self.proxy_mode_combo = QComboBox()
        self.proxy_mode_combo.addItem("Use the Windows proxy settings", "system")
        self.proxy_mode_combo.addItem("Connect directly (no proxy)", "direct")
        self.proxy_mode_combo.addItem("Use a manual HTTP proxy", "manual")
        index = self.proxy_mode_combo.findData(
            network.normalize_proxy_mode(getattr(self._settings, "proxy_mode", "system"))
        )
        self.proxy_mode_combo.setCurrentIndex(max(0, index))
        layout.addWidget(self.proxy_mode_combo)

        proxy_grid = QGridLayout()
        proxy_grid.setHorizontalSpacing(10)
        proxy_grid.setVerticalSpacing(7)
        proxy_grid.addWidget(make_label("Host:"), 0, 0)
        self.proxy_host_edit = QLineEdit(
            str(getattr(self._settings, "proxy_host", "") or "")
        )
        self.proxy_host_edit.setPlaceholderText("proxy.example.com")
        self.proxy_host_edit.setMinimumHeight(30)
        proxy_grid.addWidget(self.proxy_host_edit, 0, 1)
        proxy_grid.addWidget(make_label("Port:"), 0, 2)
        self.proxy_port_spin = QSpinBox()
        self.proxy_port_spin.setRange(1, 65535)
        self.proxy_port_spin.setValue(
            int(getattr(self._settings, "proxy_port", 8080) or 8080)
        )
        proxy_grid.addWidget(self.proxy_port_spin, 0, 3)
        proxy_grid.addWidget(make_label("Bypass:"), 1, 0)
        self.proxy_bypass_edit = QLineEdit(
            str(getattr(self._settings, "proxy_bypass", "") or "")
        )
        self.proxy_bypass_edit.setPlaceholderText("localhost, 192.168.0.*, *.local")
        self.proxy_bypass_edit.setMinimumHeight(30)
        proxy_grid.addWidget(self.proxy_bypass_edit, 1, 1, 1, 3)
        layout.addLayout(proxy_grid)

        self.proxy_auth_check = QCheckBox("The proxy requires authentication")
        self.proxy_auth_check.setChecked(
            bool(getattr(self._settings, "proxy_use_auth", False))
        )
        layout.addWidget(self.proxy_auth_check)
        proxy_auth_row = QHBoxLayout()
        proxy_auth_row.setSpacing(8)
        self.proxy_username_edit = QLineEdit(
            str(getattr(self._settings, "proxy_username", "") or "")
        )
        self.proxy_username_edit.setPlaceholderText("User name")
        self.proxy_username_edit.setMinimumHeight(30)
        self.proxy_password_edit = QLineEdit()
        self.proxy_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.proxy_password_edit.setMinimumHeight(30)
        self.proxy_password_edit.setPlaceholderText(
            "Saved password" if self._proxy_has_password else "Password"
        )
        self.proxy_forget_button = QPushButton("Forget")
        self.proxy_forget_button.setObjectName("SubtleButton")
        self.proxy_forget_button.setToolTip(
            "Remove the password from Windows Credential Manager"
        )
        self.proxy_forget_button.clicked.connect(self._forget_proxy_password)
        proxy_auth_row.addWidget(self.proxy_username_edit, 1)
        proxy_auth_row.addWidget(self.proxy_password_edit, 1)
        proxy_auth_row.addWidget(self.proxy_forget_button)
        layout.addLayout(proxy_auth_row)
        proxy_hint = make_label(
            "Proxy passwords are stored in Windows Credential Manager, not in "
            "the IDM database. The bypass list accepts hosts, domain suffixes "
            "and * wildcards.",
            "HintLabel",
        )
        proxy_hint.setWordWrap(True)
        layout.addWidget(proxy_hint)
        self.proxy_mode_combo.currentIndexChanged.connect(
            self._update_proxy_controls
        )
        self.proxy_auth_check.toggled.connect(self._update_proxy_controls)
        self._update_proxy_controls()
        layout.addSpacing(14)

        layout.addWidget(make_label("SERVER AUTHENTICATION", "FieldLabel"))
        auth_hint = make_label(
            "Automatically sign in to password-protected HTTP, HTTPS or FTP "
            "servers. Passwords are kept in Windows Credential Manager.",
            "HintLabel",
        )
        auth_hint.setWordWrap(True)
        layout.addWidget(auth_hint)
        self.site_auth_table = QTableWidget(0, 3)
        self.site_auth_table.setHorizontalHeaderLabels(["Host", "User name", "Method"])
        self.site_auth_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.site_auth_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.site_auth_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.site_auth_table.verticalHeader().setVisible(False)
        self.site_auth_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.site_auth_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.site_auth_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.site_auth_table.setMinimumHeight(120)
        self.site_auth_table.itemSelectionChanged.connect(
            self._update_auth_buttons
        )
        self.site_auth_table.itemDoubleClicked.connect(
            lambda _item: self._edit_site_auth()
        )
        layout.addWidget(self.site_auth_table)
        auth_buttons = QHBoxLayout()
        auth_buttons.setSpacing(8)
        self.add_auth_button = QPushButton("Add…")
        self.edit_auth_button = QPushButton("Edit…")
        self.remove_auth_button = QPushButton("Remove")
        self.remove_auth_button.setObjectName("DangerButton")
        self.add_auth_button.clicked.connect(self._add_site_auth)
        self.edit_auth_button.clicked.connect(self._edit_site_auth)
        self.remove_auth_button.clicked.connect(self._remove_site_auth)
        auth_buttons.addWidget(self.add_auth_button)
        auth_buttons.addWidget(self.edit_auth_button)
        auth_buttons.addWidget(self.remove_auth_button)
        auth_buttons.addStretch(1)
        layout.addLayout(auth_buttons)
        self._refresh_site_auth_table()
        layout.addSpacing(14)

        layout.addWidget(make_label("TIMEOUTS", "FieldLabel"))
        timeout_row = QHBoxLayout()
        timeout_row.setSpacing(10)
        timeout_row.addWidget(make_label("Connect timeout:"))
        self.connect_timeout_spin = QSpinBox()
        self.connect_timeout_spin.setRange(3, 120)
        self.connect_timeout_spin.setSuffix(" s")
        self.connect_timeout_spin.setValue(
            int(getattr(self._settings, "connect_timeout", 15) or 15)
        )
        timeout_row.addWidget(self.connect_timeout_spin)
        timeout_row.addSpacing(16)
        timeout_row.addWidget(make_label("Read timeout:"))
        self.read_timeout_spin = QSpinBox()
        self.read_timeout_spin.setRange(3, 300)
        self.read_timeout_spin.setSuffix(" s")
        self.read_timeout_spin.setValue(
            int(getattr(self._settings, "read_timeout", 30) or 30)
        )
        timeout_row.addWidget(self.read_timeout_spin)
        timeout_row.addStretch(1)
        layout.addLayout(timeout_row)
        timeout_hint = make_label(
            "A stalled connection is retried after the read timeout. Increase "
            "both values on very slow or high-latency links.",
            "HintLabel",
        )
        timeout_hint.setWordWrap(True)
        layout.addWidget(timeout_hint)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------ proxy/auth
    def _forget_proxy_password(self) -> None:
        self._proxy_password_removed = True
        self._proxy_has_password = False
        self.proxy_password_edit.clear()
        self.proxy_password_edit.setPlaceholderText("No password saved")
        self._update_proxy_controls()

    def _update_proxy_controls(self) -> None:
        manual = self.proxy_mode_combo.currentData() == "manual"
        use_auth = manual and self.proxy_auth_check.isChecked()
        for widget in (
            self.proxy_host_edit,
            self.proxy_port_spin,
            self.proxy_bypass_edit,
            self.proxy_auth_check,
        ):
            widget.setEnabled(manual)
        for widget in (
            self.proxy_username_edit,
            self.proxy_password_edit,
            self.proxy_forget_button,
        ):
            widget.setEnabled(use_auth)

    def _refresh_site_auth_table(self) -> None:
        table = self.site_auth_table
        table.blockSignals(True)
        table.setRowCount(0)
        for entry in self._site_auth:
            row = table.rowCount()
            table.insertRow(row)
            host_item = QTableWidgetItem(entry["host"])
            host_item.setData(Qt.ItemDataRole.UserRole, entry["host"])
            table.setItem(row, 0, host_item)
            table.setItem(row, 1, QTableWidgetItem(entry["username"]))
            table.setItem(
                row,
                2,
                QTableWidgetItem("Digest" if entry["scheme"] == "digest" else "Basic"),
            )
        table.blockSignals(False)
        self._update_auth_buttons()

    def _selected_site_auth(self) -> dict | None:
        rows = self.site_auth_table.selectionModel().selectedRows()
        if not rows:
            return None
        host = self.site_auth_table.item(rows[0].row(), 0).data(
            Qt.ItemDataRole.UserRole
        )
        return next(
            (entry for entry in self._site_auth if entry["host"] == host), None
        )

    def _update_auth_buttons(self) -> None:
        selected = self._selected_site_auth() is not None
        self.edit_auth_button.setEnabled(selected)
        self.remove_auth_button.setEnabled(selected)

    def _add_site_auth(self) -> None:
        dialog = SiteAuthDialog(self._theme, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        host, username, scheme, password = dialog.values()
        self._pending_site_passwords[host] = (username, password)
        self._site_auth = [
            entry for entry in self._site_auth if entry["host"] != host
        ]
        self._site_auth.append(
            {"host": host, "username": username, "scheme": scheme}
        )
        self._site_auth.sort(key=lambda entry: entry["host"])
        self._refresh_site_auth_table()

    def _edit_site_auth(self) -> None:
        entry = self._selected_site_auth()
        if entry is None:
            return
        has_password = entry["host"] in self._pending_site_passwords or (
            network.has_site_password(entry["host"])
            and entry["host"] not in self._removed_site_hosts
        )
        dialog = SiteAuthDialog(
            self._theme, entry=entry, has_password=has_password, parent=self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        host, username, scheme, password = dialog.values()
        old_host = entry["host"]
        if host != old_host:
            self._removed_site_hosts.add(old_host)
            self._pending_site_passwords.pop(old_host, None)
            if not password and not network.has_site_password(host):
                self._show_error(
                    "Enter the password again when the host changes."
                )
                return
        if password:
            self._pending_site_passwords[host] = (username, password)
        elif username != entry["username"]:
            self._show_error("Enter the password again when the user name changes.")
            return
        self._site_auth = [
            item for item in self._site_auth if item["host"] != old_host
        ]
        self._site_auth.append(
            {"host": host, "username": username, "scheme": scheme}
        )
        self._site_auth.sort(key=lambda item: item["host"])
        self._refresh_site_auth_table()

    def _remove_site_auth(self) -> None:
        entry = self._selected_site_auth()
        if entry is None:
            return
        self._site_auth = [
            item for item in self._site_auth if item["host"] != entry["host"]
        ]
        self._removed_site_hosts.add(entry["host"])
        self._pending_site_passwords.pop(entry["host"], None)
        self._refresh_site_auth_table()

    def _apply_site_credentials(self) -> None:
        for host, (username, password) in self._pending_site_passwords.items():
            network.set_site_password(host, username, password)
        for host in self._removed_site_hosts:
            if host in self._original_site_auth:
                network.clear_site_password(host)
        if self._proxy_password_removed:
            network.clear_proxy_password()
            self._proxy_has_password = False
        if self.proxy_password_edit.text() and self.proxy_auth_check.isChecked():
            network.set_proxy_password(
                self.proxy_username_edit.text().strip(),
                self.proxy_password_edit.text(),
            )
            self._proxy_has_password = True
        self.proxy_password_edit.clear()
        self._pending_site_passwords.clear()
        self._removed_site_hosts.clear()
        self._original_site_auth = {
            entry["host"]: dict(entry) for entry in self._site_auth
        }
        self._proxy_password_removed = False
        self.proxy_password_edit.setPlaceholderText(
            "Saved password" if self._proxy_has_password else "Password"
        )

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

        layout.addWidget(make_label("AUTOMATIC UPDATES", "FieldLabel"))
        self.auto_check_checkbox = QCheckBox(
            "Check for updates automatically"
        )
        self.auto_check_checkbox.setChecked(
            bool(getattr(self._settings, "update_auto_check", True))
        )
        layout.addWidget(self.auto_check_checkbox)

        interval_row = QHBoxLayout()
        interval_row.setSpacing(8)
        interval_label = make_label("Check every", "HintLabel")
        interval_row.addWidget(interval_label)
        self.update_interval_spin = QSpinBox()
        self.update_interval_spin.setRange(1, 168)
        self.update_interval_spin.setSuffix(" hours")
        self.update_interval_spin.setValue(
            int(getattr(self._settings, "update_check_interval_hours", 24))
        )
        interval_row.addWidget(self.update_interval_spin)
        interval_row.addStretch(1)
        layout.addLayout(interval_row)

        self.update_notify_checkbox = QCheckBox(
            "Notify me when a new version is available"
        )
        self.update_notify_checkbox.setChecked(
            bool(getattr(self._settings, "update_notify", True))
        )
        layout.addWidget(self.update_notify_checkbox)

        auto_hint = make_label(
            "IDM checks after startup and then at the configured interval. "
            "Checks are postponed while downloads are active. Automatic checking "
            "never installs a version without your approval.",
            "HintLabel",
        )
        auto_hint.setWordWrap(True)
        layout.addWidget(auto_hint)
        layout.addSpacing(12)

        layout.addWidget(make_label("INSTALLATION", "FieldLabel"))
        self.auto_download_checkbox = QCheckBox(
            "Download new versions automatically"
        )
        self.auto_download_checkbox.setChecked(
            bool(getattr(self._settings, "update_auto_download", False))
        )
        layout.addWidget(self.auto_download_checkbox)
        self.ask_install_checkbox = QCheckBox(
            "Ask before installing an update"
        )
        self.ask_install_checkbox.setChecked(
            bool(getattr(self._settings, "update_ask_before_install", True))
        )
        layout.addWidget(self.ask_install_checkbox)
        install_hint = make_label(
            "IDM backs up the database, settings, history and queue before an "
            "update and pauses active downloads only with your consent.",
            "HintLabel",
        )
        install_hint.setWordWrap(True)
        layout.addWidget(install_hint)
        layout.addSpacing(12)

        layout.addWidget(make_label("UPDATE STATUS", "FieldLabel"))
        self.update_status_label = make_label(
            f"Installed version: {current_version()}   ·   "
            f"Channel: {getattr(self._settings, 'update_channel', 'stable')}",
            "HintLabel",
        )
        layout.addWidget(self.update_status_label)
        self.last_check_label = make_label(
            "Last check: "
            + _format_update_time(getattr(self._settings, "update_last_check", "")),
            "HintLabel",
        )
        layout.addWidget(self.last_check_label)
        self.last_success_label = make_label(
            "Last successful update: "
            + _format_update_time(getattr(self._settings, "update_last_success", "")),
            "HintLabel",
        )
        layout.addWidget(self.last_success_label)
        check_now = secondary_button("Check for Updates Now")
        check_now.clicked.connect(self._request_update_check)
        layout.addWidget(check_now, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addSpacing(12)

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
            "When a publisher is set, installers must have a valid Windows "
            "Authenticode signature and the signer must match this name exactly. "
            "Without a publisher, IDM still installs packages that match the "
            "Ed25519-signed manifest and its SHA-256 hash. The "
            "IDM_UPDATE_PUBLISHER environment variable overrides this value.",
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
        cards = QGridLayout()
        cards.setHorizontalSpacing(10)
        cards.setVerticalSpacing(10)
        self.theme_cards: dict[str, ThemeCard] = {}
        for index, mode in enumerate(THEME_ORDER):
            card = ThemeCard(mode, mode == self._settings.theme, page)
            card.clicked.connect(self._preview_theme)
            cards.addWidget(card, index // 2, index % 2)
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

        proxy_mode = str(self.proxy_mode_combo.currentData() or "system")
        proxy_host = self.proxy_host_edit.text().strip()
        proxy_use_auth = self.proxy_auth_check.isChecked()
        if proxy_mode == "manual" and not network.valid_proxy_host(proxy_host):
            self._show_error(
                "Enter the proxy host name without http:// or a path."
            )
            return
        if proxy_mode == "manual" and proxy_use_auth:
            if not self.proxy_username_edit.text().strip():
                self._show_error("Enter the user name for the proxy.")
                return
            stored = self._proxy_has_password and not self._proxy_password_removed
            if not self.proxy_password_edit.text() and not stored:
                self._show_error("Enter the password for the proxy.")
                return

        site_auth = network.normalize_site_auth(self._site_auth)
        for entry in site_auth:
            host = entry["host"]
            if host in self._pending_site_passwords:
                continue
            if network.has_site_password(host):
                continue
            self._show_error(
                f"Enter the password for {host} before saving."
            )
            return

        try:
            self._apply_site_credentials()
        except CredentialError as exc:
            self._show_error(str(exc))
            return

        self._values = {
            "theme": self._preview_mode,
            "download_dir": folder,
            "max_concurrent": self.concurrent_spin.value(),
            "connections_per_download": self.segments_spin.value(),
            "auto_retry": self.retry_checkbox.isChecked(),
            "max_retries": self.retry_spin.value(),
            "speed_limit_kbps": self.speed_spin.value(),
            "speed_limit_mode": self._speed_limit_mode(),
            "speed_limit_percent": self.speed_percent_spin.value(),
            "proxy_mode": proxy_mode,
            "proxy_host": proxy_host,
            "proxy_port": self.proxy_port_spin.value(),
            "proxy_username": self.proxy_username_edit.text().strip(),
            "proxy_use_auth": proxy_use_auth,
            "proxy_bypass": self.proxy_bypass_edit.text().strip(),
            "site_auth": site_auth,
            "connect_timeout": self.connect_timeout_spin.value(),
            "read_timeout": self.read_timeout_spin.value(),
            "confirm_delete": self.confirm_checkbox.isChecked(),
            "show_completion_dialog": self.completion_checkbox.isChecked(),
            "start_immediately": self.start_checkbox.isChecked(),
            "restore_session": self.restore_checkbox.isChecked(),
            "start_with_windows": self.startup_checkbox.isChecked(),
            "tray_enabled": self.tray_checkbox.isChecked(),
            "tray_on_close": self.tray_close_checkbox.isChecked(),
            "native_notifications": self.native_notify_checkbox.isChecked(),
            "show_toolbar": self.toolbar_check.isChecked(),
            "show_sidebar": self.sidebar_check.isChecked(),
            "show_download_list": self.list_check.isChecked(),
            "show_status_bar": self.status_check.isChecked(),
            "update_manifest_url": update_url,
            "update_publisher": self.publisher_edit.text().strip(),
            "update_channel": self.update_channel_combo.currentData(),
            "update_auto_check": self.auto_check_checkbox.isChecked(),
            "update_check_interval_hours": self.update_interval_spin.value(),
            "update_auto_download": self.auto_download_checkbox.isChecked(),
            "update_ask_before_install": self.ask_install_checkbox.isChecked(),
            "update_notify": self.update_notify_checkbox.isChecked(),
            "location_config": config,
        }
        self.accept()

    def _request_update_check(self) -> None:
        self._check_requested = True
        self._save()

    def wants_update_check(self) -> bool:
        return self._values is not None and self._check_requested

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
