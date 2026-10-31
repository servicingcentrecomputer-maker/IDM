"""Verified, timestamped backups taken before an update is installed.

A backup folder contains a consistent SQLite copy plus JSON snapshots of the
settings, download records, queue, browser integration manifests, update
configuration and the release manifest.  ``backup-manifest.json`` records the
SHA-256 and size of every file so a backup can be verified before it is used to
restore user data.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..core.paths import update_backups_dir
from .errors import BackupError

logger = logging.getLogger(__name__)

MANIFEST_NAME = "backup-manifest.json"
DATABASE_NAME = "idm.sqlite3"
_MAX_KEEP = 10
_SAFE_PART_RE = re.compile(r"[^0-9A-Za-z._-]+")


@dataclass(frozen=True)
class UpdateBackup:
    directory: Path
    database: Path
    created_at: str
    files: dict[str, str]
    verified: bool = True


def create_pre_update_backup(
    *,
    database,
    from_version: str,
    target_version: str,
    settings_snapshot: dict,
    update_config: dict | None = None,
    manifest: object | None = None,
    browser_manifest_dir: Path | None = None,
    base_dir: Path | None = None,
    keep: int = 5,
    now: datetime | None = None,
) -> UpdateBackup:
    """Create and verify a backup folder for one update attempt."""
    moment = now or datetime.now(timezone.utc)
    stamp = moment.astimezone().strftime("%Y%m%d-%H%M%S")
    root = Path(base_dir) if base_dir is not None else update_backups_dir()
    root.mkdir(parents=True, exist_ok=True)
    directory = root / (
        f"{stamp}-{_safe_part(from_version)}-to-{_safe_part(target_version)}"
    )
    directory.mkdir(parents=True, exist_ok=False)

    created_at = moment.astimezone(timezone.utc).isoformat(timespec="seconds")
    files: dict[str, str] = {}
    try:
        db_path = database.backup(directory / DATABASE_NAME)

        _write_json(directory / "settings.json", settings_snapshot)
        _write_json(directory / "update-config.json", update_config or {})
        _write_json(directory / "queue.json", _safe_call(database.load_queue, []))
        _write_json(directory / "downloads.json", _safe_call(database.load_downloads, []))
        _write_json(
            directory / "manifest.json",
            manifest.to_dict() if hasattr(manifest, "to_dict") else None,
        )

        browser_files = _backup_browser_integration(
            directory / "browser-integration", browser_manifest_dir
        )
        _write_json(
            directory / "browser-integration" / "inventory.json",
            {"files": browser_files, "source": str(browser_manifest_dir or "")},
        )

        info = {
            "from_version": str(from_version),
            "target_version": str(target_version),
            "created_at": created_at,
            "database_schema_version": _safe_call(database.schema_version, 0),
        }
        _write_json(directory / "backup-info.json", info)

        payload = {
            "created_at": created_at,
            "from_version": str(from_version),
            "target_version": str(target_version),
            "files": {},
        }
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.name == MANIFEST_NAME:
                continue
            relative = path.relative_to(directory).as_posix()
            files[relative] = sha256_file(path)
            payload["files"][relative] = {
                "sha256": files[relative],
                "size": path.stat().st_size,
            }
        _write_json(directory / MANIFEST_NAME, payload)
        verify_backup(directory)
    except Exception as exc:
        logger.exception("Pre-update backup failed")
        _remove_directory(directory)
        if isinstance(exc, BackupError):
            raise
        raise BackupError(f"The pre-update backup could not be created: {exc}") from exc

    prune_backups(root, keep=keep)
    logger.info("Pre-update backup verified at %s", directory)
    return UpdateBackup(
        directory=directory,
        database=db_path,
        created_at=created_at,
        files=files,
    )


def verify_backup(directory: Path) -> None:
    """Verify every file listed in ``backup-manifest.json``."""
    directory = Path(directory)
    manifest_path = directory / MANIFEST_NAME
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BackupError("The backup manifest is missing.") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupError("The backup manifest could not be read.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), dict):
        raise BackupError("The backup manifest is not valid.")

    listed = payload["files"]
    if DATABASE_NAME not in listed:
        raise BackupError("The backup does not contain a database copy.")

    for relative, expected in listed.items():
        if not isinstance(expected, dict):
            raise BackupError("The backup manifest contains an invalid entry.")
        path = _safe_child(directory, str(relative))
        if not path.is_file():
            raise BackupError(f"The backup file “{relative}” is missing.")
        size = path.stat().st_size
        if size != int(expected.get("size", -1)):
            raise BackupError(f"The backup file “{relative}” has the wrong size.")
        digest = sha256_file(path)
        if digest.lower() != str(expected.get("sha256", "")).lower():
            raise BackupError(f"The backup file “{relative}” failed verification.")

    database_path = directory / DATABASE_NAME
    _quick_check_database(database_path)


def restore_database(backup_dir: Path, destination: Path) -> Path:
    """Restore only the SQLite database from a verified backup."""
    backup_dir = Path(backup_dir)
    verify_backup(backup_dir)
    source = backup_dir / DATABASE_NAME
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f"{destination.name}.restore-{os.getpid()}")
    try:
        shutil.copy2(source, temporary)
        with open(temporary, "rb+") as handle:
            os.fsync(handle.fileno())
        # Stale journals from the interrupted database would otherwise be
        # replayed against the restored file.
        for suffix in ("-wal", "-shm", "-journal"):
            destination.with_name(destination.name + suffix).unlink(missing_ok=True)
        os.replace(temporary, destination)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise BackupError("The database backup could not be restored.") from exc
    logger.info("Database restored from %s", backup_dir)
    return destination


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prune_backups(root: Path, keep: int = 5) -> int:
    keep = max(1, min(int(keep), _MAX_KEEP))
    try:
        entries = [entry for entry in Path(root).iterdir() if entry.is_dir()]
    except OSError:
        return 0
    entries.sort(key=lambda entry: entry.stat().st_mtime, reverse=True)
    removed = 0
    for entry in entries[keep:]:
        if _remove_directory(entry):
            removed += 1
    return removed


def _backup_browser_integration(
    destination: Path, source_dir: Path | None
) -> list[str]:
    destination.mkdir(parents=True, exist_ok=True)
    if source_dir is None:
        return []
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        return []
    copied: list[str] = []
    try:
        candidates = sorted(source_dir.glob("com.idm.native.*.json"))
    except OSError:
        return []
    for path in candidates:
        try:
            shutil.copy2(path, destination / path.name)
            copied.append(path.name)
        except OSError:
            logger.debug("Could not back up %s", path, exc_info=True)
    return copied


def _safe_child(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise BackupError("The backup manifest contains an unsafe path.")
    resolved = (Path(root) / candidate).resolve()
    try:
        resolved.relative_to(Path(root).resolve())
    except ValueError as exc:
        raise BackupError("The backup manifest contains an unsafe path.") from exc
    return resolved


def _quick_check_database(path: Path) -> None:
    import sqlite3

    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = connection.execute("PRAGMA quick_check").fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise BackupError("The backed-up database could not be opened.") from exc
    result = str(row[0]) if row else "missing"
    if result.casefold() != "ok":
        raise BackupError(f"The backed-up database failed its integrity check: {result}")


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _safe_call(function, fallback):
    try:
        return function()
    except Exception:
        logger.debug("Backup snapshot step failed", exc_info=True)
        return fallback


def _safe_part(value: str) -> str:
    cleaned = _SAFE_PART_RE.sub("-", str(value).strip()).strip(".-")
    return cleaned or "0.0.0"


def _remove_directory(path: Path) -> bool:
    try:
        shutil.rmtree(path)
        return True
    except OSError:
        logger.debug("Could not remove backup directory %s", path, exc_info=True)
        return False
