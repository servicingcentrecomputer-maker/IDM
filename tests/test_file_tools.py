"""File tools added in 3.6.3: rename, link refresh and manual checksum verify."""

from __future__ import annotations

import hashlib
import json
import time
from types import SimpleNamespace

import pytest

from idm.engine.manager import DownloadManager
from idm.engine.segmented import journal_path
from idm.models.download_item import DownloadStatus
from tests.http_server import payload

SIZE = 64 * 1024


def make_manager(**overrides) -> DownloadManager:
    options = {
        "max_concurrent": 2,
        "auto_retry": False,
        "max_retries": 0,
        "speed_limit_kbps": 0,
        "connections_per_download": 1,
        "auto_resume_on_network": False,
        "site_auth": [],
        "custom_categories": [],
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


def wait_completed(qt_app, manager, item) -> None:
    assert wait_until(
        qt_app,
        lambda: item.status == DownloadStatus.COMPLETED and not manager._workers,
    ), f"{item.status} ({item.error})"


@pytest.fixture
def manager(qt_app):
    instance = make_manager()
    yield instance
    instance.shutdown()


# ------------------------------------------------------------------------- rename
def test_rename_moves_the_finished_file(qt_app, manager, server, tmp_path):
    item = manager.add_download(server.url(f"/file/{SIZE}"), "before.bin", str(tmp_path))
    wait_completed(qt_app, manager, item)

    assert manager.rename(item.id, "after.bin") == ""
    assert item.filename == "after.bin"
    assert item.path.read_bytes() == payload(SIZE)
    assert not (tmp_path / "before.bin").exists()


def test_rename_updates_the_persisted_record(qt_app, server, tmp_path, monkeypatch):
    from idm.core.settings import AppSettings

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    settings = AppSettings()
    manager = DownloadManager(settings)
    try:
        item = manager.add_download(
            server.url(f"/file/{SIZE}"), "one.bin", str(tmp_path / "dl")
        )
        wait_completed(qt_app, manager, item)
        assert manager.rename(item.id, "two.bin") == ""
        identifier = item.id
    finally:
        manager.shutdown()
        settings.close()

    reopened = AppSettings()
    restored = DownloadManager(reopened)
    try:
        moved = restored.get(identifier)
        assert moved is not None
        assert moved.filename == "two.bin"
        assert moved.path.is_file()
    finally:
        restored.shutdown()
        reopened.close()


def test_rename_moves_the_partial_and_journal(qt_app, manager, tmp_path):
    item = manager.add_download(
        "https://example.invalid/chunky.bin", "chunky.bin", str(tmp_path),
        start_immediately=False,
    )
    item.part_path.write_bytes(b"partial-data")
    journal_path(item.part_path).write_text(
        json.dumps({"unused": True}), encoding="utf-8"
    )

    assert manager.rename(item.id, "renamed.bin") == ""
    assert item.part_path.is_file()
    assert item.part_path.read_bytes() == b"partial-data"
    assert journal_path(item.part_path).is_file()
    assert not (tmp_path / "chunky.bin.idm.part").exists()


def test_rename_refuses_bad_conflicting_and_active_names(qt_app, manager, server, tmp_path):
    item = manager.add_download(server.url(f"/file/{SIZE}"), "keep.bin", str(tmp_path))
    wait_completed(qt_app, manager, item)
    (tmp_path / "taken.bin").write_bytes(b"x")

    assert manager.rename(item.id, "taken.bin") != ""
    assert manager.rename(item.id, "...") != ""
    assert manager.rename(item.id, "same.bin") == ""
    assert item.filename == "same.bin"

    running = manager.add_download(
        server.url(f"/slow/{4 * 1024 * 1024}"), "busy.bin", str(tmp_path)
    )
    assert wait_until(qt_app, lambda: running.status == DownloadStatus.DOWNLOADING)
    assert "Stop the download" in manager.rename(running.id, "later.bin")
    manager.stop([running.id])
    assert wait_until(qt_app, lambda: not manager._workers)


def test_rename_recategorises_when_the_extension_changes(qt_app, manager, server, tmp_path):
    item = manager.add_download(server.url(f"/file/{SIZE}"), "clip.bin", str(tmp_path))
    wait_completed(qt_app, manager, item)
    assert item.category == "General"

    assert manager.rename(item.id, "clip.mp4") == ""
    assert item.category == "Videos"


# ------------------------------------------------------------------- link refresh
def test_refresh_link_requeues_with_the_new_url(qt_app, manager, server, tmp_path):
    item = manager.add_download(
        server.url("/missing/1024"), "stale.bin", str(tmp_path)
    )
    assert wait_until(qt_app, lambda: item.status == DownloadStatus.FAILED)

    assert manager.refresh_link(item.id, server.url(f"/file/{SIZE}")) == ""
    wait_completed(qt_app, manager, item)
    assert item.path.read_bytes() == payload(SIZE)
    assert item.error == ""


def test_refresh_link_rejects_an_unusable_url(qt_app, manager, tmp_path):
    item = manager.add_download("https://example.invalid/x.bin", "idle.bin", str(tmp_path))
    assert wait_until(qt_app, lambda: item.status in {DownloadStatus.FAILED, DownloadStatus.PAUSED})
    assert manager.refresh_link(item.id, "file:///C:/Windows/win.ini") != ""


# ---------------------------------------------------------------------- checksum
def test_verify_checksum_reports_the_digest(qt_app, manager, server, tmp_path):
    results = []
    manager.checksum_checked.connect(lambda item, digest, status: results.append((item.id, digest, status)))
    item = manager.add_download(server.url(f"/file/{SIZE}"), "hash.bin", str(tmp_path))
    wait_completed(qt_app, manager, item)

    assert manager.verify_checksum(item.id) == ""
    assert wait_until(qt_app, lambda: bool(results))
    digest = results[0][1]
    assert digest == hashlib.sha256(payload(SIZE)).hexdigest()
    assert item.checksum_status == "not-requested"


def test_verify_checksum_matches_the_expected_digest(qt_app, manager, server, tmp_path):
    digest = hashlib.sha256(payload(SIZE)).hexdigest()
    statuses = []
    manager.checksum_checked.connect(lambda item, value, status: statuses.append(status))
    item = manager.add_download(
        server.url(f"/file/{SIZE}"), "expected.bin", str(tmp_path),
        expected_sha256=digest,
    )
    wait_completed(qt_app, manager, item)
    assert item.checksum_status == "verified"

    item.integrity_verified_at = ""
    assert manager.verify_checksum(item.id) == ""
    assert wait_until(qt_app, lambda: bool(statuses))
    assert statuses[-1] == "verified"
    assert item.integrity_verified_at


def test_verify_checksum_flags_a_mismatch(qt_app, manager, server, tmp_path):
    statuses = []
    manager.checksum_checked.connect(lambda item, value, status: statuses.append(status))
    item = manager.add_download(
        server.url(f"/file/{SIZE}"), "changed.bin", str(tmp_path)
    )
    wait_completed(qt_app, manager, item)
    # A hash recorded after the fact, for example when the user supplies the
    # digest published by the site only once the file is already on disk.
    item.expected_sha256 = "0" * 64

    assert manager.verify_checksum(item.id) == ""
    assert wait_until(qt_app, lambda: bool(statuses))
    assert statuses[-1] == "mismatch"
    assert item.checksum_status == "mismatch"


def test_verify_checksum_needs_a_completed_file(qt_app, manager, tmp_path):
    item = manager.add_download(
        "https://example.invalid/none.bin", "none.bin", str(tmp_path),
        start_immediately=False,
    )
    assert "completed" in manager.verify_checksum(item.id)
    item.status = DownloadStatus.COMPLETED
    assert "no longer on disk" in manager.verify_checksum(item.id)
