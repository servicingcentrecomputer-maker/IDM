"""Rollback support: cached installers, binary snapshots and plans.

Before IDM closes for an update it records how to return to the previous
version.  Two restore sources are supported:

* a verified copy of the previous ``IDM_Setup_<version>.exe`` (preferred),
* a snapshot of the installation directory (used when no installer is cached).

Both live under ``%APPDATA%\\IDM Download Manager\\updates\\rollback`` so the
standalone updater can reach them after IDM has closed.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..core.paths import update_rollback_dir
from .backup import sha256_file, verify_backup
from .errors import RollbackError
from .version_manager import Version, VersionError

logger = logging.getLogger(__name__)

PLAN_NAME = "last-rollback.json"
_INSTALLER_PREFIX = "IDM_Setup_"
_SNAPSHOT_PREFIX = "app-"
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_SAFE_VERSION_RE = re.compile(r"[^0-9A-Za-z._-]+")
_MAX_KEEP_INSTALLERS = 3
_MAX_KEEP_SNAPSHOTS = 1
_DEFAULT_MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024 * 1024
_SNAPSHOT_IGNORE = shutil.ignore_patterns(
    "downloads", "logs", "*.idm.part", "*.part", "*.tmp", "__pycache__", ".git"
)


@dataclass(frozen=True)
class RollbackPlan:
    from_version: str
    target_version: str
    db_backup: str
    backup_dir: str
    previous_installer: str = ""
    previous_installer_sha256: str = ""
    previous_publisher: str = ""
    binary_snapshot: str = ""
    app_exe: str = ""
    log_file: str = ""
    restart: bool = True
    parent_pid: int = 0

    @property
    def can_restore_binaries(self) -> bool:
        return bool(self.previous_installer or self.binary_snapshot)


def cache_installer(
    installer: Path,
    version: str,
    sha256: str,
    *,
    base_dir: Path | None = None,
) -> Path:
    """Copy a verified installer into the rollback cache for future use."""
    source = Path(installer)
    if not source.is_file():
        raise RollbackError("The installer to cache does not exist.")
    if not _SHA256_RE.fullmatch(str(sha256)):
        raise RollbackError("The cached installer SHA-256 is invalid.")
    actual = sha256_file(source)
    if actual.lower() != str(sha256).lower():
        raise RollbackError("The installer changed before it could be cached.")

    root = _rollback_root(base_dir)
    destination = root / f"{_INSTALLER_PREFIX}{_safe_version(version)}.exe"
    if not destination.is_file() or sha256_file(destination) != actual:
        temporary = destination.with_name(f"{destination.name}.{os.getpid()}.tmp")
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, destination)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise RollbackError("The installer could not be cached for rollback.") from exc
    _prune(root.glob(f"{_INSTALLER_PREFIX}*.exe"), keep=_MAX_KEEP_INSTALLERS)
    return destination


def find_cached_installer(
    version: str, *, base_dir: Path | None = None
) -> tuple[Path, str] | None:
    path = _rollback_root(base_dir) / (
        f"{_INSTALLER_PREFIX}{_safe_version(version)}.exe"
    )
    if not path.is_file():
        return None
    try:
        return path, sha256_file(path)
    except OSError:
        return None


def create_binary_snapshot(
    app_dir: Path,
    version: str,
    *,
    base_dir: Path | None = None,
    max_bytes: int = _DEFAULT_MAX_SNAPSHOT_BYTES,
    now: datetime | None = None,
) -> Path | None:
    """Copy the installation directory so it can be restored if necessary."""
    app_dir = Path(app_dir)
    if not app_dir.is_dir():
        logger.warning("Cannot snapshot missing application directory %s", app_dir)
        return None
    try:
        total = _directory_size(app_dir)
    except OSError:
        logger.warning("Could not inspect the application directory", exc_info=True)
        return None
    if total <= 0 or total > max_bytes:
        logger.warning(
            "Skipping binary snapshot (%d bytes, limit %d)", total, max_bytes
        )
        return None

    moment = now or datetime.now(timezone.utc)
    stamp = moment.astimezone().strftime("%Y%m%d-%H%M%S")
    root = _rollback_root(base_dir)
    destination = root / f"{_SNAPSHOT_PREFIX}{_safe_version(version)}-{stamp}"
    if destination.exists():
        raise RollbackError("A rollback snapshot with this timestamp already exists.")
    try:
        shutil.copytree(app_dir, destination, ignore=_SNAPSHOT_IGNORE)
    except OSError as exc:
        _remove(destination)
        logger.warning("Binary snapshot failed: %s", exc)
        return None
    _prune(root.glob(f"{_SNAPSHOT_PREFIX}*"), keep=_MAX_KEEP_SNAPSHOTS, only_dirs=True)
    logger.info("Binary rollback snapshot written to %s", destination)
    return destination


def restore_binary_snapshot(snapshot: Path, app_dir: Path) -> None:
    """Replace the installation directory contents with a snapshot."""
    snapshot = Path(snapshot)
    app_dir = Path(app_dir)
    if not snapshot.is_dir():
        raise RollbackError("The rollback snapshot is missing.")
    if not snapshot.name.startswith(_SNAPSHOT_PREFIX):
        raise RollbackError("The rollback snapshot name is not recognised.")
    if not app_dir.is_dir():
        raise RollbackError("The installation directory is missing.")
    try:
        snapshot_resolved = snapshot.resolve()
        app_resolved = app_dir.resolve()
        snapshot_resolved.relative_to(app_resolved)
    except ValueError:
        pass
    else:
        raise RollbackError("The snapshot cannot be inside the installation folder.")
    try:
        app_resolved.relative_to(snapshot_resolved)
    except ValueError:
        pass
    else:
        raise RollbackError("The installation folder cannot be inside the snapshot.")

    for child in app_resolved.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    for child in snapshot_resolved.iterdir():
        target = app_resolved / child.name
        if child.is_dir() and not child.is_symlink():
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)
    logger.info("Application binaries restored from %s", snapshot)


def build_rollback_plan(
    *,
    from_version: str,
    target_version: str,
    backup_dir: Path,
    db_backup: Path,
    previous_installer: Path | None,
    previous_installer_sha256: str,
    previous_publisher: str,
    binary_snapshot: Path | None,
    app_exe: Path,
    log_file: Path,
    restart: bool = True,
    parent_pid: int = 0,
) -> RollbackPlan:
    plan = RollbackPlan(
        from_version=str(from_version),
        target_version=str(target_version),
        backup_dir=str(backup_dir),
        db_backup=str(db_backup),
        previous_installer=str(previous_installer or ""),
        previous_installer_sha256=str(previous_installer_sha256 or ""),
        previous_publisher=str(previous_publisher or ""),
        binary_snapshot=str(binary_snapshot or ""),
        app_exe=str(app_exe),
        log_file=str(log_file),
        restart=bool(restart),
        parent_pid=max(0, int(parent_pid)),
    )
    validate_plan(plan)
    return plan


def write_rollback_plan(plan: RollbackPlan, path: Path | None = None) -> Path:
    validate_plan(plan)
    target = Path(path) if path is not None else update_rollback_dir() / PLAN_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(asdict(plan), indent=2), encoding="utf-8")
    try:
        with open(temporary, "rb+") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise RollbackError("The rollback plan could not be written.") from exc
    return target


def read_rollback_plan(path: Path | None = None) -> RollbackPlan:
    source = Path(path) if path is not None else update_rollback_dir() / PLAN_NAME
    try:
        data = json.loads(source.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise RollbackError("No rollback plan is available.") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RollbackError("The rollback plan could not be read.") from exc
    if not isinstance(data, dict):
        raise RollbackError("The rollback plan is not valid.")
    values = {}
    for field in RollbackPlan.__dataclass_fields__:
        default = getattr(RollbackPlan, field, None)
        if field == "restart":
            values[field] = bool(data.get(field, True))
        elif field == "parent_pid":
            try:
                values[field] = max(0, int(data.get(field, 0)))
            except (TypeError, ValueError):
                values[field] = 0
        else:
            values[field] = str(data.get(field, "") or "")
    plan = RollbackPlan(**values)
    validate_plan(plan)
    return plan


def validate_plan(plan: RollbackPlan) -> None:
    for field in ("from_version", "target_version"):
        try:
            Version.parse(getattr(plan, field))
        except VersionError as exc:
            raise RollbackError(f"The rollback {field} is invalid.") from exc
    if plan.from_version == plan.target_version:
        raise RollbackError("The rollback source and target versions match.")

    backup_dir = Path(plan.backup_dir)
    db_backup = Path(plan.db_backup)
    if not backup_dir.is_absolute() or not db_backup.is_absolute():
        raise RollbackError("The rollback backup paths must be absolute.")
    try:
        db_backup.resolve().relative_to(backup_dir.resolve())
    except ValueError as exc:
        raise RollbackError("The database backup is outside the backup folder.") from exc
    verify_backup(backup_dir)

    if plan.previous_installer:
        installer = Path(plan.previous_installer)
        if not installer.is_absolute() or installer.suffix.casefold() != ".exe":
            raise RollbackError("The rollback installer path is invalid.")
        if not _SHA256_RE.fullmatch(plan.previous_installer_sha256):
            raise RollbackError("The rollback installer SHA-256 is invalid.")
        if not plan.previous_publisher.strip():
            raise RollbackError("The rollback installer has no trusted publisher.")
        if not installer.is_file():
            raise RollbackError("The rollback installer is missing.")
        if sha256_file(installer).lower() != plan.previous_installer_sha256.lower():
            raise RollbackError("The rollback installer failed SHA-256 verification.")

    if plan.binary_snapshot:
        snapshot = Path(plan.binary_snapshot)
        if not snapshot.is_absolute() or not snapshot.is_dir():
            raise RollbackError("The rollback snapshot is missing.")
        if not snapshot.name.startswith(_SNAPSHOT_PREFIX):
            raise RollbackError("The rollback snapshot name is invalid.")

    if not plan.previous_installer and not plan.binary_snapshot:
        raise RollbackError("No previous version is available to restore.")
    if not Path(plan.app_exe).is_absolute():
        raise RollbackError("The rollback application path is invalid.")
    if not isinstance(plan.parent_pid, int) or plan.parent_pid < 0:
        raise RollbackError("The rollback parent process ID is invalid.")


def clear_rollback_plan(path: Path | None = None) -> None:
    source = Path(path) if path is not None else update_rollback_dir() / PLAN_NAME
    try:
        source.unlink(missing_ok=True)
    except OSError:
        logger.debug("Could not remove the rollback plan", exc_info=True)


def _rollback_root(base_dir: Path | None) -> Path:
    root = Path(base_dir) if base_dir is not None else update_rollback_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_version(version: str) -> str:
    cleaned = _SAFE_VERSION_RE.sub("-", str(version).strip()).strip(".-")
    return cleaned or "0.0.0"


def _directory_size(directory: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(directory):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


def _prune(paths, keep: int, only_dirs: bool = False) -> None:
    entries = []
    for path in paths:
        try:
            if only_dirs and not path.is_dir():
                continue
            entries.append((path.stat().st_mtime, path))
        except OSError:
            continue
    entries.sort(key=lambda item: item[0], reverse=True)
    for _mtime, path in entries[keep:]:
        _remove(path)


def _remove(path: Path) -> None:
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    except OSError:
        logger.debug("Could not remove %s", path, exc_info=True)
