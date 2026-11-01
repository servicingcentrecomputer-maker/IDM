"""Windows registration of the IDM native messaging host.

Each Chromium-family browser reads the host manifest path from its own
``HKCU`` registry key.  Registration writes a browser-specific manifest
(``allowed_origins`` for Chrome/Edge, ``allowed_extensions`` for Firefox) and
then points the registry value at that file.  Unregistration only removes the
values and keys this module created; a key that contains anything else is left
untouched.

The module is intentionally Qt-free so it can run from the build scripts and
from a plain Python interpreter.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import NATIVE_HOST_NAME
from .browser_registry import (
    native_manifest,
    validate_native_manifest,
)
from .paths import manifest_file, native_manifest_dir

if os.name == "nt":  # pragma: no cover - exercised on Windows
    import winreg
else:  # pragma: no cover
    winreg = None  # type: ignore[assignment]

SUPPORTED_BROWSERS = ("chrome", "edge", "firefox")

_REGISTRY_ROOTS = {
    "chrome": r"Software\Google\Chrome\NativeMessagingHosts",
    "edge": r"Software\Microsoft\Edge\NativeMessagingHosts",
    "firefox": r"Software\Mozilla\NativeMessagingHosts",
}


class RegistrationError(RuntimeError):
    """Registration could not be completed safely."""


def _require_windows() -> None:
    if winreg is None:
        raise RegistrationError("Native messaging registration requires Windows.")


def registry_subkey(browser: str) -> str:
    try:
        root = _REGISTRY_ROOTS[browser]
    except KeyError as exc:
        raise RegistrationError(f"Unsupported browser: {browser}") from exc
    return f"{root}\\{NATIVE_HOST_NAME}"


def _registry_views() -> list[tuple[str, int]]:
    flags = getattr(winreg, "KEY_WOW64_64KEY", 0)
    views = [("64", flags)]
    fallback = getattr(winreg, "KEY_WOW64_32KEY", None)
    if fallback is not None:
        views.append(("32", fallback))
    return views


def read_registration(browser: str) -> dict[str, Any]:
    """Return the current registry value in both registry views."""
    _require_windows()
    subkey = registry_subkey(browser)
    values: dict[str, str | None] = {}
    errors: list[str] = []
    for label, flag in _registry_views():
        value: str | None = None
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                subkey,
                0,
                winreg.KEY_READ | flag,
            ) as key:
                try:
                    value, _ = winreg.QueryValueEx(key, "")
                except FileNotFoundError:
                    value = None
        except FileNotFoundError:
            value = None
        except OSError as exc:
            errors.append(f"{label}-bit view: {exc}")
        values[label] = value
    return {
        "browser": browser,
        "subkey": subkey,
        "values": values,
        "errors": errors,
    }


def _write_registry_value(subkey: str, value: str) -> list[str]:
    errors: list[str] = []
    for label, flag in _registry_views():
        try:
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                subkey,
                0,
                winreg.KEY_SET_VALUE | flag,
            ) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, value)
        except OSError as exc:
            errors.append(f"{label}-bit view: {exc}")
    return errors


def _same_path(first: str | Path, second: str | Path) -> bool:
    def normalized(value: str | Path) -> str:
        return os.path.normcase(os.path.abspath(os.fspath(value)))

    return normalized(first) == normalized(second)


def _remove_registry_value(
    subkey: str, expected: str | Path | Iterable[str | Path]
) -> list[str]:
    """Remove our value/key without disturbing a value owned by someone else."""
    targets = (
        [expected]
        if isinstance(expected, (str, Path))
        else [item for item in expected]
    )
    errors: list[str] = []
    for label, flag in _registry_views():
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                subkey,
                0,
                winreg.KEY_READ | winreg.KEY_SET_VALUE | flag,
            ) as key:
                try:
                    current, _ = winreg.QueryValueEx(key, "")
                except FileNotFoundError:
                    current = None
                if current is not None and not any(
                    _same_path(current, target) for target in targets
                ):
                    errors.append(
                        f"{label}-bit view points to a different manifest; left unchanged."
                    )
                    continue
                if current is not None:
                    winreg.DeleteValue(key, "")
                subkeys, values, _ = winreg.QueryInfoKey(key)
                empty = subkeys == 0 and values == 0
        except FileNotFoundError:
            continue
        except OSError as exc:
            errors.append(f"{label}-bit view: {exc}")
            continue
        if empty:
            try:
                winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, subkey, flag)
            except FileNotFoundError:
                pass
            except OSError as exc:
                errors.append(f"{label}-bit view key: {exc}")
    return errors


def installed_root() -> Path | None:
    """Folder that contains the frozen executable, or None when running from source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return None


def installed_manifest_file(browser: str) -> Path | None:
    """Manifest written by the installer, next to IDM.exe."""
    root = installed_root()
    if root is None:
        return None
    return root / "browser-integration" / f"{NATIVE_HOST_NAME}.{browser}.json"


def manifest_candidates(browser: str) -> list[Path]:
    """Every location IDM may have registered for this browser."""
    paths = [manifest_file(browser)]
    installed = installed_manifest_file(browser)
    if installed is not None and not any(_same_path(installed, path) for path in paths):
        paths.append(installed)
    return paths


def extension_dir() -> Path:
    """Folder holding the unpacked IDM Video Assistant extension."""
    root = installed_root()
    if root is not None:
        return root / "BrowserExtension" / "IDMVideoAssistant"
    return project_root() / "BrowserExtension" / "IDMVideoAssistant"


def write_manifest(
    browser: str,
    host_path: str | Path,
    environ: Mapping[str, str] | None = None,
) -> Path:
    _require_windows()
    manifest = native_manifest(browser, host_path, environ)
    problems = validate_native_manifest(manifest, browser, host_path)
    if problems:
        raise RegistrationError(
            "The native messaging manifest is invalid: " + " ".join(problems)
        )
    path = manifest_file(browser)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)
    return path


def install_browser(
    browser: str,
    host_path: str | Path,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Write the manifest and registry value for one browser."""
    _require_windows()
    resolved = Path(host_path)
    if not resolved.is_absolute():
        raise RegistrationError("The native host path must be absolute.")
    if not resolved.is_file():
        raise RegistrationError(f"The native host executable was not found: {resolved}")

    # Reuse a manifest the installer already wrote (custom install folders,
    # Program Files) before creating a second copy in AppData.
    path: Path | None = None
    for candidate in manifest_candidates(browser):
        if not candidate.is_file():
            continue
        try:
            manifest = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not validate_native_manifest(manifest, browser, resolved):
            path = candidate
            break
    if path is None:
        path = write_manifest(browser, resolved, environ)
    errors = _write_registry_value(registry_subkey(browser), str(path))
    read_back = read_registration(browser)
    registered_views = [
        label
        for label, value in read_back["values"].items()
        if value and _same_path(value, path)
    ]
    if not registered_views:
        raise RegistrationError(
            "The native messaging registry value could not be written: "
            + "; ".join(errors or read_back["errors"] or ["unknown error"])
        )
    result = {
        "browser": browser,
        "ok": True,
        "manifest": str(path),
        "host": str(resolved),
        "registered_views": registered_views,
    }
    if errors:
        result["warnings"] = errors
    return result


def uninstall_browser(browser: str) -> dict[str, Any]:
    """Remove our registration and manifest for one browser."""
    _require_windows()
    path = manifest_file(browser)
    paths = manifest_candidates(browser)
    errors = _remove_registry_value(registry_subkey(browser), paths)
    still_referenced = any(
        value and any(_same_path(value, candidate) for candidate in paths)
        for value in read_registration(browser)["values"].values()
    )
    removed_manifest = False
    if not still_referenced and path.is_file():
        try:
            path.unlink()
            removed_manifest = True
        except OSError as exc:
            errors.append(f"manifest: {exc}")
    return {
        "browser": browser,
        "ok": not errors,
        "manifest": str(path),
        "removed_manifest": removed_manifest,
        "warnings": errors,
    }


def browser_status(browser: str) -> dict[str, Any]:
    _require_windows()
    paths = manifest_candidates(browser)
    existing = [candidate for candidate in paths if candidate.is_file()]
    path = existing[0] if existing else paths[0]
    registry = read_registration(browser)
    manifest: dict[str, Any] | None = None
    problems: list[str] = []

    # Prefer a manifest that actually validates, so a stale copy in AppData
    # cannot hide a working installer registration.
    for candidate in existing:
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        host_value = data.get("path")
        host_path = Path(host_value) if isinstance(host_value, str) else None
        if not validate_native_manifest(data, browser, host_path):
            path = candidate
            manifest = data
            break
    if manifest is None and path.is_file():
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append(f"The manifest cannot be read: {exc}")
    if manifest is None and not path.is_file():
        problems.append("The native messaging manifest does not exist.")

    host: Path | None = None
    if isinstance(manifest, dict):
        candidate = manifest.get("path")
        if isinstance(candidate, str) and candidate:
            host = Path(candidate)
        problems.extend(validate_native_manifest(manifest, browser, host))

    registered_views = [
        label
        for label, value in registry["values"].items()
        if value and any(_same_path(value, candidate) for candidate in paths)
    ]
    other_views = [
        label
        for label, value in registry["values"].items()
        if value and not any(_same_path(value, candidate) for candidate in paths)
    ]
    if not registered_views:
        problems.append("The registry does not point at IDM's manifest.")
    if host is not None and not host.is_file():
        problems.append(f"The native host executable is missing: {host}")
    return {
        "browser": browser,
        "installed": bool(registered_views) and not problems,
        "manifest": str(path),
        "manifest_exists": path.is_file(),
        "host": str(host) if host else "",
        "registered_views": registered_views,
        "conflicting_views": other_views,
        "problems": problems,
        "registry": registry,
    }


def install(
    browsers: Iterable[str],
    host_path: str | Path,
    environ: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    results = []
    for browser in browsers:
        results.append(install_browser(browser, host_path, environ))
    return results


def uninstall(browsers: Iterable[str]) -> list[dict[str, Any]]:
    return [uninstall_browser(browser) for browser in browsers]


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_host_paths(root: Path | None = None) -> list[Path]:
    root = root or project_root()
    candidates: list[Path] = []
    installed = installed_root()
    if installed is not None:
        candidates.append(installed / "IDM_NativeHost.exe")
    candidates.extend(
        [
            root / "dist" / "IDM" / "IDM_NativeHost.exe",
            root / "dist" / "IDM_NativeHost.exe",
        ]
    )
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Programs" / "IDM" / "IDM_NativeHost.exe")
    return candidates


def find_host_path(root: Path | None = None) -> Path | None:
    for candidate in default_host_paths(root):
        if candidate.is_file():
            return candidate
    return None


def create_dev_launcher(
    root: Path | None = None, python: str | None = None
) -> Path:
    """Create a batch launcher for running the host from source.

    This is a development convenience only; the built ``IDM_NativeHost.exe``
    is used by the installer and should be preferred.
    """
    root = root or project_root()
    script = root / "integrations" / "native_host.py"
    if not script.is_file():
        raise RegistrationError(f"The native host script was not found: {script}")
    executable = Path(python or sys.executable)
    windowless = executable.with_name("pythonw.exe")
    if windowless.is_file():
        executable = windowless
    launcher = native_manifest_dir() / f"{NATIVE_HOST_NAME}.cmd"
    launcher.write_text(
        "@echo off\r\n"
        'setlocal\r\n'
        f'"{executable}" "{script}"\r\n',
        encoding="utf-8",
        newline="",
    )
    return launcher


__all__ = [
    "RegistrationError",
    "SUPPORTED_BROWSERS",
    "browser_status",
    "create_dev_launcher",
    "default_host_paths",
    "find_host_path",
    "install",
    "install_browser",
    "read_registration",
    "registry_subkey",
    "uninstall",
    "uninstall_browser",
    "write_manifest",
]
