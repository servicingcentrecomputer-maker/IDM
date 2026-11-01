"""Validate and package the IDM Video Assistant as a plain unpacked ZIP.

The project deliberately does not produce a CRX.  The archive keeps
``manifest.json`` at its root so the contents can be extracted and loaded with
Chrome's or Edge's "Load unpacked" action.

Usage::

    python scripts/package_video_assistant.py
    python scripts/package_video_assistant.py --output-dir dist-extensions
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from integrations.browser_registry import CHROME_EXTENSION_ID  # noqa: E402
from scripts.package_extensions import extension_id_from_key  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "BrowserExtension" / "IDMVideoAssistant"
REQUIRED_FILES = (
    "manifest.json",
    "background.js",
    "content.js",
    "media-detector.js",
    "native-messaging.js",
    "popup.html",
    "popup.css",
    "popup.js",
    "README.md",
    "InstallationGuide.md",
    "icons/icon16.png",
    "icons/icon32.png",
    "icons/icon48.png",
    "icons/icon128.png",
)
EXPECTED_PERMISSIONS = [
    "nativeMessaging",
    "downloads",
    "contextMenus",
    "storage",
    "activeTab",
]
FORBIDDEN_SUFFIXES = {".crx", ".pem", ".key", ".p12", ".pfx"}
ZIP_TIMESTAMP = (2026, 1, 1, 0, 0, 0)


class PackagingError(RuntimeError):
    pass


def validate_extension(folder: Path = EXTENSION) -> dict:
    """Check the unpacked folder and return its validated manifest."""
    folder = Path(folder)
    if not folder.is_dir():
        raise PackagingError(f"Missing extension directory: {folder}")

    for relative in REQUIRED_FILES:
        path = folder / relative
        if not path.is_file():
            raise PackagingError(f"Missing {relative}")
        if path.stat().st_size == 0:
            raise PackagingError(f"{relative} is empty")

    for path in folder.rglob("*"):
        if path.is_file() and path.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise PackagingError(f"Private or signed key material is not allowed: {path.name}")

    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PackagingError(f"manifest.json is invalid: {exc}") from exc

    if manifest.get("manifest_version") != 3:
        raise PackagingError("manifest_version must be 3.")
    if manifest.get("name") != "IDM Video Assistant":
        raise PackagingError("Unexpected extension name.")
    version = str(manifest.get("version", ""))
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise PackagingError("version must be MAJOR.MINOR.PATCH.")
    if manifest.get("background") != {"service_worker": "background.js"}:
        raise PackagingError("background.service_worker must be background.js.")
    if manifest.get("action", {}).get("default_popup") != "popup.html":
        raise PackagingError("action.default_popup must be popup.html.")
    if "host_permissions" in manifest:
        raise PackagingError("host_permissions are not part of the minimum permission set.")

    key = manifest.get("key")
    if not isinstance(key, str) or not key:
        raise PackagingError("The manifest must pin the extension key.")
    derived = extension_id_from_key(key)
    if derived != CHROME_EXTENSION_ID:
        raise PackagingError(
            f"The embedded key derives ID {derived}, expected {CHROME_EXTENSION_ID}."
        )

    if manifest.get("permissions") != EXPECTED_PERMISSIONS:
        raise PackagingError(
            "The permission list must stay exactly: " + ", ".join(EXPECTED_PERMISSIONS)
        )

    scripts = manifest.get("content_scripts")
    if not isinstance(scripts, list) or len(scripts) != 1:
        raise PackagingError("Exactly one content_scripts entry is expected.")
    entry = scripts[0]
    if set(entry.get("matches", [])) != {"http://*/*", "https://*/*"}:
        raise PackagingError("Content scripts must match only http and https pages.")
    if entry.get("js") != ["media-detector.js", "content.js"]:
        raise PackagingError("Content script order must be media-detector.js, content.js.")
    if entry.get("all_frames") is not True:
        raise PackagingError("Content scripts must run in all frames.")

    icons = manifest.get("icons")
    if not isinstance(icons, dict) or set(icons) != {"16", "32", "48", "128"}:
        raise PackagingError("The manifest must reference all four icon sizes.")

    return {"folder": folder, "manifest": manifest, "version": version}


def iter_files(folder: Path) -> list[Path]:
    files = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            continue
        if path.name in {".DS_Store", "Thumbs.db"}:
            continue
        files.append(path)
    return files


def build_package(info: dict, output_dir: Path) -> dict:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"IDM_Video_Assistant_{info['version']}.zip"
    files = iter_files(info["folder"])
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for path in files:
            relative = path.relative_to(info["folder"]).as_posix()
            entry = zipfile.ZipInfo(relative, date_time=ZIP_TIMESTAMP)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            package.writestr(entry, path.read_bytes())
    return {
        "archive": archive,
        "bytes": archive.stat().st_size,
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "files": len(files),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "dist-extensions"),
        help="Directory for the ZIP package (default: dist-extensions).",
    )
    args = parser.parse_args(argv)

    try:
        info = validate_extension()
        result = build_package(info, Path(args.output_dir))
    except PackagingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    size_kb = result["bytes"] / 1024
    print(
        f"{result['archive'].name}: {size_kb:.1f} KB, "
        f"{result['files']} files, SHA256 {result['sha256']}"
    )
    print(f"Unpacked source: {info['folder']}")
    print("No CRX was produced. Extract the ZIP and use Load unpacked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
