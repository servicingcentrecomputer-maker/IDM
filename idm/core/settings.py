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
from .bandwidth import MIN_SPEED_LIMIT_PERCENT, normalize_speed_limit_mode
from .categories import normalize_category_paths, normalize_custom_categories
from .database import Database
from .network import (
    MAX_CONNECT_TIMEOUT,
    MAX_READ_TIMEOUT,
    MIN_TIMEOUT,
    normalize_proxy_mode,
    normalize_site_auth,
)
from .paths import default_download_dir, settings_file

logger = logging.getLogger(__name__)

_UPDATE_CHANNELS = {"stable", "beta"}

_DEFAULTS: dict[str, Any] = {
    "theme": "light",
    "download_dir": default_download_dir(),
    "max_concurrent": 3,
    "connections_per_download": 12,
    "auto_retry": True,
    "max_retries": 3,
    "auto_resume_on_network": True,
    "speed_limit_kbps": 0,
    "speed_limit_mode": "unlimited",
    "speed_limit_percent": 50,
    "measured_capacity_kbps": 0,
    "proxy_mode": "system",
    "proxy_host": "",
    "proxy_port": 8080,
    "proxy_username": "",
    "proxy_use_auth": False,
    "proxy_bypass": "",
    "site_auth": [],
    "connect_timeout": 15,
    "read_timeout": 30,
    "confirm_delete": True,
    "show_completion_dialog": True,
    "start_immediately": True,
    "restore_session": True,
    "start_with_windows": False,
    "tray_enabled": True,
    "tray_on_close": False,
    "native_notifications": True,
    "show_toolbar": True,
    "show_sidebar": True,
    "show_status_bar": True,
    "show_download_list": True,
    "sidebar_collapsed": False,
    "ui_animations": True,
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
    "custom_categories": [],
    "category_paths": {},
}

_THEMES = {"classic", "light", "dark", "system"}

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
        self.speed_limit_mode: str = _DEFAULTS["speed_limit_mode"]
        self.speed_limit_percent: int = _DEFAULTS["speed_limit_percent"]
        self.measured_capacity_kbps: int = _DEFAULTS["measured_capacity_kbps"]
        self.proxy_mode: str = _DEFAULTS["proxy_mode"]
        self.proxy_host: str = _DEFAULTS["proxy_host"]
        self.proxy_port: int = _DEFAULTS["proxy_port"]
        self.proxy_username: str = _DEFAULTS["proxy_username"]
        self.proxy_use_auth: bool = _DEFAULTS["proxy_use_auth"]
        self.proxy_bypass: str = _DEFAULTS["proxy_bypass"]
        self.site_auth: list[dict[str, str]] = []
        self.connect_timeout: int = _DEFAULTS["connect_timeout"]
        self.read_timeout: int = _DEFAULTS["read_timeout"]
        self.confirm_delete: bool = _DEFAULTS["confirm_delete"]
        self.show_completion_dialog: bool = _DEFAULTS["show_completion_dialog"]
        self.start_immediately: bool = _DEFAULTS["start_immediately"]
        self.restore_session: bool = _DEFAULTS["restore_session"]
        self.start_with_windows: bool = _DEFAULTS["start_with_windows"]
        self.tray_enabled: bool = _DEFAULTS["tray_enabled"]
        self.tray_on_close: bool = _DEFAULTS["tray_on_close"]
        self.native_notifications: bool = _DEFAULTS["native_notifications"]
        self.show_toolbar: bool = _DEFAULTS["show_toolbar"]
        self.show_sidebar: bool = _DEFAULTS["show_sidebar"]
        self.show_status_bar: bool = _DEFAULTS["show_status_bar"]
        self.show_download_list: bool = _DEFAULTS["show_download_list"]
        self.sidebar_collapsed: bool = _DEFAULTS["sidebar_collapsed"]
        self.ui_animations: bool = _DEFAULTS["ui_animations"]
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
        self.custom_categories: list[dict[str, Any]] = []
        self.category_paths: dict[str, str] = {}
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
        # A 3.6.2 settings file only knows the fixed KB/s limit, so a non-zero
        # value there still means "limit at this rate" after the upgrade.
        self.speed_limit_mode = normalize_speed_limit_mode(
            values.get("speed_limit_mode"), self.speed_limit_kbps
        )
        self.speed_limit_percent = _coerce_int(
            values.get("speed_limit_percent", _DEFAULTS["speed_limit_percent"]),
            _DEFAULTS["speed_limit_percent"],
            MIN_SPEED_LIMIT_PERCENT,
            100,
        )
        self.measured_capacity_kbps = _coerce_int(
            values.get(
                "measured_capacity_kbps", _DEFAULTS["measured_capacity_kbps"]
            ),
            _DEFAULTS["measured_capacity_kbps"],
            0,
            MAX_SPEED_LIMIT_KBPS,
        )
        self.proxy_mode = normalize_proxy_mode(
            values.get("proxy_mode", _DEFAULTS["proxy_mode"])
        )
        self.proxy_host = str(
            values.get("proxy_host", _DEFAULTS["proxy_host"]) or ""
        ).strip()[:255]
        self.proxy_port = _coerce_int(
            values.get("proxy_port", _DEFAULTS["proxy_port"]),
            _DEFAULTS["proxy_port"],
            1,
            65535,
        )
        self.proxy_username = str(
            values.get("proxy_username", _DEFAULTS["proxy_username"]) or ""
        ).strip()[:513]
        self.proxy_use_auth = _coerce_bool(
            values.get("proxy_use_auth", _DEFAULTS["proxy_use_auth"]),
            _DEFAULTS["proxy_use_auth"],
        )
        self.proxy_bypass = str(
            values.get("proxy_bypass", _DEFAULTS["proxy_bypass"]) or ""
        ).strip()[:2000]
        self.site_auth = normalize_site_auth(
            values.get("site_auth", _DEFAULTS["site_auth"])
        )
        self.connect_timeout = _coerce_int(
            values.get("connect_timeout", _DEFAULTS["connect_timeout"]),
            _DEFAULTS["connect_timeout"],
            int(MIN_TIMEOUT),
            int(MAX_CONNECT_TIMEOUT),
        )
        self.read_timeout = _coerce_int(
            values.get("read_timeout", _DEFAULTS["read_timeout"]),
            _DEFAULTS["read_timeout"],
            int(MIN_TIMEOUT),
            int(MAX_READ_TIMEOUT),
        )
        self.confirm_delete = _coerce_bool(
            values.get("confirm_delete", _DEFAULTS["confirm_delete"]),
            _DEFAULTS["confirm_delete"],
        )
        self.show_completion_dialog = _coerce_bool(
            values.get(
                "show_completion_dialog", _DEFAULTS["show_completion_dialog"]
            ),
            _DEFAULTS["show_completion_dialog"],
        )
        self.start_immediately = _coerce_bool(
            values.get("start_immediately", _DEFAULTS["start_immediately"]),
            _DEFAULTS["start_immediately"],
        )
        self.restore_session = _coerce_bool(
            values.get("restore_session", _DEFAULTS["restore_session"]),
            _DEFAULTS["restore_session"],
        )
        self.start_with_windows = _coerce_bool(
            values.get("start_with_windows", _DEFAULTS["start_with_windows"]),
            _DEFAULTS["start_with_windows"],
        )
        self.tray_enabled = _coerce_bool(
            values.get("tray_enabled", _DEFAULTS["tray_enabled"]),
            _DEFAULTS["tray_enabled"],
        )
        self.tray_on_close = _coerce_bool(
            values.get("tray_on_close", _DEFAULTS["tray_on_close"]),
            _DEFAULTS["tray_on_close"],
        )
        self.native_notifications = _coerce_bool(
            values.get("native_notifications", _DEFAULTS["native_notifications"]),
            _DEFAULTS["native_notifications"],
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
        self.sidebar_collapsed = _coerce_bool(
            values.get("sidebar_collapsed", _DEFAULTS["sidebar_collapsed"]),
            _DEFAULTS["sidebar_collapsed"],
        )
        self.ui_animations = _coerce_bool(
            values.get("ui_animations", _DEFAULTS["ui_animations"]),
            _DEFAULTS["ui_animations"],
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
        self.custom_categories = normalize_custom_categories(
            values.get("custom_categories")
        )
        self.category_paths = normalize_category_paths(
            values.get("category_paths"), self.custom_categories
        )

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
        if "speed_limit_mode" in values:
            self.speed_limit_mode = normalize_speed_limit_mode(
                values["speed_limit_mode"], self.speed_limit_kbps
            )
        if "speed_limit_percent" in values:
            self.speed_limit_percent = _coerce_int(
                values["speed_limit_percent"],
                self.speed_limit_percent,
                MIN_SPEED_LIMIT_PERCENT,
                100,
            )
        if "measured_capacity_kbps" in values:
            self.measured_capacity_kbps = _coerce_int(
                values["measured_capacity_kbps"],
                self.measured_capacity_kbps,
                0,
                MAX_SPEED_LIMIT_KBPS,
            )
        if "proxy_mode" in values:
            self.proxy_mode = normalize_proxy_mode(values["proxy_mode"])
        if "proxy_host" in values:
            self.proxy_host = str(values["proxy_host"] or "").strip()[:255]
        if "proxy_port" in values:
            self.proxy_port = _coerce_int(
                values["proxy_port"], self.proxy_port, 1, 65535
            )
        if "proxy_username" in values:
            self.proxy_username = str(values["proxy_username"] or "").strip()[:513]
        if "proxy_use_auth" in values:
            self.proxy_use_auth = bool(values["proxy_use_auth"])
        if "proxy_bypass" in values:
            self.proxy_bypass = str(values["proxy_bypass"] or "").strip()[:2000]
        if "site_auth" in values:
            self.site_auth = normalize_site_auth(values["site_auth"])
        if "connect_timeout" in values:
            self.connect_timeout = _coerce_int(
                values["connect_timeout"],
                self.connect_timeout,
                int(MIN_TIMEOUT),
                int(MAX_CONNECT_TIMEOUT),
            )
        if "read_timeout" in values:
            self.read_timeout = _coerce_int(
                values["read_timeout"],
                self.read_timeout,
                int(MIN_TIMEOUT),
                int(MAX_READ_TIMEOUT),
            )
        for key in (
            "confirm_delete",
            "show_completion_dialog",
            "start_immediately",
            "restore_session",
            "start_with_windows",
            "tray_enabled",
            "tray_on_close",
            "native_notifications",
            "show_toolbar",
            "show_sidebar",
            "show_status_bar",
            "show_download_list",
            "sidebar_collapsed",
            "ui_animations",
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
        if "custom_categories" in values:
            self.custom_categories = normalize_custom_categories(
                values["custom_categories"]
            )
            self.category_paths = normalize_category_paths(
                self.category_paths, self.custom_categories
            )
        if "category_paths" in values:
            self.category_paths = normalize_category_paths(
                values["category_paths"], self.custom_categories
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
            "speed_limit_mode": self.speed_limit_mode,
            "speed_limit_percent": self.speed_limit_percent,
            "measured_capacity_kbps": self.measured_capacity_kbps,
            "proxy_mode": self.proxy_mode,
            "proxy_host": self.proxy_host,
            "proxy_port": self.proxy_port,
            "proxy_username": self.proxy_username,
            "proxy_use_auth": self.proxy_use_auth,
            "proxy_bypass": self.proxy_bypass,
            "site_auth": [dict(entry) for entry in self.site_auth],
            "connect_timeout": self.connect_timeout,
            "read_timeout": self.read_timeout,
            "confirm_delete": self.confirm_delete,
            "show_completion_dialog": self.show_completion_dialog,
            "start_immediately": self.start_immediately,
            "restore_session": self.restore_session,
            "start_with_windows": self.start_with_windows,
            "tray_enabled": self.tray_enabled,
            "tray_on_close": self.tray_on_close,
            "native_notifications": self.native_notifications,
            "show_toolbar": self.show_toolbar,
            "show_sidebar": self.show_sidebar,
            "show_status_bar": self.show_status_bar,
            "show_download_list": self.show_download_list,
            "sidebar_collapsed": self.sidebar_collapsed,
            "ui_animations": self.ui_animations,
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
            "custom_categories": [dict(entry) for entry in self.custom_categories],
            "category_paths": dict(self.category_paths),
            **self.location_config.to_settings(),
        }

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-safe copy of every persisted setting."""
        return dict(self._as_dict())

    # ------------------------------------------------------------------ updates
    def remembered_folder(self, category: str) -> str:
        """Folder remembered for a category, or an empty string."""
        return self.category_paths.get(str(category or "").strip(), "")

    def remember_category_folder(self, category: str, folder: str) -> None:
        name = str(category or "").strip()
        path = str(folder or "").strip()
        if not name or not path:
            return
        paths = dict(self.category_paths)
        paths[name] = path
        self.category_paths = normalize_category_paths(
            paths, self.custom_categories
        )
        self.save()

    def forget_category_folder(self, category: str) -> None:
        name = str(category or "").strip()
        if not name or name not in self.category_paths:
            return
        paths = dict(self.category_paths)
        paths.pop(name, None)
        self.category_paths = paths
        self.save()

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
