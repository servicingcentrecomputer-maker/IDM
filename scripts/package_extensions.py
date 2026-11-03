"""Validate the browser extensions and build store-ready ZIP packages.

Outputs (in ``dist-extensions`` by default)::

    IDM_Chrome_Extension.zip
    IDM_Edge_Extension.zip
    IDM_Firefox_Extension.zip

The ZIP root contains ``manifest.json`` directly, which is what the Chrome Web
Store, Microsoft Edge Add-ons and Mozilla Add-ons expect.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import zipfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from integrations.browser_registry import (  # noqa: E402
    CHROME_EXTENSION_ID,
    CHROME_EXTENSION_KEY,
    FIREFOX_EXTENSION_ID,
)

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = {
    "chrome": "IDM_Chrome_Extension.zip",
    "edge": "IDM_Edge_Extension.zip",
    "firefox": "IDM_Firefox_Extension.zip",
}
REQUIRED_FILES = (
    "manifest.json",
    "background.js",
    "popup.html",
    "popup.js",
    "popup.css",
)
REQUIRED_ICONS = tuple(f"icons/icon{size}.png" for size in (16, 32, 48, 128))
ZIP_TIMESTAMP = (2026, 1, 1, 0, 0, 0)


class PackagingError(RuntimeError):
    pass


def extension_id_from_key(key: str) -> str:
    der = base64.b64decode(key)
    digest = hashlib.sha256(der).hexdigest()[:32]
    return "".join(chr(ord("a") + int(char, 16)) for char in digest)


def validate_extension(browser: str) -> dict:
    folder = ROOT / "extensions" / browser
    if not folder.is_dir():
        raise PackagingError(f"Missing extension directory: {folder}")

    for relative in (*REQUIRED_FILES, *REQUIRED_ICONS):
        path = folder / relative
        if not path.is_file():
            raise PackagingError(f"{browser}: missing {relative}")
        if path.stat().st_size == 0:
            raise PackagingError(f"{browser}: {relative} is empty")

    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PackagingError(f"{browser}: manifest.json is invalid: {exc}") from exc

    if manifest.get("name") in (None, ""):
        raise PackagingError(f"{browser}: manifest has no name.")
    if not str(manifest.get("version", "")).count(".") == 2:
        raise PackagingError(f"{browser}: manifest version must be MAJOR.MINOR.PATCH.")

    background = (folder / "background.js").read_text(encoding="utf-8")
    if browser == "firefox":
        expected_constant = 'const BROWSER = "firefox";'
        if expected_constant not in background:
            raise PackagingError(
                f"{browser}: background.js must declare {expected_constant}"
            )
    else:
        # The MV3 folder is also loaded in Brave and Opera, which the native host
        # distinguishes by the browser each request claims.
        if "const BROWSER = detectBrowser();" not in background:
            raise PackagingError(
                f"{browser}: background.js must resolve BROWSER with detectBrowser()."
            )
        if f'return "{browser}";' not in background:
            raise PackagingError(
                f"{browser}: detectBrowser() must fall back to \"{browser}\"."
            )

    if browser in {"chrome", "edge"}:
        if manifest.get("manifest_version") != 3:
            raise PackagingError(f"{browser}: manifest_version must be 3.")
        key = manifest.get("key")
        if not isinstance(key, str) or not key:
            raise PackagingError(f"{browser}: the manifest must pin the extension key.")
        derived = extension_id_from_key(key)
        if derived != CHROME_EXTENSION_ID:
            raise PackagingError(
                f"{browser}: the embedded key derives ID {derived}, "
                f"expected {CHROME_EXTENSION_ID}."
            )
        worker = manifest.get("background", {}).get("service_worker")
        if worker != "background.js":
            raise PackagingError(f"{browser}: background.service_worker must be background.js.")
        permissions = manifest.get("permissions", [])
    else:
        if manifest.get("manifest_version") != 2:
            raise PackagingError("firefox: manifest_version must be 2 for MV2.")
        gecko = manifest.get("browser_specific_settings", {}).get("gecko", {})
        if gecko.get("id") != FIREFOX_EXTENSION_ID:
            raise PackagingError(
                f"firefox: browser_specific_settings.gecko.id must be "
                f"{FIREFOX_EXTENSION_ID}."
            )
        scripts = manifest.get("background", {}).get("scripts", [])
        if scripts != ["background.js"]:
            raise PackagingError("firefox: background.scripts must be [background.js].")
        permissions = manifest.get("permissions", [])

    required_permissions = {"nativeMessaging", "downloads", "storage"}
    missing = required_permissions - set(permissions)
    if missing:
        raise PackagingError(
            f"{browser}: missing permissions: {', '.join(sorted(missing))}"
        )
    if len(permissions) > 6:
        raise PackagingError(f"{browser}: permissions should stay minimal ({permissions}).")

    return {
        "browser": browser,
        "folder": folder,
        "manifest": manifest,
        "version": manifest["version"],
    }


def iter_files(folder: Path) -> list[Path]:
    files = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        files.append(path)
    return files


def build_package(info: dict, output_dir: Path) -> dict:
    browser = info["browser"]
    archive = output_dir / PACKAGES[browser]
    files = iter_files(info["folder"])
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for path in files:
            relative = path.relative_to(info["folder"]).as_posix()
            entry = zipfile.ZipInfo(relative, date_time=ZIP_TIMESTAMP)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            package.writestr(entry, path.read_bytes())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    return {
        "browser": browser,
        "archive": archive,
        "bytes": archive.stat().st_size,
        "sha256": digest,
        "files": len(files),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "dist-extensions"),
        help="Directory for the ZIP packages (default: dist-extensions).",
    )
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        infos = [validate_extension(browser) for browser in PACKAGES]
        results = [build_package(info, output_dir) for info in infos]
    except PackagingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for result in results:
        size_kb = result["bytes"] / 1024
        print(
            f"{result['archive'].name}: {size_kb:.1f} KB, "
            f"{result['files']} files, SHA256 {result['sha256']}"
        )
    print(f"Packages written to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
