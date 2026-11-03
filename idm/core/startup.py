"""Register IDM to start with the current Windows user.

Two mechanisms exist on a normal machine and both mean "start with Windows":

* the ``HKCU\\...\\Run`` value, which this module owns;
* a shortcut in the user's Startup folder, which the IDM installer's optional
  task creates.

The toggle has to reflect both, otherwise the setting would claim IDM is not
starting when it is, and turning it off would leave a shortcut that keeps
launching a second IDM window.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Callable

logger = logging.getLogger("idm.core.startup")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "IDM"

_STARTUP_GLOB = "IDM*.lnk"


def launch_command(executable: Path | None = None) -> str:
    """Return the command that starts IDM when Windows logs in.

    A packaged build starts itself. A source checkout starts the same
    interpreter on ``main.py`` so the setting is usable during development.
    """
    if executable is not None:
        return f'"{_resolve(executable)}"'
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'
    script = Path(__file__).resolve().parents[2] / "main.py"
    return f'"{Path(sys.executable).resolve()}" "{script}"'


def _resolve(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path


def _startup_folder() -> Path | None:
    override = os.environ.get("IDM_STARTUP_FOLDER")
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return (
        Path(appdata)
        / r"Microsoft\Windows\Start Menu\Programs\Startup"
    )


def _installer_shortcuts() -> list[Path]:
    folder = _startup_folder()
    if folder is None or not folder.is_dir():
        return []
    return sorted(folder.glob(_STARTUP_GLOB))


def _winreg():  # pragma: no cover - thin platform shim
    import winreg

    return winreg


def _read_run_value() -> str | None:
    try:
        winreg = _winreg()
    except ImportError:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _type = winreg.QueryValueEx(key, VALUE_NAME)
    except OSError:
        return None
    return value if isinstance(value, str) else None


def is_enabled(executable: Path | None = None) -> bool:
    """Report whether IDM is configured to start with Windows by any means."""
    command = launch_command(executable)
    recorded = _read_run_value()
    if recorded and _normalize(recorded) == _normalize(command):
        return True
    return bool(_installer_shortcuts())


def _normalize(value: str) -> str:
    return value.strip().strip('"').casefold().replace("\\\\", "\\")


def set_enabled(
    enabled: bool,
    executable: Path | None = None,
    on_error: Callable[[str], None] | None = None,
) -> bool:
    """Apply the start-with-Windows choice and return the resulting state.

    A failure is reported and never raised: the setting is convenient, not
    essential, and IDM must keep working when a policy denies the registry.
    """
    command = launch_command(executable)
    applied = False
    try:
        applied = _write_run_value(command) if enabled else _remove_run_value(command)
    except OSError as exc:
        message = f"Windows refused to change the start-up setting: {exc}"
        logger.warning("%s", message)
        if on_error is not None:
            on_error(message)
        return is_enabled(executable)

    if not enabled:
        _remove_installer_shortcuts(on_error)
    return is_enabled(executable)


def _write_run_value(command: str) -> bool:
    winreg = _winreg()
    existing = _read_run_value()
    if existing and _normalize(existing) != _normalize(command):
        raise OSError(
            f"{RUN_KEY}\\{VALUE_NAME} already points at another program: {existing}"
        )
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
    logger.info("Registered IDM to start with Windows: %s", command)
    return True


def _remove_run_value(command: str) -> bool:
    winreg = _winreg()
    existing = _read_run_value()
    if existing is None:
        return True
    if _normalize(existing) != _normalize(command):
        # Another program owns this value name; removing it would break that
        # program's start-up, which is not IDM's to undo.
        raise OSError(
            f"{RUN_KEY}\\{VALUE_NAME} points at another program: {existing}"
        )
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.DeleteValue(key, VALUE_NAME)
    logger.info("Removed the IDM start-up registry value")
    return True


def _remove_installer_shortcuts(
    on_error: Callable[[str], None] | None,
) -> None:
    """Delete the Startup-folder shortcut the installer may have left.

    Only files this product names, in the current user's own Startup folder.
    """
    for shortcut in _installer_shortcuts():
        try:
            shortcut.unlink()
            logger.info("Removed the start-up shortcut %s", shortcut.name)
        except OSError as exc:
            message = f"IDM could not remove {shortcut.name}: {exc}"
            logger.warning("%s", message)
            if on_error is not None:
                on_error(message)


__all__ = [
    "RUN_KEY",
    "VALUE_NAME",
    "is_enabled",
    "launch_command",
    "set_enabled",
]
