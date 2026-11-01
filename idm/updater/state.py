"""Persistent update state: pending installs and update history.

``pending-update.json`` is written before IDM closes for an update and read on
the next start.  It is how the application learns whether the installation
actually finished, which database backup belongs to the attempt, and which
previous binaries can be restored if the update failed.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..core.paths import (
    install_result_file,
    pending_update_file,
    update_history_file,
)
from .errors import UpdateStateError
from .version_manager import Version, VersionError

logger = logging.getLogger(__name__)

_MAX_STATE_BYTES = 256 * 1024
_MAX_HISTORY_ENTRIES = 25


@dataclass(frozen=True)
class PendingUpdate:
    from_version: str
    target_version: str
    started_at: str
    backup_dir: str
    db_backup: str
    previous_installer: str = ""
    previous_installer_sha256: str = ""
    previous_publisher: str = ""
    binary_snapshot: str = ""
    app_exe: str = ""
    channel: str = "stable"
    reinstall: bool = False

    @property
    def rollback_available(self) -> bool:
        return bool(self.previous_installer or self.binary_snapshot)


@dataclass(frozen=True)
class PendingOutcome:
    status: str
    pending: PendingUpdate | None = None
    message: str = ""


@dataclass(frozen=True)
class InstallResult:
    target_version: str
    success: bool
    exit_code: int = 0
    reinstall: bool = False
    completed_at: str = ""


def write_install_result(result: InstallResult, path: Path | None = None) -> Path:
    try:
        Version.parse(result.target_version)
    except VersionError as exc:
        raise UpdateStateError(
            "The installer result target version is not valid."
        ) from exc
    target = Path(path) if path is not None else install_result_file()
    _write_json(target, asdict(result))
    return target


def read_install_result(path: Path | None = None) -> InstallResult | None:
    source = Path(path) if path is not None else install_result_file()
    data = _read_json(source, missing_ok=True)
    if data is None:
        return None
    if not isinstance(data, dict):
        raise UpdateStateError("The installer result file is not valid.")
    try:
        exit_code = max(0, int(data.get("exit_code", 0)))
    except (TypeError, ValueError) as exc:
        raise UpdateStateError(
            "The installer result exit code is not valid."
        ) from exc
    result = InstallResult(
        target_version=str(data.get("target_version") or ""),
        success=bool(data.get("success", False)),
        exit_code=exit_code,
        reinstall=bool(data.get("reinstall", False)),
        completed_at=str(data.get("completed_at") or ""),
    )
    try:
        Version.parse(result.target_version)
    except VersionError as exc:
        raise UpdateStateError(
            "The installer result target version is not valid."
        ) from exc
    return result


def clear_install_result(path: Path | None = None) -> None:
    source = Path(path) if path is not None else install_result_file()
    try:
        source.unlink(missing_ok=True)
    except OSError:
        logger.debug("Could not remove the installer result file", exc_info=True)


def write_pending_update(
    pending: PendingUpdate, path: Path | None = None
) -> Path:
    _validate_pending(pending)
    target = Path(path) if path is not None else pending_update_file()
    _write_json(target, asdict(pending))
    return target


def read_pending_update(path: Path | None = None) -> PendingUpdate | None:
    source = Path(path) if path is not None else pending_update_file()
    data = _read_json(source, missing_ok=True)
    if data is None:
        return None
    if not isinstance(data, dict):
        raise UpdateStateError("The pending update file is not valid.")
    values = {}
    for field in PendingUpdate.__dataclass_fields__:
        if field == "reinstall":
            values[field] = bool(data.get(field, False))
            continue
        value = data.get(field, "")
        values[field] = "" if value is None else str(value)
    pending = PendingUpdate(**values)
    _validate_pending(pending)
    return pending


def clear_pending_update(path: Path | None = None) -> None:
    source = Path(path) if path is not None else pending_update_file()
    try:
        source.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Could not remove the pending update file", exc_info=True)
        raise UpdateStateError("The pending update file could not be removed.") from exc


def append_history(entry: dict, path: Path | None = None) -> None:
    target = Path(path) if path is not None else update_history_file()
    history = load_history(path=target)
    item = dict(entry)
    item.setdefault("at", _utc_now())
    history.insert(0, item)
    _write_json(target, history[:_MAX_HISTORY_ENTRIES])


def load_history(path: Path | None = None) -> list[dict]:
    source = Path(path) if path is not None else update_history_file()
    data = _read_json(source, missing_ok=True)
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)][:_MAX_HISTORY_ENTRIES]


def record_event(
    event: str,
    *,
    from_version: str,
    target_version: str,
    message: str = "",
    backup_dir: str = "",
    path: Path | None = None,
) -> None:
    append_history(
        {
            "event": str(event),
            "from_version": str(from_version),
            "target_version": str(target_version),
            "message": str(message),
            "backup_dir": str(backup_dir),
            "at": _utc_now(),
        },
        path=path,
    )


def evaluate_pending_update(
    current_version: str, path: Path | None = None
) -> PendingOutcome:
    """Classify a pending install against the version that is running now."""
    pending = read_pending_update(path)
    if pending is None:
        return PendingOutcome("none")
    current = str(current_version).strip()
    if pending.reinstall:
        try:
            result = read_install_result()
        except UpdateStateError:
            logger.warning("The installer result could not be read", exc_info=True)
            result = None
        if result is not None and result.target_version == pending.target_version:
            if result.success:
                return PendingOutcome("succeeded", pending)
            return PendingOutcome(
                "not-installed",
                pending,
                f"The reinstall of IDM {pending.target_version} did not "
                "finish. IDM is still installed and your data is intact.",
            )
        if current == pending.target_version:
            return PendingOutcome("succeeded", pending)
        return PendingOutcome(
            "version-mismatch",
            pending,
            f"IDM reports version {current}, but the reinstall expected "
            f"{pending.target_version}.",
        )
    if current == pending.target_version:
        return PendingOutcome("succeeded", pending)
    if current == pending.from_version:
        return PendingOutcome(
            "not-installed",
            pending,
            f"The update to IDM {pending.target_version} did not finish. "
            f"IDM {pending.from_version} is still installed.",
        )
    return PendingOutcome(
        "version-mismatch",
        pending,
        f"IDM reports version {current}, but the update expected "
        f"{pending.from_version} or {pending.target_version}.",
    )


def finalize_pending_update(
    settings, current_version: str, path: Path | None = None
) -> PendingOutcome:
    """Record the outcome of a pending install and clear the pending file."""
    outcome = evaluate_pending_update(current_version, path)
    if outcome.pending is None:
        return outcome

    pending = outcome.pending
    clear_install_result()
    if outcome.status == "succeeded":
        try:
            settings.database.quick_check()
        except Exception as exc:
            logger.exception("The database failed its integrity check")
            message = (
                "The database failed its integrity check after the reinstall."
                if pending.reinstall
                else "The database failed its integrity check after the update."
            )
            record_event(
                "failure",
                from_version=pending.from_version,
                target_version=pending.target_version,
                message=message,
                backup_dir=pending.backup_dir,
            )
            clear_pending_update(path)
            return PendingOutcome("database-error", pending, message)
        settings.note_update_success(pending.target_version)
        record_event(
            "success",
            from_version=pending.from_version,
            target_version=pending.target_version,
            message=(
                "Reinstall completed successfully."
                if pending.reinstall
                else "Update installed successfully."
            ),
            backup_dir=pending.backup_dir,
        )
    else:
        record_event(
            "failure",
            from_version=pending.from_version,
            target_version=pending.target_version,
            message=outcome.message,
            backup_dir=pending.backup_dir,
        )
    clear_pending_update(path)
    return outcome


def _validate_pending(pending: PendingUpdate) -> None:
    for field in ("from_version", "target_version"):
        try:
            Version.parse(getattr(pending, field))
        except VersionError as exc:
            raise UpdateStateError(
                f"The pending update {field} is not a valid version."
            ) from exc
    if pending.from_version == pending.target_version:
        if not pending.reinstall:
            raise UpdateStateError(
                "The pending update target matches the source version."
            )
    elif pending.reinstall:
        raise UpdateStateError(
            "The pending reinstall must keep the installed version."
        )
    if not pending.backup_dir.strip():
        raise UpdateStateError("The pending update has no backup directory.")
    for field in (
        "backup_dir",
        "db_backup",
        "previous_installer",
        "binary_snapshot",
        "app_exe",
    ):
        value = getattr(pending, field)
        if value and not Path(value).is_absolute():
            raise UpdateStateError(
                f"The pending update {field} path must be absolute."
            )


def _write_json(target: Path, payload) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    try:
        temporary.write_text(text, encoding="utf-8")
        with open(temporary, "rb+") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise UpdateStateError(f"The update state file could not be written: {target.name}") from exc


def _read_json(source: Path, missing_ok: bool) -> object | None:
    try:
        if source.stat().st_size > _MAX_STATE_BYTES:
            raise UpdateStateError("The update state file is unexpectedly large.")
        text = source.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        if missing_ok:
            return None
        raise UpdateStateError("The update state file is missing.")
    except OSError as exc:
        raise UpdateStateError("The update state file could not be read.") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise UpdateStateError("The update state file is not valid JSON.") from exc


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
