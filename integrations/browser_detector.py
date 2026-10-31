"""Windows browser discovery without third-party dependencies.

Two questions are answered here:

* which browser launched the native host process (used for logging, download
  attribution and duplicate diagnostics);
* which supported browsers are installed (used by the registration script and
  the installer).

Process enumeration uses the Toolhelp snapshot API through :mod:`ctypes`.
Registry and filesystem probing is best effort: a failure to read one location
never prevents the others from being checked.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SUPPORTED_BROWSERS = ("chrome", "edge", "firefox")

_DISPLAY_NAMES = {
    "chrome": "Google Chrome",
    "edge": "Microsoft Edge",
    "firefox": "Mozilla Firefox",
}

_PROCESS_NAMES = {
    "chrome.exe": "chrome",
    "msedge.exe": "edge",
    "firefox.exe": "firefox",
}

_MAX_ANCESTOR_LEVELS = 8


def browser_display_name(browser: str) -> str:
    return _DISPLAY_NAMES.get(browser, browser.capitalize() if browser else "Unknown")


# ---------------------------------------------------------------------------
# Calling process
# ---------------------------------------------------------------------------


def _windows_process_table() -> dict[int, tuple[int, str]]:
    """Return ``pid -> (parent_pid, executable_name)`` using Toolhelp32."""
    if sys.platform != "win32":
        return {}
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.CreateToolhelp32Snapshot.argtypes = [
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        kernel32.Process32FirstW.restype = wintypes.BOOL
        kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        kernel32.Process32NextW.restype = wintypes.BOOL
        kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
        if not snapshot or snapshot == wintypes.HANDLE(-1).value:
            return {}
        table: dict[int, tuple[int, str]] = {}
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        try:
            present = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while present:
                table[int(entry.th32ProcessID)] = (
                    int(entry.th32ParentProcessID),
                    str(entry.szExeFile),
                )
                present = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
        return table
    except Exception:
        return {}


def detect_calling_browser() -> str:
    """Walk the parent chain and return chrome/edge/firefox, or an empty string."""
    if sys.platform != "win32":
        return ""
    table = _windows_process_table()
    if not table:
        return ""
    try:
        import ctypes

        pid = int(ctypes.windll.kernel32.GetCurrentProcessId())
    except Exception:
        return ""

    seen: set[int] = set()
    for _ in range(_MAX_ANCESTOR_LEVELS):
        if pid in seen or pid <= 0:
            break
        seen.add(pid)
        parent, name = table.get(pid, (0, ""))
        browser = _PROCESS_NAMES.get(name.lower())
        if browser:
            return browser
        pid = parent
    return ""


# ---------------------------------------------------------------------------
# Installed browsers
# ---------------------------------------------------------------------------


def _app_path(executable: str) -> str:
    if sys.platform != "win32":
        return ""
    try:
        import winreg
    except ImportError:
        return ""

    subkey = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{executable}"
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for access in (0, getattr(winreg, "KEY_WOW64_32KEY", 0)):
            try:
                with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ | access) as key:
                    value, _ = winreg.QueryValueEx(key, None)
                    path = str(value).strip().strip('"')
                    if path and Path(path).is_file():
                        return path
            except OSError:
                continue
    return ""


def _first_existing(candidates: list[str]) -> str:
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return ""


def detect_installed_browsers() -> dict[str, str]:
    """Return ``browser -> executable path`` for installed supported browsers."""
    if sys.platform != "win32":
        return {}

    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local_app_data = os.environ.get("LOCALAPPDATA", "")

    found: dict[str, str] = {}

    chrome = _app_path("chrome.exe") or _first_existing(
        [
            os.path.join(program_files, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(program_files_x86, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(local_app_data, r"Google\Chrome\Application\chrome.exe"),
        ]
    )
    if chrome:
        found["chrome"] = chrome

    edge = _app_path("msedge.exe") or _first_existing(
        [
            os.path.join(program_files_x86, r"Microsoft\Edge\Application\msedge.exe"),
            os.path.join(program_files, r"Microsoft\Edge\Application\msedge.exe"),
        ]
    )
    if edge:
        found["edge"] = edge

    firefox = _app_path("firefox.exe") or _first_existing(
        [
            os.path.join(program_files, r"Mozilla Firefox\firefox.exe"),
            os.path.join(program_files_x86, r"Mozilla Firefox\firefox.exe"),
        ]
    )
    if firefox:
        found["firefox"] = firefox

    return found


def is_browser_installed(browser: str) -> bool:
    return browser in detect_installed_browsers()


__all__ = [
    "SUPPORTED_BROWSERS",
    "browser_display_name",
    "detect_calling_browser",
    "detect_installed_browsers",
    "is_browser_installed",
]
