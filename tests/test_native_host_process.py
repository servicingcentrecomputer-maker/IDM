"""End-to-end native host stdio test without a browser or Qt."""

from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

from integrations import PROTOCOL_VERSION
from integrations.browser_registry import CHROME_EXTENSION_ID
from integrations.protocol import (
    decode_line,
    encode_line,
    encode_message,
    read_message,
    response_error,
    response_ok,
)

ROOT = Path(__file__).resolve().parents[1]


class _FakeBridge:
    def __init__(self) -> None:
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(4)
        self.server.settimeout(0.1)
        self.port = self.server.getsockname()[1]
        self.token = "p" * 32
        self.received: list[dict] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                connection, _address = self.server.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with connection:
                buffer = bytearray()
                while b"\n" not in buffer:
                    chunk = connection.recv(65536)
                    if not chunk:
                        break
                    buffer.extend(chunk)
                line, _, _ = bytes(buffer).partition(b"\n")
                if not line:
                    continue
                request = json.loads(line.decode("utf-8"))
                self.received.append(request)
                if request.get("token") != self.token:
                    response = response_error(
                        request.get("request_id"), "unauthorized", "bad token"
                    )
                elif request.get("type") == "status":
                    response = response_ok(
                        request.get("request_id"),
                        "status",
                        status={"idm_running": True, "download_count": 0},
                    )
                else:
                    response = response_ok(
                        request.get("request_id"),
                        "download_accepted",
                        download={"id": "dl-process", "filename": "file.zip"},
                    )
                connection.sendall(encode_line(response))

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5.0)
        self.server.close()


def _appdata(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    appdata = tmp_path / "appdata"
    runtime = appdata / "IDM Download Manager" / "runtime"
    runtime.mkdir(parents=True)
    environment = dict(os.environ)
    environment["APPDATA"] = str(appdata)
    return runtime, environment


def _run_host(environment: dict[str, str], messages: list[dict]) -> subprocess.CompletedProcess:
    payload = b"".join(encode_message(message) for message in messages)
    return subprocess.run(
        [sys.executable, str(ROOT / "integrations" / "native_host.py")],
        input=payload,
        capture_output=True,
        cwd=str(ROOT),
        env=environment,
        timeout=30,
    )


def _message(message_type: str, **overrides) -> dict:
    message = {
        "type": message_type,
        "request_id": "req-process01",
        "browser": "chrome",
        "extension_id": CHROME_EXTENSION_ID,
        "client_version": "1.0.0",
    }
    message.update(overrides)
    return message


def test_native_host_process_speaks_framed_json_to_the_bridge(tmp_path: Path) -> None:
    runtime, environment = _appdata(tmp_path)
    bridge = _FakeBridge()
    try:
        (runtime / "browser_bridge.json").write_text(
            json.dumps(
                {
                    "protocol": PROTOCOL_VERSION,
                    "port": bridge.port,
                    "token": bridge.token,
                }
            ),
            encoding="utf-8",
        )
        completed = _run_host(
            environment,
            [
                _message("status"),
                _message(
                    "request_download",
                    request_id="req-process02",
                    url="https://example.com/file.zip",
                    filename="file.zip",
                    total_bytes=2048,
                ),
            ],
        )
    finally:
        bridge.close()

    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    # stdout contains protocol frames only.
    stream = io.BytesIO(completed.stdout)
    status = read_message(stream)
    accepted = read_message(stream)
    assert read_message(stream) is None

    assert status is not None
    assert status["ok"] is True
    assert status["connected"] is True
    assert status["native_protocol"] == PROTOCOL_VERSION

    assert accepted is not None
    assert accepted["ok"] is True
    assert accepted["type"] == "download_accepted"
    assert accepted["download"]["id"] == "dl-process"

    assert [request["type"] for request in bridge.received] == [
        "status",
        "request_download",
    ]
    assert all(request["token"] == bridge.token for request in bridge.received)
    assert bridge.received[1]["filename"] == "file.zip"


def test_native_host_process_reports_idm_offline(tmp_path: Path) -> None:
    _runtime, environment = _appdata(tmp_path)
    completed = _run_host(environment, [_message("status")])

    assert completed.returncode == 0
    response = read_message(io.BytesIO(completed.stdout))
    assert response is not None
    assert response["ok"] is True
    assert response["connected"] is False
    assert response["status"]["idm_running"] is False


def test_native_host_process_rejects_an_invalid_frame(tmp_path: Path) -> None:
    _runtime, environment = _appdata(tmp_path)
    completed = subprocess.run(
        [sys.executable, str(ROOT / "integrations" / "native_host.py")],
        input=b"\x04\x00\x00\x00nope",
        capture_output=True,
        cwd=str(ROOT),
        env=environment,
        timeout=30,
    )
    assert completed.returncode == 2
    response = read_message(io.BytesIO(completed.stdout))
    assert response is not None
    assert response["ok"] is False
    assert response["error"]["code"] == "invalid_message"
