"""Advanced Settings workspace with the most useful persisted options."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...core.paths import ensure_download_dir
from ...core.settings import AppSettings
from .. import icons
from ..theme import THEME_LABELS, THEME_ORDER, ThemeManager
from .common import Card, PageScroll


class AdvancedSettingsPage(QWidget):
    settings_applied = Signal()
    options_requested = Signal()
    import_requested = Signal()
    export_requested = Signal()
    scheduler_requested = Signal()
    queue_requested = Signal()
    message = Signal(str)

    def __init__(
        self,
        theme: ThemeManager,
        settings: AppSettings,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._settings = settings
        self.setObjectName("PageArea")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        page = PageScroll(theme, self)
        root.addWidget(page)
        body = page.body

        location = Card(
            theme,
            "Download location",
            "New downloads and recovered partial files are stored here.",
        )
        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        self._folder_edit = QLineEdit()
        self._browse_button = QPushButton("Browse…")
        self._browse_button.setIcon(
            icons.icon("folder", theme.palette.text_muted, 14)
        )
        self._browse_button.clicked.connect(self._browse)
        folder_row.addWidget(self._folder_edit, 1)
        folder_row.addWidget(self._browse_button)
        location.add_layout(folder_row)
        body.addWidget(location)

        transfers = Card(theme, "Transfers", "Engine limits applied to new connections")
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        self._concurrent = QSpinBox()
        self._concurrent.setRange(1, 10)
        self._connections = QSpinBox()
        self._connections.setRange(1, 16)
        self._speed = QSpinBox()
        self._speed.setRange(0, 1024 * 1024)
        self._speed.setSingleStep(64)
        self._speed.setSuffix(" KB/s")
        self._speed.setSpecialValueText("Unlimited")
        self._start_check = QCheckBox("Start downloads immediately")
        self._restore_check = QCheckBox("Restore the download list at startup")
        self._retry_check = QCheckBox("Retry transient network failures")
        self._network_check = QCheckBox("Resume automatically when the connection returns")
        self._confirm_check = QCheckBox("Ask before removing downloads")
        rows = (
            ("Simultaneous downloads", self._concurrent),
            ("Connections per download", self._connections),
            ("Global speed limit", self._speed),
            ("", self._start_check),
            ("", self._restore_check),
            ("", self._retry_check),
            ("", self._network_check),
            ("", self._confirm_check),
        )
        for row, (title, widget) in enumerate(rows):
            if title:
                label = QLabel(title)
                label.setObjectName("SettingTitle")
                grid.addWidget(label, row, 0)
            grid.addWidget(widget, row, 1, 1, 2)
        grid.setColumnStretch(1, 1)
        transfers.add_layout(grid)
        body.addWidget(transfers)

        interface = Card(theme, "Interface", "Sidebar, toolbar and list visibility")
        ui_grid = QGridLayout()
        ui_grid.setHorizontalSpacing(16)
        ui_grid.setVerticalSpacing(8)
        self._theme_combo = QComboBox()
        for mode in THEME_ORDER:
            self._theme_combo.addItem(THEME_LABELS[mode], mode)
        self._toolbar_check = QCheckBox("Show the toolbar")
        self._sidebar_check = QCheckBox("Show the navigation sidebar")
        self._list_check = QCheckBox("Show the download list")
        self._status_check = QCheckBox("Show the status bar")
        theme_label = QLabel("Colour theme")
        theme_label.setObjectName("SettingTitle")
        ui_grid.addWidget(theme_label, 0, 0)
        ui_grid.addWidget(self._theme_combo, 0, 1, 1, 2)
        for row, widget in enumerate(
            (
                self._toolbar_check,
                self._sidebar_check,
                self._list_check,
                self._status_check,
            ),
            start=1,
        ):
            ui_grid.addWidget(widget, row, 1, 1, 2)
        ui_grid.setColumnStretch(1, 1)
        interface.add_layout(ui_grid)
        body.addWidget(interface)

        tools = Card(theme, "Tools", "Import, export, scheduling and the full options dialog")
        tool_row = QHBoxLayout()
        tool_row.setSpacing(8)
        import_button = QPushButton("  Import downloads")
        import_button.setIcon(icons.icon("import", theme.palette.text_muted, 14))
        import_button.clicked.connect(self.import_requested)
        export_button = QPushButton("  Export downloads")
        export_button.setIcon(icons.icon("export", theme.palette.text_muted, 14))
        export_button.clicked.connect(self.export_requested)
        scheduler_button = QPushButton("  Scheduler")
        scheduler_button.setIcon(icons.icon("scheduler", theme.palette.text_muted, 14))
        scheduler_button.clicked.connect(self.scheduler_requested)
        queue_button = QPushButton("  Queue")
        queue_button.setIcon(icons.icon("queue", theme.palette.text_muted, 14))
        queue_button.clicked.connect(self.queue_requested)
        options_button = QPushButton("All options…")
        options_button.clicked.connect(self.options_requested)
        for button in (
            import_button,
            export_button,
            scheduler_button,
            queue_button,
            options_button,
        ):
            tool_row.addWidget(button)
        tool_row.addStretch(1)
        tools.add_layout(tool_row)
        body.addWidget(tools)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self._apply_button = QPushButton("Apply settings")
        self._apply_button.setObjectName("PrimaryButton")
        self._apply_button.clicked.connect(self._apply)
        self._reload_button = QPushButton("Discard changes")
        self._reload_button.setObjectName("SubtleButton")
        self._reload_button.clicked.connect(self._load)
        footer.addWidget(self._apply_button)
        footer.addWidget(self._reload_button)
        footer.addStretch(1)
        body.addLayout(footer)
        body.addStretch(1)

        theme.changed.connect(self._load_theme)
        self._load()

    # ------------------------------------------------------------------ data
    def _load_theme(self) -> None:
        index = self._theme_combo.findData(self._settings.theme)
        if index >= 0:
            self._theme_combo.setCurrentIndex(index)

    def _load(self) -> None:
        s = self._settings
        self._folder_edit.setText(s.download_dir)
        self._concurrent.setValue(int(s.max_concurrent))
        self._connections.setValue(int(s.connections_per_download))
        self._speed.setValue(int(s.speed_limit_kbps))
        self._start_check.setChecked(bool(s.start_immediately))
        self._restore_check.setChecked(bool(s.restore_session))
        self._retry_check.setChecked(bool(s.auto_retry))
        self._network_check.setChecked(bool(s.auto_resume_on_network))
        self._confirm_check.setChecked(bool(s.confirm_delete))
        self._toolbar_check.setChecked(bool(s.show_toolbar))
        self._sidebar_check.setChecked(bool(s.show_sidebar))
        self._list_check.setChecked(bool(s.show_download_list))
        self._status_check.setChecked(bool(s.show_status_bar))
        self._load_theme()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._load()

    def _browse(self) -> None:
        start = self._folder_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose download folder", start
        )
        if chosen:
            self._folder_edit.setText(chosen)

    def _apply(self) -> None:
        folder_text = self._folder_edit.text().strip()
        if not folder_text:
            QMessageBox.warning(
                self, "Download folder", "Choose a folder for new downloads."
            )
            return
        try:
            folder = ensure_download_dir(folder_text)
        except OSError as exc:
            QMessageBox.warning(
                self, "Download folder", f"Could not use that folder:\n\n{exc}"
            )
            return

        s = self._settings
        s.download_dir = str(folder)
        s.max_concurrent = int(self._concurrent.value())
        s.connections_per_download = int(self._connections.value())
        s.speed_limit_kbps = int(self._speed.value())
        s.start_immediately = bool(self._start_check.isChecked())
        s.restore_session = bool(self._restore_check.isChecked())
        s.auto_retry = bool(self._retry_check.isChecked())
        s.auto_resume_on_network = bool(self._network_check.isChecked())
        s.confirm_delete = bool(self._confirm_check.isChecked())
        s.show_toolbar = bool(self._toolbar_check.isChecked())
        s.show_sidebar = bool(self._sidebar_check.isChecked())
        s.show_download_list = bool(self._list_check.isChecked())
        s.show_status_bar = bool(self._status_check.isChecked())
        selected_theme = str(self._theme_combo.currentData() or s.theme)
        s.theme = selected_theme
        s.save()
        self._theme.set_mode(selected_theme)
        self.settings_applied.emit()
        self.message.emit("Settings saved.")
