"""Application-side helpers for staging and launching the updater."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .handoff import (
    UpdateHandoff,
    has_completion_marker,
    safe_remove_update_dir,
    write_handoff,
)
from .errors import UpdaterError

logger = logging.getLogger(__name__)

ENV_UPDATER_EXE = "IDM_UPDATER_EXE"
UPDATER_EXE_NAME = "IDM_Updater.exe"

_DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
_CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
_STALE_UPDATE_AGE = 24 * 60 * 60


@dataclass(frozen=True)
class InstallRequest:
    installer: Path
    sha256: str
    publisher: str
    target_version: str
    update_dir: Path
    restart: bool
    manifest: object | None = None


def updater_executable() -> Path | None:
    override = os.environ.get(ENV_UPDATER_EXE, "").strip()
    if override:
        candidate = Path(override)
        return candidate if candidate.is_file() else None

    if not getattr(sys, "frozen", False):
        return None

    candidate = Path(sys.executable).with_name(UPDATER_EXE_NAME)
    return candidate if candidate.is_file() else None


def create_update_directory(base: Path | None = None) -> Path:
    root = Path(base) if base is not None else None
    if root is not None:
        root.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="IDM-Update-", dir=str(root) if root else None))
    logger.info("Created temporary update directory %s", directory)
    return directory


def cleanup_stale_update_directories(max_age_seconds: int = _STALE_UPDATE_AGE) -> int:
    """Remove abandoned update downloads.

    Directories marked as completed by the updater are removed immediately;
    everything else is kept until it is older than ``max_age_seconds``.
    """
    temp_root = Path(tempfile.gettempdir())
    removed = 0
    now = time.time()
    try:
        entries = list(temp_root.glob("IDM-Update-*"))
    except OSError:
        return 0
    for entry in entries:
        try:
            if not entry.is_dir() or entry.is_symlink():
                continue
            if (
                not has_completion_marker(entry)
                and now - entry.stat().st_mtime < max_age_seconds
            ):
                continue
        except OSError:
            continue
        if safe_remove_update_dir(entry):
            removed += 1
    if removed:
        logger.info("Removed %d stale update director(ies)", removed)
    return removed


def build_handoff(
    request: InstallRequest, app_exe: Path, log_file: Path
) -> UpdateHandoff:
    return UpdateHandoff(
        installer=Path(request.installer),
        sha256=request.sha256,
        publisher=request.publisher,
        parent_pid=os.getpid(),
        app_exe=Path(app_exe),
        target_version=request.target_version,
        restart=bool(request.restart),
        update_dir=Path(request.update_dir),
        log_file=Path(log_file),
    )


def launch_updater(updater: Path, handoff_path: Path) -> int:
    updater = Path(updater)
    if not updater.is_file():
        raise UpdaterError(
            "The IDM Updater component is missing from this installation. "
            "Reinstall IDM to repair the update system."
        )
    flags = 0
    if sys.platform == "win32":
        flags = _DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP
    try:
        process = subprocess.Popen(
            [str(updater), "--handoff", str(handoff_path)],
            cwd=str(updater.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=flags,
        )
    except OSError as exc:
        raise UpdaterError(f"The updater could not be started: {exc}") from exc
    logger.info("Started updater process %s", process.pid)
    return process.pid


def launch_rollback(updater: Path, plan_path: Path) -> int:
    """Start the updater in rollback mode; it waits for this process to exit."""
    updater = Path(updater)
    if not updater.is_file():
        raise UpdaterError(
            "The IDM Updater component is missing from this installation. "
            "Reinstall IDM to repair the update system."
        )
    flags = 0
    if sys.platform == "win32":
        flags = _DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP
    try:
        process = subprocess.Popen(
            [str(updater), "--rollback", str(plan_path)],
            cwd=str(updater.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=flags,
        )
    except OSError as exc:
        raise UpdaterError(f"The updater could not be started: {exc}") from exc
    logger.info("Started rollback updater process %s", process.pid)
    return process.pid


def stage_updater(updater: Path, update_dir: Path) -> Path:
    """Copy the updater into the update folder so it can replace its own install."""
    source = Path(updater)
    if not source.is_file():
        raise UpdaterError(
            "The IDM Updater component is missing from this installation. "
            "Reinstall IDM to repair the update system."
        )
    target = Path(update_dir) / UPDATER_EXE_NAME
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
    except OSError as exc:
        raise UpdaterError(f"The updater could not be prepared: {exc}") from exc
    return target


def stage_and_launch(
    request: InstallRequest,
    updater: Path,
    app_exe: Path,
    log_file: Path,
) -> UpdateHandoff:
    handoff = build_handoff(request, app_exe, log_file)
    staged = stage_updater(updater, request.update_dir)
    handoff_path = Path(request.update_dir) / "update-handoff.json"
    write_handoff(handoff_path, handoff)
    launch_updater(staged, handoff_path)
    return handoff
