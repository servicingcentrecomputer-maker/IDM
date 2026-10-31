"""Installer download, resume, cancellation and hash verification tests."""

from __future__ import annotations

import threading

import pytest
import requests

from idm.updater.errors import (
    DownloadCancelled,
    DownloadError,
    HashMismatchError,
)
from idm.updater.update_downloader import InstallerDownloader
from tests.update_helpers import (
    FakeResponse,
    FakeSession,
    RangeDownloadSession,
    installer_bytes,
    make_config,
    make_manifest,
    sha256_bytes,
)


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(
        "idm.updater.update_downloader.time.sleep", lambda _seconds: None
    )


def test_download_success_writes_verified_installer(tmp_path):
    payload = installer_bytes()
    manifest = make_manifest(payload)
    progress: list[tuple[int, int | None]] = []
    downloader = InstallerDownloader(
        make_config(), session=RangeDownloadSession(payload)
    )
    result = downloader.download(
        manifest, tmp_path, progress=lambda done, total: progress.append((done, total))
    )
    assert result.path.name == "IDM_Setup_1.1.0.exe"
    assert result.path.read_bytes() == payload
    assert result.sha256 == sha256_bytes(payload)
    assert result.size == len(payload)
    assert not result.path.with_name(result.path.name + ".part").exists()
    assert progress[-1] == (len(payload), len(payload))


def test_download_rejects_wrong_sha_and_deletes_files(tmp_path):
    payload = installer_bytes()
    manifest = make_manifest(payload, sha256="0" * 64)
    downloader = InstallerDownloader(
        make_config(), session=RangeDownloadSession(payload)
    )
    with pytest.raises(HashMismatchError):
        downloader.download(manifest, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_download_resumes_with_http_range(tmp_path):
    payload = installer_bytes(size=300_000)
    split = 120_000
    manifest = make_manifest(payload)
    session = RangeDownloadSession(payload, interrupt_first_at=split)
    downloader = InstallerDownloader(make_config(), session=session)
    result = downloader.download(manifest, tmp_path)
    assert result.path.read_bytes() == payload
    assert "Range" in session.calls[1]
    assert len(session.calls) == 2


def test_download_restarts_when_server_ignores_range(tmp_path):
    payload = installer_bytes(size=300_000)
    manifest = make_manifest(payload)
    session = RangeDownloadSession(
        payload, interrupt_first_at=120_000, ignore_range=True
    )
    downloader = InstallerDownloader(make_config(), session=session)
    result = downloader.download(manifest, tmp_path)
    assert result.path.read_bytes() == payload
    assert "Range" in session.calls[1]


def test_download_rejects_truncated_response(tmp_path):
    payload = installer_bytes(size=4096)
    manifest = make_manifest(payload)
    short = payload[:1000]
    response = FakeResponse(
        short, headers={"Content-Length": str(len(payload))}
    )
    downloader = InstallerDownloader(
        make_config(), session=FakeSession(response)
    )
    with pytest.raises(DownloadError):
        downloader.download(manifest, tmp_path, attempts=1)
    assert not (tmp_path / "IDM_Setup_1.1.0.exe").exists()


def test_download_restarts_after_http_416(tmp_path):
    payload = installer_bytes()
    manifest = make_manifest(payload)
    session = FakeSession(
        FakeResponse(b"", status_code=416),
        FakeResponse(payload, headers={"Content-Length": str(len(payload))}),
    )
    downloader = InstallerDownloader(make_config(), session=session)
    result = downloader.download(manifest, tmp_path)
    assert result.path.read_bytes() == payload
    assert len(session.calls) == 2


def test_download_cancelled_before_start(tmp_path):
    cancel = threading.Event()
    cancel.set()
    payload = installer_bytes()
    manifest = make_manifest(payload)
    session = RangeDownloadSession(payload)
    downloader = InstallerDownloader(
        make_config(), cancel_event=cancel, session=session
    )
    with pytest.raises(DownloadCancelled):
        downloader.download(manifest, tmp_path)
    assert session.calls == []
    assert list(tmp_path.iterdir()) == []


def test_download_cancelled_while_streaming(tmp_path):
    cancel = threading.Event()
    payload = installer_bytes(size=500_000)
    manifest = make_manifest(payload)

    def progress(done: int, total: int | None) -> None:
        if done:
            cancel.set()

    downloader = InstallerDownloader(
        make_config(),
        cancel_event=cancel,
        session=RangeDownloadSession(payload),
    )
    with pytest.raises(DownloadCancelled):
        downloader.download(manifest, tmp_path, progress=progress)
    assert list(tmp_path.iterdir()) == []


def test_download_rejects_empty_installer(tmp_path):
    payload = b""
    manifest = make_manifest(payload)
    downloader = InstallerDownloader(
        make_config(),
        session=RangeDownloadSession(payload),
    )
    with pytest.raises(DownloadError, match="empty"):
        downloader.download(manifest, tmp_path, attempts=1)


def test_download_rejects_untrusted_host(tmp_path):
    payload = installer_bytes()
    manifest = make_manifest(payload)
    downloader = InstallerDownloader(
        make_config(trusted_hosts=("other.example.com",)),
        session=RangeDownloadSession(payload),
    )
    with pytest.raises(DownloadError, match="trusted"):
        downloader.download(manifest, tmp_path)


def test_download_rejects_untrusted_redirect(tmp_path):
    payload = installer_bytes()
    manifest = make_manifest(payload)
    response = FakeResponse(
        payload,
        history=[FakeResponse(url="https://evil.example.com/setup.exe")],
    )
    downloader = InstallerDownloader(
        make_config(), session=FakeSession(response)
    )
    with pytest.raises(DownloadError, match="untrusted"):
        downloader.download(manifest, tmp_path, attempts=1)


def test_download_rejects_declared_oversize_installer(tmp_path):
    payload = installer_bytes()
    manifest = make_manifest(payload)
    downloader = InstallerDownloader(
        make_config(max_installer_bytes=1024),
        session=RangeDownloadSession(payload),
    )
    with pytest.raises(DownloadError, match="size limit"):
        downloader.download(manifest, tmp_path, attempts=1)


def test_download_retries_then_reports_network_failure(tmp_path):
    payload = installer_bytes()
    manifest = make_manifest(payload)
    downloader = InstallerDownloader(
        make_config(),
        session=FakeSession(
            requests.ConnectionError("offline"),
            requests.ConnectionError("offline"),
        ),
    )
    with pytest.raises(DownloadError, match="interrupted"):
        downloader.download(manifest, tmp_path, attempts=2)
