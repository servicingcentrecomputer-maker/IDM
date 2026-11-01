"""Asynchronous link inspection used by the Download File Info dialog.

A HEAD request is tried first because it is the cheapest way to learn the size,
type and validators of a resource.  Many servers reject or mis-handle HEAD, so
the probe then falls back to ``GET`` with ``Range: bytes=0-0`` and aborts as
soon as the response headers arrive.  The fallback therefore never downloads
the file just to inspect it, and it also works for servers that ignore Range:
the full Content-Length is read from the headers and the body is discarded.

Every request follows at most eight same-or-higher-security redirects, has a
hard timeout and is cancelled when the dialog closes.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from ..constants import APP_USER_AGENT
from .url_utils import (
    InvalidUrlError,
    filename_from_content_disposition,
    parse_content_range_total,
    validate_url,
)

_OVERALL_TIMEOUT_MS = 20_000
_PER_REQUEST_TIMEOUT_MS = 9_000
_MAX_REDIRECTS = 8

# Statuses that commonly mean "HEAD is not supported / not allowed" rather than
# "the resource does not exist".  A Range GET is worth trying for these.
_HEAD_FALLBACK_STATUSES = {400, 403, 405, 406, 501, 502, 503, 504}


@dataclass(frozen=True)
class ProbeResult:
    final_url: str
    filename: str | None
    total_bytes: int | None
    content_type: str
    range_supported: bool
    requested_url: str = ""
    status_code: int | None = None
    etag: str = ""
    last_modified: str = ""
    accept_ranges: str = ""
    content_disposition: str = ""
    method: str = ""

    @property
    def size_known(self) -> bool:
        return self.total_bytes is not None

    @property
    def status_text(self) -> str:
        if self.status_code is None:
            return "Unknown"
        reason = _HTTP_REASONS.get(self.status_code, "")
        return f"HTTP {self.status_code} {reason}".strip()


class LinkProbe(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._manager = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None
        self._request_url = ""
        self._phase = ""
        self._head_result: ProbeResult | None = None
        self._get_captured = False
        self._get_error_status: int | None = None
        self._last_error = ""

        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.setInterval(_OVERALL_TIMEOUT_MS)
        self._timeout.timeout.connect(self._on_timeout)

    # ------------------------------------------------------------------ public
    def start(self, url: str) -> None:
        self.abort()
        try:
            normalized = validate_url(url)
        except InvalidUrlError as exc:
            self.failed.emit(str(exc))
            return

        self._request_url = normalized
        self._head_result = None
        self._get_captured = False
        self._get_error_status = None
        self._last_error = ""
        self._timeout.start()
        self._start_head()

    def abort(self) -> None:
        self._timeout.stop()
        reply = self._reply
        self._reply = None
        self._phase = ""
        if reply is not None:
            try:
                reply.abort()
            except RuntimeError:
                pass
            reply.deleteLater()

    # ------------------------------------------------------------------ requests
    def _request(self) -> QNetworkRequest:
        request = QNetworkRequest(QUrl(self._request_url))
        request.setRawHeader(b"User-Agent", APP_USER_AGENT.encode("ascii", "ignore"))
        request.setRawHeader(b"Accept", b"*/*")
        request.setRawHeader(b"Accept-Encoding", b"identity")
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )
        request.setMaximumRedirectsAllowed(_MAX_REDIRECTS)
        request.setTransferTimeout(_PER_REQUEST_TIMEOUT_MS)
        return request

    def _start_head(self) -> None:
        self._phase = "head"
        reply = self._manager.head(self._request())
        self._reply = reply
        reply.finished.connect(lambda r=reply: self._on_head_finished(r))

    def _start_get(self, reason: str = "") -> None:
        self._last_error = reason or self._last_error
        self._phase = "get"
        self._get_captured = False
        request = self._request()
        request.setRawHeader(b"Range", b"bytes=0-0")
        reply = self._manager.get(request)
        self._reply = reply
        reply.metaDataChanged.connect(lambda r=reply: self._on_get_metadata(r))
        reply.finished.connect(lambda r=reply: self._on_get_finished(r))

    # ------------------------------------------------------------------ HEAD
    def _on_head_finished(self, reply: QNetworkReply) -> None:
        if reply is not self._reply:
            reply.deleteLater()
            return
        self._reply = None
        status = _status_of(reply)
        error = reply.error()

        if error != QNetworkReply.NetworkError.NoError and status is None:
            reason = _friendly_error(error, reply.errorString())
            reply.deleteLater()
            self._start_get(reason)
            return

        if status is not None and status >= 400:
            reply.deleteLater()
            if status in _HEAD_FALLBACK_STATUSES:
                self._start_get(_http_message(status))
            else:
                self._fail(_http_message(status))
            return

        final_url = reply.url().toString()
        if QUrl(final_url).scheme().lower() not in {"http", "https"}:
            reply.deleteLater()
            self._fail("The server redirected to an unsupported address.")
            return

        result = _result_from(reply, "HEAD")
        reply.deleteLater()
        if result.total_bytes is None:
            # HEAD was accepted but did not reveal the size; a ranged GET can
            # still report Content-Range without transferring the file.
            self._head_result = result
            self._start_get("The server did not report a file size.")
            return
        self._complete(result)

    # ------------------------------------------------------------------ Range GET
    def _on_get_metadata(self, reply: QNetworkReply) -> None:
        if reply is not self._reply or self._get_captured:
            return
        status = _status_of(reply)
        if status is None:
            return

        if status == 416:
            # "Range Not Satisfiable" normally means an empty file.  The total
            # size in Content-Range is authoritative when present.
            self._get_captured = True
            result = _result_from(reply, "GET")
            self._reply = None
            reply.abort()
            reply.deleteLater()
            self._complete(result)
            return

        if status >= 400:
            self._get_captured = True
            self._get_error_status = status
            self._reply = None
            reply.abort()
            reply.deleteLater()
            if self._head_result is not None:
                self._complete(self._head_result)
            else:
                self._fail(_http_message(status))
            return

        self._get_captured = True
        result = _result_from(reply, "GET")
        self._reply = None
        reply.abort()
        reply.deleteLater()
        self._complete(result)

    def _on_get_finished(self, reply: QNetworkReply) -> None:
        if reply is not self._reply:
            reply.deleteLater()
            return
        if self._get_captured:
            return
        self._reply = None
        status = _status_of(reply)
        error = reply.error()
        reply.deleteLater()
        if self._head_result is not None:
            self._complete(self._head_result)
            return
        if status is not None and status >= 400:
            self._fail(_http_message(status))
            return
        self._fail(_friendly_error(error, self._last_error or reply.errorString()))

    # ------------------------------------------------------------------ results
    def _complete(self, result: ProbeResult) -> None:
        self._timeout.stop()
        self._phase = ""
        self._head_result = None
        self.finished.emit(result)

    def _fail(self, message: str) -> None:
        self._timeout.stop()
        self._phase = ""
        self._head_result = None
        self.failed.emit(message or "The link could not be inspected.")

    def _on_timeout(self) -> None:
        self.abort()
        self.failed.emit("The server took too long to respond.")


def _status_of(reply: QNetworkReply) -> int | None:
    status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
    if status is None:
        return None
    try:
        return int(status)
    except (TypeError, ValueError):
        return None


def _header(reply: QNetworkReply, name: bytes) -> str:
    # PySide6 exposes rawHeader() with a str argument, unlike the C++ API.
    try:
        header_name = name.decode("latin-1") if isinstance(name, bytes) else str(name)
        value = reply.rawHeader(header_name)
    except (TypeError, ValueError, AttributeError):
        return ""
    if value is None:
        return ""
    try:
        return bytes(value).decode("latin-1", errors="replace")
    except (TypeError, ValueError):
        return ""


def _result_from(reply: QNetworkReply, method: str) -> ProbeResult:
    status = _status_of(reply)
    disposition = _header(reply, b"Content-Disposition")
    filename = filename_from_content_disposition(disposition)
    accept_ranges = _header(reply, b"Accept-Ranges")
    content_range = _header(reply, b"Content-Range")

    total: int | None = None
    if status == 206 or status == 416:
        total = parse_content_range_total(content_range)
    if total is None:
        content_length = reply.header(QNetworkRequest.KnownHeaders.ContentLengthHeader)
        try:
            if content_length is not None and int(content_length) >= 0:
                total = int(content_length)
        except (TypeError, ValueError):
            total = None
    if status == 416 and total is None:
        total = 0

    content_type = str(
        reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader) or ""
    )
    content_type = content_type.split(";")[0].strip()

    range_supported = status == 206 or "bytes" in accept_ranges.lower()

    return ProbeResult(
        final_url=reply.url().toString(),
        filename=filename,
        total_bytes=total,
        content_type=content_type,
        range_supported=range_supported,
        requested_url=reply.request().url().toString(),
        status_code=status,
        etag=_header(reply, b"ETag"),
        last_modified=_header(reply, b"Last-Modified"),
        accept_ranges=accept_ranges,
        content_disposition=disposition,
        method=method,
    )


_HTTP_REASONS = {
    200: "OK",
    204: "No Content",
    206: "Partial Content",
    301: "Moved Permanently",
    302: "Found",
    304: "Not Modified",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    406: "Not Acceptable",
    407: "Proxy Authentication Required",
    408: "Request Timeout",
    410: "Gone",
    416: "Range Not Satisfiable",
    429: "Too Many Requests",
    500: "Internal Server Error",
    501: "Not Implemented",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
}


def _http_message(status: int) -> str:
    reason = _HTTP_REASONS.get(status, "HTTP error")
    return f"The server responded with HTTP {status} ({reason})."


def _friendly_error(error: QNetworkReply.NetworkError, fallback: str) -> str:
    messages = {
        QNetworkReply.NetworkError.HostNotFoundError: "Could not find that server.",
        QNetworkReply.NetworkError.ConnectionRefusedError: "The server refused the connection.",
        QNetworkReply.NetworkError.RemoteHostClosedError: "The server closed the connection.",
        QNetworkReply.NetworkError.TimeoutError: "The server took too long to respond.",
        QNetworkReply.NetworkError.OperationCanceledError: "The request was cancelled.",
        QNetworkReply.NetworkError.SslHandshakeFailedError: (
            "The server certificate could not be verified."
        ),
        QNetworkReply.NetworkError.ContentNotFoundError: "The link returned Not Found (404).",
        QNetworkReply.NetworkError.ProtocolUnknownError: "The link uses an unsupported protocol.",
        QNetworkReply.NetworkError.TemporaryNetworkFailureError: (
            "The network connection was interrupted."
        ),
        QNetworkReply.NetworkError.NetworkSessionFailedError: (
            "The network connection could not be opened."
        ),
    }
    return messages.get(error, fallback or "The link could not be inspected.")
