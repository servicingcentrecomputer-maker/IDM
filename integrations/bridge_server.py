"""Authenticated loopback bridge between the native host and IDM.

The native messaging host is a separate process launched by the browser, while
downloads must be added by the running desktop application on its GUI thread.
The desktop application therefore listens on a random loopback port and
publishes the port and a per-run random token in
``%APPDATA%\\IDM Download Manager\\runtime\\browser_bridge.json`` (mode 0600
where the platform supports it).  The native host reads that file for every
request, so an IDM restart is picked up without restarting the browser.

This is deliberately *not* an unauthenticated local HTTP server: only
127.0.0.1 is bound, every request must carry the token, malformed or oversized
frames close the connection, and no file contents or commands are accepted.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QHostAddress, QTcpServer, QTcpSocket

from idm.version import APP_VERSION

from . import NATIVE_HOST_VERSION, PROTOCOL_VERSION
from .paths import bridge_file
from .protocol import MAX_MESSAGE_BYTES, ProtocolError, decode_line, encode_line

logger = logging.getLogger(__name__)

MAX_AUTH_FAILURES = 4
MAX_CONNECTIONS = 24
MAX_PENDING_BYTES = MAX_MESSAGE_BYTES * 2

Respond = Callable[[dict[str, Any]], None]
RequestHandler = Callable[[dict[str, Any], Respond], None]


class _Connection:
    __slots__ = ("socket", "buffer", "failures")

    def __init__(self, socket: QTcpSocket) -> None:
        self.socket = socket
        self.buffer = bytearray()
        self.failures = 0


class BrowserBridgeServer(QObject):
    """QTcpServer that forwards authenticated JSON requests to a handler."""

    started = Signal(int)
    stopped = Signal()
    failed = Signal(str)
    request_received = Signal(str)

    def __init__(
        self,
        handler: RequestHandler,
        parent: QObject | None = None,
        descriptor_path: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self._handler = handler
        self._descriptor_path = Path(descriptor_path) if descriptor_path else bridge_file()
        self._token = ""
        self._port = 0
        self._connections: dict[QTcpSocket, _Connection] = {}
        self._server = QTcpServer(self)
        self._server.newConnection.connect(self._on_new_connection)

    # ------------------------------------------------------------------ state
    @property
    def port(self) -> int:
        return self._port

    @property
    def token(self) -> str:
        return self._token

    @property
    def is_running(self) -> bool:
        return bool(self._server.isListening() and self._port and self._token)

    @property
    def descriptor_path(self) -> Path:
        return self._descriptor_path

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> bool:
        if self.is_running:
            return True
        self._token = secrets.token_urlsafe(32)
        self._port = 0
        if not self._server.listen(QHostAddress.SpecialAddress.LocalHost, 0):
            message = self._server.errorString() or "unknown error"
            self._token = ""
            logger.warning("Browser bridge could not listen: %s", message)
            self.failed.emit(f"Browser integration could not start: {message}")
            return False

        self._port = int(self._server.serverPort())
        try:
            self._write_descriptor()
        except OSError as exc:
            logger.warning("Could not publish the browser bridge descriptor: %s", exc)
            self.stop()
            self.failed.emit(
                "Browser integration could not publish its local endpoint."
            )
            return False

        logger.info(
            "Browser bridge listening on 127.0.0.1:%d (native host %s)",
            self._port,
            NATIVE_HOST_VERSION,
        )
        self.started.emit(self._port)
        return True

    def stop(self) -> None:
        for socket in list(self._connections):
            try:
                socket.abort()
                socket.deleteLater()
            except RuntimeError:
                pass
        self._connections.clear()
        if self._server.isListening():
            self._server.close()
        self._remove_descriptor()
        was_running = bool(self._port)
        self._port = 0
        self._token = ""
        if was_running:
            self.stopped.emit()
            logger.info("Browser bridge stopped")

    def _write_descriptor(self) -> None:
        payload = {
            "protocol": PROTOCOL_VERSION,
            "port": self._port,
            "token": self._token,
            "pid": os.getpid(),
            "app_version": APP_VERSION,
            "native_host_version": NATIVE_HOST_VERSION,
            "started_at": datetime.now().isoformat(timespec="seconds"),
        }
        path = self._descriptor_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, path)

    def _remove_descriptor(self) -> None:
        path = self._descriptor_path
        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("token") == self._token:
                    path.unlink(missing_ok=True)
        except (OSError, ValueError):
            path.unlink(missing_ok=True)

    # ------------------------------------------------------------------ sockets
    def _on_new_connection(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                break
            if len(self._connections) >= MAX_CONNECTIONS:
                socket.abort()
                socket.deleteLater()
                continue
            self._connections[socket] = _Connection(socket)
            socket.readyRead.connect(lambda s=socket: self._on_ready_read(s))
            socket.disconnected.connect(lambda s=socket: self._on_disconnected(s))

    def _on_disconnected(self, socket: QTcpSocket) -> None:
        self._connections.pop(socket, None)
        socket.deleteLater()

    def _close(self, socket: QTcpSocket) -> None:
        self._connections.pop(socket, None)
        try:
            socket.abort()
            socket.deleteLater()
        except RuntimeError:
            pass

    def _on_ready_read(self, socket: QTcpSocket) -> None:
        connection = self._connections.get(socket)
        if connection is None:
            return
        chunk = bytes(socket.readAll())
        if not chunk:
            return
        connection.buffer.extend(chunk)
        if len(connection.buffer) > MAX_PENDING_BYTES:
            logger.warning("Browser bridge rejected an oversized frame")
            self._close(socket)
            return

        while b"\n" in connection.buffer:
            line, _, remainder = connection.buffer.partition(b"\n")
            connection.buffer = bytearray(remainder)
            if not line.strip():
                continue
            self._handle_line(connection, bytes(line))

    def _handle_line(self, connection: _Connection, line: bytes) -> None:
        socket = connection.socket
        try:
            request = decode_line(line)
        except ProtocolError as exc:
            connection.failures += 1
            self._send(socket, _bridge_error(None, exc.code, str(exc)))
            if connection.failures >= MAX_AUTH_FAILURES:
                self._close(socket)
            return

        token = request.get("token")
        if not isinstance(token, str) or not hmac.compare_digest(token, self._token):
            connection.failures += 1
            logger.warning("Browser bridge rejected a request with a bad token")
            self._send(
                socket,
                _bridge_error(
                    request.get("request_id") if isinstance(request.get("request_id"), str) else None,
                    "unauthorized",
                    "The IDM bridge token is invalid. Restart IDM and try again.",
                ),
            )
            if connection.failures >= MAX_AUTH_FAILURES:
                self._close(socket)
            return
        connection.failures = 0

        request_type = request.get("type")
        if isinstance(request_type, str):
            self.request_received.emit(request_type)

        responded = False

        def respond(response: dict[str, Any]) -> None:
            nonlocal responded
            if responded:
                return
            responded = True
            if not isinstance(response, dict):
                response = _bridge_error(
                    request.get("request_id") if isinstance(request.get("request_id"), str) else None,
                    "internal_error",
                    "IDM produced an invalid response.",
                )
            self._send(socket, response)

        try:
            self._handler(request, respond)
        except Exception:
            logger.exception("Browser bridge handler failed")
            respond(
                _bridge_error(
                    request.get("request_id") if isinstance(request.get("request_id"), str) else None,
                    "internal_error",
                    "IDM could not process the browser request.",
                )
            )

    def _send(self, socket: QTcpSocket, response: dict[str, Any]) -> None:
        if socket.state() != QTcpSocket.SocketState.ConnectedState:
            return
        try:
            socket.write(encode_line(response))
            socket.flush()
        except (OSError, RuntimeError):
            logger.debug("Could not write a bridge response", exc_info=True)


def _bridge_error(
    request_id: str | None, code: str, message: str, retryable: bool = False
) -> dict[str, Any]:
    return {
        "ok": False,
        "protocol": PROTOCOL_VERSION,
        "type": "error",
        "request_id": request_id or "",
        "error": {"code": code, "message": message, "retryable": bool(retryable)},
    }


__all__ = ["BrowserBridgeServer"]
