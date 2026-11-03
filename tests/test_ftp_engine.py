"""FTP transport coverage: the segmented HTTP engine has none of this."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from idm.core.network import NetworkProfile
from idm.core.probe import LinkProbe
from idm.engine.manager import DownloadManager
from idm.engine.speed_limiter import SpeedLimiter
from idm.engine.worker import DownloadWorker
from idm.models.download_item import DownloadStatus
from tests.ftp_server import MiniFtpServer, ftp_payload
from tests.http_server import payload

SIZE = 120 * 1024
HALF = 60 * 1024


def make_manager(**overrides) -> DownloadManager:
    options = {
        "max_concurrent": 2,
        "auto_retry": False,
        "max_retries": 0,
        "speed_limit_kbps": 0,
        "connections_per_download": 1,
        "auto_resume_on_network": False,
        "site_auth": [],
    }
    options.update(overrides)
    return DownloadManager(SimpleNamespace(**options))


@pytest.fixture
def ftp_root(tmp_path):
    root = tmp_path / "ftp"
    root.mkdir()
    (root / "large.bin").write_bytes(payload(SIZE))
    (root / "empty.bin").write_bytes(b"")
    return root


@pytest.fixture
def server(ftp_root):
    instance = MiniFtpServer(ftp_root).start()
    yield instance
    instance.stop()


def wait_until(app, predicate, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return bool(predicate())


def run_to_completion(qt_app, manager, item, timeout: float = 20.0):
    assert wait_until(
        qt_app,
        lambda: item.status in {DownloadStatus.COMPLETED, DownloadStatus.FAILED}
        and not manager._workers,
        timeout,
    ), f"FTP download hung: {item.status} ({item.error})"
    return item.status


# --------------------------------------------------------------------- transfer
def test_ftp_download_completes(qt_app, server, tmp_path):
    manager = make_manager()
    try:
        item = manager.add_download(
            server.url("large.bin"), "ftp-large.bin", str(tmp_path)
        )
        assert run_to_completion(qt_app, manager, item) == DownloadStatus.COMPLETED
        assert item.path.read_bytes() == payload(SIZE)
        assert item.total_bytes == SIZE
        assert not item.part_path.exists()
    finally:
        manager.shutdown()


def test_ftp_download_of_empty_file(qt_app, server, tmp_path):
    manager = make_manager()
    try:
        item = manager.add_download(
            server.url("empty.bin"), "ftp-empty.bin", str(tmp_path)
        )
        assert run_to_completion(qt_app, manager, item) == DownloadStatus.COMPLETED
        assert item.path.read_bytes() == b""
    finally:
        manager.shutdown()


def test_ftp_resumes_from_a_partial_file(qt_app, server, tmp_path):
    manager = make_manager()
    try:
        item = manager.add_download(
            server.url("large.bin"), "resumed.bin", str(tmp_path),
            start_immediately=False,
        )
        item.part_path.write_bytes(payload(SIZE)[:HALF])
        manager.resume([item.id])
        assert run_to_completion(qt_app, manager, item) == DownloadStatus.COMPLETED
        assert item.path.read_bytes() == payload(SIZE)
    finally:
        manager.shutdown()


def test_ftp_restarts_from_zero_when_rest_is_rejected(qt_app, ftp_root, tmp_path):
    server = MiniFtpServer(ftp_root, supports_rest=False).start()
    manager = make_manager()
    try:
        item = manager.add_download(
            server.url("large.bin"), "no-rest.bin", str(tmp_path),
            start_immediately=False,
        )
        item.part_path.write_bytes(b"stale-garbage" * 100)
        manager.resume([item.id])
        assert run_to_completion(qt_app, manager, item) == DownloadStatus.COMPLETED
        assert item.path.read_bytes() == payload(SIZE)
    finally:
        manager.shutdown()
        server.stop()


def test_ftp_truncated_transfer_does_not_finalize(qt_app, ftp_root, tmp_path):
    server = MiniFtpServer(ftp_root, short_by=1024).start()
    manager = make_manager()
    try:
        item = manager.add_download(server.url("large.bin"), "short.bin", str(tmp_path))
        assert run_to_completion(qt_app, manager, item) == DownloadStatus.FAILED
        assert not item.path.exists()
        assert "interrupted" in item.error.lower() or "before the whole file" in (
            item.error
        )
    finally:
        manager.shutdown()
        server.stop()


def test_ftp_missing_file_is_reported(qt_app, server, tmp_path):
    manager = make_manager()
    try:
        item = manager.add_download(
            server.url("does-not-exist.bin"), "gone.bin", str(tmp_path)
        )
        assert run_to_completion(qt_app, manager, item) == DownloadStatus.FAILED
        assert "not found" in item.error.lower() or "denied" in item.error.lower()
    finally:
        manager.shutdown()


def test_ftp_folder_url_is_rejected(qt_app, server, tmp_path):
    manager = make_manager()
    try:
        item = manager.add_download(
            server.url(""), "folder.bin", str(tmp_path)
        )
        assert run_to_completion(qt_app, manager, item) == DownloadStatus.FAILED
        assert "folder" in item.error.lower()
    finally:
        manager.shutdown()


def test_ftp_bad_credentials_are_reported(qt_app, ftp_root, tmp_path, monkeypatch):
    server = MiniFtpServer(ftp_root, username="ftpuser", password="secret").start()
    manager = make_manager()
    monkeypatch.setattr(
        "idm.engine.manager.network_profile",
        lambda settings, url: NetworkProfile(auth=("ftpuser", "wrong", "basic")),
    )
    try:
        item = manager.add_download(server.url("large.bin"), "auth.bin", str(tmp_path))
        assert run_to_completion(qt_app, manager, item) == DownloadStatus.FAILED
        assert "user name or password" in item.error
    finally:
        manager.shutdown()
        server.stop()


def test_ftp_uses_the_saved_server_credential(qt_app, ftp_root, tmp_path, monkeypatch):
    server = MiniFtpServer(ftp_root, username="ftpuser", password="secret").start()
    manager = make_manager()
    monkeypatch.setattr(
        "idm.engine.manager.network_profile",
        lambda settings, url: NetworkProfile(auth=("ftpuser", "secret", "basic")),
    )
    try:
        item = manager.add_download(server.url("large.bin"), "good-auth.bin", str(tmp_path))
        assert run_to_completion(qt_app, manager, item) == DownloadStatus.COMPLETED
        assert item.path.read_bytes() == payload(SIZE)
    finally:
        manager.shutdown()
        server.stop()


# ------------------------------------------------------------------------- misc
def test_worker_dispatches_ftp_without_an_http_session(qt_app, server, tmp_path):
    worker = DownloadWorker(
        download_id="ftp-worker",
        url=server.url("large.bin"),
        folder=str(tmp_path),
        filename="direct-ftp.bin",
        auto_retry=False,
        max_retries=0,
        limiter=SpeedLimiter(0),
        connections=1,
    )
    try:
        assert worker._transfer() == DownloadStatus.COMPLETED
        assert worker.final_path.read_bytes() == payload(SIZE)
        assert worker._session is None
    finally:
        worker.deleteLater()


def test_ftp_link_probe_reports_the_file(qt_app, server) -> None:
    probe = LinkProbe()
    failures: list[str] = []
    results = []
    probe.failed.connect(failures.append)
    probe.finished.connect(results.append)
    probe.start(server.url("large.bin"))
    assert wait_until(qt_app, lambda: bool(results or failures), 20)
    probe.deleteLater()
    assert failures == [], failures
    result = results[0]
    assert result.total_bytes == SIZE
    assert result.filename == "large.bin"
    assert result.method == "FTP"


def test_ftp_link_probe_reports_a_missing_file(qt_app, server) -> None:
    probe = LinkProbe()
    failures: list[str] = []
    probe.failed.connect(failures.append)
    probe.start(server.url("nope.bin"))
    assert wait_until(qt_app, lambda: bool(failures), 20)
    probe.deleteLater()
    assert "not found" in failures[0].lower() or "denied" in failures[0].lower()


def test_ftp_payload_helper_matches_the_http_payload() -> None:
    assert ftp_payload(1024) == payload(1024)
