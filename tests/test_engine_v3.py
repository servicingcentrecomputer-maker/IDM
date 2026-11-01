"""Engine capabilities introduced for IDM 3.0.

These cover optional SHA-256 verification, disk-space preflight, media discovery
from HTTP metadata and automatic recovery after a network outage.
"""

from __future__ import annotations

import hashlib
import time
from types import SimpleNamespace

import pytest

from idm.engine.manager import (
    _NETWORK_WAIT_MESSAGE,
    _looks_like_network_failure,
    DownloadManager,
)
from idm.models.download_item import DownloadStatus
from tests.http_server import payload


def make_manager(**overrides) -> DownloadManager:
    options = {
        "max_concurrent": 2,
        "auto_retry": False,
        "max_retries": 0,
        "speed_limit_kbps": 0,
        "connections_per_download": 1,
        "auto_resume_on_network": True,
    }
    options.update(overrides)
    return DownloadManager(SimpleNamespace(**options))


def wait_until(app, predicate, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return bool(predicate())


def wait_status(app, item, status, timeout: float = 20.0) -> None:
    assert wait_until(app, lambda: item.status == status, timeout), (
        f"expected {status}, got {item.status} ({item.error})"
    )


def wait_completed(app, manager, item, timeout: float = 30.0) -> None:
    assert wait_until(
        app,
        lambda: item.status == DownloadStatus.COMPLETED and not manager._workers,
        timeout,
    ), f"download did not complete: {item.status} ({item.error})"


@pytest.fixture
def manager(qt_app):
    instance = make_manager()
    yield instance
    instance.shutdown()


@pytest.mark.parametrize("connections", [1, 4])
def test_expected_sha256_is_verified(qt_app, server, tmp_path, connections):
    size = 3 * 1024 * 1024
    digest = hashlib.sha256(payload(size)).hexdigest()
    manager = make_manager(connections_per_download=connections)
    try:
        item = manager.add_download(
            server.url(f"/file/{size}"),
            "verified.bin",
            str(tmp_path),
            expected_sha256=digest.upper(),
        )
        wait_completed(qt_app, manager, item)
        assert item.path.read_bytes() == payload(size)
        assert item.expected_sha256 == digest
        assert item.checksum_status == "verified"
        assert item.integrity_verified_at
    finally:
        manager.shutdown()


def test_checksum_mismatch_discards_the_download(qt_app, server, tmp_path):
    size = 128 * 1024
    manager = make_manager()
    try:
        item = manager.add_download(
            server.url(f"/file/{size}"),
            "corrupt.bin",
            str(tmp_path),
            expected_sha256="0" * 64,
        )
        wait_status(qt_app, item, DownloadStatus.FAILED)
        assert item.checksum_status == "mismatch"
        assert "integrity" in item.error.casefold()
        assert not item.path.exists()
        assert not item.part_path.exists()
    finally:
        manager.shutdown()


def test_disk_space_preflight_stops_before_writing(
    qt_app, server, tmp_path, monkeypatch
):
    manager = make_manager()
    monkeypatch.setattr(
        "idm.engine.worker.shutil.disk_usage",
        lambda path: SimpleNamespace(free=1024),
    )
    try:
        item = manager.add_download(
            server.url("/file/65536"), "large.bin", str(tmp_path)
        )
        wait_status(qt_app, item, DownloadStatus.FAILED)
        assert "disk space" in item.error.casefold()
        assert not item.path.exists()
        assert not item.part_path.exists()
    finally:
        manager.shutdown()


def test_media_metadata_is_discovered_from_content_type(
    qt_app, server, tmp_path
):
    size = 64 * 1024
    manager = make_manager()
    try:
        item = manager.add_download(
            server.url(f"/media/{size}"), "clip", str(tmp_path)
        )
        wait_completed(qt_app, manager, item)
        assert item.media_kind == "video"
        assert item.is_video
        assert item.file_format == "mp4"
        assert item.source_domain == "127.0.0.1"
        assert item.content_type == "video/mp4"
        assert manager.video_items() == [item]
    finally:
        manager.shutdown()


def test_network_timeouts_are_recognised():
    assert _looks_like_network_failure("Network error: getaddrinfo failed")
    assert _looks_like_network_failure("The connection timed out.")
    assert _looks_like_network_failure(
        "The connection was interrupted: connection reset by peer"
    )
    assert not _looks_like_network_failure(
        "The file was not found on the server (HTTP 404)."
    )
    assert not _looks_like_network_failure("Access was denied by the server (HTTP 403).")


def test_network_failure_waits_and_resumes(qt_app, tmp_path, monkeypatch):
    manager = make_manager(auto_retry=True, max_retries=1)
    try:
        item = manager.add_download(
            "https://example.com/archive.bin",
            "archive.bin",
            str(tmp_path),
            start_immediately=False,
        )
        monkeypatch.setattr(manager, "_pump", lambda: None)
        manager._on_worker_failed(item.id, "Network error: connection refused")
        assert item.status == DownloadStatus.PAUSED
        assert item.error == _NETWORK_WAIT_MESSAGE
        assert item.id in manager._network_waiting

        manager._on_network_changed(True)
        assert item.id not in manager._network_waiting
        assert item.status == DownloadStatus.QUEUED
        assert item.error == ""
    finally:
        manager.shutdown()


def test_network_wait_can_be_disabled(qt_app, tmp_path):
    manager = make_manager(
        auto_retry=True, max_retries=1, auto_resume_on_network=False
    )
    try:
        item = manager.add_download(
            "https://example.com/archive.bin",
            "archive.bin",
            str(tmp_path),
            start_immediately=False,
        )
        manager._on_worker_failed(item.id, "Network error: connection refused")
        assert item.status == DownloadStatus.FAILED
        assert item.id not in manager._network_waiting
    finally:
        manager.shutdown()


def test_http_errors_never_enter_network_wait(qt_app, server, manager, tmp_path):
    item = manager.add_download(server.url("/missing"), "missing.bin", str(tmp_path))
    wait_status(qt_app, item, DownloadStatus.FAILED)
    assert "404" in item.error
    assert item.error != _NETWORK_WAIT_MESSAGE
