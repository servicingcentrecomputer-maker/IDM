"""Assemble a distributable Windows release package for IDM.

The package is built from the artifacts produced by ``build_windows.ps1``::

    dist-installer\\IDM_Setup.exe
    dist\\IDM\\                  (portable application)
    dist-extensions\\*.zip      (browser extension packages)

It validates that the application, installer and extension versions agree,
then writes a versioned directory and a deterministic ZIP::

    release\\IDM-<version>-win64\\
        IDM_Setup_<version>.exe
        portable\\IDM\\...
        browser-extensions\\...
        docs\\...
        README.txt
        RELEASE_NOTES.md
        VERSION.json
        SHA256SUMS.txt
    release\\IDM-<version>-win64.zip
    release\\IDM-<version>-win64.zip.sha256

Nothing outside ``release`` (and the generated extension ZIPs) is modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "release"
ZIP_TIMESTAMP = (2026, 1, 1, 0, 0, 0)

EXTENSION_PACKAGES = {
    "chrome": "IDM_Chrome_Extension.zip",
    "edge": "IDM_Edge_Extension.zip",
    "firefox": "IDM_Firefox_Extension.zip",
}

DOCUMENTS = {
    "README.md": "README.md",
    "PACKAGING.md": "PACKAGING.md",
    "docs/BROWSER_INTEGRATION.md": "BROWSER_INTEGRATION.md",
    "docs/BROWSER_STORE_PUBLISHING.md": "BROWSER_STORE_PUBLISHING.md",
    "docs/UPDATES.md": "UPDATES.md",
}

RUNTIME_SOURCE_DIRS = ("idm", "integrations", "downloads", "assets")
RUNTIME_SOURCE_FILES = (
    "main.py",
    "native_host_main.py",
    "updater_main.py",
    "config.py",
)


class ReleaseError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GiB"


def read_source_version(root: Path) -> str:
    source = (root / "idm" / "version.py").read_text(encoding="utf-8")
    match = re.search(r'CURRENT_VERSION\s*=\s*"([^"]+)"', source)
    if not match:
        raise ReleaseError("Could not read CURRENT_VERSION from idm/version.py.")
    return match.group(1)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReleaseError(message)


def validate_versions(root: Path, version: str) -> None:
    """Fail when the installer, resources or extensions disagree on the version."""
    require(
        re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", version) is not None,
        f"'{version}' is not a valid MAJOR.MINOR.PATCH version.",
    )
    numeric = ".".join(version.split("-", 1)[0].split(".")) + ".0"

    iss_path = root / "installer" / "IDM_Setup.iss"
    iss = iss_path.read_text(encoding="utf-8")
    require(
        f'#define MyAppVersion "{version}"' in iss,
        f"installer/IDM_Setup.iss does not declare MyAppVersion \"{version}\".",
    )
    require(
        f"VersionInfoVersion={numeric}" in iss,
        f"installer/IDM_Setup.iss does not declare VersionInfoVersion={numeric}.",
    )

    for info_name in (
        "version_info.txt",
        "version_info_updater.txt",
        "version_info_native_host.txt",
    ):
        info_path = root / info_name
        if not info_path.is_file():
            raise ReleaseError(f"Missing Windows version resource: {info_name}")
        values = set(
            re.findall(r"(?:filevers|prodvers)=\((\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)", info_path.read_text(encoding="utf-8"))
        )
        expected = tuple(version.split("-", 1)[0].split(".")) + ("0",)
        require(
            values == {expected},
            f"{info_name} version tuple does not match {version}.",
        )

    for browser in EXTENSION_PACKAGES:
        manifest_path = root / "extensions" / browser / "manifest.json"
        require(manifest_path.is_file(), f"Missing extension manifest: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        require(
            manifest.get("version") == version,
            f"extensions/{browser}/manifest.json version "
            f"{manifest.get('version')!r} does not match {version}.",
        )


def validate_extension_packages(src_dir: Path, version: str) -> list[dict]:
    results = []
    for browser, filename in EXTENSION_PACKAGES.items():
        archive = src_dir / filename
        require(archive.is_file(), f"Missing extension package: {archive}")
        try:
            with zipfile.ZipFile(archive) as package:
                manifest = json.loads(package.read("manifest.json"))
        except (KeyError, ValueError, zipfile.BadZipFile) as exc:
            raise ReleaseError(f"{filename} is not a valid extension package: {exc}") from exc
        require(
            manifest.get("version") == version,
            f"{filename} contains version {manifest.get('version')!r}, expected {version}. "
            "Run scripts/package_extensions.py after bumping the version.",
        )
        results.append(
            {
                "browser": browser,
                "file": filename,
                "version": manifest.get("version"),
                "bytes": archive.stat().st_size,
                "sha256": sha256_file(archive),
            }
        )
    return results


def iter_source_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(
                item
                for item in path.rglob("*")
                if item.is_file()
                and "__pycache__" not in item.parts
                and item.suffix not in {".pyc", ".pyo"}
            )
    return files


def newest_mtime(paths: list[Path]) -> float:
    files = iter_source_files(paths)
    return max((item.stat().st_mtime for item in files), default=0.0)


def age_warning(label: str, artifact: Path, source_mtime: float) -> str | None:
    if not artifact.exists() or not source_mtime:
        return None
    if artifact.stat().st_mtime + 1.0 < source_mtime:
        built = datetime.fromtimestamp(artifact.stat().st_mtime, timezone.utc)
        newest = datetime.fromtimestamp(source_mtime, timezone.utc)
        return (
            f"{label} was built at {built:%Y-%m-%d %H:%M UTC}, before the newest "
            f"source change at {newest:%Y-%m-%d %H:%M UTC}. Rebuild it before publishing."
        )
    return None


def directory_stats(path: Path) -> tuple[int, int]:
    files = [item for item in path.rglob("*") if item.is_file()]
    return len(files), sum(item.stat().st_size for item in files)


def remove_previous(package_dir: Path, zip_path: Path, force: bool) -> None:
    if package_dir.exists():
        marker = package_dir / "VERSION.json"
        if not marker.is_file() and not force:
            raise ReleaseError(
                f"{package_dir} exists and was not created by this packager. "
                "Move it away or pass --force."
            )
        shutil.rmtree(package_dir)
    if zip_path.exists():
        zip_path.unlink()


def copy_documents(root: Path, package_dir: Path) -> None:
    docs_dir = package_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    for relative, name in DOCUMENTS.items():
        source = root / relative
        require(source.is_file(), f"Missing documentation file: {source}")
        shutil.copy2(source, docs_dir / name)


def write_readme(package_dir: Path, version: str, include_installer: bool, include_portable: bool) -> None:
    lines = [
        f"IDM - Internet Download Manager {version}",
        "Windows 10/11 x64",
        "",
        "Contents",
        "--------",
    ]
    if include_installer:
        lines.append(f"  {'IDM_Setup_' + version + '.exe':<30}Installer")
    if include_portable:
        lines.append(f"  {'portable\\IDM\\IDM.exe':<30}Portable application")
    lines += [
        f"  {'browser-extensions\\':<30}Chrome, Edge and Firefox packages",
        f"  {'docs\\':<30}Full documentation",
        f"  {'RELEASE_NOTES.md':<30}What changed in this release",
        f"  {'VERSION.json':<30}Component versions and build metadata",
        f"  {'SHA256SUMS.txt':<30}SHA-256 digest for every packaged file",
        "",
        "Install",
        "-------",
    ]
    if include_installer:
        lines += [
            f"1. Verify the installer against SHA256SUMS.txt.",
            f"2. Run IDM_Setup_{version}.exe.",
            "3. Optionally select the browser-integration tasks for your browsers.",
        ]
    else:
        lines.append("Run portable\\IDM\\IDM.exe directly; no installation is required.")
    lines += [
        "",
        "Verify",
        "------",
        "  certutil -hashfile IDM_Setup_" + version + ".exe SHA256",
        "Compare the digest with the matching line in SHA256SUMS.txt.",
        "",
        "Notes",
        "-----",
        "- The application and installer are not code-signed in this build.",
        "- Automatic updates are not configured until an HTTPS endpoint, Ed25519",
        "  manifest key and Authenticode publisher are supplied.",
        "- Windows 10 is supported by the installer configuration but this build",
        "  was validated on Windows 11 x64 only.",
        "- User data lives in %APPDATA%\\IDM Download Manager and survives upgrades.",
        "",
        "See docs\\README.md and docs\\PACKAGING.md for details.",
    ]
    (package_dir / "README.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
    )


def write_checksums(package_dir: Path) -> int:
    entries = []
    for path in sorted(package_dir.rglob("*")):
        if not path.is_file() or path.name == "SHA256SUMS.txt":
            continue
        relative = path.relative_to(package_dir).as_posix()
        entries.append((relative, sha256_file(path)))
    content = "".join(f"{digest}  {relative}\n" for relative, digest in entries)
    (package_dir / "SHA256SUMS.txt").write_text(
        content, encoding="utf-8", newline="\n"
    )
    return len(entries)


def create_zip(package_dir: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = f"{package_dir.name}/{path.relative_to(package_dir).as_posix()}"
            info = zipfile.ZipInfo(relative, date_time=ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with path.open("rb") as source, archive.open(info, "w") as target:
                shutil.copyfileobj(source, target)


def build_release(
    root: Path,
    output_dir: Path,
    *,
    include_installer: bool = True,
    include_portable: bool = True,
    create_archive: bool = True,
    force: bool = False,
    version_override: str | None = None,
) -> Path:
    version = read_source_version(root)
    if version_override and version_override != version:
        raise ReleaseError(
            f"--version {version_override} does not match idm/version.py ({version})."
        )
    validate_versions(root, version)

    dist_dir = root / "dist"
    installer = root / "dist-installer" / "IDM_Setup.exe"
    portable_dir = dist_dir / "IDM"
    extensions_dir = root / "dist-extensions"

    require(
        not include_installer or installer.is_file(),
        f"Installer not found: {installer}. Run build_windows.ps1 or pass --no-installer.",
    )
    require(
        not include_portable or portable_dir.is_dir(),
        f"Portable build not found: {portable_dir}. Run build_windows.ps1 or pass --no-portable.",
    )
    if include_portable:
        require(
            (portable_dir / "IDM.exe").is_file(),
            f"Portable build is incomplete: {portable_dir / 'IDM.exe'} is missing.",
        )

    extensions = validate_extension_packages(extensions_dir, version)

    runtime_source_mtime = newest_mtime(
        [root / name for name in RUNTIME_SOURCE_DIRS]
        + [root / name for name in RUNTIME_SOURCE_FILES]
    )
    installer_source_mtime = newest_mtime(
        [root / name for name in RUNTIME_SOURCE_DIRS]
        + [root / name for name in RUNTIME_SOURCE_FILES]
        + [root / "extensions"]
    )

    warnings = []
    if include_installer:
        warning = age_warning("The installer", installer, installer_source_mtime)
        if warning:
            warnings.append(warning)
    if include_portable:
        warning = age_warning("The portable build", portable_dir / "IDM.exe", runtime_source_mtime)
        if warning:
            warnings.append(warning)

    package_name = f"IDM-{version}-win64"
    package_dir = output_dir / package_name
    zip_path = output_dir / f"{package_name}.zip"

    output_dir.mkdir(parents=True, exist_ok=True)
    remove_previous(package_dir, zip_path, force)
    package_dir.mkdir(parents=True)

    components: dict[str, object] = {}

    if include_installer:
        target = package_dir / f"IDM_Setup_{version}.exe"
        shutil.copy2(installer, target)
        components["installer"] = {
            "file": target.name,
            "bytes": target.stat().st_size,
            "sha256": sha256_file(target),
            "built_at": datetime.fromtimestamp(installer.stat().st_mtime, timezone.utc).isoformat(),
        }

    if include_portable:
        target = package_dir / "portable" / "IDM"
        shutil.copytree(portable_dir, target)
        file_count, total_bytes = directory_stats(target)
        components["portable"] = {
            "directory": target.relative_to(package_dir).as_posix(),
            "files": file_count,
            "bytes": total_bytes,
            "sha256_of_executable": sha256_file(target / "IDM.exe"),
            "built_at": datetime.fromtimestamp(
                (portable_dir / "IDM.exe").stat().st_mtime, timezone.utc
            ).isoformat(),
        }

    extensions_target = package_dir / "browser-extensions"
    extensions_target.mkdir()
    for extension in extensions:
        shutil.copy2(extensions_dir / extension["file"], extensions_target / extension["file"])
    components["extensions"] = {
        item["browser"]: {
            "file": item["file"],
            "version": item["version"],
            "bytes": item["bytes"],
            "sha256": item["sha256"],
        }
        for item in extensions
    }

    copy_documents(root, package_dir)
    shutil.copy2(root / "RELEASE_NOTES.md", package_dir / "RELEASE_NOTES.md")
    write_readme(package_dir, version, include_installer, include_portable)

    metadata = {
        "schema": 1,
        "product": "IDM",
        "description": "Internet Download Manager",
        "version": version,
        "platform": "windows-x64",
        "channel": "stable",
        "packaged_at": datetime.now(timezone.utc).isoformat(),
        "package": package_name,
        "components": components,
        "warnings": warnings,
    }
    version_file = package_dir / "VERSION.json"
    version_file.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    # Two passes so VERSION.json carries totals that include itself and
    # SHA256SUMS.txt while the checksum file still covers the final metadata.
    write_checksums(package_dir)
    file_count, total_bytes = directory_stats(package_dir)
    metadata["totals"] = {"files": file_count, "bytes": total_bytes}
    version_file.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    checksummed = write_checksums(package_dir)

    if create_archive:
        create_zip(package_dir, zip_path)
        digest = sha256_file(zip_path)
        (output_dir / f"{zip_path.name}.sha256").write_text(
            f"{digest}  {zip_path.name}\n", encoding="utf-8", newline="\n"
        )
        print(f"Archive : {zip_path} ({human_size(zip_path.stat().st_size)})")
        print(f"SHA-256 : {digest}")

    print(f"Package : {package_dir}")
    print(f"Version : {version}")
    print(f"Files   : {file_count} ({human_size(total_bytes)})")
    print(f"Checksums: {checksummed} files in SHA256SUMS.txt")
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return package_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT), help="Project root (default: repository).")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Where the release directory and ZIP are written (default: release).",
    )
    parser.add_argument("--version", default=None, help="Expected version; must match idm/version.py.")
    parser.add_argument("--no-installer", action="store_true", help="Omit IDM_Setup.exe.")
    parser.add_argument("--no-portable", action="store_true", help="Omit the portable application.")
    parser.add_argument("--no-zip", action="store_true", help="Write the directory without the ZIP archive.")
    parser.add_argument("--force", action="store_true", help="Replace an unrecognised existing package directory.")
    args = parser.parse_args(argv)

    try:
        build_release(
            Path(args.root).resolve(),
            Path(args.output_dir).resolve(),
            include_installer=not args.no_installer,
            include_portable=not args.no_portable,
            create_archive=not args.no_zip,
            force=args.force,
            version_override=args.version,
        )
    except ReleaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
