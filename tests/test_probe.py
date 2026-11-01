"""Link probe tests: HEAD, Range GET fallback, redirects and failures."""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from idm.core.probe import LinkProbe


def wait_until(app, predicate, timeout: float = 12.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return bool(predicate())


class _State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.sent: dict[str, int] = {}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "IDMProbeTest/1.0"
    state: _State

    def log_message(self, format: str, *args) -> None:
        return

    def do_HEAD(self) -> None:
        self._dispatch(head=True)

    def do_GET(self) -> None:
        self._dispatch(head=False)

    # ------------------------------------------------------------------ routes
    def _dispatch(self, head: bool) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/ok":
            self._reply(200, 1234, head=head, ranged=False, name=None)
            return
        if path == "/nohead":
            if head:
                self._reply(405, 0, head=True)
            else:
                self._reply(206, 2048, head=False, ranged=True, name="from-get.bin")
            return
        if path == "/nosize":
            if head:
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
            else:
                self._reply(206, 3072, head=False, ranged=True)
            return
        if path == "/head-accepted-no-size":
            if head:
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
            else:
                self._reply(200, 4096, head=False, ranged=False, accept_ranges=False)
            return
        if path == "/norange":
            if head:
                self._reply(405, 0, head=True)
            else:
                self._slow_full_body(8 * 1024 * 1024)
            return
        if path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/notfound":
            self._reply(404, 4, head=head, text=b"nope")
            return
        if path == "/forbidden":
            self._reply(403, 4, head=head, text=b"nope")
            return
        if path == "/server-error":
            self._reply(500, 4, head=head, text=b"nope")
            return
        if path == "/empty":
            if head:
                self._reply(405, 0, head=True)
            else:
                self.send_response(416)
                self.send_header("Content-Range", "bytes */0")
                self.send_header("Content-Length", "0")
                self.end_headers()
            return
        if path == "/chunked":
            if head:
                self._reply(405, 0, head=True)
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                try:
                    self.wfile.write(b"4\r\ntest\r\n0\r\n\r\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
            return
        self._reply(404, 0, head=head)

    # ------------------------------------------------------------------ helpers
    def _reply(
        self,
        status: int,
        length: int,
        *,
        head: bool,
        ranged: bool = False,
        name: str | None = None,
        text: bytes | None = None,
        accept_ranges: bool = True,
    ) -> None:
        body = text if text is not None else b"x" * length
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        if accept_ranges:
            self.send_header("Accept-Ranges", "bytes")
        self.send_header("ETag", '"abc123"')
        self.send_header("Last-Modified", "Wed, 21 Oct 2026 07:28:00 GMT")
        if ranged:
            self.send_header("Content-Range", f"bytes 0-{length - 1}/{length}")
        if name:
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.end_headers()
        if head:
            return
        try:
            self.wfile.write(body)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _slow_full_body(self, size: int) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        chunk = b"z" * (64 * 1024)
        written = 0
        try:
            while written < size:
                self.wfile.write(chunk)
                self.wfile.flush()
                written += len(chunk)
                with self.state.lock:
                    self.state.sent[self.path] = written
                time.sleep(0.005)
        except (BrokenPipeError, ConnectionResetError):
            pass


class _Server:
    def __init__(self) -> None:
        self.state = _State()
        handler = type("Handler", (_Handler,), {"state": self.state})
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="idm-probe-test", daemon=True
        )

    def start(self) -> "_Server":
        self._thread.start()
        return self

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self._httpd.server_address[1]}{path}"

    def sent(self, path: str) -> int:
        with self.state.lock:
            return self.state.sent.get(path, 0)

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=3)


@pytest.fixture(scope="module")
def probe_server():
    instance = _Server().start()
    yield instance
    instance.stop()


def run_probe(qt_app, url: str, timeout: float = 12.0):
    finished: list = []
    failures: list[str] = []
    probe = LinkProbe()
    probe.finished.connect(finished.append)
    probe.failed.connect(failures.append)
    probe.start(url)
    assert wait_until(qt_app, lambda: bool(finished or failures), timeout), "probe stalled"
    probe.deleteLater()
    return finished[0] if finished else failures[0]


def test_head_reports_metadata_without_downloading(qt_app, probe_server) -> None:
    result = run_probe(qt_app, probe_server.url("/ok"))
    assert result.method == "HEAD"
    assert result.status_code == 200
    assert result.status_text == "HTTP 200 OK"
    assert result.total_bytes == 1234
    assert result.size_known is True
    assert result.content_type == "application/octet-stream"
    assert result.range_supported is True
    assert result.etag == '"abc123"'
    assert result.last_modified == "Wed, 21 Oct 2026 07:28:00 GMT"
    assert result.final_url == probe_server.url("/ok")
    assert probe_server.sent("/ok") == 0


def test_head_rejection_falls_back_to_range_get(qt_app, probe_server) -> None:
    result = run_probe(qt_app, probe_server.url("/nohead"))
    assert result.method == "GET"
    assert result.status_code == 206
    assert result.total_bytes == 2048
    assert result.range_supported is True
    assert result.filename == "from-get.bin"


def test_head_without_size_uses_range_get(qt_app, probe_server) -> None:
    result = run_probe(qt_app, probe_server.url("/head-accepted-no-size"))
    assert result.method == "GET"
    assert result.total_bytes == 4096
    assert result.range_supported is False


def test_range_get_supplies_size_when_head_has_none(qt_app, probe_server) -> None:
    result = run_probe(qt_app, probe_server.url("/nosize"))
    assert result.method == "GET"
    assert result.total_bytes == 3072


def test_range_ignoring_server_is_not_downloaded_fully(qt_app, probe_server) -> None:
    result = run_probe(qt_app, probe_server.url("/norange"), timeout=20)
    assert result.method == "GET"
    assert result.total_bytes == 8 * 1024 * 1024
    assert result.range_supported is False
    assert probe_server.sent("/norange") < 8 * 1024 * 1024


def test_redirects_are_followed(qt_app, probe_server) -> None:
    result = run_probe(qt_app, probe_server.url("/redirect"))
    assert result.status_code == 200
    assert result.total_bytes == 1234
    assert result.final_url == probe_server.url("/ok")
    assert result.requested_url == probe_server.url("/redirect")


def test_unknown_size_is_reported_as_unknown(qt_app, probe_server) -> None:
    result = run_probe(qt_app, probe_server.url("/chunked"))
    assert result.total_bytes is None
    assert result.size_known is False


def test_empty_file_reports_zero_bytes(qt_app, probe_server) -> None:
    result = run_probe(qt_app, probe_server.url("/empty"))
    assert result.total_bytes == 0


def test_http_errors_are_reported(qt_app, probe_server) -> None:
    not_found = run_probe(qt_app, probe_server.url("/notfound"))
    assert isinstance(not_found, str)
    assert "404" in not_found

    forbidden = run_probe(qt_app, probe_server.url("/forbidden"))
    assert isinstance(forbidden, str)
    assert "403" in forbidden

    server_error = run_probe(qt_app, probe_server.url("/server-error"))
    assert isinstance(server_error, str)
    assert "500" in server_error


def test_connection_failure_is_readable(qt_app) -> None:
    message = run_probe(qt_app, "http://127.0.0.1:1/unreachable", timeout=15)
    assert isinstance(message, str)
    assert message


def test_unsupported_scheme_is_rejected_without_a_request(qt_app) -> None:
    for url in ("file:///C:/Windows/win.ini", "ftp://example.com/file.zip"):
        message = run_probe(qt_app, url)
        assert isinstance(message, str)
        assert "HTTP and HTTPS" in message


def test_probe_timeout_reports_a_friendly_error(qt_app) -> None:
    failures: list[str] = []
    probe = LinkProbe()
    probe.failed.connect(failures.append)
    probe.start("http://127.0.0.1:1/slow")
    probe._on_timeout()
    assert failures == ["The server took too long to respond."]
    probe.deleteLater()
