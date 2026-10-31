"""Destination folder policy for downloads, including browser downloads.

Three modes are supported:

``default``
    Every file goes to the configured default download folder.
``ask``
    The desktop application asks the user for a folder before each download.
``type``
    A user-editable set of extension-to-folder rules chooses the folder.
    Unmatched files fall back to the default folder.

This module is Qt-free so the policy can be unit-tested and reused outside
the GUI.  It never creates a folder without an explicit approval callback, and
it refuses paths that escape a selected folder or contain unsafe components.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from idm.core.url_utils import (
    category_for_filename,
    extension_of,
    sanitize_filename,
)

MODE_DEFAULT = "default"
MODE_ASK = "ask"
MODE_TYPE = "type"
MODES = (MODE_DEFAULT, MODE_ASK, MODE_TYPE)
MODE_LABELS = {
    MODE_DEFAULT: "Default location",
    MODE_ASK: "Ask every time",
    MODE_TYPE: "File type based locations",
}

WILDCARD = "*"
MIN_FREE_HEADROOM = 32 * 1024 * 1024
_EXTENSION = re.compile(r"^[a-z0-9][a-z0-9_+-]{0,15}$")
_DRIVE = re.compile(r"^[A-Za-z]:")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

_GROUP_FOLDERS = (
    ("Archives", ("zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "xz", "cab")),
    ("Software", ("exe", "msi", "msix", "appx", "bat", "cmd", "ps1", "apk", "iso")),
    ("Documents", ("pdf", "docx", "doc", "xlsx", "xls", "pptx", "ppt", "txt", "epub")),
    ("Media", ("mp4", "mkv", "avi", "mov", "mp3", "wav", "flac", "m4a", "webm")),
    ("Images", ("jpg", "jpeg", "png", "gif", "webp", "bmp", "svg", "tif", "tiff")),
)


class LocationError(ValueError):
    """A folder or rule cannot be used safely."""

    def __init__(self, message: str, code: str = "invalid_location") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LocationRule:
    folder: str
    extensions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"folder": self.folder, "extensions": list(self.extensions)}

    @classmethod
    def from_dict(cls, value: Any) -> "LocationRule":
        if not isinstance(value, Mapping):
            raise LocationError("A file type rule must be an object.")
        folder = validate_folder_path(str(value.get("folder") or ""))
        raw_extensions = value.get("extensions")
        if not isinstance(raw_extensions, (list, tuple)):
            raise LocationError("A file type rule needs a list of extensions.")
        extensions = normalize_extensions(raw_extensions)
        if not extensions:
            raise LocationError("A file type rule needs at least one extension.")
        return cls(folder=folder, extensions=extensions)


def normalize_extensions(values: Iterable[Any]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        extension = str(value or "").strip().lower().lstrip(".")
        if not extension:
            continue
        if extension == WILDCARD:
            normalized = WILDCARD
        elif not _EXTENSION.match(extension):
            raise LocationError(
                f"“{extension}” is not a valid file extension."
            )
        else:
            normalized = extension
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return tuple(result)


def _reserved_name(part: str) -> bool:
    stem = part.split(".", 1)[0].upper()
    return stem in {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }


def validate_folder_path(raw: str) -> str:
    """Validate and normalize an absolute, traversal-free folder path."""
    text = str(raw or "").strip().strip('"')
    if not text:
        raise LocationError("Choose a destination folder.")
    if len(text) > 4096 or _CONTROL.search(text):
        raise LocationError("The folder path contains invalid characters.")
    if not Path(text).is_absolute() or not _DRIVE.match(text):
        raise LocationError(
            "Use a full path such as C:\\Users\\You\\Downloads.",
            "invalid_folder",
        )
    parts = Path(text).parts
    if any(part == ".." for part in parts):
        raise LocationError(
            "The folder path must not contain “..” segments.",
            "path_traversal",
        )
    if any(_reserved_name(part) for part in parts[1:] if part not in ("\\", "/")):
        raise LocationError("The folder path uses a reserved Windows name.")
    try:
        path = Path(text)
    except (OSError, ValueError) as exc:
        raise LocationError(f"That folder path is not valid: {exc}") from exc
    if path.exists() and not path.is_dir():
        raise LocationError("That path points to a file, not a folder.")
    return str(path)


def ensure_folder(
    folder: str,
    approve_create: Callable[[str], bool] | None = None,
) -> str:
    """Create a missing folder only after ``approve_create`` agrees.

    ``approve_create`` receives the path and must return ``True``.  When it is
    omitted, a missing folder is rejected with ``folder_missing``.
    """
    folder = validate_folder_path(folder)
    path = Path(folder)
    if path.exists():
        if not path.is_dir():
            raise LocationError("That path points to a file, not a folder.")
        return folder
    if approve_create is None or not approve_create(folder):
        raise LocationError(
            f"The folder does not exist: {folder}",
            "folder_missing",
        )
    try:
        path.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        raise LocationError(
            f"IDM is not allowed to create the folder: {folder}",
            "permission_denied",
        ) from exc
    except OSError as exc:
        raise LocationError(
            f"The folder could not be created: {exc}", "invalid_folder"
        ) from exc
    if not path.is_dir():
        raise LocationError("The destination is not a folder.", "invalid_folder")
    return folder


def _existing_ancestor(path: Path) -> Path | None:
    candidate = path
    while True:
        if candidate.exists() and candidate.is_dir():
            return candidate
        if candidate.parent == candidate:
            return None
        candidate = candidate.parent


def check_disk_space(folder: str, total_bytes: int | None) -> None:
    """Reject a download that cannot fit with a small safety margin."""
    if total_bytes is None:
        return
    path = Path(folder)
    anchor = path if path.exists() else _existing_ancestor(path)
    if anchor is None:
        return
    try:
        usage = shutil.disk_usage(str(anchor))
    except OSError as exc:
        raise LocationError(
            f"Free disk space could not be checked for {anchor}: {exc}",
            "space_check_failed",
        ) from exc
    required = int(total_bytes) + max(MIN_FREE_HEADROOM, int(total_bytes) // 50)
    if usage.free < required:
        free_gb = usage.free / (1024**3)
        need_gb = required / (1024**3)
        raise LocationError(
            f"Not enough free space in {anchor}. "
            f"{need_gb:.1f} GB is needed but only {free_gb:.1f} GB is free.",
            "insufficient_space",
        )


def safe_filename(filename: str) -> str:
    """Validate a browser-supplied base name and return a Windows-safe name."""
    text = str(filename or "").strip()
    if not text:
        raise LocationError("The file name is empty.", "invalid_filename")
    if any(separator in text for separator in ("/", "\\", ":")):
        raise LocationError(
            "The file name must not contain a path.", "invalid_filename"
        )
    cleaned = sanitize_filename(text)
    if not cleaned or cleaned in {".", ".."}:
        raise LocationError("The file name is invalid.", "invalid_filename")
    return cleaned


def safe_join(folder: str, filename: str) -> Path:
    """Join a validated folder and name, refusing any escape from the folder."""
    folder = validate_folder_path(folder)
    name = safe_filename(filename)
    base = Path(folder).resolve(strict=False)
    candidate = (base / name).resolve(strict=False)
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise LocationError(
            "The destination path escapes the selected folder.",
            "path_traversal",
        ) from exc
    if candidate.parent != base:
        raise LocationError("The destination path is not safe.", "path_traversal")
    return candidate


def default_rules_for(folder: str) -> list[LocationRule]:
    """Recommended rules created under the user's default folder."""
    base = Path(validate_folder_path(folder))
    return [
        LocationRule(str(base / name), extensions)
        for name, extensions in _GROUP_FOLDERS
    ]


@dataclass
class DownloadLocationConfig:
    mode: str = MODE_DEFAULT
    rules: list[LocationRule] = field(default_factory=list)

    def normalized(self) -> "DownloadLocationConfig":
        mode = self.mode if self.mode in MODES else MODE_DEFAULT
        return DownloadLocationConfig(mode=mode, rules=list(self.rules))

    def to_settings(self) -> dict[str, Any]:
        return {
            "download_mode": self.mode if self.mode in MODES else MODE_DEFAULT,
            "download_type_rules": [rule.to_dict() for rule in self.rules],
        }

    @classmethod
    def from_settings(cls, values: Mapping[str, Any] | None) -> "DownloadLocationConfig":
        values = values or {}
        mode = str(values.get("download_mode") or MODE_DEFAULT)
        if mode not in MODES:
            mode = MODE_DEFAULT
        rules: list[LocationRule] = []
        raw_rules = values.get("download_type_rules")
        if isinstance(raw_rules, (list, tuple)):
            for raw in raw_rules:
                try:
                    rules.append(LocationRule.from_dict(raw))
                except LocationError:
                    # A hand-edited or obsolete rule must not break startup.
                    continue
        return cls(mode=mode, rules=rules)

    def folder_for(self, filename: str, default_folder: str) -> str:
        """Choose a folder for a file without touching the filesystem."""
        if self.mode != MODE_TYPE:
            return default_folder
        extension = extension_of(filename)
        wildcard: str | None = None
        for rule in self.rules:
            if extension and extension in rule.extensions:
                return rule.folder
            if WILDCARD in rule.extensions and wildcard is None:
                wildcard = rule.folder
        return wildcard or default_folder

    def validate(self) -> None:
        """Check rules for invalid paths, duplicates and overlaps."""
        seen: dict[str, str] = {}
        wildcard_seen = False
        for rule in self.rules:
            validate_folder_path(rule.folder)
            for extension in rule.extensions:
                if extension == WILDCARD:
                    if wildcard_seen:
                        raise LocationError(
                            "Only one catch-all (*) rule is allowed.",
                            "duplicate_rule",
                        )
                    wildcard_seen = True
                    continue
                if extension in seen:
                    raise LocationError(
                        f"The .{extension} extension is already used by "
                        f"{seen[extension]}.",
                        "duplicate_rule",
                    )
                seen[extension] = rule.folder


def resolve_destination(
    config: DownloadLocationConfig,
    filename: str,
    default_folder: str,
    total_bytes: int | None = None,
    ask: Callable[[str, str], str | None] | None = None,
    approve_create: Callable[[str], bool] | None = None,
) -> tuple[str, str]:
    """Return ``(folder, filename)`` for a validated request.

    ``ask`` is called only in ask mode and receives the suggested file name and
    the default folder.  Returning ``None`` cancels the download.
    """
    name = safe_filename(filename)
    mode = config.mode if config.mode in MODES else MODE_DEFAULT
    if mode == MODE_ASK:
        if ask is None:
            raise LocationError(
                "Ask-every-time mode requires user interaction.", "ask_unavailable"
            )
        selected = ask(name, default_folder)
        if not selected:
            raise LocationError(
                "The user cancelled the folder selection.", "cancelled"
            )
        folder = validate_folder_path(selected)
    elif mode == MODE_TYPE:
        folder = config.folder_for(name, default_folder)
        folder = validate_folder_path(folder)
    else:
        folder = validate_folder_path(default_folder)

    folder = ensure_folder(folder, approve_create=approve_create)
    check_disk_space(folder, total_bytes)
    safe_join(folder, name)
    return folder, name


def suggested_rules_for(filename: str, folder: str) -> LocationRule:
    """Create a convenient rule for the extension of ``filename``."""
    extension = extension_of(filename)
    if not extension:
        raise LocationError("The file has no extension to match.")
    return LocationRule(
        folder=validate_folder_path(folder),
        extensions=(extension,),
    )


def rule_category(rule: LocationRule) -> str:
    """Category label used by options UI hints."""
    if not rule.extensions:
        return "Other"
    return category_for_filename(f"file.{rule.extensions[0]}")


def is_within(folder: str, parent: str) -> bool:
    try:
        Path(folder).resolve(strict=False).relative_to(
            Path(parent).resolve(strict=False)
        )
    except ValueError:
        return False
    return True


def environment_default_folder() -> str:
    """Best-effort fallback when a request arrives before settings load."""
    downloads = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Downloads"
    return str(downloads)


__all__ = [
    "DownloadLocationConfig",
    "LocationError",
    "LocationRule",
    "MODE_ASK",
    "MODE_DEFAULT",
    "MODE_LABELS",
    "MODE_TYPE",
    "MODES",
    "MIN_FREE_HEADROOM",
    "WILDCARD",
    "check_disk_space",
    "default_rules_for",
    "ensure_folder",
    "environment_default_folder",
    "is_within",
    "normalize_extensions",
    "resolve_destination",
    "rule_category",
    "safe_filename",
    "safe_join",
    "suggested_rules_for",
    "validate_folder_path",
]
