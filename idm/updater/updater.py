"""Standalone updater process.

Responsibilities:

* validate the handoff written by IDM
* re-verify the installer's SHA-256 and, when configured, Authenticode signature
* wait for IDM to close
* run the Inno Setup installer (UAC is left to Windows)
* restart IDM when requested
* remove only its own temporary update directory
* restore the previous version (``--rollback``) from a verified installer or
  a binary snapshot, together with the pre-update database backup

The updater never executes scripts or commands supplied by the update server.
User files inside the download folder are never deleted.
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ..core.paths import database_file
from .backup import restore_database
from .errors import RollbackError, SignatureVerificationError, UpdaterError
from .handoff import (
    UpdateHandoff,
    read_handoff,
    safe_remove_update_dir,
    write_completion_marker,
)
from .package_verifier import SignatureRunner, verify_installer
from .rollback import (
    RollbackPlan,
    clear_rollback_plan,
    read_rollback_plan,
    restore_binary_snapshot,
)
from .state import (
    InstallResult,
    clear_pending_update,
    record_event,
    write_install_result,
)

logger = logging.getLogger("idm.updater")

_WAIT_TIMEOUT_SECONDS = 180
_SYNCHRONIZE = 0x00100000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_WAIT_OBJECT_0 = 0x00000000
_WAIT_TIMEOUT = 0x00000102
_ERROR_INVALID_PARAMETER = 87
_ERROR_ACCESS_DENIED = 5

_DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="IDM_Updater")
    parser.add_argument("--handoff", help="Path to update-handoff.json")
    parser.add_argument("--rollback", help="Path to a rollback plan JSON file")
    parser.add_argument("--version", action="store_true", help="Print updater version")
    args = parser.parse_args(argv)

    if args.version:
        from ..version import CURRENT_VERSION

        print(CURRENT_VERSION)
        return 0

    if args.rollback:
        try:
            plan = read_rollback_plan(Path(args.rollback))
        except RollbackError as exc:
            _configure_logging(_fallback_log_file())
            logger.error("Invalid rollback plan: %s", exc)
            _notify("IDM Update", f"The previous version could not be restored.\n\n{exc}", error=True)
            return 2
        _configure_logging(Path(plan.log_file) if plan.log_file else _fallback_log_file())
        try:
            return run_rollback(plan)
        except Exception as exc:
            logger.exception("Unexpected rollback failure")
            _notify(
                "IDM Update",
                "The previous version could not be restored. Your user data "
                f"backup is intact.\n\n{exc}\n\nSee the updater log for details.",
                error=True,
            )
            return 1

    if not args.handoff:
        parser.error("--handoff or --rollback is required unless --version is used")

    try:
        handoff = read_handoff(Path(args.handoff))
    except UpdaterError as exc:
        _configure_logging(_fallback_log_file())
        logger.error("Invalid update handoff: %s", exc)
        _notify("IDM Update", f"The update could not be started.\n\n{exc}", error=True)
        return 2

    _configure_logging(handoff.log_file)
    logger.info(
        "Updater started for IDM %s (parent pid %s)",
        handoff.target_version,
        handoff.parent_pid,
    )
    try:
        return run_update(handoff)
    except Exception as exc:  # last-resort guard for a windowed process
        logger.exception("Unexpected updater failure")
        _notify(
            "IDM Update",
            "The update failed unexpectedly. IDM was not modified.\n\n"
            f"{exc}\n\nSee the updater log for details.",
            error=True,
        )
        return 1


def run_update(
    handoff: UpdateHandoff,
    *,
    signature_runner: SignatureRunner | None = None,
    wait_for_parent=None,
    installer_runner=None,
    restart_app=None,
    cleanup=None,
    notify=None,
    result_writer=None,
) -> int:
    wait = wait_for_parent or _wait_for_process
    run_installer = installer_runner or _run_installer
    restart = restart_app or _restart_app
    remove_directory = cleanup or safe_remove_update_dir
    message = notify or _notify
    record_result = result_writer or _write_install_result

    def safe_record_result(exit_code: int) -> None:
        try:
            record_result(handoff, exit_code)
        except Exception:
            logger.warning("Could not record the installer result", exc_info=True)

    logger.info("Waiting for IDM to close")
    if not wait(handoff.parent_pid, handoff.app_exe, _WAIT_TIMEOUT_SECONDS):
        logger.error("IDM did not close; the installer was not launched")
        safe_record_result(3)
        message(
            "IDM Update",
            "IDM did not close, so the update was not installed. "
            "Close IDM and try again from Help → Check for Updates.",
            error=True,
        )
        return 3

    try:
        verified = verify_installer(
            handoff.installer,
            handoff.sha256,
            handoff.publisher,
            signature_runner=signature_runner,
        )
    except SignatureVerificationError as exc:
        logger.error("Package verification failed: %s", exc)
        safe_record_result(4)
        message(
            "IDM Update",
            "The update package failed security verification and was not "
            f"installed.\n\n{exc}",
            error=True,
        )
        return 4

    logger.info(
        "Installer verified (%s bytes, %s)",
        verified.size,
        f"publisher {verified.publisher}"
        if verified.publisher
        else "SHA-256 only",
    )
    args = installer_arguments(
        handoff.app_exe, handoff.update_dir / "installer-install.log"
    )
    command = [str(handoff.installer), *args]
    logger.info("Launching installer (scope=%s)", "machine" if "/ALLUSERS" in args else "user")
    exit_code = run_installer(command)
    logger.info("Installer exited with code %s", exit_code)
    safe_record_result(exit_code)

    if exit_code == 0:
        removed = remove_directory(handoff.update_dir)
        if not removed and Path(handoff.update_dir).is_dir():
            # The updater's own executable is still locked.  The restarted
            # application removes this marked directory on its next start.
            write_completion_marker(handoff.update_dir, handoff.target_version)
        logger.info("Update installed; update directory removed=%s", removed)
        if handoff.restart:
            restart(handoff.app_exe)
        else:
            message(
                "IDM Update",
                f"IDM was updated to version {handoff.target_version}.\n\n"
                "Start IDM from the Start menu when you are ready.",
                error=False,
            )
        return 0

    detail = _installer_error_text(exit_code)
    logger.error("Installation failed: %s", detail)
    message(
        "IDM Update",
        "The update was not installed.\n\n"
        f"{detail}\n\nYour existing IDM installation and user data are intact.",
        error=True,
    )
    if handoff.restart:
        restart(handoff.app_exe)
    return 5


def run_rollback(
    plan: RollbackPlan,
    *,
    signature_runner: SignatureRunner | None = None,
    wait_for_parent=None,
    installer_runner=None,
    snapshot_restore=None,
    restart_app=None,
    notify=None,
) -> int:
    """Restore the previous binaries and the pre-update database."""
    wait = wait_for_parent or _wait_for_process
    run_installer = installer_runner or _run_installer
    restore_snapshot = snapshot_restore or restore_binary_snapshot
    restart = restart_app or _restart_app
    message = notify or _notify

    app_exe = Path(plan.app_exe)
    logger.info(
        "Rollback requested from %s to %s", plan.target_version, plan.from_version
    )
    if plan.parent_pid and not wait(plan.parent_pid, app_exe, _WAIT_TIMEOUT_SECONDS):
        logger.error("IDM did not close; rollback was not started")
        message(
            "IDM Update",
            "IDM did not close, so the previous version was not restored. "
            "Close IDM and try again.",
            error=True,
        )
        return 3

    log_path = Path(plan.log_file) if plan.log_file else _fallback_log_file()
    if plan.previous_installer:
        installer = Path(plan.previous_installer)
        try:
            verified = verify_installer(
                installer,
                plan.previous_installer_sha256,
                plan.previous_publisher,
                signature_runner=signature_runner,
            )
        except SignatureVerificationError as exc:
            logger.error("Rollback package verification failed: %s", exc)
            message(
                "IDM Update",
                "The previous installer failed security verification, so "
                f"nothing was restored.\n\n{exc}",
                error=True,
            )
            return 4
        logger.info(
            "Rollback installer verified (%s bytes, %s)",
            verified.size,
            f"publisher {verified.publisher}"
            if verified.publisher
            else "SHA-256 only",
        )
        command = [
            str(installer),
            *installer_arguments(app_exe, log_path.with_name("rollback-install.log")),
        ]
        exit_code = run_installer(command)
        logger.info("Rollback installer exited with code %s", exit_code)
        if exit_code != 0:
            logger.error("Rollback installer failed: %s", _installer_error_text(exit_code))
            message(
                "IDM Update",
                "The previous version could not be installed.\n\n"
                f"{_installer_error_text(exit_code)}\n\nYour user data is intact.",
                error=True,
            )
            return 5
    elif plan.binary_snapshot:
        try:
            restore_snapshot(Path(plan.binary_snapshot), app_exe.parent)
        except Exception as exc:
            logger.exception("Binary rollback failed")
            message(
                "IDM Update",
                f"The previous application files could not be restored.\n\n{exc}",
                error=True,
            )
            return 6
    else:
        logger.error("The rollback plan has no restore source")
        message(
            "IDM Update",
            "No previous version is available to restore.",
            error=True,
        )
        return 7

    try:
        restore_database(Path(plan.backup_dir), database_file())
    except Exception as exc:
        logger.exception("Database rollback failed")
        message(
            "IDM Update",
            "The previous application files were restored, but the database "
            f"backup could not be restored.\n\n{exc}",
            error=True,
        )
        return 8

    record_event(
        "rollback",
        from_version=plan.target_version,
        target_version=plan.from_version,
        message="The previous version and database backup were restored.",
        backup_dir=plan.backup_dir,
    )
    clear_pending_update()
    clear_rollback_plan()
    logger.info("Rollback to %s completed", plan.from_version)

    if plan.restart:
        restart(app_exe)
    else:
        message(
            "IDM Update",
            f"IDM {plan.from_version} was restored. Start IDM when you are ready.",
            error=False,
        )
    return 0


def installer_arguments(app_exe: Path, log_file: Path) -> list[str]:
    arguments = [
        "/SILENT",
        "/SP-",
        "/NORESTART",
        "/CLOSEAPPLICATIONS",
        f"/LOG={log_file}",
    ]
    if machine_wide_install(app_exe):
        arguments.insert(0, "/ALLUSERS")
    return arguments


def machine_wide_install(app_exe: Path) -> bool:
    try:
        resolved = Path(app_exe).resolve()
    except OSError:
        return False
    for variable in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(variable)
        if not root:
            continue
        try:
            resolved.relative_to(Path(root).resolve())
            return True
        except (ValueError, OSError):
            continue
    return False


def _write_install_result(handoff: UpdateHandoff, exit_code: int) -> None:
    write_install_result(
        InstallResult(
            target_version=handoff.target_version,
            success=exit_code == 0,
            exit_code=int(exit_code),
            reinstall=bool(handoff.reinstall),
            completed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
    )


def _installer_error_text(exit_code: int) -> str:
    if exit_code in {1223, 1602}:
        return "The installation was cancelled."
    if exit_code == 5:
        return "The installation was cancelled."
    return (
        f"The installer returned error code {exit_code}. You can retry from "
        "Help → Check for Updates after restarting IDM."
    )


def _run_installer(command: list[str]) -> int:
    try:
        result = subprocess.run(command, check=False)
    except OSError as exc:
        logger.error("Could not start the installer: %s", exc)
        return 1
    return int(result.returncode)


def _restart_app(app_exe: Path) -> None:
    app_exe = Path(app_exe)
    if not app_exe.is_file():
        logger.error("Cannot restart IDM: %s is missing", app_exe)
        _notify(
            "IDM Update",
            "The update was installed, but IDM could not be restarted "
            "automatically. Start it from the Start menu.",
            error=True,
        )
        return
    flags = _DETACHED_PROCESS if sys.platform == "win32" else 0
    try:
        subprocess.Popen(
            [str(app_exe)],
            cwd=str(app_exe.parent),
            close_fds=True,
            creationflags=flags,
        )
    except OSError as exc:
        logger.error("Could not restart IDM: %s", exc)
        _notify(
            "IDM Update",
            "The update was installed, but IDM could not be restarted "
            f"automatically.\n\n{exc}",
            error=True,
        )


def _wait_for_process(
    process_id: int, app_exe: Path, timeout_seconds: int
) -> bool:
    """Wait until the given IDM process exits without killing it."""
    if sys.platform != "win32":
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel32.WaitForSingleObject.restype = ctypes.c_ulong
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    kernel32.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    kernel32.QueryFullProcessImageNameW.restype = ctypes.c_int

    handle = kernel32.OpenProcess(
        _SYNCHRONIZE | _PROCESS_QUERY_LIMITED_INFORMATION,
        0,
        int(process_id),
    )
    if not handle:
        error = ctypes.get_last_error()
        if error == _ERROR_INVALID_PARAMETER:
            # The process has already exited.
            return True
        if error == _ERROR_ACCESS_DENIED:
            logger.warning("Access to the IDM process was denied")
            return False
        logger.warning("OpenProcess failed with error %s", error)
        return False

    try:
        if not _same_image(kernel32, handle, app_exe):
            logger.info("The parent process ID was reused; IDM already exited")
            return True

        deadline = timeout_seconds * 10
        for _ in range(max(1, deadline)):
            result = kernel32.WaitForSingleObject(handle, 100)
            if result == _WAIT_OBJECT_0:
                return True
            if result != _WAIT_TIMEOUT:
                logger.warning("WaitForSingleObject returned %s", result)
                return False
        return False
    finally:
        kernel32.CloseHandle(handle)


def _same_image(kernel32, handle, app_exe: Path) -> bool:
    buffer = ctypes.create_unicode_buffer(4096)
    length = ctypes.c_ulong(len(buffer))
    if not kernel32.QueryFullProcessImageNameW(
        handle, 0, buffer, ctypes.byref(length)
    ):
        return True
    try:
        return os.path.normcase(buffer.value) == os.path.normcase(
            str(Path(app_exe).resolve())
        )
    except OSError:
        return True


def _notify(title: str, message: str, error: bool) -> None:
    logger.info("Updater notification: %s", message)
    if sys.platform != "win32":
        return
    try:
        icon = 0x10 if error else 0x40  # MB_ICONERROR / MB_ICONINFORMATION
        ctypes.windll.user32.MessageBoxW(None, message, title, icon | 0x00040000)
    except Exception:
        logger.debug("Could not display the updater message", exc_info=True)


def _configure_logging(log_file: Path) -> None:
    root = logging.getLogger()
    if getattr(root, "_idm_updater_configured", False):
        return
    try:
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_file, maxBytes=1024 * 1024, backupCount=2, encoding="utf-8"
        )
    except OSError:
        root.addHandler(logging.NullHandler())
        root._idm_updater_configured = True  # type: ignore[attr-defined]
        return
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    )
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if sys.stderr is not None:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(handler.formatter)
        root.addHandler(console)
    root._idm_updater_configured = True  # type: ignore[attr-defined]


def _fallback_log_file() -> Path:
    roaming = os.environ.get("APPDATA")
    if roaming:
        return Path(roaming) / "IDM Download Manager" / "logs" / "updater.log"
    return Path.home() / ".idm-download-manager" / "logs" / "updater.log"


if __name__ == "__main__":  # pragma: no cover - exercised by the executable
    raise SystemExit(main())
