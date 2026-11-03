"""Tests for secure credential storage and network configuration."""

from __future__ import annotations

import sys
import time
import uuid
from types import SimpleNamespace

import pytest

from idm.core import credentials, network
from idm.core.settings import AppSettings
from idm.engine.manager import DownloadManager
from idm.models.download_item import DownloadStatus
from tests.http_server import payload


def test_credential_roundtrip_uses_windows_vault() -> None:
    if sys.platform != "win32":
        pytest.skip("Windows Credential Manager is not available")
    prefix = f"IDMTest-{uuid.uuid4().hex[:12]}"
    try:
        assert credentials.get_secret("unit", "host", prefix) is None
        credentials.set_secret("unit", "Host.Example", "alice", "s3cret", prefix)
        assert credentials.get_secret("unit", "host.example", prefix) == (
            "alice",
            "s3cret",
        )
        assert credentials.has_secret("unit", "host.example", prefix)
        assert credentials.delete_secret("unit", "host.example", prefix) is True
        assert credentials.delete_secret("unit", "host.example", prefix) is False
        assert credentials.get_secret("unit", "host.example", prefix) is None
    finally:
        credentials.delete_secret("unit", "host.example", prefix)


def test_credential_rejects_invalid_values() -> None:
    with pytest.raises(credentials.CredentialError):
        credentials.target_name("", "host")
    with pytest.raises(credentials.CredentialError):
        credentials.target_name("unit", "")
    if sys.platform == "win32":
        with pytest.raises(credentials.CredentialError):
            credentials.set_secret("unit", "host", "user", "")


def test_normalize_site_auth_removes_invalid_and_duplicate_entries() -> None:
    entries = network.normalize_site_auth(
        [
            {"host": "Files.Example.com", "username": " Alice ", "scheme": "DIGEST"},
            {"host": "files.example.com", "username": "bob", "scheme": "basic"},
            {"host": "https://bad.example", "username": "eve"},
            {"host": "ok.example", "username": ""},
            {"host": "other.example", "username": "carol", "scheme": "unknown"},
            "not-a-dict",
        ]
    )
    assert entries == [
        {"host": "files.example.com", "username": "Alice", "scheme": "digest"},
        {"host": "other.example", "username": "carol", "scheme": "basic"},
    ]


def test_proxy_bypass_matches_domains_and_wildcards() -> None:
    assert network.bypasses_proxy("localhost", "localhost, *.local")
    assert network.bypasses_proxy("api.local", "localhost, *.local")
    assert network.bypasses_proxy("deep.api.local", ".local")
    assert network.bypasses_proxy("anything.example", "*")
    assert not network.bypasses_proxy("example.com", "localhost, *.local")
    assert network.bypasses_proxy("10.0.0.5", "10.0.0.5:8080")


def test_proxy_settings_modes(monkeypatch) -> None:
    settings = type(
        "Settings",
        (),
        {
            "proxy_mode": "direct",
            "proxy_host": "proxy.example",
            "proxy_port": 3128,
            "proxy_username": "",
            "proxy_use_auth": False,
            "proxy_bypass": "",
        },
    )()
    assert network.proxy_settings(settings, "example.com") == ({}, False)

    settings.proxy_mode = "system"
    assert network.proxy_settings(settings, "example.com") == (None, True)

    settings.proxy_mode = "manual"
    assert network.proxy_settings(settings, "example.com") == (
        {"http": "http://proxy.example:3128", "https": "http://proxy.example:3128"},
        False,
    )

    settings.proxy_bypass = "*.example"
    assert network.proxy_settings(settings, "www.example") == ({}, False)

    settings.proxy_bypass = ""
    settings.proxy_use_auth = True
    settings.proxy_username = "user name"
    monkeypatch.setattr(network, "proxy_password", lambda _settings: "p@ss word")
    proxy = network.build_proxy_url(settings)
    assert proxy == "http://user%20name:p%40ss%20word@proxy.example:3128"

    settings.proxy_host = "https://proxy.example/path"
    assert network.build_proxy_url(settings) == ""


def test_network_profile_clamps_timeouts_and_reads_auth(monkeypatch) -> None:
    settings = type(
        "Settings",
        (),
        {
            "proxy_mode": "direct",
            "proxy_host": "",
            "proxy_port": 8080,
            "proxy_username": "",
            "proxy_use_auth": False,
            "proxy_bypass": "",
            "connect_timeout": 1,
            "read_timeout": 999,
            "site_auth": [],
        },
    )()
    monkeypatch.setattr(
        network, "site_auth_for", lambda _settings, _url: ("bob", "pw", "digest")
    )
    profile = network.network_profile(settings, "https://example.com/file.zip")
    assert profile.proxies == {}
    assert profile.trust_env is False
    assert profile.auth == ("bob", "pw", "digest")
    assert profile.connect_timeout == network.MIN_TIMEOUT
    assert profile.read_timeout == network.MAX_READ_TIMEOUT
    assert profile.timeout == (network.MIN_TIMEOUT, network.MAX_READ_TIMEOUT)


def test_network_settings_persist_without_passwords(qt_app, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    settings = AppSettings()
    try:
        settings.update(
            {
                "proxy_mode": "manual",
                "proxy_host": "proxy.example",
                "proxy_port": 3128,
                "proxy_username": "alice",
                "proxy_use_auth": True,
                "proxy_bypass": "localhost",
                "site_auth": [
                    {"host": "files.example", "username": "bob", "scheme": "digest"}
                ],
                "connect_timeout": 20,
                "read_timeout": 45,
            }
        )
        settings.save()
        snapshot = settings.snapshot()
        assert snapshot["proxy_mode"] == "manual"
        assert snapshot["site_auth"] == [
            {"host": "files.example", "username": "bob", "scheme": "digest"}
        ]
        assert "password" not in repr(snapshot).lower()

        reloaded = AppSettings()
        try:
            assert reloaded.proxy_host == "proxy.example"
            assert reloaded.proxy_port == 3128
            assert reloaded.connect_timeout == 20
            assert reloaded.read_timeout == 45
            assert reloaded.site_auth == snapshot["site_auth"]
        finally:
            reloaded.close()
    finally:
        settings.close()


def _wait(app, predicate, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return bool(predicate())


def _auth_manager() -> DownloadManager:
    settings = SimpleNamespace(
        max_concurrent=1,
        connections_per_download=1,
        auto_retry=False,
        max_retries=0,
        speed_limit_kbps=0,
        proxy_mode="direct",
        restore_session=False,
    )
    return DownloadManager(settings)


def test_worker_uses_stored_basic_authentication(
    qt_app, server, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        network, "site_auth_for", lambda _settings, _url: ("bob", "pw", "basic")
    )
    manager = _auth_manager()
    try:
        size = 256 * 1024
        item = manager.add_download(
            server.url(f"/protected/{size}"), "private.bin", str(tmp_path), connections=1
        )
        assert _wait(
            qt_app,
            lambda: item.status == DownloadStatus.COMPLETED and not manager._workers,
            20,
        ), f"{item.status}: {item.error}"
        assert item.path.read_bytes() == payload(size)
    finally:
        manager.shutdown()


def test_missing_authentication_fails_with_401(qt_app, server, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(network, "site_auth_for", lambda _settings, _url: None)
    manager = _auth_manager()
    try:
        item = manager.add_download(
            server.url("/protected/1024"), "denied.bin", str(tmp_path), connections=1
        )
        assert _wait(
            qt_app,
            lambda: item.status == DownloadStatus.FAILED and not manager._workers,
            20,
        ), f"{item.status}: {item.error}"
        assert "401" in item.error
    finally:
        manager.shutdown()
