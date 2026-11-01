"""URL validation, filename detection and display formatting helpers."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from ..constants import CATEGORY_GENERAL, EXTENSION_TO_CATEGORY

_ALLOWED_SCHEMES = {"http", "https"}
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MAX_FILENAME_LENGTH = 180


class InvalidUrlError(ValueError):
    """Raised when a URL cannot be used for a download."""


def validate_url(raw: str) -> str:
    """Return a normalised URL or raise InvalidUrlError with a readable message."""
    url = (raw or "").strip()
    if not url:
        raise InvalidUrlError("Enter a download link.")
    if any(character.isspace() for character in url):
        raise InvalidUrlError("The link contains spaces. Copy the full URL again.")
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise InvalidUrlError("That link is not a valid URL.") from exc

    scheme = parsed.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise InvalidUrlError("Only HTTP and HTTPS links are supported.")
    if not parsed.hostname:
        raise InvalidUrlError("The link is missing a host name.")
    if parsed.username or parsed.password:
        raise InvalidUrlError("Links containing embedded credentials are not supported.")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise InvalidUrlError("The link contains an invalid port.") from exc
    return url


def is_valid_url(raw: str) -> bool:
    try:
        validate_url(raw)
    except InvalidUrlError:
        return False
    return True


def host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def redact_url(url: str) -> str:
    """Return a log-safe identifier that cannot leak tokens or credentials."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return "[invalid-url]"
    scheme = parsed.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES or not parsed.hostname:
        return "[redacted-url]"
    port = ""
    try:
        if parsed.port and parsed.port not in {80, 443}:
            port = f":{parsed.port}"
    except ValueError:
        port = ""
    return f"{scheme}://{parsed.hostname}{port}/…"


def sanitize_filename(name: str, fallback: str = "download") -> str:
    """Make a server-supplied or user-supplied name safe for Windows paths."""
    name = unquote(name or "").strip().strip(".")
    name = _INVALID_FILENAME_CHARS.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    if not name:
        return fallback

    path = Path(name)
    stem = path.stem or "download"
    suffix = path.suffix
    if stem.upper() in _WINDOWS_RESERVED:
        stem = f"_{stem}"

    max_stem = max(1, _MAX_FILENAME_LENGTH - len(suffix))
    if len(stem) > max_stem:
        stem = stem[:max_stem].rstrip(" .")
    cleaned = f"{stem}{suffix}"
    return cleaned.strip(" .") or fallback


def guess_filename(url: str, fallback: str = "download") -> str:
    try:
        path = urlparse(url).path
    except ValueError:
        return fallback
    candidate = unquote(path.rstrip("/").rsplit("/", 1)[-1])
    candidate = candidate.strip()
    if not candidate:
        return fallback
    return sanitize_filename(candidate, fallback)


def filename_from_content_disposition(value: str | None) -> str | None:
    if not value:
        return None

    encoded = re.search(
        r"filename\*\s*=\s*(?P<charset>[^']*)'[^']*'(?P<name>[^;]+)",
        value,
        flags=re.IGNORECASE,
    )
    if encoded:
        name = unquote(encoded.group("name").strip().strip('"'))
        if name:
            return sanitize_filename(name)

    plain = re.search(
        r'filename\s*=\s*(?:"(?P<quoted>[^"]*)"|(?P<plain>[^;]+))',
        value,
        flags=re.IGNORECASE,
    )
    if plain:
        name = (plain.group("quoted") or plain.group("plain") or "").strip()
        if name:
            return sanitize_filename(name)
    return None


def extension_of(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


def category_for_filename(filename: str) -> str:
    return EXTENSION_TO_CATEGORY.get(extension_of(filename), CATEGORY_GENERAL)


def _part_name(filename: str) -> str:
    return f"{filename}.idm.part"


def unique_filename(
    folder: str | Path, filename: str, reserved: Iterable[str] = ()
) -> str:
    """Return a name free on disk and not reserved by another active download."""
    folder = Path(folder)
    safe = sanitize_filename(filename)
    reserved_names = {name.casefold() for name in reserved}
    candidate = safe
    stem = Path(safe).stem
    suffix = Path(safe).suffix
    counter = 1
    while counter < 10_000:
        free_on_disk = (
            not (folder / candidate).exists()
            and not (folder / _part_name(candidate)).exists()
        )
        if free_on_disk and candidate.casefold() not in reserved_names:
            return candidate
        candidate = f"{stem} ({counter}){suffix}"
        counter += 1
    raise RuntimeError("Could not find a free file name in the destination folder.")


def format_size(size: float | None) -> str:
    if size is None or size < 0:
        return "—"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def format_speed(bytes_per_second: float | None) -> str:
    if not bytes_per_second or bytes_per_second <= 0:
        return "—"
    return f"{format_size(bytes_per_second)}/s"


def format_eta(seconds: float | None) -> str:
    if seconds is None or seconds <= 0:
        return "—"
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_timestamp(moment: datetime | None) -> str:
    if moment is None:
        return "—"
    return moment.strftime("%Y-%m-%d %H:%M")


def format_last_try(moment: datetime | None) -> str:
    """Compact timestamp used by the Last Try table column."""
    if moment is None:
        return "—"
    today = datetime.now().date()
    day = moment.date()
    if day == today:
        return f"Today {moment:%H:%M}"
    if (today - day).days == 1:
        return f"Yesterday {moment:%H:%M}"
    if day.year == today.year:
        return moment.strftime("%b %d, %H:%M")
    return moment.strftime("%Y-%m-%d %H:%M")


def parse_content_range_total(value: str | None) -> int | None:
    """Extract the total size from a Content-Range header."""
    if not value:
        return None
    match = re.search(r"/\s*(\d+)\s*$", value)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def parse_content_range_start(value: str | None) -> int | None:
    if not value:
        return None
    match = re.match(r"\s*bytes\s+(\d+)-", value, flags=re.IGNORECASE)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None
