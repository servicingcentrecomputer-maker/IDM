"""Update handoff file shared by the application and the updater.

The application downloads and verifies the installer, then writes a small JSON
description and launches ``IDM_Updater.exe``.  The updater re-validates the
handoff, re-verifies the package, waits for IDM to exit and only then starts the
signed Inno Setup installer.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .errors import UpdaterError
from .version_manager import Version, VersionError

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
COMPLETION_MARKER = "update-complete.json"
_MAX_HANDOFF_BYTES = 64 * 1024
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_UPDATE_DIR_PREFIX = "IDM-Update-"


@dataclass(frozen=True)
class UpdateHandoff:
    installer: Path
    sha256: str
    publisher: str
    parent_pid: int
    app_exe: Path
    target_version: str
    restart: bool
    update_dir: Path
    log_file: Path

    @property
    def app_dir(self) -> Path:
        return self.app_exe.parent


def write_handoff(path: Path, handoff: UpdateHandoff) -> Path:
    target = Path(path)
    validate_handoff_values(handoff)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": SCHEMA_VERSION,
        "installer": str(handoff.installer),
        "sha256": handoff.sha256,
        "publisher": handoff.publisher,
        "parent_pid": handoff.parent_pid,
        "app_exe": str(handoff.app_exe),
        "target_version": handoff.target_version,
        "restart": handoff.restart,
        "update_dir": str(handoff.update_dir),
        "log_file": str(handoff.log_file),
    }
    text = json.dumps(payload, indent=2)
    target.write_text(text, encoding="utf-8")
    try:
        with open(target, "rb") as handle:
            os.fsync(handle.fileno())
    except OSError:
        logger.debug("Could not flush the update handoff file", exc_info=True)
    return target


def read_handoff(path: Path) -> UpdateHandoff:
    source = Path(path)
    try:
        if source.stat().st_size > _MAX_HANDOFF_BYTES:
            raise UpdaterError("The update handoff file is unexpectedly large.")
        text = source.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise UpdaterError("The update handoff file is missing.") from exc
    except OSError as exc:
        raise UpdaterError("The update handoff file could not be read.") from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise UpdaterError("The update handoff file is not valid JSON.") from exc
    if not isinstance(data, dict):
        raise UpdaterError("The update handoff file is not valid.")

    schema = data.get("schema")
    if schema != SCHEMA_VERSION:
        raise UpdaterError("The update handoff schema is not supported.")

    restart = data.get("restart")
    if not isinstance(restart, bool):
        raise UpdaterError("The handoff restart flag is invalid.")
    parent_pid = data.get("parent_pid")
    if not isinstance(parent_pid, int) or isinstance(parent_pid, bool) or parent_pid < 1:
        raise UpdaterError("The handoff process ID is invalid.")

    handoff = UpdateHandoff(
        installer=_absolute_path(data.get("installer"), "installer"),
        sha256=str(data.get("sha256") or ""),
        publisher=str(data.get("publisher") or ""),
        parent_pid=parent_pid,
        app_exe=_absolute_path(data.get("app_exe"), "app_exe"),
        target_version=str(data.get("target_version") or ""),
        restart=restart,
        update_dir=_absolute_path(data.get("update_dir"), "update_dir"),
        log_file=_absolute_path(data.get("log_file"), "log_file"),
    )
    validate_handoff_values(handoff)
    return handoff


def validate_handoff_values(handoff: UpdateHandoff) -> None:
    if not _SHA256_RE.fullmatch(handoff.sha256):
        raise UpdaterError("The handoff SHA-256 value is invalid.")
    if not handoff.publisher.strip():
        raise UpdaterError("The handoff does not name a trusted publisher.")
    if handoff.installer.suffix.casefold() != ".exe":
        raise UpdaterError("The handoff installer must be an .exe file.")
    if not handoff.installer.is_absolute() or not handoff.update_dir.is_absolute():
        raise UpdaterError("The handoff paths must be absolute.")
    if not handoff.app_exe.is_absolute() or not handoff.log_file.is_absolute():
        raise UpdaterError("The handoff paths must be absolute.")
    if not _is_relative_to(handoff.installer, handoff.update_dir):
        raise UpdaterError(
            "The installer is not inside the temporary update directory."
        )
    if not handoff.update_dir.name.startswith(_UPDATE_DIR_PREFIX):
        raise UpdaterError("The update directory name is not recognized.")
    try:
        Version.parse(handoff.target_version)
    except VersionError as exc:
        raise UpdaterError("The handoff target version is invalid.") from exc


def write_completion_marker(update_dir: Path, version: str) -> Path | None:
    """Leave a marker when the running updater could not delete its own folder."""
    target = Path(update_dir) / COMPLETION_MARKER
    payload = {
        "target_version": version,
        "completed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        logger.debug("Could not write the update completion marker", exc_info=True)
        return None
    return target


def has_completion_marker(update_dir: Path) -> bool:
    try:
        return (Path(update_dir) / COMPLETION_MARKER).is_file()
    except OSError:
        return False


def safe_remove_update_dir(path: Path) -> bool:
    """Delete a temporary update directory without touching user data."""
    directory = Path(path)
    try:
        resolved = directory.resolve()
    except OSError:
        return False
    if directory.is_symlink():
        logger.warning("Refusing to remove a symlinked update directory")
        return False
    if not resolved.name.startswith(_UPDATE_DIR_PREFIX):
        logger.warning("Refusing to remove an unrecognized directory: %s", resolved)
        return False
    temp_root = Path(tempfile.gettempdir()).resolve()
    if resolved == temp_root or not _is_relative_to(resolved, temp_root):
        logger.warning(
            "Refusing to remove an update directory outside the temp folder: %s",
            resolved,
        )
        return False
    try:
        shutil.rmtree(resolved)
        return True
    except OSError:
        logger.warning("Could not remove update directory %s", resolved, exc_info=True)
        return False


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
    except (ValueError, OSError):
        return False
    return True


def _absolute_path(value: object, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise UpdaterError(f"The handoff {field} path is missing.")
    path = Path(value)
    if not path.is_absolute():
        raise UpdaterError(f"The handoff {field} path must be absolute.")
    return path
