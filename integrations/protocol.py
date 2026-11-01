"""Native messaging protocol, framing and strict message validation.

Three boundaries use this module:

* the browser <-> native host stdio channel, which uses the standard
  four-byte little-endian length prefix followed by UTF-8 JSON;
* the native host <-> IDM desktop loopback bridge, which uses one JSON object
  per line;
* validation of every download request before it can reach the download
  engine.

Nothing here imports Qt or opens a socket, so the same code runs inside the
desktop application and inside the standalone native messaging host.
"""

from __future__ import annotations

import json
import re
import struct
from collections import OrderedDict
from typing import Any, BinaryIO
from urllib.parse import urlparse

from idm.core.url_utils import sanitize_filename, validate_url

PROTOCOL_VERSION = 2

# Chrome rejects host->browser messages above 1 MiB.  Browser->host requests
# are capped at the same value so a compromised page cannot exhaust memory.
MAX_MESSAGE_BYTES = 1024 * 1024

SUPPORTED_BROWSERS = ("chrome", "edge", "firefox")
REQUEST_TYPES = {
    "hello",
    "status",
    "request_download",
    "open_idm",
    "open_settings",
    "list_downloads",
}

_HEADER = struct.Struct("<I")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_EXTENSION_ID = re.compile(r"^[A-Za-z0-9@._-]{4,256}$")
_MIME = re.compile(r"^[A-Za-z0-9!#$&^_.+*-]+/[A-Za-z0-9!#$&^_.+*-]+$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

MAX_URL_LENGTH = 8192
MAX_FILENAME_LENGTH = 512
MAX_TOTAL_BYTES = 10**15
MAX_PAGE_TITLE_LENGTH = 512
MAX_QUALITY_LABEL_LENGTH = 64
MAX_DURATION_SECONDS = 7 * 24 * 60 * 60
MEDIA_KINDS = frozenset({"", "video", "audio"})
DETECTION_SOURCES = frozenset({"", "link", "media", "browser", "manual"})


class ProtocolError(ValueError):
    """Raised when framing or JSON is invalid."""

    def __init__(self, message: str, code: str = "invalid_message") -> None:
        super().__init__(message)
        self.code = code


class ValidationError(ValueError):
    """A well-framed message that must not be acted on."""

    def __init__(self, message: str, code: str = "invalid_message") -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# Framing: four-byte little-endian length prefix + UTF-8 JSON
# ---------------------------------------------------------------------------


def encode_message(message: dict[str, Any]) -> bytes:
    payload = json.dumps(
        message, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ProtocolError("The message is too large.", "message_too_large")
    return _HEADER.pack(len(payload)) + payload


def _read_exact(stream: BinaryIO, count: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < count:
        block = stream.read(count - len(chunks))
        if not block:
            break
        chunks.extend(block)
    return bytes(chunks)


def read_message(stream: BinaryIO) -> dict[str, Any] | None:
    """Read one native message.  Return ``None`` on clean end-of-stream."""
    header = _read_exact(stream, _HEADER.size)
    if not header:
        return None
    if len(header) != _HEADER.size:
        raise ProtocolError("The message header is truncated.", "truncated_message")
    (length,) = _HEADER.unpack(header)
    if length <= 0:
        raise ProtocolError("The message is empty.", "empty_message")
    if length > MAX_MESSAGE_BYTES:
        raise ProtocolError(
            f"The message exceeds the {MAX_MESSAGE_BYTES} byte limit.",
            "message_too_large",
        )
    payload = _read_exact(stream, length)
    if len(payload) != length:
        raise ProtocolError("The message body is truncated.", "truncated_message")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"The message is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ProtocolError("The message must be a JSON object.")
    return value


def write_message(stream: BinaryIO, message: dict[str, Any]) -> None:
    stream.write(encode_message(message))
    stream.flush()


def encode_line(message: dict[str, Any]) -> bytes:
    payload = json.dumps(
        message, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ProtocolError("The message is too large.", "message_too_large")
    return payload + b"\n"


def decode_line(line: bytes) -> dict[str, Any]:
    if len(line) > MAX_MESSAGE_BYTES:
        raise ProtocolError("The message is too large.", "message_too_large")
    try:
        value = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"The bridge message is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ProtocolError("The bridge message must be a JSON object.")
    return value


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        raise ValidationError("Expected a text value.")
    text = value.strip()
    if len(text) > limit:
        raise ValidationError("A field is longer than the allowed limit.")
    if _CONTROL.search(text):
        raise ValidationError("A field contains invalid control characters.")
    return text


def require_request_id(message: dict[str, Any]) -> str:
    request_id = _text(message.get("request_id"), 128)
    if not _REQUEST_ID.match(request_id):
        raise ValidationError(
            "The request ID must be 8-128 characters from A-Z, a-z, 0-9 and .:-_",
            "invalid_request_id",
        )
    return request_id


def require_browser(message: dict[str, Any]) -> str:
    browser = _text(message.get("browser"), 16).lower()
    if browser not in SUPPORTED_BROWSERS:
        raise ValidationError(
            "The requesting browser is not supported.", "unsupported_browser"
        )
    return browser


def require_extension_id(message: dict[str, Any]) -> str:
    extension_id = _text(message.get("extension_id"), 256)
    if not _EXTENSION_ID.match(extension_id):
        raise ValidationError("The extension ID is invalid.", "invalid_extension")
    return extension_id


def validate_http_url(value: Any, field: str = "url") -> str:
    try:
        text = _text(value, MAX_URL_LENGTH)
    except ValidationError as exc:
        raise ValidationError(f"The {field} is invalid.", "invalid_url") from exc
    if not text:
        raise ValidationError(f"The {field} is empty.", "invalid_url")
    scheme = urlparse(text).scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValidationError(
            f"{field.capitalize()} scheme “{scheme or 'missing'}” is not supported. "
            "IDM only accepts HTTP and HTTPS downloads.",
            "unsupported_url",
        )
    try:
        return validate_url(text)
    except ValueError as exc:
        raise ValidationError(str(exc), "invalid_url") from exc


def validate_referrer(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        text = _text(value, MAX_URL_LENGTH)
    except ValidationError as exc:
        raise ValidationError("The referrer is invalid.", "invalid_referrer") from exc
    if not text:
        return ""
    scheme = urlparse(text).scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValidationError(
            "The referrer must be an HTTP or HTTPS address.", "invalid_referrer"
        )
    try:
        validate_url(text)
    except ValueError as exc:
        raise ValidationError("The referrer is invalid.", "invalid_referrer") from exc
    return text


def validate_filename(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        text = _text(value, MAX_FILENAME_LENGTH)
    except ValidationError as exc:
        raise ValidationError("The file name is invalid.", "invalid_filename") from exc
    if not text:
        return ""
    if any(separator in text for separator in ("/", "\\", ":")):
        raise ValidationError(
            "The file name must not contain a path.", "invalid_filename"
        )
    if text in {".", ".."}:
        raise ValidationError("The file name is invalid.", "invalid_filename")
    cleaned = sanitize_filename(text)
    if cleaned != text:
        raise ValidationError(
            "The file name contains characters that are not safe on Windows.",
            "invalid_filename",
        )
    return cleaned


def validate_mime(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        text = _text(value, 255)
    except ValidationError as exc:
        raise ValidationError("The MIME type is invalid.", "invalid_mime") from exc
    if not text:
        return ""
    if not _MIME.match(text):
        raise ValidationError("The MIME type is invalid.", "invalid_mime")
    return text.lower()


def validate_total_bytes(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("The file size is invalid.", "invalid_metadata")
    if value < 0 or value > MAX_TOTAL_BYTES:
        raise ValidationError("The file size is invalid.", "invalid_metadata")
    return value


def validate_ask_folder(value: Any) -> bool:
    """Return whether the user asked IDM to show a folder picker."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    raise ValidationError(
        "The folder-picker flag must be a boolean.", "invalid_metadata"
    )


def validate_page_title(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        return _text(value, MAX_PAGE_TITLE_LENGTH)
    except ValidationError as exc:
        raise ValidationError("The page title is invalid.", "invalid_metadata") from exc


def validate_media_kind(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        text = _text(value, 16).lower()
    except ValidationError as exc:
        raise ValidationError("The media kind is invalid.", "invalid_metadata") from exc
    if text not in MEDIA_KINDS:
        raise ValidationError("The media kind is invalid.", "invalid_metadata")
    return text


def validate_quality_label(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        return _text(value, MAX_QUALITY_LABEL_LENGTH)
    except ValidationError as exc:
        raise ValidationError(
            "The quality label is invalid.", "invalid_metadata"
        ) from exc


def validate_duration_seconds(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("The media duration is invalid.", "invalid_metadata")
    if value < 0 or value > MAX_DURATION_SECONDS:
        raise ValidationError("The media duration is invalid.", "invalid_metadata")
    return value or None


def validate_detected_by(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        text = _text(value, 32).lower()
    except ValidationError as exc:
        raise ValidationError(
            "The detection source is invalid.", "invalid_metadata"
        ) from exc
    if text not in DETECTION_SOURCES:
        raise ValidationError("The detection source is invalid.", "invalid_metadata")
    return text


def normalize_download_request(message: dict[str, Any]) -> dict[str, Any]:
    """Return a validated, normalized download request."""
    if not isinstance(message, dict):
        raise ValidationError("The request must be an object.")
    if message.get("type") != "request_download":
        raise ValidationError("Unexpected message type.", "unsupported_type")

    url = validate_http_url(message.get("url"), "download URL")
    filename = validate_filename(message.get("filename"))
    referrer = validate_referrer(message.get("referrer"))
    page_url = validate_referrer(message.get("page_url"))
    mime = validate_mime(message.get("mime"))
    total_bytes = validate_total_bytes(message.get("total_bytes"))
    ask_folder = validate_ask_folder(message.get("ask_folder"))
    page_title = validate_page_title(message.get("page_title"))
    media_kind = validate_media_kind(message.get("media_kind"))
    quality_label = validate_quality_label(message.get("quality_label"))
    duration_seconds = validate_duration_seconds(message.get("duration_seconds"))
    detected_by = validate_detected_by(message.get("detected_by"))

    return {
        "type": "request_download",
        "request_id": require_request_id(message),
        "browser": require_browser(message),
        "extension_id": require_extension_id(message),
        "client_version": _text(message.get("client_version", ""), 32),
        "url": url,
        "filename": filename,
        "referrer": referrer,
        "page_url": page_url,
        "mime": mime,
        "total_bytes": total_bytes,
        "ask_folder": ask_folder,
        "page_title": page_title,
        "media_kind": media_kind,
        "quality_label": quality_label,
        "duration_seconds": duration_seconds,
        "detected_by": detected_by,
    }


# ---------------------------------------------------------------------------
# Duplicate protection
# ---------------------------------------------------------------------------


class DuplicateTracker:
    """Bounded, time-limited cache of accepted request IDs.

    A resent interactive request (service worker restarted while waiting for
    the native response) must receive the original answer instead of adding a
    second download.  Entries also expire so a user can intentionally download
    the same URL again later.
    """

    def __init__(self, ttl_seconds: float = 300.0, limit: int = 256) -> None:
        self._ttl = ttl_seconds
        self._limit = max(16, limit)
        self._entries: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()

    def get(self, request_id: str, now: float) -> dict[str, Any] | None:
        entry = self._entries.get(request_id)
        if entry is None:
            return None
        created, response = entry
        if now - created > self._ttl:
            self._entries.pop(request_id, None)
            return None
        return dict(response)

    def put(self, request_id: str, response: dict[str, Any], now: float) -> None:
        self._entries[request_id] = (now, dict(response))
        self._entries.move_to_end(request_id)
        while len(self._entries) > self._limit:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()


def response_ok(
    request_id: str | None, message_type: str, **payload: Any
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "ok": True,
        "protocol": PROTOCOL_VERSION,
        "type": message_type,
        "request_id": request_id or "",
    }
    response.update(payload)
    return response


def response_error(
    request_id: str | None,
    code: str,
    message: str,
    retryable: bool = False,
) -> dict[str, Any]:
    return {
        "ok": False,
        "protocol": PROTOCOL_VERSION,
        "type": "error",
        "request_id": request_id or "",
        "error": {
            "code": code,
            "message": message,
            "retryable": bool(retryable),
        },
    }


__all__ = [
    "DuplicateTracker",
    "MAX_DURATION_SECONDS",
    "MAX_FILENAME_LENGTH",
    "MAX_MESSAGE_BYTES",
    "MAX_PAGE_TITLE_LENGTH",
    "MAX_QUALITY_LABEL_LENGTH",
    "MAX_TOTAL_BYTES",
    "MAX_URL_LENGTH",
    "MEDIA_KINDS",
    "PROTOCOL_VERSION",
    "ProtocolError",
    "REQUEST_TYPES",
    "SUPPORTED_BROWSERS",
    "ValidationError",
    "decode_line",
    "encode_line",
    "encode_message",
    "normalize_download_request",
    "read_message",
    "require_browser",
    "require_extension_id",
    "require_request_id",
    "response_error",
    "response_ok",
    "validate_detected_by",
    "validate_duration_seconds",
    "validate_filename",
    "validate_http_url",
    "validate_media_kind",
    "validate_mime",
    "validate_page_title",
    "validate_ask_folder",
    "validate_quality_label",
    "validate_referrer",
    "validate_total_bytes",
    "write_message",
]
