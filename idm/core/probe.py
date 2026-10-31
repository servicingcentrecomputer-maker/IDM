"""Asynchronous HEAD probe used to enrich the Add Download dialog."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from ..constants import APP_USER_AGENT
from .url_utils import InvalidUrlError, filename_from_content_disposition, validate_url

_TIMEOUT_MS = 10_000


@dataclass(frozen=True)
class ProbeResult:
    final_url: str
    filename: str | None
    total_bytes: int | None
    content_type: str
    range_supported: bool


class LinkProbe(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._manager = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None
        self._request_url = ""
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.setInterval(_TIMEOUT_MS)
        self._timeout.timeout.connect(self._on_timeout)

    def start(self, url: str) -> None:
        self.abort()
        try:
            normalized = validate_url(url)
        except InvalidUrlError as exc:
            self.failed.emit(str(exc))
            return

        self._request_url = normalized
        request = QNetworkRequest(QUrl(normalized))
        request.setRawHeader(b"User-Agent", APP_USER_AGENT.encode("ascii", "ignore"))
        request.setRawHeader(b"Accept", b"*/*")
        request.setRawHeader(b"Accept-Encoding", b"identity")
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )
        request.setMaximumRedirectsAllowed(8)
        request.setTransferTimeout(9000)

        reply = self._manager.head(request)
        self._reply = reply
        reply.finished.connect(self._on_finished)
        self._timeout.start()

    def abort(self) -> None:
        self._timeout.stop()
        reply = self._reply
        self._reply = None
        self._request_url = ""
        if reply is not None:
            try:
                reply.finished.disconnect()
            except (RuntimeError, TypeError):
                pass
            reply.abort()
            reply.deleteLater()

    def _on_timeout(self) -> None:
        self.abort()
        self.failed.emit("The server took too long to respond.")

    def _on_finished(self) -> None:
        reply = self._reply
        if reply is None:
            return
        self._reply = None
        self._timeout.stop()
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.failed.emit(_friendly_error(reply.error(), reply.errorString()))
                return

            final_url = reply.url().toString()
            if QUrl(final_url).scheme().lower() not in {"http", "https"}:
                self.failed.emit("The server redirected to an unsupported address.")
                return

            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            if status is not None and int(status) >= 400:
                self.failed.emit(f"The server responded with HTTP {int(status)}.")
                return

            raw_disposition = bytes(reply.rawHeader("Content-Disposition")).decode(
                "latin-1", errors="replace"
            )
            filename = filename_from_content_disposition(raw_disposition)

            total: int | None = None
            content_length = reply.header(QNetworkRequest.KnownHeaders.ContentLengthHeader)
            try:
                if content_length is not None and int(content_length) >= 0:
                    total = int(content_length)
            except (TypeError, ValueError):
                total = None

            content_type = str(reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader) or "")
            content_type = content_type.split(";")[0].strip()
            accept_ranges = bytes(reply.rawHeader("Accept-Ranges")).decode(
                "latin-1", errors="replace"
            )
            range_supported = (
                status is not None and int(status) == 206
            ) or "bytes" in accept_ranges.lower()

            self.finished.emit(
                ProbeResult(
                    final_url=final_url,
                    filename=filename,
                    total_bytes=total,
                    content_type=content_type,
                    range_supported=range_supported,
                )
            )
        finally:
            reply.deleteLater()


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
    }
    return messages.get(error, fallback or "The link could not be inspected.")
