"""Native messaging host: bridge client, validation and dispatch."""

from __future__ import annotations

import json
import socket
import threading
from pathlib import Path

import pytest

from integrations import PROTOCOL_VERSION
from integrations.browser_registry import CHROME_EXTENSION_ID, FIREFOX_EXTENSION_ID
from integrations.message_handler import (
    BridgeClient,
    BridgeUnavailable,
    NativeHostMessageHandler,
)


class FakeBridge:
    def __init__(self, response=None, error=None) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple[dict, float]] = []

    def request(self, payload, timeout):
        self.calls.append((dict(payload), timeout))
        if self.error is not None:
            raise self.error
        return dict(self.response or {})


def _message(**overrides):
    message = {
        "type": "status",
        "request_id": "req-12345678",
        "browser": "chrome",
        "extension_id": CHROME_EXTENSION_ID,
    }
    message.update(overrides)
    return message


def test_status_without_idm_reports_disconnected() -> None:
    bridge = FakeBridge(error=BridgeUnavailable("IDM is not running."))
    handler = NativeHostMessageHandler(
        client=bridge, environ={}, detected_browser="chrome"
    )
    response = handler.handle(_message(type="hello"))
    assert response["ok"] is True
    assert response["type"] == "status"
    assert response["connected"] is False
    assert response["bridge_available"] is False
    assert response["status"]["idm_running"] is False
    assert response["downloads"] == []


def test_status_with_idm_returns_live_counts() -> None:
    bridge = FakeBridge(
        response={
            "ok": True,
            "type": "status",
            "status": {"idm_running": True, "download_count": 4, "active_count": 1},
            "downloads": [
                {
                    "id": "abc",
                    "filename": "report.pdf",
                    "status": "Downloading",
                }
            ],
        }
    )
    handler = NativeHostMessageHandler(
        client=bridge, environ={}, detected_browser="chrome"
    )
    response = handler.handle(_message())
    assert response["ok"] is True
    assert response["connected"] is True
    assert response["status"]["download_count"] == 4
    assert response["downloads"][0]["filename"] == "report.pdf"
    assert response["browser_display"] == "Google Chrome"
    assert response["native_host_version"]
    assert bridge.calls[0][0]["type"] == "status"


def test_status_error_response_marks_disconnected() -> None:
    bridge = FakeBridge(
        response={"ok": False, "error": {"message": "Protocol mismatch"}}
    )
    handler = NativeHostMessageHandler(
        client=bridge, environ={}, detected_browser="chrome"
    )
    response = handler.handle(_message())
    assert response["connected"] is False
    assert response["status"]["message"] == "Protocol mismatch"


def test_download_request_is_forwarded_and_deduplicated() -> None:
    accepted = {
        "ok": True,
        "type": "download_accepted",
        "download": {"id": "dl-1", "filename": "file.zip"},
    }
    bridge = FakeBridge(response=accepted)
    handler = NativeHostMessageHandler(
        client=bridge, environ={}, detected_browser="chrome"
    )
    request = _message(
        type="request_download",
        url="https://example.com/file.zip",
        filename="file.zip",
        total_bytes=1024,
        ask_folder=True,
        page_url="https://example.com/page",
        page_title="Example page",
        media_kind="video",
        quality_label="720p",
        duration_seconds=42,
        detected_by="media",
    )
    first = handler.handle(request)
    second = handler.handle(request)

    assert first == second
    assert len(bridge.calls) == 1, "a resent request must not add a second download"
    payload, timeout = bridge.calls[0]
    assert "token" not in payload  # the bridge client injects it later
    assert payload["url"] == "https://example.com/file.zip"
    assert payload["filename"] == "file.zip"
    assert payload["total_bytes"] == 1024
    assert payload["ask_folder"] is True
    assert payload["page_title"] == "Example page"
    assert payload["media_kind"] == "video"
    assert payload["quality_label"] == "720p"
    assert payload["duration_seconds"] == 42
    assert payload["detected_by"] == "media"
    assert timeout > 0


def test_rejected_download_is_not_cached() -> None:
    bridge = FakeBridge(
        response={"ok": False, "type": "error", "error": {"code": "duplicate"}}
    )
    handler = NativeHostMessageHandler(
        client=bridge, environ={}, detected_browser="chrome"
    )
    request = _message(
        type="request_download", url="https://example.com/file.zip"
    )
    handler.handle(request)
    handler.handle(request)
    assert len(bridge.calls) == 2


def test_download_when_idm_stops_is_retryable() -> None:
    bridge = FakeBridge(error=BridgeUnavailable("IDM is not reachable."))
    handler = NativeHostMessageHandler(
        client=bridge, environ={}, detected_browser="chrome"
    )
    response = handler.handle(
        _message(type="request_download", url="https://example.com/file.zip")
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "idm_not_running"
    assert response["error"]["retryable"] is True


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"browser": "safari"}, "unsupported_browser"),
        ({"extension_id": "unauthorized-id-1234"}, "unauthorized_extension"),
        ({"request_id": "short"}, "invalid_request_id"),
        ({"type": "delete_everything"}, "unsupported_type"),
    ],
)
def test_invalid_messages_are_rejected(overrides, code) -> None:
    bridge = FakeBridge(response={"ok": True})
    handler = NativeHostMessageHandler(
        client=bridge, environ={}, detected_browser="chrome"
    )
    response = handler.handle(_message(**overrides))
    assert response["ok"] is False
    assert response["error"]["code"] == code
    assert bridge.calls == []


def test_browser_mismatch_is_rejected() -> None:
    bridge = FakeBridge(response={"ok": True})
    handler = NativeHostMessageHandler(
        client=bridge, environ={}, detected_browser="firefox"
    )
    response = handler.handle(_message())
    assert response["ok"] is False
    assert response["error"]["code"] == "browser_mismatch"


def test_firefox_extension_is_allowed_when_configured() -> None:
    bridge = FakeBridge(
        response={"ok": True, "type": "status", "status": {"idm_running": True}}
    )
    handler = NativeHostMessageHandler(
        client=bridge, environ={}, detected_browser="firefox"
    )
    response = handler.handle(
        _message(browser="firefox", extension_id=FIREFOX_EXTENSION_ID)
    )
    assert response["ok"] is True
    assert response["browser"] == "firefox"


def test_open_and_list_requests_are_forwarded() -> None:
    bridge = FakeBridge(response={"ok": True, "type": "opened"})
    handler = NativeHostMessageHandler(
        client=bridge, environ={}, detected_browser="chrome"
    )
    handler.handle(_message(type="open_idm"))
    handler.handle(_message(type="open_settings"))
    handler.handle(_message(type="list_downloads", limit=5))

    forwarded = [call[0]["type"] for call in bridge.calls]
    assert forwarded == ["open_idm", "open_settings", "list_downloads"]
    assert bridge.calls[2][0]["limit"] == 5


def test_non_object_message_is_rejected() -> None:
    handler = NativeHostMessageHandler(
        client=FakeBridge(), environ={}, detected_browser=""
    )
    response = handler.handle(["not", "a", "dict"])  # type: ignore[arg-type]
    assert response["ok"] is False


# ---------------------------------------------------------------------------
# BridgeClient descriptor parsing and transport
# ---------------------------------------------------------------------------


def _descriptor(tmp_path: Path, **overrides) -> Path:
    payload = {
        "protocol": PROTOCOL_VERSION,
        "port": 45678,
        "token": "x" * 32,
    }
    payload.update(overrides)
    path = tmp_path / "browser_bridge.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_descriptor_must_exist_and_be_well_formed(tmp_path: Path) -> None:
    client = BridgeClient(tmp_path / "missing.json")
    with pytest.raises(BridgeUnavailable):
        client.read_descriptor()

    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    with pytest.raises(BridgeUnavailable):
        BridgeClient(bad).read_descriptor()

    for overrides in (
        {"port": 0},
        {"port": 70000},
        {"token": "short"},
        {"protocol": 999},
    ):
        with pytest.raises(BridgeUnavailable):
            BridgeClient(_descriptor(tmp_path, **overrides)).read_descriptor()


def test_bridge_client_sends_the_token_and_reads_one_line(tmp_path: Path) -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    descriptor = _descriptor(tmp_path, port=port, token="t" * 32)
    received: list[dict] = []

    def serve() -> None:
        connection, _address = server.accept()
        with connection:
            buffer = bytearray()
            while b"\n" not in buffer:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                buffer.extend(chunk)
            line, _, _ = bytes(buffer).partition(b"\n")
            received.append(json.loads(line.decode("utf-8")))
            connection.sendall(
                b'{"ok":true,"type":"status","status":{"idm_running":true}}\n'
            )

    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    try:
        response = BridgeClient(descriptor).request(
            {"type": "status", "request_id": "req-12345678"}, timeout=5.0
        )
    finally:
        worker.join(timeout=5.0)
        server.close()

    assert response["ok"] is True
    assert received[0]["token"] == "t" * 32
    assert received[0]["type"] == "status"


def test_bridge_client_rejects_a_silent_server(tmp_path: Path) -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    descriptor = _descriptor(tmp_path, port=port)

    def serve() -> None:
        connection, _address = server.accept()
        connection.close()

    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    try:
        with pytest.raises(BridgeUnavailable):
            BridgeClient(descriptor).request(
                {"type": "status", "request_id": "req-12345678"}, timeout=5.0
            )
    finally:
        worker.join(timeout=5.0)
        server.close()
