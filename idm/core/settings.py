"""Persistent application settings backed by SQLite.

Older builds stored settings in ``settings.ini``.  On first launch the values
are imported into the SQLite database so existing users keep their theme,
download folder, window geometry and engine preferences.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from PySide6.QtCore import QSettings

import config as app_config

from downloads.location_manager import (
    MODE_DEFAULT,
    DownloadLocationConfig,
)

from ..constants import MAX_SPEED_LIMIT_KBPS
from .database import Database
from .paths import default_download_dir, settings_file

logger = logging.getLogger(__name__)

_UPDATE_CHANNELS = {"stable", "beta"}

_DEFAULTS: dict[str, Any] = {
    "theme": "classic",
    "download_dir": default_download_dir(),
    "max_concurrent": 3,
    "connections_per_download": 12,
    "auto_retry": True,
    "max_retries": 3,
    "auto_resume_on_network": True,
    "speed_limit_kbps": 0,
    "confirm_delete": True,
    "start_immediately": True,
    "restore_session": True,
    "show_toolbar": True,
    "show_sidebar": True,
    "show_status_bar": True,
    "show_download_list": True,
    "update_manifest_url": "",
    "update_publisher": "",
    "update_channel": app_config.UPDATE_CHANNEL,
    "update_auto_check": True,
    "update_check_interval_hours": 24,
    "update_auto_download": False,
    "update_ask_before_install": True,
    "update_notify": True,
    "update_last_check": "",
    "update_last_success": "",
    "update_last_success_version": "",
    "update_remind_after": "",
    "update_remind_version": "",
    "download_mode": MODE_DEFAULT,
    "download_type_rules": [],
}

_THEMES = {"classic", "light", "dark"}

_LEGACY_KEYS = {
    "theme": "general/theme",
    "download_dir": "general/download_dir",
    "max_concurrent": "downloads/max_concurrent",
    "auto_retry": "downloads/auto_retry",
    "max_retries": "downloads/max_retries",
    "speed_limit_kbps": "bandwidth/speed_limit_kbps",
}


class AppSettings:
    def __init__(self) -> None:
        self._database = Database()
        self._migrate_legacy_ini()

        self.theme: str = _DEFAULTS["theme"]
        self.download_dir: str = _DEFAULTS["download_dir"]
        self.max_concurrent: int = _DEFAULTS["max_concurrent"]
        self.connections_per_download: int = _DEFAULTS["connections_per_download"]
        self.auto_retry: bool = _DEFAULTS["auto_retry"]
        self.max_retries: int = _DEFAULTS["max_retries"]
        self.auto_resume_on_network: bool = _DEFAULTS["auto_resume_on_network"]
        self.speed_limit_kbps: int = _DEFAULTS["speed_limit_kbps"]
        self.confirm_delete: bool = _DEFAULTS["confirm_delete"]
        self.start_immediately: bool = _DEFAULTS["start_immediately"]
        self.restore_session: bool = _DEFAULTS["restore_session"]
        self.show_toolbar: bool = _DEFAULTS["show_toolbar"]
        self.show_sidebar: bool = _DEFAULTS["show_sidebar"]
        self.show_status_bar: bool = _DEFAULTS["show_status_bar"]
        self.show_download_list: bool = _DEFAULTS["show_download_list"]
        self.update_manifest_url: str = _DEFAULTS["update_manifest_url"]
        self.update_publisher: str = _DEFAULTS["update_publisher"]
        self.update_channel: str = _DEFAULTS["update_channel"]
        self.update_auto_check: bool = _DEFAULTS["update_auto_check"]
        self.update_check_interval_hours: int = _DEFAULTS[
            "update_check_interval_hours"
        ]
        self.update_auto_download: bool = _DEFAULTS["update_auto_download"]
        self.update_ask_before_install: bool = _DEFAULTS[
            "update_ask_before_install"
        ]
        self.update_notify: bool = _DEFAULTS["update_notify"]
        self.update_last_check: str = _DEFAULTS["update_last_check"]
        self.update_last_success: str = _DEFAULTS["update_last_success"]
        self.update_last_success_version: str = _DEFAULTS[
            "update_last_success_version"
        ]
        self.update_remind_after: str = _DEFAULTS["update_remind_after"]
        self.update_remind_version: str = _DEFAULTS["update_remind_version"]
        self.location_config = DownloadLocationConfig()
        self.load()

    # ------------------------------------------------------------------ access
    @property
    def database(self) -> Database:
        return self._database

    # ------------------------------------------------------------------ loading
    def load(self) -> None:
        values = self._database.load_settings()

        theme = str(values.get("theme", _DEFAULTS["theme"]))
        self.theme = theme if theme in _THEMES else _DEFAULTS["theme"]

        download_dir = str(values.get("download_dir", _DEFAULTS["download_dir"]))
        self.download_dir = download_dir.strip() or _DEFAULTS["download_dir"]

        self.max_concurrent = _coerce_int(
            values.get("max_concurrent", _DEFAULTS["max_concurrent"]),
            _DEFAULTS["max_concurrent"],
            1,
            10,
        )
        self.connections_per_download = _coerce_int(
            values.get(
                "connections_per_download", _DEFAULTS["connections_per_download"]
            ),
            _DEFAULTS["connections_per_download"],
            1,
            16,
        )
        self.auto_retry = _coerce_bool(
            values.get("auto_retry", _DEFAULTS["auto_retry"]),
            _DEFAULTS["auto_retry"],
        )
        self.max_retries = _coerce_int(
            values.get("max_retries", _DEFAULTS["max_retries"]),
            _DEFAULTS["max_retries"],
            0,
            10,
        )
        self.auto_resume_on_network = _coerce_bool(
            values.get(
                "auto_resume_on_network", _DEFAULTS["auto_resume_on_network"]
            ),
            _DEFAULTS["auto_resume_on_network"],
        )
        self.speed_limit_kbps = _coerce_int(
            values.get("speed_limit_kbps", _DEFAULTS["speed_limit_kbps"]),
            _DEFAULTS["speed_limit_kbps"],
            0,
            MAX_SPEED_LIMIT_KBPS,
        )
        self.confirm_delete = _coerce_bool(
            values.get("confirm_delete", _DEFAULTS["confirm_delete"]),
            _DEFAULTS["confirm_delete"],
        )
        self.start_immediately = _coerce_bool(
            values.get("start_immediately", _DEFAULTS["start_immediately"]),
            _DEFAULTS["start_immediately"],
        )
        self.restore_session = _coerce_bool(
            values.get("restore_session", _DEFAULTS["restore_session"]),
            _DEFAULTS["restore_session"],
        )
        self.show_toolbar = _coerce_bool(
            values.get("show_toolbar", _DEFAULTS["show_toolbar"]),
            _DEFAULTS["show_toolbar"],
        )
        self.show_sidebar = _coerce_bool(
            values.get("show_sidebar", _DEFAULTS["show_sidebar"]),
            _DEFAULTS["show_sidebar"],
        )
        self.show_status_bar = _coerce_bool(
            values.get("show_status_bar", _DEFAULTS["show_status_bar"]),
            _DEFAULTS["show_status_bar"],
        )
        self.show_download_list = _coerce_bool(
            values.get("show_download_list", _DEFAULTS["show_download_list"]),
            _DEFAULTS["show_download_list"],
        )
        self.update_manifest_url = str(
            values.get("update_manifest_url", _DEFAULTS["update_manifest_url"])
        ).strip()
        self.update_publisher = str(
            values.get("update_publisher", _DEFAULTS["update_publisher"])
        ).strip()
        channel = str(
            values.get("update_channel", _DEFAULTS["update_channel"])
        ).strip().lower()
        self.update_channel = (
            channel if channel in _UPDATE_CHANNELS else _DEFAULTS["update_channel"]
        )
        self.update_auto_check = _coerce_bool(
            values.get("update_auto_check", _DEFAULTS["update_auto_check"]),
            _DEFAULTS["update_auto_check"],
        )
        self.update_check_interval_hours = _coerce_int(
            values.get(
                "update_check_interval_hours",
                _DEFAULTS["update_check_interval_hours"],
            ),
            _DEFAULTS["update_check_interval_hours"],
            1,
            168,
        )
        self.update_auto_download = _coerce_bool(
            values.get("update_auto_download", _DEFAULTS["update_auto_download"]),
            _DEFAULTS["update_auto_download"],
        )
        self.update_ask_before_install = _coerce_bool(
            values.get(
                "update_ask_before_install",
                _DEFAULTS["update_ask_before_install"],
            ),
            _DEFAULTS["update_ask_before_install"],
        )
        self.update_notify = _coerce_bool(
            values.get("update_notify", _DEFAULTS["update_notify"]),
            _DEFAULTS["update_notify"],
        )
        self.update_last_check = _coerce_text(
            values.get("update_last_check", _DEFAULTS["update_last_check"])
        )
        self.update_last_success = _coerce_text(
            values.get("update_last_success", _DEFAULTS["update_last_success"])
        )
        self.update_last_success_version = _coerce_text(
            values.get(
                "update_last_success_version",
                _DEFAULTS["update_last_success_version"],
            )
        )
        self.update_remind_after = _coerce_text(
            values.get("update_remind_after", _DEFAULTS["update_remind_after"])
        )
        self.update_remind_version = _coerce_text(
            values.get("update_remind_version", _DEFAULTS["update_remind_version"])
        )
        self.location_config = DownloadLocationConfig.from_settings(values)

    # ------------------------------------------------------------------ saving
    def save(self) -> None:
        try:
            self._database.save_settings(self._as_dict())
        except Exception:
            logger.exception("Could not save application settings")

    def update(self, values: dict[str, Any]) -> None:
        if "theme" in values and values["theme"] in _THEMES:
            self.theme = values["theme"]
        if "download_dir" in values:
            directory = str(values["download_dir"]).strip()
            if directory:
                self.download_dir = directory
        if "max_concurrent" in values:
            self.max_concurrent = _coerce_int(
                values["max_concurrent"], self.max_concurrent, 1, 10
            )
        if "connections_per_download" in values:
            self.connections_per_download = _coerce_int(
                values["connections_per_download"],
                self.connections_per_download,
                1,
                16,
            )
        if "auto_retry" in values:
            self.auto_retry = bool(values["auto_retry"])
        if "max_retries" in values:
            self.max_retries = _coerce_int(
                values["max_retries"], self.max_retries, 0, 10
            )
        if "auto_resume_on_network" in values:
            self.auto_resume_on_network = bool(values["auto_resume_on_network"])
        if "speed_limit_kbps" in values:
            self.speed_limit_kbps = _coerce_int(
                values["speed_limit_kbps"],
                self.speed_limit_kbps,
                0,
                MAX_SPEED_LIMIT_KBPS,
            )
        for key in (
            "confirm_delete",
            "start_immediately",
            "restore_session",
            "show_toolbar",
            "show_sidebar",
            "show_status_bar",
            "show_download_list",
        ):
            if key in values:
                setattr(self, key, bool(values[key]))
        if "update_manifest_url" in values:
            self.update_manifest_url = str(values["update_manifest_url"]).strip()
        if "update_publisher" in values:
            self.update_publisher = str(values["update_publisher"]).strip()
        if "update_channel" in values:
            channel = str(values["update_channel"]).strip().lower()
            if channel in _UPDATE_CHANNELS:
                self.update_channel = channel
        for key in (
            "update_auto_check",
            "update_auto_download",
            "update_ask_before_install",
            "update_notify",
        ):
            if key in values:
                setattr(self, key, bool(values[key]))
        if "update_check_interval_hours" in values:
            self.update_check_interval_hours = _coerce_int(
                values["update_check_interval_hours"],
                self.update_check_interval_hours,
                1,
                168,
            )
        for key in (
            "update_last_check",
            "update_last_success",
            "update_last_success_version",
            "update_remind_after",
            "update_remind_version",
        ):
            if key in values:
                setattr(self, key, str(values[key]).strip())
        if isinstance(values.get("location_config"), DownloadLocationConfig):
            self.location_config = values["location_config"].normalized()
        elif "download_mode" in values or "download_type_rules" in values:
            current = self.location_config.to_settings()
            self.location_config = DownloadLocationConfig.from_settings(
                {
                    "download_mode": values.get(
                        "download_mode", current["download_mode"]
                    ),
                    "download_type_rules": values.get(
                        "download_type_rules", current["download_type_rules"]
                    ),
                }
            )

    def _as_dict(self) -> dict[str, Any]:
        return {
            "theme": self.theme,
            "download_dir": self.download_dir,
            "max_concurrent": self.max_concurrent,
            "connections_per_download": self.connections_per_download,
            "auto_retry": self.auto_retry,
            "max_retries": self.max_retries,
            "auto_resume_on_network": self.auto_resume_on_network,
            "speed_limit_kbps": self.speed_limit_kbps,
            "confirm_delete": self.confirm_delete,
            "start_immediately": self.start_immediately,
            "restore_session": self.restore_session,
            "show_toolbar": self.show_toolbar,
            "show_sidebar": self.show_sidebar,
            "show_status_bar": self.show_status_bar,
            "show_download_list": self.show_download_list,
            "update_manifest_url": self.update_manifest_url,
            "update_publisher": self.update_publisher,
            "update_channel": self.update_channel,
            "update_auto_check": self.update_auto_check,
            "update_check_interval_hours": self.update_check_interval_hours,
            "update_auto_download": self.update_auto_download,
            "update_ask_before_install": self.update_ask_before_install,
            "update_notify": self.update_notify,
            "update_last_check": self.update_last_check,
            "update_last_success": self.update_last_success,
            "update_last_success_version": self.update_last_success_version,
            "update_remind_after": self.update_remind_after,
            "update_remind_version": self.update_remind_version,
            **self.location_config.to_settings(),
        }

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-safe copy of every persisted setting."""
        return dict(self._as_dict())

    # ------------------------------------------------------------------ updates
    def note_update_check(self) -> None:
        self.update_last_check = _utc_now()
        self.save()

    def note_update_success(self, version: str) -> None:
        self.update_last_success = _utc_now()
        self.update_last_success_version = str(version).strip()
        self.clear_update_reminder(save=False)
        self.save()

    def remind_later(self, version: str, hours: int = 24) -> None:
        moment = datetime.now(timezone.utc) + timedelta(hours=max(1, int(hours)))
        self.update_remind_after = moment.isoformat(timespec="seconds")
        self.update_remind_version = str(version).strip()
        self.save()

    def clear_update_reminder(self, save: bool = True) -> None:
        self.update_remind_after = ""
        self.update_remind_version = ""
        if save:
            self.save()

    # ------------------------------------------------------------------ blobs
    def load_bytes(self, key: str) -> bytes | None:
        try:
            value = self._database.load_settings().get(key)
        except Exception:
            logger.debug("Could not read setting %s", key, exc_info=True)
            return None
        if isinstance(value, (bytes, bytearray)):
            return bytes(value)
        return None

    def save_bytes(self, key: str, value: bytes) -> None:
        try:
            self._database.save_settings({key: bytes(value)})
        except Exception:
            logger.debug("Could not save binary setting %s", key, exc_info=True)

    # ------------------------------------------------------------------ legacy
    def _migrate_legacy_ini(self) -> None:
        try:
            if self._database.setting_count() > 0:
                return
        except Exception:
            logger.debug("Could not inspect the settings database", exc_info=True)
            return

        legacy_path = settings_file()
        if not legacy_path.exists():
            return

        legacy = QSettings(str(legacy_path), QSettings.Format.IniFormat)
        migrated: dict[str, Any] = {}
        for key, legacy_key in _LEGACY_KEYS.items():
            if legacy.contains(legacy_key):
                migrated[key] = legacy.value(legacy_key)

        geometry = legacy.value("window/geometry")
        if isinstance(geometry, bytes):
            migrated["window/geometry"] = geometry
        elif hasattr(geometry, "data"):
            migrated["window/geometry"] = bytes(geometry.data())

        if migrated:
            try:
                self._database.save_settings(migrated)
                logger.info("Imported %d settings from settings.ini", len(migrated))
            except Exception:
                logger.exception("Could not import legacy settings")

    # ------------------------------------------------------------------ lifecycle
    def close(self) -> None:
        self._database.close()


def _coerce_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    if isinstance(value, int):
        return bool(value)
    return default
