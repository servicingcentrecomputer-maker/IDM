"""Filesystem locations used by the application.

All mutable data lives in the user's roaming AppData directory, never inside
the installation directory::

    %APPDATA%\\IDM Download Manager\\
        database\\idm.sqlite3
        logs\\idm.log
        settings\\schedules.json
        downloads\\

The folder name deliberately differs from ``%APPDATA%\\IDM`` because the
commercial Internet Download Manager uses that directory (including its own
``downloads`` folder and ``idm.log``).  Sharing it would mix two products'
data and make the uninstaller's optional data cleanup unsafe.

Read-only assets are resolved relative to the project root, or to the
PyInstaller bundle when frozen.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from ..constants import APP_DATA_DIR_NAME

_LAYOUT_DIRS = ("database", "logs", "settings", "downloads")


def _base_data_dir() -> Path:
    roaming = os.environ.get("APPDATA")
    if roaming:
        return Path(roaming) / APP_DATA_DIR_NAME
    return Path.home() / f".{APP_DATA_DIR_NAME.lower().replace(' ', '-')}"


def app_data_dir() -> Path:
    directory = _base_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def database_dir() -> Path:
    directory = app_data_dir() / "database"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def logs_dir() -> Path:
    directory = app_data_dir() / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def settings_dir() -> Path:
    directory = app_data_dir() / "settings"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def downloads_dir() -> Path:
    directory = app_data_dir() / "downloads"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def settings_file() -> Path:
    return settings_dir() / "settings.ini"


def schedules_file() -> Path:
    return settings_dir() / "schedules.json"


def log_file() -> Path:
    return logs_dir() / "idm.log"


def database_file() -> Path:
    return database_dir() / "idm.sqlite3"


def database_backup_dir() -> Path:
    directory = database_dir() / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def updater_log_file() -> Path:
    return logs_dir() / "updater.log"


def updates_dir() -> Path:
    directory = app_data_dir() / "updates"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def update_backups_dir() -> Path:
    directory = updates_dir() / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def update_rollback_dir() -> Path:
    directory = updates_dir() / "rollback"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def pending_update_file() -> Path:
    return updates_dir() / "pending-update.json"


def update_history_file() -> Path:
    return updates_dir() / "update-history.json"


def last_rollback_plan_file() -> Path:
    return update_rollback_dir() / "last-rollback.json"


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def asset_path(*parts: str) -> Path:
    return project_root().joinpath("assets", *parts)


def default_download_dir() -> str:
    # Store new downloads inside the application's own data folder so the
    # uninstaller's optional data cleanup has a clearly defined boundary.
    # Users can pick any folder from Options.
    return str(downloads_dir())


def ensure_download_dir(directory: str) -> Path:
    path = Path(directory).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_app_layout() -> Path:
    """Create the application data directory tree and return its root."""
    root = app_data_dir()
    for name in _LAYOUT_DIRS:
        (root / name).mkdir(parents=True, exist_ok=True)
    return root
