"""Desktop bridge server and browser integration service tests."""

from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import pytest

from downloads.location_manager import (
    MODE_ASK,
    MODE_DEFAULT,
    MODE_TYPE,
    DownloadLocationConfig,
    LocationRule,
)
from idm.core.settings import AppSettings
from idm.engine.manager import DownloadManager
from integrations import PROTOCOL_VERSION
from integrations.bridge_server import BrowserBridgeServer
from integrations.browser_registry import CHROME_EXTENSION_ID
from integrations.protocol import decode_line, encode_line, response_ok
from integrations.service import BrowserIntegrationService


def wait_events(app, predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return bool(predicate())


def _request(**overrides):
    request = {
        "type": "status",
        "request_id": "req-12345678",
        "browser": "chrome",
        "extension_id": CHROME_EXTENSION_ID,
    }
    request.update(overrides)
    return request


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    instance = AppSettings()
    instance.download_dir = str(tmp_path / "Downloads")
    Path(instance.download_dir).mkdir(parents=True, exist_ok=True)
    instance.start_immediately = False
    instance.location_config = DownloadLocationConfig(MODE_DEFAULT)
    yield instance
    instance.close()


@pytest.fixture
def manager(qt_app, settings):
    instance = DownloadManager(settings)
    yield instance
    instance.shutdown()


@pytest.fixture
def service(qt_app, settings, manager, tmp_path):
    instance = BrowserIntegrationService(
        settings,
        manager,
        descriptor_path=tmp_path / "runtime" / "browser_bridge.json",
    )
    yield instance
    instance.stop()


def _call(service: BrowserIntegrationService, request: dict) -> dict:
    responses: list[dict] = []
    service.handle_request(request, responses.append)
    assert responses, "the service must answer every request"
    return responses[0]


# ---------------------------------------------------------------------------
# Direct service behaviour
# ---------------------------------------------------------------------------


def test_status_reports_folder_and_counts(service, settings, manager) -> None:
    manager.add_download(
        "https://example.com/idle.bin",
        "idle.bin",
        settings.download_dir,
        start_immediately=False,
    )
    response = _call(service, _request())
    assert response["ok"] is True
    assert response["type"] == "status"
    status = response["status"]
    assert status["idm_running"] is True
    assert status["download_count"] == 1
    assert status["default_folder"] == settings.download_dir
    assert status["browser"] == "chrome"
    assert status["browser_display"] == "Google Chrome"
    assert [item["filename"] for item in response["downloads"]] == ["idle.bin"]


def test_download_is_added_with_browser_metadata(service, settings, manager) -> None:
    response = _call(
        service,
        _request(
            type="request_download",
            url="https://example.com/file.zip",
            filename="file.zip",
            referrer="https://example.com/page",
            total_bytes=4096,
        ),
    )
    assert response["ok"] is True
    assert response["type"] == "download_accepted"
    assert response["duplicate"] is False
    download = response["download"]
    assert download["filename"] == "file.zip"
    assert download["browser"] == "chrome"
    assert download["referrer"] == "https://example.com/page"
    assert download["folder"] == settings.download_dir

    item = manager.get(download["id"])
    assert item is not None
    assert item.source_browser == "chrome"
    assert item.referrer == "https://example.com/page"


def test_media_request_keeps_observed_metadata(
    service, settings, manager
) -> None:
    response = _call(
        service,
        _request(
            type="request_download",
            url="https://cdn.example.com/stream/abc123",
            filename="clip.mp4",
            mime="video/mp4",
            page_url="https://example.com/library",
            page_title="Library clip",
            media_kind="video",
            quality_label="720p",
            duration_seconds=93,
            detected_by="media",
        ),
    )
    assert response["ok"] is True
    download = response["download"]
    assert download["media_kind"] == "video"
    assert download["page_title"] == "Library clip"
    assert download["source_domain"] == "cdn.example.com"
    assert download["file_format"] == "mp4"

    item = manager.get(download["id"])
    assert item is not None
    assert item.media_kind == "video"
    assert item.page_url == "https://example.com/library"
    assert item.page_title == "Library clip"
    assert item.source_domain == "cdn.example.com"
    assert item.file_format == "mp4"

    stored = settings.database.load_media_metadata(item.id)
    assert stored is not None
    assert stored["quality_label"] == "720p"
    assert stored["duration_seconds"] == 93
    assert stored["detected_by"] == "media"


def test_media_kind_hint_does_not_relabel_plain_files(service, manager) -> None:
    response = _call(
        service,
        _request(
            type="request_download",
            url="https://example.com/setup.zip",
            filename="setup.zip",
            media_kind="video",
        ),
    )
    assert response["ok"] is True
    item = manager.get(response["download"]["id"])
    assert item is not None
    assert item.media_kind == ""


def test_media_kind_hint_fills_an_unclassifiable_stream(service, manager) -> None:
    response = _call(
        service,
        _request(
            type="request_download",
            url="https://cdn.example.com/stream/abc123",
            filename="abc123",
            media_kind="audio",
            detected_by="media",
        ),
    )
    assert response["ok"] is True
    item = manager.get(response["download"]["id"])
    assert item is not None
    assert item.media_kind == "audio"


def test_repeated_request_id_returns_the_cached_response(
    service, settings, manager
) -> None:
    request = _request(
        type="request_download", url="https://example.com/file.zip"
    )
    first = _call(service, request)
    second = _call(service, request)
    assert first == second
    assert len(manager.items()) == 1


def test_same_url_with_a_new_request_is_marked_duplicate(
    service, settings, manager
) -> None:
    first = _call(
        service,
        _request(
            type="request_download",
            request_id="req-aaaaaaaa",
            url="https://example.com/file.zip",
        ),
    )
    second = _call(
        service,
        _request(
            type="request_download",
            request_id="req-bbbbbbbb",
            url="https://example.com/file.zip",
        ),
    )
    assert second["ok"] is True
    assert second["duplicate"] is True
    assert second["download"]["id"] == first["download"]["id"]
    assert len(manager.items()) == 1


def test_unauthorized_extension_cannot_add_downloads(service, manager) -> None:
    response = _call(
        service,
        _request(
            type="request_download",
            extension_id="unauthorized-id-1234",
            url="https://example.com/file.zip",
        ),
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "unauthorized_extension"
    assert manager.items() == []


def test_unsafe_url_is_rejected(service, manager) -> None:
    for url in ("file:///C:/Windows/win.ini", "javascript:alert(1)"):
        response = _call(
            service,
            _request(type="request_download", url=url),
        )
        assert response["ok"] is False
        assert response["error"]["code"] in {"unsupported_url", "invalid_url"}
    assert manager.items() == []


def test_type_mode_uses_rules_and_approves_new_folders(
    qt_app, settings, manager, tmp_path
) -> None:
    archives = tmp_path / "Archives"
    settings.location_config = DownloadLocationConfig(
        MODE_TYPE, [LocationRule(str(archives), ("zip",))]
    )
    asked: list[str] = []
    service = BrowserIntegrationService(
        settings,
        manager,
        create_prompt=lambda folder: asked.append(folder) or True,
        descriptor_path=tmp_path / "runtime" / "bridge.json",
    )
    try:
        response = _call(
            service,
            _request(
                type="request_download",
                url="https://example.com/archive.zip",
                filename="archive.zip",
            ),
        )
    finally:
        service.stop()

    assert response["ok"] is True
    assert response["download"]["folder"] == str(archives)
    assert archives.is_dir()
    assert asked == [str(archives)]


def test_ask_mode_prompts_and_can_be_cancelled(
    qt_app, settings, manager, tmp_path
) -> None:
    settings.location_config = DownloadLocationConfig(MODE_ASK)
    chosen = tmp_path / "Chosen"
    chosen.mkdir()
    prompts: list[tuple[str, str, str]] = []
    service = BrowserIntegrationService(
        settings,
        manager,
        folder_prompt=lambda name, folder, browser: (
            prompts.append((name, folder, browser)) or str(chosen)
        ),
        descriptor_path=tmp_path / "runtime" / "bridge.json",
    )
    try:
        accepted = _call(
            service,
            _request(
                type="request_download",
                url="https://example.com/movie.mkv",
                filename="movie.mkv",
            ),
        )
    finally:
        service.stop()

    assert accepted["ok"] is True
    assert accepted["download"]["folder"] == str(chosen)
    assert prompts == [("movie.mkv", settings.download_dir, "Google Chrome")]

    cancelling = BrowserIntegrationService(
        settings,
        manager,
        folder_prompt=lambda _name, _folder, _browser: None,
        descriptor_path=tmp_path / "runtime" / "bridge-cancel.json",
    )
    try:
        cancelled = _call(
            cancelling,
            _request(
                type="request_download",
                url="https://example.com/other.mkv",
                filename="other.mkv",
                request_id="req-cancel01",
            ),
        )
    finally:
        cancelling.stop()
    assert cancelled["ok"] is False
    assert cancelled["error"]["code"] == "cancelled"


def test_ask_mode_without_a_prompt_is_rejected(
    qt_app, settings, manager, tmp_path
) -> None:
    settings.location_config = DownloadLocationConfig(MODE_ASK)
    service = BrowserIntegrationService(
        settings, manager, descriptor_path=tmp_path / "runtime" / "bridge.json"
    )
    try:
        response = _call(
            service,
            _request(
                type="request_download",
                url="https://example.com/file.zip",
            ),
        )
    finally:
        service.stop()
    assert response["ok"] is False
    assert response["error"]["code"] == "ask_unavailable"


def test_ask_folder_overrides_saved_file_type_rules(
    qt_app, settings, manager, tmp_path
) -> None:
    archives = tmp_path / "Archives"
    settings.location_config = DownloadLocationConfig(
        MODE_TYPE, [LocationRule(str(archives), ("zip",))]
    )
    chosen = tmp_path / "Picked"
    chosen.mkdir()
    prompts: list[tuple[str, str, str]] = []
    service = BrowserIntegrationService(
        settings,
        manager,
        folder_prompt=lambda name, folder, browser: (
            prompts.append((name, folder, browser)) or str(chosen)
        ),
        descriptor_path=tmp_path / "runtime" / "bridge.json",
    )
    try:
        response = _call(
            service,
            _request(
                type="request_download",
                url="https://example.com/archive.zip",
                filename="archive.zip",
                ask_folder=True,
            ),
        )
    finally:
        service.stop()

    assert response["ok"] is True
    assert response["download"]["folder"] == str(chosen)
    assert prompts == [("archive.zip", settings.download_dir, "Google Chrome")]
    assert not archives.exists()


def test_ask_folder_cancel_keeps_the_request_out_of_idm(
    qt_app, settings, manager, tmp_path
) -> None:
    service = BrowserIntegrationService(
        settings,
        manager,
        folder_prompt=lambda _name, _folder, _browser: None,
        descriptor_path=tmp_path / "runtime" / "bridge.json",
    )
    try:
        response = _call(
            service,
            _request(
                type="request_download",
                url="https://example.com/archive.zip",
                filename="archive.zip",
                ask_folder=True,
            ),
        )
    finally:
        service.stop()

    assert response["ok"] is False
    assert response["error"]["code"] == "cancelled"
    assert manager.items() == []


def test_list_and_open_actions(service, manager, settings, qt_app) -> None:
    item = manager.add_download(
        "https://example.com/listed.bin",
        "listed.bin",
        settings.download_dir,
        start_immediately=False,
        source_browser="chrome",
    )
    listed = _call(service, _request(type="list_downloads", request_id="req-list0001"))
    assert listed["ok"] is True
    assert listed["total"] == 1
    assert listed["downloads"][0]["id"] == item.id
    assert listed["downloads"][0]["filename"] == "listed.bin"

    opened: list[str] = []
    service._raise_window = lambda: opened.append("idm")
    service._open_settings = lambda: opened.append("settings")
    assert _call(service, _request(type="open_idm", request_id="req-open0001"))[
        "ok"
    ]
    assert _call(service, _request(type="open_settings", request_id="req-open0002"))[
        "ok"
    ]
    assert wait_events(qt_app, lambda: opened == ["idm", "settings"])


def test_unsupported_message_type(service) -> None:
    response = _call(service, _request(type="format_disk"))
    assert response["ok"] is False
    assert response["error"]["code"] == "unsupported_type"


# ---------------------------------------------------------------------------
# Transport: token authentication over the loopback bridge
# ---------------------------------------------------------------------------


def _bridge_exchange(qt_app, port: int, message: dict) -> dict | None:
    result: dict = {}

    def worker() -> None:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5.0) as sock:
                sock.sendall(encode_line(message))
                buffer = bytearray()
                while b"\n" not in buffer:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    buffer.extend(chunk)
                line, _, _ = bytes(buffer).partition(b"\n")
                result["response"] = decode_line(line) if line else None
        except OSError as exc:  # pragma: no cover - surfaced as assertion below
            result["error"] = exc

    worker_thread = threading.Thread(target=worker, daemon=True)
    worker_thread.start()
    wait_events(qt_app, lambda: not worker_thread.is_alive())
    worker_thread.join(timeout=5.0)
    return result.get("response")


def test_bridge_requires_the_descriptor_token(qt_app, service) -> None:
    assert service.start() is True
    descriptor = json.loads(service.bridge.descriptor_path.read_text(encoding="utf-8"))
    assert descriptor["protocol"] == PROTOCOL_VERSION
    assert service.bridge.port > 0
    assert service.bridge.token

    unauthorized = _bridge_exchange(
        qt_app,
        service.bridge.port,
        {**_request(), "token": "wrong-token"},
    )
    assert unauthorized is not None
    assert unauthorized["ok"] is False
    assert unauthorized["error"]["code"] == "unauthorized"


def test_bridge_round_trips_an_authenticated_status(qt_app, service) -> None:
    assert service.start() is True
    response = _bridge_exchange(
        qt_app,
        service.bridge.port,
        {**_request(), "token": service.bridge.token},
    )
    assert response is not None
    assert response["ok"] is True
    assert response["type"] == "status"
    assert response["status"]["idm_running"] is True

    descriptor = service.bridge.descriptor_path
    assert descriptor.is_file()
    service.stop()
    assert not descriptor.exists()


def test_bridge_server_direct_echo_and_malformed_frames(qt_app, tmp_path) -> None:
    received: list[dict] = []
    server = BrowserBridgeServer(
        lambda request, respond: (
            received.append(request),
            respond(response_ok(request.get("request_id"), "echo")),
        ),
        parent=qt_app,
        descriptor_path=tmp_path / "runtime" / "echo.json",
    )
    assert server.start() is True
    try:
        response = _bridge_exchange(
            qt_app,
            server.port,
            {**_request(type="hello"), "token": server.token},
        )
        assert response is not None
        assert response["type"] == "echo"
        assert received[0]["type"] == "hello"

        # A malformed line is rejected without reaching the handler.
        result: dict = {}

        def send_bad() -> None:
            with socket.create_connection(("127.0.0.1", server.port), timeout=5.0) as sock:
                sock.sendall(b"this is not json\n")
                result["data"] = sock.recv(65536)

        worker = threading.Thread(target=send_bad, daemon=True)
        worker.start()
        wait_events(qt_app, lambda: not worker.is_alive())
        worker.join(timeout=5.0)
        assert result["data"]
        response = decode_line(result["data"].split(b"\n", 1)[0])
        assert response["ok"] is False
    finally:
        server.stop()
        qt_app.processEvents()
