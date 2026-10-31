"""Integration tests for the download engine against a local HTTP server."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from idm.core.scheduler import DownloadScheduler
from idm.core.url_utils import unique_filename, validate_url
from idm.engine.manager import DownloadManager
from idm.engine.speed_limiter import SpeedLimiter
from idm.engine.worker import DownloadWorker
from idm.models.download_item import DownloadStatus
from tests.http_server import payload


def make_manager(**overrides) -> DownloadManager:
    options = {
        "max_concurrent": 3,
        "auto_retry": False,
        "max_retries": 0,
        "speed_limit_kbps": 0,
    }
    options.update(overrides)
    return DownloadManager(SimpleNamespace(**options))


@pytest.fixture
def manager(qt_app):
    instance = make_manager()
    yield instance
    instance.shutdown()


def wait_until(app, predicate, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return bool(predicate())


def wait_status(app, item, status, timeout=15.0) -> None:
    assert wait_until(app, lambda: item.status == status, timeout), (
        f"expected {status}, got {item.status} ({item.error})"
    )


def wait_completed(app, manager, item, timeout=20.0) -> None:
    assert wait_until(
        app,
        lambda: item.status == DownloadStatus.COMPLETED and not manager._workers,
        timeout,
    ), f"download did not complete: {item.status} ({item.error})"


def assert_payload(item, size: int) -> None:
    assert item.path.is_file(), "final file is missing"
    assert item.path.read_bytes() == payload(size)
    assert not item.part_path.exists(), "partial file was not cleaned up"


# --------------------------------------------------------------------------- URLs
def test_url_validation() -> None:
    assert validate_url(" https://example.com/file.zip ") == "https://example.com/file.zip"
    for bad in (
        "",
        "not a url",
        "ftp://example.com/file.zip",
        "file:///C:/Windows/win.ini",
        "https://user:pass@example.com/file.zip",
        "https://example.com:notaport/file.zip",
        "https:///missing-host",
        "https://example.com/a b.zip",
    ):
        with pytest.raises(ValueError):
            validate_url(bad)


def test_unique_filename_avoids_disk_and_reserved(tmp_path) -> None:
    (tmp_path / "report.pdf").write_bytes(b"x")
    (tmp_path / "photo.jpg.idm.part").write_bytes(b"y")
    assert unique_filename(tmp_path, "report.pdf") == "report (1).pdf"
    assert unique_filename(tmp_path, "photo.jpg") == "photo (1).jpg"
    assert (
        unique_filename(tmp_path, "video.mp4", reserved={"video.mp4"})
        == "video (1).mp4"
    )


# --------------------------------------------------------------------------- engine
def test_large_byte_counts_survive_worker_signals(qt_app, tmp_path):
    """Sizes above 2 GiB must not overflow Qt's 32-bit int marshalling."""
    worker = DownloadWorker(
        download_id="big",
        url="https://example.com/big.iso",
        folder=str(tmp_path),
        filename="big.iso",
        auto_retry=False,
        max_retries=0,
        limiter=SpeedLimiter(0),
    )
    total = 3 * 1024**3 + 12345
    received: list[tuple] = []
    worker.progress.connect(lambda *args: received.append(args))
    worker.metadata.connect(lambda *args: received.append(args))

    def emit() -> None:
        worker.progress.emit("big", total, total, 4.0, 1.0)
        worker.metadata.emit("big", total, "application/octet-stream", True)

    thread = threading.Thread(target=emit)
    thread.start()
    thread.join()
    wait_until(qt_app, lambda: len(received) >= 2, timeout=5.0)

    assert ("big", total, total, 4.0, 1.0) in received
    assert ("big", total, "application/octet-stream", True) in received


def test_small_download_with_range(qt_app, server, manager, tmp_path):
    size = 128 * 1024
    item = manager.add_download(
        server.url(f"/file/{size}"), "small.bin", str(tmp_path)
    )
    wait_completed(qt_app, manager, item)
    assert_payload(item, size)
    assert item.total_bytes == size
    assert item.downloaded_bytes == size
    assert item.range_supported is True


def test_server_without_range_support(qt_app, server, manager, tmp_path):
    size = 96 * 1024
    item = manager.add_download(
        server.url(f"/norange/{size}"), "no-range.bin", str(tmp_path)
    )
    wait_completed(qt_app, manager, item)
    assert_payload(item, size)
    assert item.range_supported is False


def test_pause_and_resume_uses_http_range(qt_app, server, manager, tmp_path):
    size = 2 * 1024 * 1024
    item = manager.add_download(
        server.url(f"/slow/{size}"), "paused.bin", str(tmp_path)
    )
    assert wait_until(qt_app, lambda: item.downloaded_bytes >= 128 * 1024), (
        "download finished too quickly to pause"
    )
    assert manager.pause([item.id]) == 1
    assert wait_until(
        qt_app,
        lambda: item.status == DownloadStatus.PAUSED and not manager._workers,
        10,
    ), item.error

    assert item.part_path.exists()
    part_size = item.part_path.stat().st_size
    assert 0 < part_size < size

    assert manager.resume([item.id]) == 1
    wait_completed(qt_app, manager, item)
    assert_payload(item, size)


def test_resume_without_range_restarts_safely(qt_app, server, manager, tmp_path):
    size = 1024 * 1024
    item = manager.add_download(
        server.url(f"/slow-norange/{size}"), "restart.bin", str(tmp_path)
    )
    assert wait_until(qt_app, lambda: item.downloaded_bytes >= 128 * 1024)
    manager.pause([item.id])
    assert wait_until(
        qt_app,
        lambda: item.status == DownloadStatus.PAUSED and not manager._workers,
        10,
    ), item.error
    assert item.part_path.exists()

    manager.resume([item.id])
    wait_completed(qt_app, manager, item)
    assert_payload(item, size)


def test_stop_keeps_partial_file(qt_app, server, manager, tmp_path):
    size = 1024 * 1024
    item = manager.add_download(
        server.url(f"/slow/{size}"), "stopped.bin", str(tmp_path)
    )
    assert wait_until(qt_app, lambda: item.downloaded_bytes >= 64 * 1024)
    assert manager.stop([item.id]) == 1
    assert wait_until(
        qt_app,
        lambda: item.status == DownloadStatus.STOPPED and not manager._workers,
        10,
    ), item.error
    assert item.part_path.exists()
    assert not item.path.exists()

    assert manager.resume([item.id]) == 1
    wait_completed(qt_app, manager, item)
    assert_payload(item, size)


def test_truncated_response_is_never_marked_complete(qt_app, server, tmp_path):
    manager = make_manager(auto_retry=False, max_retries=0)
    try:
        size = 200 * 1024
        item = manager.add_download(
            server.url(f"/truncated/{size}"), "truncated.bin", str(tmp_path)
        )
        wait_status(qt_app, item, DownloadStatus.FAILED)
        assert not item.path.exists(), "incomplete download must not be finalized"
        assert item.part_path.exists()
        assert item.part_path.stat().st_size < size
        assert item.error, "failure should carry a readable reason"
    finally:
        manager.shutdown()


def test_missing_file_reports_failure(qt_app, server, manager, tmp_path):
    item = manager.add_download(server.url("/missing"), "missing.bin", str(tmp_path))
    wait_status(qt_app, item, DownloadStatus.FAILED)
    assert "404" in item.error
    assert not item.path.exists()


def test_retry_after_server_error(qt_app, server, tmp_path):
    manager = make_manager(auto_retry=True, max_retries=2)
    try:
        size = 64 * 1024
        path = f"/flaky/{size}?failures=1"
        item = manager.add_download(server.url(path), "retried.bin", str(tmp_path))
        wait_completed(qt_app, manager, item, timeout=20)
        assert_payload(item, size)
        assert server.request_count(f"/flaky/{size}?failures=1") >= 2
    finally:
        manager.shutdown()


def test_retry_after_header_is_respected(qt_app, server, tmp_path):
    manager = make_manager(auto_retry=True, max_retries=2)
    try:
        size = 32 * 1024
        path = f"/ratelimit/{size}?failures=1"
        started = time.monotonic()
        item = manager.add_download(server.url(path), "rate-limited.bin", str(tmp_path))
        wait_completed(qt_app, manager, item, timeout=20)
        elapsed = time.monotonic() - started
        assert_payload(item, size)
        assert elapsed >= 0.9, f"Retry-After was ignored ({elapsed:.2f}s)"
        assert server.request_count(f"/ratelimit/{size}?failures=1") == 2
    finally:
        manager.shutdown()


def test_scheduler_pauses_and_resumes(qt_app, server, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    manager = make_manager(auto_retry=False)
    scheduler = DownloadScheduler(manager)
    try:
        item = manager.add_download(
            server.url("/slow/4194304"), "scheduled.bin", str(tmp_path)
        )
        assert wait_until(qt_app, lambda: item.status == DownloadStatus.DOWNLOADING, 10)

        pause_entry = scheduler.add(datetime.now() + timedelta(seconds=5), "pause_all")
        pause_entry.run_at = datetime.now() + timedelta(milliseconds=50)
        time.sleep(0.06)
        scheduler._tick()
        assert wait_until(
            qt_app,
            lambda: item.status == DownloadStatus.PAUSED and not manager._workers,
            10,
        ), item.error

        resume_entry = scheduler.add(datetime.now() + timedelta(seconds=5), "resume_all")
        resume_entry.run_at = datetime.now() + timedelta(milliseconds=50)
        time.sleep(0.06)
        scheduler._tick()
        assert wait_until(
            qt_app, lambda: item.status == DownloadStatus.DOWNLOADING, 10
        ), item.error
        manager.stop([item.id])
        assert wait_until(qt_app, lambda: not manager._workers, 10)
    finally:
        scheduler.shutdown()
        manager.shutdown()


def test_invalid_url_is_rejected(manager, tmp_path):
    with pytest.raises(ValueError):
        manager.add_download("file:///C:/Windows/win.ini", "x.bin", str(tmp_path))


def test_duplicate_names_are_unique(qt_app, server, manager, tmp_path):
    size = 512 * 1024
    first = manager.add_download(
        server.url(f"/slow/{size}"), "duplicate.bin", str(tmp_path)
    )
    second = manager.add_download(
        server.url(f"/slow/{size}"), "duplicate.bin", str(tmp_path)
    )
    assert first.filename == "duplicate.bin"
    assert second.filename == "duplicate (1).bin"

    wait_completed(qt_app, manager, first)
    wait_completed(qt_app, manager, second)
    assert_payload(first, size)
    assert_payload(second, size)

    third = manager.add_download(
        server.url(f"/slow/{size}"), "duplicate.bin", str(tmp_path)
    )
    assert third.filename == "duplicate (2).bin"
    wait_completed(qt_app, manager, third)


def test_max_concurrent_limit(qt_app, server, tmp_path):
    manager = make_manager(max_concurrent=2)
    try:
        size = 512 * 1024
        items = [
            manager.add_download(
                server.url(f"/slow/{size}"), f"concurrent-{index}.bin", str(tmp_path)
            )
            for index in range(3)
        ]
        assert len(manager._workers) == 2
        assert sum(
            1 for item in items if item.status == DownloadStatus.QUEUED
        ) == 1

        peak = 0
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            qt_app.processEvents()
            peak = max(peak, len(manager._workers))
            assert peak <= 2
            if all(item.status == DownloadStatus.COMPLETED for item in items):
                break
            time.sleep(0.01)

        for item in items:
            wait_completed(qt_app, manager, item)
            assert_payload(item, size)
    finally:
        manager.shutdown()
