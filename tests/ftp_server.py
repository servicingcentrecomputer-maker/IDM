"""A minimal FTP server for the engine tests.

Only the subset of RFC 959 that :mod:`idm.engine.worker` uses is implemented:
USER/PASS login, TYPE I, PASV, SIZE, MDTM, REST, RETR and QUIT.  Keeping it in
the repository avoids a third-party test dependency while still exercising the
real ``ftplib`` client, including passive-mode data connections and resume.
"""

from __future__ import annotations

import socket
import threading
from datetime import UTC, datetime
from pathlib import Path


def ftp_payload(size: int) -> bytes:
    from tests.http_server import payload

    return payload(size)


class _Session:
    def __init__(self, server: "MiniFtpServer", conn: socket.socket) -> None:
        self.server = server
        self.conn = conn
        self.file = conn.makefile("rwb")
        self.user = ""
        self.data: socket.socket | None = None
        self.rest: int | None = None
        self.authenticated = server.username is None

    def reply(self, code: int, text: str) -> None:
        self.file.write(f"{code} {text}\r\n".encode())
        self.file.flush()

    def close_data(self) -> None:
        if self.data is not None:
            try:
                self.data.close()
            except OSError:
                pass
            self.data = None

    def serve(self) -> None:
        self.reply(220, "IDM test FTP ready")
        try:
            while True:
                line = self.file.readline()
                if not line:
                    return
                try:
                    text = line.decode("utf-8", "replace").rstrip("\r\n")
                except Exception:  # pragma: no cover - defensive
                    return
                if not text:
                    continue
                command, _, argument = text.partition(" ")
                if self.handle(command.upper(), argument.strip()) == "quit":
                    return
        except (OSError, socket.timeout):  # pragma: no cover - client vanished
            return
        finally:
            self.close_data()
            try:
                self.conn.close()
            except OSError:
                pass

    def resolve(self, argument: str) -> Path | None:
        name = argument.lstrip("/")
        if not name:
            return None
        candidate = (self.server.root / name).resolve()
        try:
            candidate.relative_to(self.server.root.resolve())
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    def handle(self, command: str, argument: str) -> str | None:
        if command == "USER":
            self.user = argument
            if self.server.username is None:
                self.authenticated = True
            self.reply(331, "Password required")
            return None
        if command == "PASS":
            expected = self.server.username, self.server.password
            if self.server.username is None or (self.user, argument) == expected:
                self.authenticated = True
                self.reply(230, "Logged in")
            else:
                self.reply(530, "Not logged in")
            return None
        if command == "QUIT":
            self.reply(221, "Goodbye")
            return "quit"
        if not self.authenticated:
            self.reply(530, "Please log in first")
            return None
        if command == "SYST":
            self.reply(215, "UNIX Type: L8")
        elif command == "FEAT":
            self.file.write(b"211-Features:\r\n SIZE\r\n MDTM\r\n REST STREAM\r\n211 End\r\n")
            self.file.flush()
        elif command in ("PWD", "XPWD"):
            self.reply(257, '"/"')
        elif command in ("CWD", "CDUP"):
            self.reply(250, "OK")
        elif command == "TYPE":
            self.reply(200, "Type set")
        elif command == "NOOP":
            self.reply(200, "OK")
        elif command == "PASV":
            self._pasv()
        elif command == "SIZE":
            path = self.resolve(argument)
            if path is None:
                self.reply(550, "Could not open file")
            else:
                self.reply(213, str(path.stat().st_size))
        elif command == "MDTM":
            path = self.resolve(argument)
            if path is None:
                self.reply(550, "Could not open file")
            else:
                stamp = datetime.fromtimestamp(
                    path.stat().st_mtime, UTC
                ).strftime("%Y%m%d%H%M%S")
                self.reply(213, stamp)
        elif command == "REST":
            if not self.server.supports_rest:
                self.reply(500, '"REST": command not understood')
                return None
            try:
                self.rest = int(argument)
            except ValueError:
                self.reply(501, "Invalid restart position")
                return None
            self.reply(350, "Restarting")
        elif command == "RETR":
            self._retr(argument)
        else:
            self.reply(502, "Command not implemented")
        return None

    def _pasv(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(10)
        self.server.listeners.append(listener)
        host, port = listener.getsockname()
        parts = host.split(".")
        self.reply(
            227,
            f"Entering Passive Mode ({','.join(parts)},{port // 256},{port % 256}).",
        )
        try:
            conn, _ = listener.accept()
            conn.settimeout(10)
            self.close_data()
            self.data = conn
        except OSError:
            self.reply(425, "Cannot open data connection")

    def _retr(self, argument: str) -> None:
        if self.data is None:
            self.reply(425, "No data connection")
            return
        path = self.resolve(argument)
        if path is None:
            self.rest = None
            self.reply(550, "Failed to open file")
            return
        data = path.read_bytes()
        offset = self.rest or 0
        self.rest = None
        body = data[offset:]
        if self.server.short_by is not None:
            body = body[: self.server.short_by]
        self.reply(150, "Opening data connection")
        try:
            self.data.sendall(body)
        except OSError:  # pragma: no cover - client aborted
            self.close_data()
            return
        self.close_data()
        self.reply(226, "Transfer complete")


class MiniFtpServer:
    """Serves ``root`` over plain FTP on 127.0.0.1."""

    def __init__(
        self,
        root: Path,
        username: str | None = None,
        password: str | None = None,
        supports_rest: bool = True,
        short_by: int | None = None,
    ) -> None:
        self.root = Path(root)
        self.username = username
        self.password = password
        self.supports_rest = supports_rest
        self.short_by = short_by
        self.listeners: list[socket.socket] = []
        self._accept: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self.port = 0

    def start(self) -> "MiniFtpServer":
        self._accept = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._accept.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._accept.bind(("127.0.0.1", 0))
        self._accept.listen(8)
        self._accept.settimeout(0.5)
        self.port = self._accept.getsockname()[1]
        self._thread = threading.Thread(target=self._loop, name="ftptest", daemon=True)
        self._thread.start()
        return self

    def _loop(self) -> None:
        assert self._accept is not None
        while not self._stopping.is_set():
            try:
                conn, _ = self._accept.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            conn.settimeout(20)
            session = _Session(self, conn)
            threading.Thread(
                target=session.serve, name="ftptest-session", daemon=True
            ).start()

    def url(self, path: str) -> str:
        return f"ftp://127.0.0.1:{self.port}/{path.lstrip('/')}"

    def authenticated_url(self, path: str) -> str:
        if self.username is None:
            return self.url(path)
        return f"ftp://{self.username}@127.0.0.1:{self.port}/{path.lstrip('/')}"

    def stop(self) -> None:
        self._stopping.set()
        for listener in self.listeners:
            try:
                listener.close()
            except OSError:
                pass
        if self._accept is not None:
            try:
                self._accept.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=3)
