"""Main application window."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QByteArray, QModelIndex, QPoint, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QDesktopServices,
    QGuiApplication,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from ..constants import (
    APP_DESCRIPTION,
    APP_NAME,
    APP_VERSION,
    CATEGORY_FILTER_KEYS,
    PRIORITY_NORMAL,
)
from ..core.paths import database_backup_dir, updater_log_file
from ..core.scheduler import DownloadScheduler
from ..core.settings import AppSettings
from ..core.url_utils import category_for_filename, guess_filename
from ..engine.manager import DownloadManager
from ..models.download_item import DownloadItem, DownloadStatus
from ..models.table_model import DownloadFilterProxyModel, DownloadTableModel
from ..updater.errors import UpdaterError
from ..updater.launcher import (
    InstallRequest,
    stage_and_launch,
    updater_executable,
)
from integrations.service import BrowserIntegrationService
from . import icons
from .dialogs.about import AboutDialog
from .dialogs.add_download import AddDownloadDialog
from .dialogs.options import OptionsDialog
from .dialogs.progress import DownloadProgressDialog
from .dialogs.queue import QueueDialog
from .dialogs.scheduler import SchedulerDialog
from .download_view import DownloadView
from .sidebar import Sidebar
from .status_bar import StatusBar
from .theme import THEME_LABELS, THEME_ORDER, ThemeManager
from .toolbar import DownloadToolbar

logger = logging.getLogger(__name__)

_FILTER_TITLES = {
    "all": "All Downloads",
    "downloading": "Downloading",
    "completed": "Completed",
    "documents": "Documents",
    "music": "Music",
    "videos": "Videos",
    "programs": "Programs",
    "compressed": "Compressed Files",
}

_RESUMABLE_ALL = {DownloadStatus.PAUSED, DownloadStatus.STOPPED}


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings, theme: ThemeManager) -> None:
        super().__init__()
        self._settings = settings
        self._theme = theme
        self._shutdown_done = False
        self._shortcuts: list[QShortcut] = []
        self._actions: dict[str, QAction] = {}
        self._action_icons: dict[str, str] = {}
        self._theme_actions: dict[str, QAction] = {}
        self._progress_dialogs: dict[str, DownloadProgressDialog] = {}

        self._manager = DownloadManager(settings, self)
        self._browser = BrowserIntegrationService(
            settings,
            self._manager,
            folder_prompt=self._prompt_browser_folder,
            create_prompt=self._confirm_create_folder,
            raise_window=self._raise_for_browser,
            open_settings=self._open_browser_settings,
            parent=self,
        )
        self._scheduler = DownloadScheduler(self._manager, self)
        self._model = DownloadTableModel(self._manager)
        self._proxy = DownloadFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)

        self.setWindowTitle(f"{APP_NAME} – {APP_DESCRIPTION}")
        self.setWindowIcon(icons.app_icon())
        self.setMinimumSize(1040, 600)
        self.resize(1240, 760)

        self._build_menu_bar()
        self._build_ui()
        self._wire_signals()
        self._install_shortcuts()
        self._restore_geometry()
        self._apply_view_settings()
        self._refresh_page_state()
        self._update_actions()

        restored = len(self._manager.items())
        if restored:
            self._status_bar.show_message(
                f"Restored {restored} download{'s' if restored != 1 else ''} "
                "from the previous session."
            )

        self._browser.message.connect(self._status_bar.show_message)
        self._browser.bridge_failed.connect(self._status_bar.show_message)
        if self._browser.start():
            logger.info("Browser integration is available on port %d", self._browser.bridge.port)
        else:
            logger.warning("Browser integration is unavailable in this session")

        self._theme.apply_window_chrome(self)
        logger.info("Main window ready")

    # ------------------------------------------------------------------ menu
    def _build_menu_bar(self) -> None:
        bar = self.menuBar()
        bar.setNativeMenuBar(False)
        p = self._theme.palette

        file_menu = bar.addMenu("&File")
        self._add_action(
            file_menu, "add", "Add Download…", self._add_download,
            "Ctrl+N", "add",
        )
        self._add_action(
            file_menu, "import", "Import Downloads…", self._import_downloads,
            "Ctrl+Shift+I", "import",
        )
        self._add_action(
            file_menu, "export", "Export Downloads…", self._export_downloads,
            "Ctrl+Shift+E", "export",
        )
        file_menu.addSeparator()
        self._add_action(
            file_menu, "exit", "Exit", self.close, "Ctrl+Q", "exit"
        )

        downloads_menu = bar.addMenu("&Downloads")
        self._add_action(
            downloads_menu, "resume", "Resume", self._resume_selected,
            "Ctrl+R", "resume",
        )
        self._add_action(
            downloads_menu, "resume_all", "Resume All", self._resume_all,
            "Ctrl+Shift+R", "resume_all",
        )
        self._add_action(
            downloads_menu, "pause", "Pause", self._pause_selected,
            "Ctrl+P", "pause",
        )
        self._add_action(
            downloads_menu, "pause_all", "Pause All", self._pause_all,
            "Ctrl+Shift+P", "pause_all",
        )
        self._add_action(
            downloads_menu, "stop", "Stop", self._stop_selected,
            "Ctrl+Shift+S", "stop",
        )
        downloads_menu.addSeparator()
        self._add_action(
            downloads_menu, "delete", "Delete", self._delete_selected, None, "delete"
        )
        self._add_action(
            downloads_menu, "delete_completed", "Delete Completed",
            self._delete_completed, "Ctrl+Shift+Delete", "delete_completed",
        )

        view_menu = bar.addMenu("&View")
        self._add_view_action(view_menu, "show_toolbar", "Toolbar")
        self._add_view_action(view_menu, "show_sidebar", "Categories")
        self._add_view_action(view_menu, "show_download_list", "Download List")
        self._add_view_action(view_menu, "show_status_bar", "Status Bar")
        view_menu.addSeparator()

        theme_menu = view_menu.addMenu("Theme")
        theme_menu.setIcon(icons.icon("palette", p.text_muted, 16))
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)
        for mode in THEME_ORDER:
            action = QAction(THEME_LABELS[mode], self)
            action.setCheckable(True)
            action.setChecked(self._settings.theme == mode)
            action.triggered.connect(
                lambda _checked=False, selected=mode: self._set_theme(selected)
            )
            theme_group.addAction(action)
            theme_menu.addAction(action)
            self._theme_actions[mode] = action

        help_menu = bar.addMenu("&Help")
        self._add_action(
            help_menu, "docs", "Documentation", self._show_documentation, "F1", "help"
        )
        self._add_action(
            help_menu, "check_updates", "Check for Updates…",
            lambda: self._show_about(check=True), None, "arrow_up",
        )
        self._add_action(
            help_menu, "about", f"About {APP_NAME}", self._show_about, None, "info"
        )

    def _add_action(
        self,
        menu: QMenu,
        key: str,
        text: str,
        callback,
        shortcut: str | None = None,
        icon_name: str | None = None,
    ) -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        if icon_name:
            action.setIcon(
                icons.icon(icon_name, self._theme.palette.text_muted, 16)
            )
            self._action_icons[key] = icon_name
        action.triggered.connect(callback)
        menu.addAction(action)
        self._actions[key] = action
        return action

    def _add_view_action(self, menu: QMenu, setting_key: str, text: str) -> None:
        action = QAction(text, self)
        action.setCheckable(True)
        action.setChecked(bool(getattr(self._settings, setting_key)))
        action.toggled.connect(
            lambda visible, key=setting_key: self._set_view_flag(key, visible)
        )
        menu.addAction(action)
        self._actions[f"view_{setting_key}"] = action

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._toolbar = DownloadToolbar(self._theme, central)
        root.addWidget(self._toolbar)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self._sidebar = Sidebar(self._theme, body)
        body_layout.addWidget(self._sidebar)

        content = QWidget()
        content.setObjectName("ContentArea")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 14, 16, 12)
        content_layout.setSpacing(10)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(16)

        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(2)
        self._page_title = QLabel("All Downloads")
        self._page_title.setObjectName("PageTitle")
        self._page_subtitle = QLabel()
        self._page_subtitle.setObjectName("PageSubtitle")
        title_box.addWidget(self._page_title)
        title_box.addWidget(self._page_subtitle)
        header_layout.addLayout(title_box)
        header_layout.addStretch(1)

        self._search = QLineEdit()
        self._search.setObjectName("SearchBox")
        self._search.setPlaceholderText("Search downloads")
        self._search.setClearButtonEnabled(True)
        self._search.setFixedWidth(260)
        self._search_action = QAction(
            icons.icon("search", self._theme.palette.text_faint, 16), "", self._search
        )
        self._search.addAction(
            self._search_action, QLineEdit.ActionPosition.LeadingPosition
        )
        header_layout.addWidget(self._search, 0, Qt.AlignmentFlag.AlignVCenter)

        content_layout.addWidget(header)

        self._download_view = DownloadView(self._theme, content)
        self._download_view.table.setModel(self._proxy)
        self._download_view.table.selectionModel().selectionChanged.connect(
            self._update_actions
        )
        self._download_view.table.customContextMenuRequested.connect(
            self._show_context_menu
        )
        self._download_view.table.doubleClicked.connect(self._on_double_click)
        self._download_view.add_requested.connect(self._add_download)
        content_layout.addWidget(self._download_view, 1)

        body_layout.addWidget(content, 1)
        root.addWidget(body, 1)

        self._status_bar = StatusBar(self._theme, central)
        root.addWidget(self._status_bar)

        self.setCentralWidget(central)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, lambda: self._theme.apply_window_chrome(self))

    # ------------------------------------------------------------------ wiring
    def _wire_signals(self) -> None:
        toolbar = self._toolbar
        toolbar.add_requested.connect(self._add_download)
        toolbar.resume_requested.connect(self._resume_selected)
        toolbar.resume_all_requested.connect(self._resume_all)
        toolbar.pause_requested.connect(self._pause_selected)
        toolbar.stop_requested.connect(self._stop_selected)
        toolbar.delete_requested.connect(self._delete_selected)
        toolbar.options_requested.connect(self._open_options)
        toolbar.scheduler_requested.connect(self._open_scheduler)
        toolbar.queue_requested.connect(self._open_queue)
        toolbar.theme_toggled.connect(self._cycle_theme)

        self._sidebar.filter_changed.connect(self._on_filter_changed)
        self._search.textChanged.connect(self._on_search_changed)

        self._manager.download_added.connect(self._on_manager_changed)
        self._manager.download_updated.connect(self._on_manager_changed)
        self._manager.download_removed.connect(self._on_manager_changed)
        self._manager.stats_changed.connect(self._on_stats_changed)
        self._manager.download_completed.connect(self._on_download_completed)
        self._manager.download_failed.connect(self._on_download_failed)

        self._scheduler.schedule_fired.connect(
            lambda action: self._status_bar.show_message(
                f"Scheduler: {action.lower()}."
            )
        )

        self._proxy.layoutChanged.connect(self._refresh_page_state)
        self._proxy.rowsInserted.connect(self._refresh_page_state)
        self._proxy.rowsRemoved.connect(self._refresh_page_state)
        self._proxy.modelReset.connect(self._refresh_page_state)

        self._theme.changed.connect(self._on_theme_changed)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._shutdown)

    def _install_shortcuts(self) -> None:
        delete_shortcut = QShortcut(
            QKeySequence(Qt.Key.Key_Delete), self._download_view.table
        )
        delete_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete_shortcut.activated.connect(self._delete_selected)
        self._shortcuts.append(delete_shortcut)

        escape_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self._search)
        escape_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        escape_shortcut.activated.connect(self._clear_search)
        self._shortcuts.append(escape_shortcut)

    def _restore_geometry(self) -> None:
        saved = self._settings.load_bytes("window/geometry")
        if saved:
            try:
                if self.restoreGeometry(QByteArray(saved)):
                    return
            except Exception:
                logger.debug("Could not restore window geometry", exc_info=True)
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            self.move(
                QPoint(
                    available.center().x() - self.width() // 2,
                    available.center().y() - self.height() // 2,
                )
            )

    # ------------------------------------------------------------------ selection
    def _selected_items(self) -> list[DownloadItem]:
        table = self._download_view.table
        selection = table.selectionModel()
        if selection is None:
            return []
        items: list[DownloadItem] = []
        seen: set[str] = set()
        for proxy_index in selection.selectedRows():
            source_index = self._proxy.mapToSource(proxy_index)
            item = self._model.item_at(source_index.row())
            if item is not None and item.id not in seen:
                seen.add(item.id)
                items.append(item)
        return items

    def _item_from_index(self, proxy_index: QModelIndex) -> DownloadItem | None:
        if not proxy_index.isValid():
            return None
        source_index = self._proxy.mapToSource(proxy_index)
        return self._model.item_at(source_index.row())

    def _update_actions(self, *_args) -> None:
        items = self._selected_items()
        all_items = self._manager.items()
        completed_exists = any(
            item.status == DownloadStatus.COMPLETED for item in all_items
        )
        resumable_all = any(item.status in _RESUMABLE_ALL for item in all_items)
        pausable_all = any(item.can_pause for item in all_items)

        self._toolbar.update_actions(
            can_pause=any(item.can_pause for item in items),
            can_resume=any(item.can_resume for item in items),
            can_stop=any(item.can_stop for item in items),
            can_delete=bool(items),
            can_resume_all=resumable_all,
        )
        self._actions["resume"].setEnabled(any(item.can_resume for item in items))
        self._actions["resume_all"].setEnabled(resumable_all)
        self._actions["pause"].setEnabled(any(item.can_pause for item in items))
        self._actions["pause_all"].setEnabled(pausable_all)
        self._actions["stop"].setEnabled(any(item.can_stop for item in items))
        self._actions["delete"].setEnabled(bool(items))
        self._actions["delete_completed"].setEnabled(completed_exists)
        self._actions["export"].setEnabled(bool(all_items))

    def _select_item(self, download_id: str) -> None:
        source_row = self._model.row_for_id(download_id)
        if source_row < 0:
            return
        source_index = self._model.index(source_row, 0)
        proxy_index = self._proxy.mapFromSource(source_index)
        if not proxy_index.isValid():
            return
        table = self._download_view.table
        table.setCurrentIndex(proxy_index)
        table.scrollTo(proxy_index, table.ScrollHint.EnsureVisible)

    # ------------------------------------------------------------------ actions
    def _add_download(self) -> None:
        dialog = AddDownloadDialog(self._settings, self._theme, self)
        try:
            if dialog.exec() != AddDownloadDialog.DialogCode.Accepted:
                return
            values = dialog.values()
        finally:
            dialog.deleteLater()

        try:
            item = self._manager.add_download(**values)
        except ValueError as exc:
            QMessageBox.warning(self, "Could not add download", str(exc))
            return
        except Exception as exc:  # defensive: never lose the message
            logger.exception("Unexpected error adding download")
            QMessageBox.warning(
                self, "Could not add download", f"Unexpected error: {exc}"
            )
            return

        if values["start_immediately"]:
            self._status_bar.show_message(
                f"Added “{_shorten(item.filename, 48)}” to the queue."
            )
        else:
            self._status_bar.show_message(
                f"Added “{_shorten(item.filename, 48)}” as paused."
            )
        self._select_item(item.id)

    def _resume_selected(self) -> None:
        items = self._selected_items()
        count = self._manager.resume([item.id for item in items])
        if count:
            self._status_bar.show_message(
                f"Resumed {count} download{'s' if count != 1 else ''}."
            )
        self._update_actions()

    def _resume_all(self) -> None:
        count = self._manager.resume_all()
        if count:
            self._status_bar.show_message(
                f"Resumed {count} download{'s' if count != 1 else ''}."
            )
        else:
            self._status_bar.show_message("There are no paused downloads to resume.")
        self._update_actions()

    def _pause_selected(self) -> None:
        items = self._selected_items()
        count = self._manager.pause([item.id for item in items])
        if count:
            self._status_bar.show_message(
                f"Paused {count} download{'s' if count != 1 else ''}."
            )
        self._update_actions()

    def _pause_all(self) -> None:
        count = self._manager.pause_all()
        if count:
            self._status_bar.show_message(
                f"Paused {count} download{'s' if count != 1 else ''}."
            )
        else:
            self._status_bar.show_message("There are no active downloads to pause.")
        self._update_actions()

    def _stop_selected(self) -> None:
        items = self._selected_items()
        count = self._manager.stop([item.id for item in items])
        if count:
            self._status_bar.show_message(
                f"Stopped {count} download{'s' if count != 1 else ''}."
            )
        self._update_actions()

    def _delete_selected(self) -> None:
        items = self._selected_items()
        if not items:
            return

        completed = [item for item in items if item.status == DownloadStatus.COMPLETED]
        active = [item for item in items if item.is_active]
        delete_files = False

        if self._settings.confirm_delete:
            message = QMessageBox(self)
            message.setWindowTitle("Remove downloads")
            message.setIcon(QMessageBox.Icon.Warning)
            message.setText(
                f"Remove {len(items)} download{'s' if len(items) != 1 else ''}?"
            )
            details = "Temporary partial files will be deleted."
            if active:
                details += " Active downloads will be stopped."
            if completed:
                details += (
                    " Completed files are kept unless you choose to delete them."
                )
            message.setInformativeText(details)

            checkbox: QCheckBox | None = None
            if completed:
                checkbox = QCheckBox("Also delete completed files from disk")
                message.setCheckBox(checkbox)

            message.setStandardButtons(
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok
            )
            message.button(QMessageBox.StandardButton.Ok).setText("Remove")
            remove_button = message.button(QMessageBox.StandardButton.Ok)
            remove_button.setObjectName("DangerButton")
            remove_button.style().unpolish(remove_button)
            remove_button.style().polish(remove_button)
            message.setDefaultButton(QMessageBox.StandardButton.Cancel)

            if message.exec() != QMessageBox.StandardButton.Ok:
                return
            delete_files = bool(checkbox and checkbox.isChecked())

        removed = self._manager.remove(
            [item.id for item in items], delete_files=delete_files
        )
        if removed:
            self._status_bar.show_message(
                f"Removed {removed} download{'s' if removed != 1 else ''}."
            )
        self._update_actions()

    def _delete_completed(self) -> None:
        count = self._manager.delete_completed()
        if count:
            self._status_bar.show_message(
                f"Cleared {count} completed download{'s' if count != 1 else ''}. "
                "Files were kept."
            )
        else:
            self._status_bar.show_message(
                "There are no completed downloads to clear."
            )

    def _open_options(self, initial_tab: int = 0) -> None:
        dialog = OptionsDialog(
            self._settings, self._theme, self, initial_tab=initial_tab
        )
        try:
            if dialog.exec() != OptionsDialog.DialogCode.Accepted:
                return
            values = dialog.values()
        finally:
            dialog.deleteLater()

        self._settings.update(values)
        self._settings.save()
        self._manager.apply_settings()
        self._theme.set_mode(self._settings.theme)
        self._apply_view_settings()
        self._status_bar.show_message("Options saved.")

    def _open_browser_settings(self) -> None:
        self._raise_for_browser()
        self._open_options(initial_tab=2)

    # ------------------------------------------------------------------ browser integration
    def _raise_for_browser(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def _prompt_browser_folder(
        self, filename: str, default_folder: str, browser: str
    ) -> str | None:
        self._raise_for_browser()
        start = default_folder if Path(default_folder).is_dir() else str(Path.home())
        title = f"Save “{_shorten(filename, 60)}” — download from {browser}"
        chosen = QFileDialog.getExistingDirectory(
            self, title, start, QFileDialog.Option.ShowDirsOnly
        )
        return chosen or None

    def _confirm_create_folder(self, folder: str) -> bool:
        self._raise_for_browser()
        answer = QMessageBox.question(
            self,
            "Create download folder",
            f"The folder does not exist:\n\n{folder}\n\nCreate it now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _set_theme(self, mode: str) -> None:
        if mode not in THEME_ORDER:
            return
        self._theme.set_mode(mode)
        self._settings.theme = mode
        self._settings.save()
        self._status_bar.show_message(f"{THEME_LABELS[mode]} theme enabled.")

    def _cycle_theme(self) -> None:
        mode = self._theme.cycle()
        self._settings.theme = mode
        self._settings.save()
        self._status_bar.show_message(f"{THEME_LABELS[mode]} theme enabled.")

    def _set_view_flag(self, key: str, visible: bool) -> None:
        setattr(self._settings, key, bool(visible))
        self._settings.save()
        self._apply_view_settings()

    def _apply_view_settings(self) -> None:
        self._toolbar.setVisible(self._settings.show_toolbar)
        self._sidebar.setVisible(self._settings.show_sidebar)
        self._status_bar.setVisible(self._settings.show_status_bar)
        self._download_view.setVisible(self._settings.show_download_list)
        for key in (
            "show_toolbar",
            "show_sidebar",
            "show_download_list",
            "show_status_bar",
        ):
            action = self._actions.get(f"view_{key}")
            if action is not None:
                action.setChecked(bool(getattr(self._settings, key)))

    def _open_scheduler(self) -> None:
        dialog = SchedulerDialog(self._scheduler, self._theme, self)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def _open_queue(self) -> None:
        dialog = QueueDialog(self._manager, self._theme, self)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def _show_progress(self, item: DownloadItem) -> None:
        existing = self._progress_dialogs.get(item.id)
        if existing is not None:
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return
        dialog = DownloadProgressDialog(
            self._manager, item.id, self._theme, self
        )
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.closed.connect(
            lambda download_id: self._progress_dialogs.pop(download_id, None)
        )
        self._progress_dialogs[item.id] = dialog
        dialog.show()
        dialog.raise_()

    def _show_about(self, check: bool = False) -> None:
        dialog = AboutDialog(
            self._theme,
            self,
            settings=self._settings,
            on_install=self._prepare_update_install,
        )
        if check:
            QTimer.singleShot(0, dialog.check_now)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def _prepare_update_install(self, request: InstallRequest) -> str | None:
        """Persist state, launch the separate updater and quit IDM."""
        if not getattr(sys, "frozen", False):
            return (
                "Automatic installation is only available in the installed "
                "IDM build. Run build_windows.ps1 to produce IDM.exe and "
                "IDM_Updater.exe, or install IDM with IDM_Setup.exe."
            )
        updater = updater_executable()
        if updater is None:
            return (
                "The IDM Updater component (IDM_Updater.exe) is missing from "
                "this installation. Reinstall IDM to repair the update system."
            )

        try:
            self._save_geometry()
            self._settings.save()
        except Exception:
            logger.exception("Could not save settings before the update")
            return "IDM could not save its settings. The update was not started."

        try:
            backup = self._backup_database()
            if backup is not None:
                logger.info("Pre-update database backup written to %s", backup)
        except Exception as exc:
            logger.exception("Could not back up the database before the update")
            return (
                "IDM could not back up its database, so the update was not "
                f"started.\n\n{exc}"
            )

        try:
            handoff = stage_and_launch(
                request,
                updater=updater,
                app_exe=Path(sys.executable),
                log_file=updater_log_file(),
            )
        except UpdaterError as exc:
            logger.error("Could not launch the updater: %s", exc)
            return str(exc)
        except Exception:
            logger.exception("Could not prepare the updater")
            return "IDM could not start the updater. See the log for details."

        logger.info(
            "Update handoff prepared for %s (restart=%s, dir=%s)",
            handoff.target_version,
            handoff.restart,
            handoff.update_dir,
        )

        try:
            self._shutdown()
            self._settings.save()
        except Exception:
            logger.exception("Could not save state while closing for the update")

        app = QApplication.instance()
        if app is not None:
            QTimer.singleShot(250, app.quit)
        return None

    def _backup_database(self) -> Path | None:
        backup_dir = database_backup_dir()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        destination = (
            backup_dir / f"idm-{APP_VERSION}-pre-update-{stamp}.sqlite3"
        )
        self._settings.database.backup(destination)
        backups = sorted(
            backup_dir.glob("idm-*-pre-update-*.sqlite3"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for old in backups[5:]:
            try:
                old.unlink()
            except OSError:
                logger.debug("Could not remove old database backup %s", old)
        return destination

    def _show_documentation(self) -> None:
        readme = Path(__file__).resolve().parents[2] / "README.md"
        if readme.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(readme)))
            return
        QMessageBox.information(
            self,
            "IDM documentation",
            "Quick reference\n\n"
            "Ctrl+N  Add a download\n"
            "Ctrl+R  Resume selected downloads\n"
            "Ctrl+P  Pause selected downloads\n"
            "Ctrl+Shift+R  Resume all\n"
            "Ctrl+Shift+P  Pause all\n"
            "Ctrl+F  Search the download list\n"
            "Ctrl+,  Open Options\n\n"
            "See the project README for setup and architecture notes.",
        )

    # ------------------------------------------------------------------ import / export
    def _export_downloads(self) -> None:
        items = self._manager.items()
        if not items:
            self._status_bar.show_message("There are no downloads to export.")
            return
        default = Path.home() / "idm-downloads.json"
        path_text, _ = QFileDialog.getSaveFileName(
            self,
            "Export downloads",
            str(default),
            "JSON files (*.json);;All files (*)",
        )
        if not path_text:
            return
        payload = {
            "application": APP_NAME,
            "format": 1,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "downloads": [
                {
                    "url": item.url,
                    "filename": item.filename,
                    "folder": item.folder,
                    "category": item.category,
                    "priority": int(item.priority),
                    "status": item.status.value,
                }
                for item in items
            ],
        }
        try:
            Path(path_text).write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            QMessageBox.warning(
                self, "Could not export downloads", f"Could not write the file: {exc}"
            )
            return
        self._status_bar.show_message(
            f"Exported {len(items)} download{'s' if len(items) != 1 else ''}."
        )

    def _import_downloads(self) -> None:
        path_text, _ = QFileDialog.getOpenFileName(
            self,
            "Import downloads",
            str(Path.home()),
            "Download lists (*.json *.txt);;JSON files (*.json);;Text files (*.txt);;All files (*)",
        )
        if not path_text:
            return
        try:
            text = Path(path_text).read_text(encoding="utf-8-sig")
        except OSError as exc:
            QMessageBox.warning(
                self, "Could not import downloads", f"Could not read the file: {exc}"
            )
            return
        try:
            entries = _parse_download_list(text)
        except ValueError as exc:
            QMessageBox.warning(self, "Could not import downloads", str(exc))
            return
        if not entries:
            self._status_bar.show_message("The selected file contains no links.")
            return

        existing = {
            (item.url, item.folder.casefold(), item.filename.casefold())
            for item in self._manager.items()
        }
        imported = 0
        skipped = 0
        errors: list[str] = []
        for entry in entries:
            url = str(entry.get("url") or "").strip()
            if not url:
                skipped += 1
                continue
            filename = str(entry.get("filename") or "").strip() or guess_filename(url)
            folder = str(entry.get("folder") or "").strip() or self._settings.download_dir
            key = (url, folder.casefold(), filename.casefold())
            if key in existing:
                skipped += 1
                continue
            try:
                self._manager.add_download(
                    url=url,
                    filename=filename,
                    folder=folder,
                    category=str(
                        entry.get("category") or category_for_filename(filename)
                    ),
                    priority=int(entry.get("priority", PRIORITY_NORMAL)),
                    start_immediately=False,
                )
            except (ValueError, OSError) as exc:
                if len(errors) < 3:
                    errors.append(f"{url}: {exc}")
                skipped += 1
                continue
            existing.add(key)
            imported += 1

        if errors:
            QMessageBox.warning(
                self,
                "Some links were skipped",
                "\n".join(errors)
                + "\n\nImported downloads are added in the paused state.",
            )
        if imported:
            self._status_bar.show_message(
                f"Imported {imported} download{'s' if imported != 1 else ''} as paused."
                + (f" Skipped {skipped}." if skipped else "")
            )
        elif skipped:
            self._status_bar.show_message(
                f"No new downloads were imported ({skipped} skipped)."
            )

    def _focus_search(self) -> None:
        self._search.setFocus()
        self._search.selectAll()

    def _clear_search(self) -> None:
        if self._search.text():
            self._search.clear()
        else:
            self._download_view.table.setFocus()

    # ------------------------------------------------------------------ filtering
    def _on_filter_changed(self, key: str) -> None:
        self._proxy.set_filter_key(key)
        self._refresh_page_state()

    def _on_search_changed(self, text: str) -> None:
        self._proxy.set_search(text)
        self._refresh_page_state()

    def _refresh_page_state(self, *_args) -> None:
        key = self._sidebar.current_key
        self._page_title.setText(_FILTER_TITLES.get(key, "All Downloads"))
        visible = self._proxy.rowCount()
        items = self._manager.items()
        total = len(items)
        search = self._search.text().strip()
        active = self._manager.active_count
        queued = sum(
            1 for item in items if item.status == DownloadStatus.QUEUED
        )

        if search:
            subtitle = (
                f"{visible} result{'s' if visible != 1 else ''} "
                f"for “{_shorten(search, 36)}”"
            )
        elif key == "all":
            if total == 0:
                subtitle = "Your downloads will appear here."
            else:
                parts = [f"{total} download{'s' if total != 1 else ''}"]
                if active:
                    parts.append(f"{active} active")
                elif queued:
                    parts.append(f"{queued} queued")
                subtitle = "   ·   ".join(parts)
        elif key == "downloading":
            subtitle = f"{visible} in progress"
        elif key == "completed":
            subtitle = f"{visible} completed"
        else:
            category = CATEGORY_FILTER_KEYS.get(key, "")
            subtitle = f"{visible} file{'s' if visible != 1 else ''} in {category}"
        self._page_subtitle.setText(subtitle)

        if total == 0:
            self._download_view.empty_state.set_message(
                "No downloads yet",
                "Paste a direct link or click Add URL to start your first download.",
            )
            self._download_view.show_empty(True)
        elif visible == 0:
            if search:
                self._download_view.empty_state.set_message(
                    "No matches",
                    f"No downloads match “{_shorten(search, 48)}”. "
                    "Try a different search.",
                )
            else:
                self._download_view.empty_state.set_message(
                    "Nothing here yet",
                    "Downloads in this view will appear here.",
                )
            self._download_view.show_empty(True)
        else:
            self._download_view.show_empty(False)

        self._sidebar.set_counts(_sidebar_counts(items))
        self._update_actions()

    # ------------------------------------------------------------------ manager events
    def _on_manager_changed(self, *_args) -> None:
        self._refresh_page_state()

    def _on_stats_changed(self, active: int, speed: float, queued: int) -> None:
        self._status_bar.set_stats(active, speed, queued)
        self._refresh_page_state()

    def _on_download_completed(self, item: DownloadItem) -> None:
        self._status_bar.show_message(
            f"Download complete — {_shorten(item.filename, 56)}"
        )

    def _on_download_failed(self, item: DownloadItem) -> None:
        self._status_bar.show_message(
            f"Download failed — {_shorten(item.filename, 40)}. "
            "Double-click for details."
        )

    # ------------------------------------------------------------------ theme
    def _on_theme_changed(self) -> None:
        p = self._theme.palette
        self._search_action.setIcon(icons.icon("search", p.text_faint, 16))
        for key, icon_name in self._action_icons.items():
            action = self._actions.get(key)
            if action is not None:
                action.setIcon(icons.icon(icon_name, p.text_muted, 16))
        for mode, action in self._theme_actions.items():
            action.setChecked(mode == self._theme.mode)
        self._download_view.table.viewport().update()
        self._download_view.table.update()
        self._theme.apply_window_chrome(self)

    # ------------------------------------------------------------------ context menu
    def _show_context_menu(self, position: QPoint) -> None:
        table = self._download_view.table
        index = table.indexAt(position)
        if not index.isValid():
            return
        if not table.selectionModel().isSelected(index):
            table.selectRow(index.row())

        items = self._selected_items()
        if not items:
            return
        item = self._item_from_index(index) or items[0]
        p = self._theme.palette

        menu = QMenu(self)
        progress_action = menu.addAction(
            icons.icon("download", p.text_muted, 16), "Download Progress"
        )
        progress_action.setEnabled(len(items) == 1)
        progress_action.triggered.connect(lambda: self._show_progress(item))

        resume_action = menu.addAction(
            icons.icon("resume", p.text_muted, 16), "Resume"
        )
        resume_action.setEnabled(any(entry.can_resume for entry in items))
        resume_action.triggered.connect(self._resume_selected)

        pause_action = menu.addAction(
            icons.icon("pause", p.text_muted, 16), "Pause"
        )
        pause_action.setEnabled(any(entry.can_pause for entry in items))
        pause_action.triggered.connect(self._pause_selected)

        stop_action = menu.addAction(
            icons.icon("stop", p.text_muted, 16), "Stop"
        )
        stop_action.setEnabled(any(entry.can_stop for entry in items))
        stop_action.triggered.connect(self._stop_selected)

        menu.addSeparator()
        if len(items) == 1:
            folder_action = menu.addAction(
                icons.icon("folder_open", p.text_muted, 16),
                "Open containing folder",
            )
            folder_action.triggered.connect(
                lambda: self._open_containing_folder(item)
            )

            copy_action = menu.addAction(
                icons.icon("copy", p.text_muted, 16), "Copy download link"
            )
            copy_action.triggered.connect(lambda: self._copy_link(item))

            if item.status == DownloadStatus.FAILED:
                error_action = menu.addAction("Show error details")
                error_action.triggered.connect(lambda: self._show_error(item))
            menu.addSeparator()

        remove_action = menu.addAction(
            icons.icon("delete", p.danger, 16), "Remove from list"
        )
        remove_action.triggered.connect(self._delete_selected)

        menu.exec(table.viewport().mapToGlobal(position))

    def _open_containing_folder(self, item: DownloadItem) -> None:
        folder = Path(item.folder)
        if not folder.exists():
            self._status_bar.show_message("The download folder no longer exists.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _copy_link(self, item: DownloadItem) -> None:
        QGuiApplication.clipboard().setText(item.url)
        self._status_bar.show_message("Download link copied to the clipboard.")

    def _show_error(self, item: DownloadItem) -> None:
        QMessageBox.warning(
            self,
            "Download error",
            item.error or "No further details are available for this download.",
        )

    def _on_double_click(self, index: QModelIndex) -> None:
        item = self._item_from_index(index)
        if item is None:
            return
        if item.status == DownloadStatus.COMPLETED:
            self._open_containing_folder(item)
        else:
            self._show_progress(item)

    # ------------------------------------------------------------------ lifecycle
    def _save_geometry(self) -> None:
        try:
            self._settings.save_bytes(
                "window/geometry", bytes(self.saveGeometry().data())
            )
            self._settings.save()
        except Exception:
            logger.debug("Could not save window geometry", exc_info=True)

    def closeEvent(self, event) -> None:
        active = self._manager.active_count
        if active:
            message = QMessageBox(self)
            message.setWindowTitle("Downloads are running")
            message.setIcon(QMessageBox.Icon.Question)
            message.setText(
                f"{active} download{'s are' if active != 1 else ' is'} still running."
            )
            message.setInformativeText(
                "Stop them and exit? Partial .idm.part files are kept on disk."
            )
            message.setStandardButtons(
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok
            )
            message.button(QMessageBox.StandardButton.Ok).setText("Stop and exit")
            message.setDefaultButton(QMessageBox.StandardButton.Cancel)
            if message.exec() != QMessageBox.StandardButton.Ok:
                event.ignore()
                return

        self._save_geometry()
        self._shutdown()
        event.accept()

    def _shutdown(self) -> None:
        if self._shutdown_done:
            return
        self._shutdown_done = True
        for dialog in list(self._progress_dialogs.values()):
            try:
                dialog.close()
            except RuntimeError:
                pass
        self._progress_dialogs.clear()
        try:
            self._browser.stop()
        except Exception:
            logger.debug("Could not stop the browser bridge", exc_info=True)
        self._scheduler.shutdown()
        self._manager.shutdown()


def _sidebar_counts(items: list[DownloadItem]) -> dict[str, int]:
    counts = {
        "all": len(items),
        "downloading": 0,
        "completed": 0,
        "documents": 0,
        "music": 0,
        "videos": 0,
        "programs": 0,
        "compressed": 0,
        "other": 0,
    }
    for item in items:
        if item.is_in_progress:
            counts["downloading"] += 1
        if item.status == DownloadStatus.COMPLETED:
            counts["completed"] += 1
        for key, category in CATEGORY_FILTER_KEYS.items():
            if item.category == category:
                counts[key] += 1
                break
    return counts


def _parse_download_list(text: str) -> list[dict]:
    stripped = text.strip()
    if not stripped:
        return []
    if stripped[0] in "[{":
        try:
            data = json.loads(stripped)
        except ValueError as exc:
            raise ValueError(f"The JSON file could not be read: {exc}") from exc
        entries = data.get("downloads") if isinstance(data, dict) else data
        if not isinstance(entries, list):
            raise ValueError("The JSON file does not contain a download list.")
        return [entry for entry in entries if isinstance(entry, dict)]
    return [
        {"url": line.strip()}
        for line in stripped.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"
