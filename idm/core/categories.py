"""Category detection and user-defined category preferences.

The built-in categories are fixed so download records written by older
versions remain readable.  Users can add custom categories with their own
extension list; those are persisted as plain data in the settings table and
never replace the built-ins.

This module is intentionally Qt-free so it can be used by the download engine,
the browser bridge and the tests without starting a GUI event loop.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from ..constants import (
    CATEGORIES,
    CATEGORY_COMPRESSED,
    CATEGORY_DOCUMENTS,
    CATEGORY_GENERAL,
    CATEGORY_IMAGES,
    CATEGORY_MUSIC,
    CATEGORY_PROGRAMS,
    CATEGORY_VIDEOS,
    EXTENSION_TO_CATEGORY,
    _BUILTIN_CATEGORY_NAMES,
)
from .url_utils import extension_of, sanitize_filename

MAX_CUSTOM_CATEGORIES = 32
MAX_CATEGORY_NAME = 32
MAX_EXTENSIONS_PER_CATEGORY = 64

_NAME_INVALID = re.compile(r"[<>:\"/\\|?*\x00-\x1f]")
_EXTENSION = re.compile(r"^[a-z0-9][a-z0-9_+-]{0,15}$")

_MIME_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        CATEGORY_DOCUMENTS,
        (
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument",
            "application/vnd.ms-excel",
            "application/vnd.ms-powerpoint",
            "application/rtf",
            "application/epub+zip",
            "application/json",
            "application/xml",
            "text/",
        ),
    ),
    (CATEGORY_MUSIC, ("audio/",)),
    (CATEGORY_VIDEOS, ("video/",)),
    (
        CATEGORY_IMAGES,
        ("image/",),
    ),
    (
        CATEGORY_COMPRESSED,
        (
            "application/zip",
            "application/x-zip",
            "application/x-rar",
            "application/vnd.rar",
            "application/x-7z",
            "application/x-tar",
            "application/gzip",
            "application/x-gzip",
            "application/x-bzip",
            "application/x-xz",
            "application/zstd",
        ),
    ),
    (
        CATEGORY_PROGRAMS,
        (
            "application/x-msdownload",
            "application/x-msi",
            "application/vnd.microsoft.portable-executable",
            "application/vnd.android.package-archive",
            "application/x-apple-diskimage",
            "application/x-debian-package",
            "application/x-rpm",
        ),
    ),
)

_FILE_TYPE_LABELS = {
    "pdf": "PDF document",
    "doc": "Word document",
    "docx": "Word document",
    "xls": "Excel workbook",
    "xlsx": "Excel workbook",
    "ppt": "PowerPoint presentation",
    "pptx": "PowerPoint presentation",
    "txt": "Text file",
    "csv": "CSV data",
    "epub": "EPUB book",
    "zip": "ZIP archive",
    "rar": "RAR archive",
    "7z": "7-Zip archive",
    "tar": "TAR archive",
    "gz": "GZip archive",
    "exe": "Windows application",
    "msi": "Windows installer",
    "msix": "Windows package",
    "apk": "Android package",
    "iso": "Disc image",
    "mp3": "MP3 audio",
    "wav": "WAV audio",
    "flac": "FLAC audio",
    "m4a": "AAC audio",
    "mp4": "MP4 video",
    "mkv": "Matroska video",
    "avi": "AVI video",
    "mov": "QuickTime video",
    "webm": "WebM video",
    "png": "PNG image",
    "jpg": "JPEG image",
    "jpeg": "JPEG image",
    "gif": "GIF image",
    "webp": "WebP image",
    "svg": "SVG image",
}


def normalize_category_name(value: Any) -> str:
    """Return a display-safe category name, or an empty string if invalid."""
    name = " ".join(str(value or "").split())
    name = _NAME_INVALID.sub("", name).strip(" .")
    if not name or len(name) > MAX_CATEGORY_NAME:
        return ""
    return name


def normalize_extensions(values: Iterable[Any]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        extension = str(value or "").strip().lower().lstrip(".")
        if not extension or extension in seen:
            continue
        if not _EXTENSION.match(extension):
            continue
        seen.add(extension)
        result.append(extension)
        if len(result) >= MAX_EXTENSIONS_PER_CATEGORY:
            break
    return tuple(result)


def normalize_custom_categories(
    values: Any,
) -> list[dict[str, Any]]:
    """Validate persisted custom categories and drop unusable entries."""
    if not isinstance(values, (list, tuple)):
        return []
    result: list[dict[str, Any]] = []
    used: set[str] = {name.casefold() for name in _BUILTIN_CATEGORY_NAMES}
    used_extensions: set[str] = set(EXTENSION_TO_CATEGORY)
    for entry in values:
        if not isinstance(entry, Mapping):
            continue
        name = normalize_category_name(entry.get("name"))
        if not name or name.casefold() in used:
            continue
        raw_extensions = entry.get("extensions")
        if not isinstance(raw_extensions, (list, tuple)):
            raw_extensions = []
        extensions = tuple(
            extension
            for extension in normalize_extensions(raw_extensions)
            if extension not in used_extensions
        )
        if not extensions:
            continue
        used.add(name.casefold())
        used_extensions.update(extensions)
        result.append({"name": name, "extensions": list(extensions)})
        if len(result) >= MAX_CUSTOM_CATEGORIES:
            break
    return result


def category_names(custom: Iterable[Mapping[str, Any]] | None = None) -> tuple[str, ...]:
    """Built-in categories followed by the user's custom categories."""
    names = list(CATEGORIES)
    for entry in custom or ():
        name = str(entry.get("name") or "").strip()
        if name and name.casefold() not in {item.casefold() for item in names}:
            names.append(name)
    return tuple(names)


def custom_category_map(
    custom: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for entry in custom or ():
        name = normalize_category_name(entry.get("name"))
        if not name:
            continue
        extensions = normalize_extensions(entry.get("extensions") or ())
        if extensions:
            result[name] = extensions
    return result


def category_for_extension(
    extension: str, custom: Iterable[Mapping[str, Any]] | None = None
) -> str | None:
    extension = str(extension or "").strip().lower().lstrip(".")
    if not extension:
        return None
    for name, extensions in custom_category_map(custom).items():
        if extension in extensions:
            return name
    return EXTENSION_TO_CATEGORY.get(extension)


def category_for_mime(mime: str) -> str | None:
    mime = str(mime or "").split(";")[0].strip().lower()
    if not mime or "/" not in mime:
        return None
    for category, prefixes in _MIME_GROUPS:
        for prefix in prefixes:
            if mime == prefix or mime.startswith(prefix):
                return category
    return None


def detect_category(
    filename: str,
    mime: str = "",
    custom: Iterable[Mapping[str, Any]] | None = None,
) -> str:
    """Detect a category from the extension first, then the MIME type."""
    by_extension = category_for_extension(extension_of(filename), custom)
    if by_extension:
        return by_extension
    return category_for_mime(mime) or CATEGORY_GENERAL


def describe_file_type(filename: str, mime: str = "") -> str:
    """Friendly type label shown in the file information panel."""
    extension = extension_of(filename)
    label = _FILE_TYPE_LABELS.get(extension)
    if label:
        return label
    mime = str(mime or "").split(";")[0].strip().lower()
    type_map = {
        "application/pdf": "PDF document",
        "application/zip": "ZIP archive",
        "application/x-msdownload": "Windows application",
        "application/octet-stream": "Binary file",
        "text/plain": "Text file",
        "text/html": "HTML document",
    }
    if mime in type_map:
        return type_map[mime]
    if mime.startswith("image/"):
        return f"{mime.split('/', 1)[1].upper()} image"
    if mime.startswith("audio/"):
        return f"{mime.split('/', 1)[1].upper()} audio"
    if mime.startswith("video/"):
        return f"{mime.split('/', 1)[1].upper()} video"
    if extension:
        return f"{extension.upper()} file"
    return "File"


def safe_category(raw: str, custom: Iterable[Mapping[str, Any]] | None = None) -> str:
    """Return a known category name, falling back to General."""
    name = str(raw or "").strip()
    if not name:
        return CATEGORY_GENERAL
    for known in category_names(custom):
        if known.casefold() == name.casefold():
            return known
    return CATEGORY_GENERAL


def normalize_category_paths(
    values: Any, custom: Iterable[Mapping[str, Any]] | None = None
) -> dict[str, str]:
    """Keep remembered folders for known categories with safe paths."""
    if not isinstance(values, Mapping):
        return {}
    known = {name.casefold(): name for name in category_names(custom)}
    result: dict[str, str] = {}
    for raw_category, raw_folder in values.items():
        category = known.get(str(raw_category or "").strip().casefold())
        folder = str(raw_folder or "").strip()
        if not category or not folder:
            continue
        try:
            from downloads.location_manager import LocationError, validate_folder_path

            result[category] = validate_folder_path(folder)
        except (LocationError, ValueError):
            continue
    return result


def ensure_filename_extension(filename: str, mime: str) -> str:
    """Append an extension implied by a well-known MIME type when missing."""
    name = sanitize_filename(filename)
    if not name or extension_of(name):
        return name
    mime = str(mime or "").split(";")[0].strip().lower()
    implied = {
        "application/pdf": "pdf",
        "application/zip": "zip",
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/gif": "gif",
        "image/webp": "webp",
        "audio/mpeg": "mp3",
        "video/mp4": "mp4",
        "text/plain": "txt",
    }.get(mime)
    return f"{name}.{implied}" if implied else name


__all__ = [
    "MAX_CUSTOM_CATEGORIES",
    "category_for_extension",
    "category_for_mime",
    "category_names",
    "custom_category_map",
    "describe_file_type",
    "detect_category",
    "ensure_filename_extension",
    "normalize_category_name",
    "normalize_category_paths",
    "normalize_custom_categories",
    "normalize_extensions",
    "safe_category",
]
