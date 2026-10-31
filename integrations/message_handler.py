"""Message handling for the native messaging host.

The host validates every message itself rather than trusting the extension or
the registry entry.  It then forwards the small set of supported operations to
the running IDM desktop process over the authenticated loopback bridge.
"""

from __future__ import annotations

import json
import logging
import platform
import socket
import time
from pathlib import Path
from typing import Any, Mapping

from . import NATIVE_HOST_VERSION, PROTOCOL_VERSION
from .browser_detector import browser_display_name, detect_calling_browser
from .browser_registry import is_allowed_extension
from .paths import bridge_file
from .protocol import (
    DuplicateTracker,
    ProtocolError,
    ValidationError,
    decode_line,
    encode_line,
    normalize_download_request,
    require_browser,
    require_extension_id,
    require_request_id,
    response_error,
    response_ok,
)

logger = logging.getLogger(__name__)

BRIDGE_CONNECT_TIMEOUT = 5.0
STATUS_TIMEOUT = 8.0
DOWNLOAD_TIMEOUT = 120.0


class BridgeUnavailable(RuntimeError):
    """IDM is not running or did not publish a usable endpoint."""


class BridgeClient:
    """Small JSON-over-loopback client with no third-party dependencies."""

    def __init__(self, descriptor: Path | None = None) -> None:
        self._descriptor = Path(descriptor) if descriptor else bridge_file()

    def read_descriptor(self) -> dict[str, Any]:
        try:
            if not self._descriptor.is_file():
                raise BridgeUnavailable(
                    "IDM is not running. Start IDM and try again."
                )
            if self._descriptor.stat().st_size > 64 * 1024:
                raise BridgeUnavailable("The IDM bridge descriptor is invalid.")
            payload = json.loads(self._descriptor.read_text(encoding="utf-8"))
        except BridgeUnavailable:
            raise
        except (OSError, ValueError) as exc:
            raise BridgeUnavailable(
                "The IDM bridge endpoint could not be read. Restart IDM."
            ) from exc
        if not isinstance(payload, dict):
            raise BridgeUnavailable("The IDM bridge descriptor is invalid.")
        port = payload.get("port")
        token = payload.get("token")
        protocol = payload.get("protocol")
        if (
            not isinstance(port, int)
            or isinstance(port, bool)
            or not 1 <= port <= 65535
            or not isinstance(token, str)
            or not 16 <= len(token) <= 256
        ):
            raise BridgeUnavailable("The IDM bridge descriptor is invalid.")
        if protocol != PROTOCOL_VERSION:
            raise BridgeUnavailable(
                "IDM and the browser extension use different protocol versions. "
                "Update IDM and the extension."
            )
        return payload

    def request(self, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        descriptor = self.read_descriptor()
        port = int(descriptor["port"])
        message = dict(payload)
        message["token"] = descriptor["token"]
        data = encode_line(message)
        try:
            with socket.create_connection(
                ("127.0.0.1", port), timeout=BRIDGE_CONNECT_TIMEOUT
            ) as connection:
                connection.settimeout(timeout)
                connection.sendall(data)
                buffer = bytearray()
                while b"\n" not in buffer:
                    chunk = connection.recv(65536)
                    if not chunk:
                        break
                    buffer.extend(chunk)
                    if len(buffer) > 1024 * 1024:
                        raise BridgeUnavailable(
                            "IDM returned an oversized response."
                        )
        except (ConnectionRefusedError, ConnectionResetError, TimeoutError, OSError) as exc:
            raise BridgeUnavailable(
                "IDM is not reachable. Start IDM and try again."
            ) from exc

        line, _, _ = bytes(buffer).partition(b"\n")
        if not line:
            raise BridgeUnavailable("IDM closed the connection without a response.")
        try:
            response = decode_line(line)
        except ProtocolError as exc:
            raise BridgeUnavailable("IDM returned an invalid response.") from exc
        return response


class NativeHostMessageHandler:
    def __init__(
        self,
        client: BridgeClient | None = None,
        environ: Mapping[str, str] | None = None,
        detected_browser: str | None = None,
    ) -> None:
        self._client = client or BridgeClient()
        self._environ = environ
        self._dedupe = DuplicateTracker()
        self._detected_browser = (
            detected_browser
            if detected_browser is not None
            else detect_calling_browser()
        )

    @property
    def detected_browser(self) -> str:
        return self._detected_browser

    def handle(self, message: dict[str, Any]) -> dict[str, Any]:
        request_id: str | None = None
        try:
            if not isinstance(message, dict):
                raise ValidationError("The message must be an object.")
            message_type = message.get("type")
            if not isinstance(message_type, str):
                raise ValidationError("The message has no type.", "invalid_message")

            value = message.get("request_id")
            request_id = value if isinstance(value, str) else None
            browser = require_browser(message)
            extension_id = require_extension_id(message)

            if self._detected_browser and self._detected_browser != browser:
                raise ValidationError(
                    "The browser that launched IDM does not match the request.",
                    "browser_mismatch",
                )
            if not is_allowed_extension(browser, extension_id, self._environ):
                raise ValidationError(
                    "This extension is not allowed to control IDM.",
                    "unauthorized_extension",
                )

            if message_type in {"hello", "status"}:
                require_request_id(message)
                return self._status(request_id, browser, extension_id)
            if message_type == "request_download":
                return self._download(message, request_id)
            if message_type in {"open_idm", "open_settings"}:
                require_request_id(message)
                return self._forward(request_id, message_type, message)
            if message_type == "list_downloads":
                require_request_id(message)
                return self._forward(request_id, message_type, message)
            raise ValidationError(
                f"Unsupported message type “{message_type}”.",
                "unsupported_type",
            )
        except ValidationError as exc:
            logger.warning("Rejected native message: %s", exc)
            return response_error(request_id, exc.code, str(exc))
        except ProtocolError as exc:
            return response_error(request_id, exc.code, str(exc))
        except Exception:
            logger.exception("Unexpected native host failure")
            return response_error(
                request_id,
                "internal_error",
                "The IDM native host could not process the request.",
            )

    # ------------------------------------------------------------------ handlers
    def _status(
        self, request_id: str | None, browser: str, extension_id: str
    ) -> dict[str, Any]:
        base = {
            "native_host_version": NATIVE_HOST_VERSION,
            "native_protocol": PROTOCOL_VERSION,
            "browser": browser,
            "browser_display": browser_display_name(browser),
            "detected_browser": self._detected_browser,
            "platform": platform.system(),
            "downloads": [],
        }
        try:
            response = self._client.request(
                {
                    "type": "status",
                    "request_id": request_id or "status-request",
                    "browser": browser,
                    "extension_id": extension_id,
                },
                STATUS_TIMEOUT,
            )
        except BridgeUnavailable as exc:
            base["status"] = {
                "idm_running": False,
                "message": str(exc),
            }
            base["bridge_available"] = False
            return response_ok(
                request_id,
                "status",
                connected=False,
                **base,
            )
        base["bridge_available"] = True
        base["connected"] = True
        base["status"] = response.get("status", {}) if response.get("ok") else {}
        downloads = response.get("downloads")
        if response.get("ok") and isinstance(downloads, list):
            base["downloads"] = downloads
        if not response.get("ok"):
            base["status"] = {
                "idm_running": False,
                "message": _error_message(response),
            }
            base["connected"] = False
        return response_ok(request_id, "status", **base)

    def _download(
        self, message: dict[str, Any], request_id: str | None
    ) -> dict[str, Any]:
        normalized = normalize_download_request(message)
        request_id = normalized["request_id"]
        now = time.monotonic()
        cached = self._dedupe.get(request_id, now)
        if cached is not None:
            return cached

        payload = dict(normalized)
        payload["type"] = "request_download"
        try:
            response = self._client.request(payload, DOWNLOAD_TIMEOUT)
        except BridgeUnavailable as exc:
            return response_error(
                request_id, "idm_not_running", str(exc), retryable=True
            )
        decorated = _decorate(response)
        if response.get("ok") and response.get("type") == "download_accepted":
            self._dedupe.put(request_id, decorated, now)
        return decorated

    def _forward(
        self,
        request_id: str | None,
        message_type: str,
        message: dict[str, Any],
    ) -> dict[str, Any]:
        browser = require_browser(message)
        payload = {
            "type": message_type,
            "request_id": request_id or f"{message_type}-request",
            "browser": browser,
            "extension_id": require_extension_id(message),
        }
        if message_type == "list_downloads":
            payload["limit"] = message.get("limit", 25)
        try:
            response = self._client.request(
                payload,
                STATUS_TIMEOUT if message_type != "list_downloads" else 15.0,
            )
        except BridgeUnavailable as exc:
            return response_error(
                request_id, "idm_not_running", str(exc), retryable=True
            )
        return _decorate(response)


def _error_message(response: dict[str, Any]) -> str:
    error = response.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or "IDM rejected the request.")
    return "IDM rejected the request."


def _decorate(response: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(response, dict):
        return response_error(None, "invalid_response", "Invalid IDM response.")
    decorated = dict(response)
    decorated.setdefault("native_host_version", NATIVE_HOST_VERSION)
    decorated.setdefault("native_protocol", PROTOCOL_VERSION)
    return decorated


__all__ = [
    "BridgeClient",
    "BridgeUnavailable",
    "NativeHostMessageHandler",
]
