"""Media classification shared by the engine, UI and browser integration.

Only observable metadata is used: the file extension and the HTTP Content-Type.
Nothing here downloads, probes or extracts protected media streams.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

VIDEO_EXTENSIONS = frozenset(
    {
        "mp4",
        "m4v",
        "webm",
        "mkv",
        "mov",
        "avi",
        "wmv",
        "flv",
        "mpg",
        "mpeg",
        "3gp",
        "ts",
        "m2ts",
        "ogv",
    }
)
AUDIO_EXTENSIONS = frozenset(
    {
        "mp3",
        "m4a",
        "aac",
        "wav",
        "flac",
        "ogg",
        "oga",
        "opus",
        "wma",
        "aiff",
        "amr",
    }
)

# The subset this application explicitly promises to download over plain HTTP.
SUPPORTED_MEDIA_EXTENSIONS = frozenset({"mp4", "webm", "m4v", "mp3", "m4a", "ogg", "wav"})

_VIDEO_TYPES = (
    "video/",
    "application/vnd.apple.mpegurl",
    "application/x-mpegurl",
    "application/dash+xml",
)
_AUDIO_TYPES = ("audio/",)

_MIME_TO_FORMAT = {
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/quicktime": "mov",
    "video/x-matroska": "mkv",
    "video/x-msvideo": "avi",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/flac": "flac",
}


def extension_of(filename: str) -> str:
    return Path(filename or "").suffix.lower().lstrip(".")


def format_for(content_type: str, filename: str) -> str:
    extension = extension_of(filename)
    if extension:
        return extension
    mime = (content_type or "").split(";")[0].strip().lower()
    return _MIME_TO_FORMAT.get(mime, "")


def media_kind_for(content_type: str, filename: str) -> str:
    """Return ``video``, ``audio`` or an empty string for non-media files."""
    extension = extension_of(filename)
    if extension in VIDEO_EXTENSIONS:
        return "video"
    if extension in AUDIO_EXTENSIONS:
        return "audio"
    mime = (content_type or "").split(";")[0].strip().lower()
    if mime.startswith(_VIDEO_TYPES):
        return "video"
    if mime.startswith(_AUDIO_TYPES):
        return "audio"
    return ""


def is_supported_media(content_type: str, filename: str) -> bool:
    return extension_of(filename) in SUPPORTED_MEDIA_EXTENSIONS or media_kind_for(
        content_type, filename
    ) == "video"


def normalize_sha256(value: str | None) -> str:
    text = (value or "").strip().lower()
    if len(text) != 64:
        return ""
    if any(character not in "0123456789abcdef" for character in text):
        return ""
    return text


def source_domain(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def media_metadata(
    *,
    url: str,
    filename: str,
    content_type: str = "",
    page_url: str = "",
    page_title: str = "",
    quality_label: str = "",
    duration_seconds: int | None = None,
    detected_by: str = "",
    media_kind_hint: str = "",
) -> dict:
    """Build a normalized metadata record; empty values are omitted by callers."""
    kind = media_kind_for(content_type, filename)
    if not kind and media_kind_hint in {"video", "audio"}:
        # The browser extension can observe a <video>/<audio> element before
        # the server reports a Content-Type.  Accept the hint only when neither
        # the file name nor the server metadata can classify the file, so it
        # never relabels an ordinary download such as a .zip archive.
        type_text = (content_type or "").split(";")[0].strip().lower()
        uninformative = not type_text or type_text == "application/octet-stream"
        if uninformative and not extension_of(filename):
            kind = media_kind_hint
    return {
        "media_kind": kind,
        "page_url": page_url,
        "page_title": page_title,
        "source_domain": source_domain(url),
        "file_format": format_for(content_type, filename),
        "quality_label": quality_label,
        "duration_seconds": duration_seconds,
        "detected_by": detected_by,
    }


__all__ = [
    "AUDIO_EXTENSIONS",
    "SUPPORTED_MEDIA_EXTENSIONS",
    "VIDEO_EXTENSIONS",
    "extension_of",
    "format_for",
    "is_supported_media",
    "media_kind_for",
    "media_metadata",
    "normalize_sha256",
    "source_domain",
]
