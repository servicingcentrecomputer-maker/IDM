"""Filesystem locations for the browser integration.

The desktop application, the native messaging host and the registration
scripts all need to agree on where the ephemeral bridge descriptor, logs and
generated native messaging manifests live.  This module is deliberately
Qt-free and performs no imports from :mod:`idm` apart from the data-directory
name constant.
"""

from __future__ import annotations

import os
from pathlib import Path

from idm.constants import APP_DATA_DIR_NAME

RUNTIME_DIR_NAME = "runtime"
BRIDGE_FILE_NAME = "browser_bridge.json"
NATIVE_LOG_NAME = "native_host.log"
NATIVE_MANIFEST_DIR_NAME = "native_messaging"


def app_data_dir() -> Path:
    roaming = os.environ.get("APPDATA")
    if roaming:
        return Path(roaming) / APP_DATA_DIR_NAME
    return Path.home() / f".{APP_DATA_DIR_NAME.lower().replace(' ', '-')}"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def runtime_dir() -> Path:
    return ensure_dir(app_data_dir() / RUNTIME_DIR_NAME)


def bridge_file() -> Path:
    return runtime_dir() / BRIDGE_FILE_NAME


def logs_dir() -> Path:
    return ensure_dir(app_data_dir() / "logs")


def native_log_file() -> Path:
    return logs_dir() / NATIVE_LOG_NAME


def native_manifest_dir() -> Path:
    return ensure_dir(app_data_dir() / NATIVE_MANIFEST_DIR_NAME)


def manifest_file(browser: str) -> Path:
    return native_manifest_dir() / f"com.idm.native.{browser}.json"


__all__ = [
    "BRIDGE_FILE_NAME",
    "NATIVE_MANIFEST_DIR_NAME",
    "app_data_dir",
    "bridge_file",
    "ensure_dir",
    "logs_dir",
    "manifest_file",
    "native_log_file",
    "native_manifest_dir",
    "runtime_dir",
]
