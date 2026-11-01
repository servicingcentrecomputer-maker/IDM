"""Local HTTP server used by the download engine tests.

Each route serves deterministic bytes so tests can verify that resumed or
restarted transfers produce exactly the original file.
"""

from __future__ import annotations

import random
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

SIZE_PATTERN = re.compile(r"^/(?P<route>[a-z-]+)/(?P<size>\d+)$")
_PAYLOAD_CACHE: dict[int, bytes] = {}
_PAYLOAD_LOCK = threading.Lock()


def payload(size: int) -> bytes:
    with _PAYLOAD_LOCK:
        data = _PAYLOAD_CACHE.get(size)
        if data is None:
            data = random.Random(size).randbytes(size)
            _PAYLOAD_CACHE[size] = data
        return data


class TestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "IDMTestServer/1.0"
    _SLOW_CHUNK = 32 * 1024
    _SLOW_DELAY = 0.02

    def log_message(self, format: str, *args) -> None:
        return

    # ------------------------------------------------------------------ routes
    def do_HEAD(self) -> None:
        self._handle(send_body=False)

    def do_GET(self) -> None:
        self._handle(send_body=True)

    def _handle(self, send_body: bool) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if send_body:
                self.wfile.write(body)
            return

        match = SIZE_PATTERN.match(parsed.path)
        if match is None:
            self._error(404, "Not found")
            return

        route = match.group("route")
        size = int(match.group("size"))
        query = parse_qs(parsed.query)
        name = query.get("name", [None])[0]

        server: TestServerState = self.server.state  # type: ignore[attr-defined]
        key = f"{self.command} {self.path}"
        with server.lock:
            server.request_counts[key] = server.request_counts.get(key, 0) + 1
            count = server.request_counts[key]

        if route in {"flaky", "ratelimit"}:
            failures = int(query.get("failures", ["1"])[0])
            if count <= failures:
                if route == "ratelimit":
                    self._error(
                        429, "Too many requests", {"Retry-After": "1"}
                    )
                else:
                    self._error(500, "Temporary failure")
                return

        if route == "truncated":
            declared = size
            actual = size // 2
            body = payload(actual)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(declared))
            self.end_headers()
            if send_body:
                self.wfile.write(body)
                self.wfile.flush()
                self.close_connection = True
            return

        if route not in {
            "file",
            "norange",
            "slow",
            "slow-norange",
            "disposition",
            "flaky",
            "ratelimit",
            "media",
        }:
            self._error(404, "Unknown route")
            return

        supports_range = route not in {"norange", "slow-norange"}
        content_type = "video/mp4" if route == "media" else "application/octet-stream"
        data = payload(size)
        start = 0
        end = size - 1
        partial = False

        range_header = self.headers.get("Range")
        if supports_range and range_header:
            range_match = re.fullmatch(
                r"bytes=(\d+)-(?:(\d+))?", range_header.strip()
            )
            if range_match:
                start = int(range_match.group(1))
                if range_match.group(2) is not None:
                    end = min(int(range_match.group(2)), size - 1)
                if start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if end < start:
                    self._error(416, "Invalid range")
                    return
                partial = True

        body = data[start : end + 1]
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if supports_range:
            self.send_header("Accept-Ranges", "bytes")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if route == "disposition":
            filename = name or "server-name.bin"
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()

        if not send_body:
            return

        slow = route.startswith("slow")
        if slow:
            position = 0
            while position < len(body):
                chunk = body[position : position + self._SLOW_CHUNK]
                try:
                    self.wfile.write(chunk)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return
                position += len(chunk)
                time.sleep(self._SLOW_DELAY)
        else:
            try:
                self.wfile.write(body)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return

    def _error(
        self, status: int, message: str, headers: dict[str, str] | None = None
    ) -> None:
        body = message.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


class TestServerState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.request_counts: dict[str, int] = {}


class _QuietHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        error = sys.exc_info()[1]
        if isinstance(
            error, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)
        ):
            return
        super().handle_error(request, client_address)


class TestFileServer:
    """Threaded local server bound to an ephemeral port."""

    __test__ = False

    def __init__(self) -> None:
        self._httpd = _QuietHTTPServer(("127.0.0.1", 0), TestHandler)
        self.state = TestServerState()
        self._httpd.state = self.state  # type: ignore[attr-defined]
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="idm-test-server", daemon=True
        )

    def start(self) -> TestFileServer:
        self._thread.start()
        return self

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def request_count(self, path: str) -> int:
        with self.state.lock:
            return self.state.request_counts.get(f"GET {path}", 0)

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=3)
