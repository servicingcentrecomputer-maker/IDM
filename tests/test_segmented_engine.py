"""Multi-connection engine, recovery and per-download limit tests."""

from __future__ import annotations

import time
from itertools import pairwise
from types import SimpleNamespace

from idm.core.settings import AppSettings
from idm.engine.manager import DownloadManager
from idm.engine.segmented import (
    SegmentPlan,
    inspect_partial,
    journal_path,
    load_plan,
    plan_segments,
)
from idm.models.download_item import DownloadStatus
from tests.http_server import payload


def make_segmented_manager(**overrides) -> DownloadManager:
    options = {
        "max_concurrent": 3,
        "auto_retry": False,
        "max_retries": 0,
        "speed_limit_kbps": 0,
        "connections_per_download": 4,
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


def wait_completed(app, manager, item, timeout: float = 25.0) -> None:
    assert wait_until(
        app,
        lambda: item.status == DownloadStatus.COMPLETED and not manager._workers,
        timeout,
    ), f"download did not complete: {item.status} ({item.error})"


def assert_payload(item, size: int) -> None:
    assert item.path.is_file()
    assert item.path.read_bytes() == payload(size)
    assert not item.part_path.exists()
    assert not journal_path(item.part_path).exists()


# --------------------------------------------------------------------------- plan
def test_segment_plan_covers_the_file_exactly() -> None:
    segments = plan_segments(4 * 1024 * 1024 + 7, 4)
    assert len(segments) == 4
    assert segments[0].start == 0
    assert segments[-1].end == 4 * 1024 * 1024 + 6
    for previous, current in pairwise(segments):
        assert current.start == previous.end + 1
    assert sum(segment.length for segment in segments) == 4 * 1024 * 1024 + 7


def test_segment_plan_round_trip_and_invalid_journal() -> None:
    plan = SegmentPlan(
        total=3 * 1024 * 1024,
        url="https://example.com/file.bin",
        etag='"abc"',
        last_modified="",
        segments=plan_segments(3 * 1024 * 1024, 3),
    )
    plan.segments[1].done = 1024
    restored = SegmentPlan.from_record(plan.to_record())
    assert restored is not None
    assert restored.downloaded == 1024
    assert restored.connection_count == 3

    broken = plan.to_record()
    broken["segments"][1]["start"] += 1
    assert SegmentPlan.from_record(broken) is None


def test_inspect_partial_prefers_journal_sum(tmp_path) -> None:
    part = tmp_path / "file.bin.idm.part"
    part.write_bytes(b"\0" * 2_000_000)
    plan = SegmentPlan(
        total=4 * 1024 * 1024,
        url="https://example.com/file.bin",
        etag="",
        last_modified="",
        segments=plan_segments(4 * 1024 * 1024, 4),
    )
    plan.segments[0].done = 512 * 1024
    journal_path(part).write_text(
        __import__("json").dumps(plan.to_record()), encoding="utf-8"
    )
    downloaded, total, loaded = inspect_partial(part)
    assert loaded is not None
    assert downloaded == 512 * 1024
    assert total == 4 * 1024 * 1024


# --------------------------------------------------------------------------- engine
def test_segmented_download_uses_multiple_range_requests(
    qt_app, server, tmp_path
) -> None:
    manager = make_segmented_manager()
    try:
        size = 4 * 1024 * 1024
        path = f"/file/{size}"
        item = manager.add_download(
            server.url(path), "segmented.bin", str(tmp_path), connections=4
        )
        wait_completed(qt_app, manager, item)
        assert_payload(item, size)
        assert item.range_supported is True
        assert item.total_bytes == size
        assert item.downloaded_bytes == size
        # One discovery request plus one request per segment.
        assert server.request_count(path) >= 5
    finally:
        manager.shutdown()


def test_no_range_server_stays_single_connection(qt_app, server, tmp_path) -> None:
    manager = make_segmented_manager()
    try:
        size = 4 * 1024 * 1024
        path = f"/norange/{size}"
        item = manager.add_download(
            server.url(path), "single.bin", str(tmp_path), connections=4
        )
        wait_completed(qt_app, manager, item)
        assert_payload(item, size)
        assert item.range_supported is False
        assert item.segments == []
        assert server.request_count(path) == 1
    finally:
        manager.shutdown()


def test_segmented_pause_resume_recovers_after_restart(
    qt_app, server, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    folder = tmp_path / "downloads"
    size = 8 * 1024 * 1024
    path = f"/slow/{size}"

    settings = AppSettings()
    settings.connections_per_download = 4
    settings.max_concurrent = 1
    manager = DownloadManager(settings)
    item = None
    restored_manager = None
    restored_settings = None
    try:
        item = manager.add_download(
            server.url(path), "recover.bin", str(folder), connections=4
        )
        assert wait_until(
            qt_app,
            lambda: item.downloaded_bytes >= 512 * 1024
            and item.range_supported is True,
            15,
        ), item.error
        assert manager.pause([item.id]) == 1
        assert wait_until(
            qt_app,
            lambda: item.status == DownloadStatus.PAUSED and not manager._workers,
            15,
        ), item.error

        plan = load_plan(item.part_path)
        assert plan is not None, "segment journal was not written"
        assert plan.connection_count >= 2
        assert 0 < plan.downloaded < size
        assert item.downloaded_bytes == plan.downloaded
        assert item.part_path.stat().st_size < size
        persisted = settings.database.load_segments(item.id)
        assert len(persisted) == plan.connection_count

        manager.shutdown()
        manager = None
        settings.close()
        settings = None

        restored_settings = AppSettings()
        restored_manager = DownloadManager(restored_settings)
        restored = restored_manager.get(item.id)
        assert restored is not None
        assert restored.status == DownloadStatus.PAUSED
        assert restored.downloaded_bytes == plan.downloaded
        assert len(restored.segments) == plan.connection_count
        assert restored.segments == plan.snapshot(interrupted=True)

        assert restored_manager.resume([restored.id]) == 1
        wait_completed(qt_app, restored_manager, restored)
        assert_payload(restored, size)
    finally:
        if manager is not None:
            manager.shutdown()
        if settings is not None:
            settings.close()
        if restored_manager is not None:
            restored_manager.shutdown()
        if restored_settings is not None:
            restored_settings.close()


def test_per_download_speed_limit_is_enforced(qt_app, server, tmp_path) -> None:
    manager = make_segmented_manager()
    try:
        size = 128 * 1024
        item = manager.add_download(
            server.url(f"/file/{size}"),
            "limited.bin",
            str(tmp_path),
            connections=1,
            speed_limit_kbps=64,
        )
        started = time.monotonic()
        wait_completed(qt_app, manager, item)
        elapsed = time.monotonic() - started
        assert_payload(item, size)
        assert elapsed >= 0.75, f"speed limit was not applied ({elapsed:.2f}s)"
    finally:
        manager.shutdown()


def test_speed_limit_can_be_changed_per_download(qt_app, tmp_path) -> None:
    manager = make_segmented_manager()
    try:
        item = manager.add_download(
            "https://example.com/file.bin",
            "limit-change.bin",
            str(tmp_path),
            start_immediately=False,
        )
        assert manager.set_speed_limit(item.id, 256) is True
        assert item.speed_limit_kbps == 256
        assert manager.set_speed_limit("missing", 256) is False
    finally:
        manager.shutdown()


def test_removing_segmented_download_deletes_journal(
    qt_app, server, tmp_path
) -> None:
    manager = make_segmented_manager()
    try:
        size = 8 * 1024 * 1024
        item = manager.add_download(
            server.url(f"/slow/{size}"),
            "removed.bin",
            str(tmp_path),
            connections=4,
        )
        assert wait_until(
            qt_app,
            lambda: item.downloaded_bytes > 0 and item.range_supported is True,
            15,
        ), item.error
        assert item.part_path.exists()
        manager.remove([item.id], delete_files=False)
        assert wait_until(qt_app, lambda: not manager._workers, 15)
        assert not item.part_path.exists()
        assert not journal_path(item.part_path).exists()
    finally:
        manager.shutdown()
