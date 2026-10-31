"""IDM desktop application entry point."""

from __future__ import annotations

import logging
import sys

from pathlib import Path

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from idm.constants import APP_NAME, APP_VERSION
from idm.core.logging_setup import setup_logging
from idm.core.paths import app_data_dir, database_file
from idm.core.settings import AppSettings
from idm.ui import icons
from idm.ui.main_window import MainWindow
from idm.ui.theme import ThemeManager
from idm.updater.backup import restore_database
from idm.updater.launcher import cleanup_stale_update_directories
from idm.updater.recovery import read_pending_safely

logger = logging.getLogger(__name__)


def _set_windows_app_id() -> None:
    """Give the process its own taskbar group and notification identity."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "IDM.DownloadManager.1"
        )
    except Exception:
        logger.debug("Could not set the Windows application ID", exc_info=True)


def _load_settings() -> tuple[AppSettings, bool]:
    """Open settings, restoring a verified database backup after a failed update."""
    pending = read_pending_safely()
    try:
        return AppSettings(), False
    except Exception:
        if pending is None:
            raise
        logger.exception(
            "Settings could not be opened; restoring the pre-update database backup"
        )
        restore_database(Path(pending.backup_dir), database_file())
        return AppSettings(), True


def main() -> int:
    setup_logging()
    _set_windows_app_id()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_NAME)
    app.setOrganizationDomain("idm.local")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 9))
    app.setWindowIcon(icons.app_icon())

    try:
        cleanup_stale_update_directories()
    except Exception:
        logger.debug("Could not clean stale update folders", exc_info=True)

    try:
        settings, database_restored = _load_settings()
    except Exception as exc:
        logger.exception("IDM could not open its settings database")
        QMessageBox.critical(
            None,
            f"{APP_NAME} could not start",
            "IDM could not open its settings database and no verified pre-update "
            f"backup was available.\n\n{exc}\n\nData folder: {app_data_dir()}",
        )
        return 1

    theme = ThemeManager(app)
    theme.set_mode(settings.theme)

    window = MainWindow(settings, theme, database_restored=database_restored)
    window.show()

    logger.info("%s %s started (data: %s)", APP_NAME, APP_VERSION, app_data_dir())
    try:
        return app.exec()
    finally:
        settings.save()
        settings.close()


if __name__ == "__main__":
    raise SystemExit(main())
