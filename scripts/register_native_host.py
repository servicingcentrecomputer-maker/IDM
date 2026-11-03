"""Register or inspect the IDM native messaging host (Windows).

Examples::

    python scripts/register_native_host.py install --dev
    python scripts/register_native_host.py install --host-path "C:\\Program Files\\IDM\\IDM_NativeHost.exe"
    python scripts/register_native_host.py install --installed
    python scripts/register_native_host.py status
    python scripts/register_native_host.py uninstall

The installer (installer\\IDM_Setup.iss) performs the same registration for a
normal installation.  This script is for development checkouts, manual
registration and verification.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from integrations.browser_detector import detect_installed_browsers  # noqa: E402
from integrations.registration import (  # noqa: E402
    SUPPORTED_BROWSERS,
    RegistrationError,
    browser_status,
    create_dev_launcher,
    find_host_path,
    install_browser,
    uninstall_browser,
)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Register the IDM native messaging host for Chrome, Edge, Firefox, "
            "Brave and Opera."
        )
    )
    parser.add_argument(
        "command", choices=("install", "uninstall", "status"), help="Action to perform."
    )
    parser.add_argument(
        "--browser",
        action="append",
        choices=SUPPORTED_BROWSERS,
        dest="browsers",
        help="Limit the action to one browser (repeatable). Default: all.",
    )
    parser.add_argument(
        "--installed",
        action="store_true",
        help="Only act on browsers detected on this computer.",
    )
    parser.add_argument(
        "--host-path",
        help="Absolute path to IDM_NativeHost.exe. Default: the built executable.",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help=(
            "Create a .cmd launcher for running integrations/native_host.py from "
            "this checkout. Development only; the packaged executable is preferred."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser.parse_args(argv)


def selected_browsers(args: argparse.Namespace) -> list[str]:
    browsers = list(args.browsers or SUPPORTED_BROWSERS)
    if args.installed:
        installed = set(detect_installed_browsers())
        browsers = [browser for browser in browsers if browser in installed]
    return browsers


def resolve_host(args: argparse.Namespace) -> Path:
    if args.host_path:
        path = Path(args.host_path).expanduser()
        if not path.is_absolute():
            raise RegistrationError("--host-path must be an absolute path.")
        if not path.is_file():
            raise RegistrationError(f"The host executable does not exist: {path}")
        return path
    if args.dev:
        return create_dev_launcher()
    found = find_host_path()
    if found is None:
        raise RegistrationError(
            "IDM_NativeHost.exe was not found. Build it first "
            "(powershell -NoProfile -ExecutionPolicy Bypass -File .\\build_windows.ps1 "
            "-SkipTests -SkipInstaller), pass --host-path, or use --dev."
        )
    return found


def print_result(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2))
        return
    browser = result.get("browser", "")
    if "installed" in result:
        state = "installed" if result["installed"] else "not registered"
        print(f"{browser:8} {state}")
        print(f"         manifest: {result.get('manifest', '')}")
        print(f"         host    : {result.get('host', '') or '(unknown)'}")
        if result.get("registered_views"):
            print(f"         registry: {', '.join(result['registered_views'])}-bit")
        for problem in result.get("problems", []):
            print(f"         ! {problem}")
        for warning in result.get("warnings", []):
            print(f"         ! {warning}")
        return
    print(f"{browser:8} {'ok' if result.get('ok') else 'failed'}")
    print(f"         manifest: {result.get('manifest', '')}")
    if result.get("host"):
        print(f"         host    : {result['host']}")
    if result.get("registered_views"):
        print(f"         registry: {', '.join(result['registered_views'])}-bit")
    for warning in result.get("warnings", []):
        print(f"         ! {warning}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    browsers = selected_browsers(args)
    if not browsers:
        print("No supported browsers were selected or detected.", file=sys.stderr)
        return 1

    try:
        if args.command == "install":
            host = resolve_host(args)
            if not args.json:
                print(f"Native host: {host}")
            results = []
            for browser in browsers:
                results.append(install_browser(browser, host))
            for result in results:
                print_result(result, args.json)
            return 0

        if args.command == "uninstall":
            results = []
            for browser in browsers:
                results.append(uninstall_browser(browser))
            for result in results:
                print_result(result, args.json)
            return 0 if all(result.get("ok") for result in results) else 1

        results = [browser_status(browser) for browser in browsers]
        for result in results:
            print_result(result, args.json)
        if args.json:
            return 0
        return 0 if all(result.get("installed") for result in results) else 1
    except RegistrationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
