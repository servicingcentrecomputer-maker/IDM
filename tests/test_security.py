"""Security-focused checks for links, file names and browser metadata."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from downloads.location_manager import MODE_DEFAULT, DownloadLocationConfig, safe_join
from idm.core.settings import AppSettings
from idm.core.url_utils import (
    InvalidUrlError,
    redact_url,
    sanitize_filename,
    validate_url,
)
from idm.engine.manager import DownloadManager
from integrations.browser_registry import CHROME_EXTENSION_ID
from integrations.protocol import normalize_download_request
from integrations.service import BrowserIntegrationService


@pytest.mark.parametrize(
    "url",
    [
        "file:///C:/Windows/win.ini",
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
        "ftp://example.com/file.zip",
        "https://user:password@example.com/file.zip",
        "https://example.com/a b.zip",
        "",
    ],
)
def test_validate_url_rejects_unsafe_links(url: str) -> None:
    with pytest.raises(InvalidUrlError):
        validate_url(url)


def test_redact_url_removes_queries_and_credentials() -> None:
    redacted = redact_url(
        "https://example.com/download?token=SECRET&session=ABC123#frag"
    )
    assert "SECRET" not in redacted
    assert "ABC123" not in redacted
    assert "download" not in redacted
    assert redacted == "https://example.com/…"

    assert redact_url("file:///C:/secret") == "[redacted-url]"
    assert "user" not in redact_url("https://user:pass@example.com/x")
    assert redact_url("https://example.com:8443/file?x=1") == (
        "https://example.com:8443/…"
    )


def test_sanitize_filename_blocks_traversal_and_reserved_names() -> None:
    for raw in (
        "../../etc/passwd",
        r"..\..\Windows\System32\evil.dll",
        "CON",
        "NUL.txt",
        "file\u0000name.exe",
        "   ",
    ):
        cleaned = sanitize_filename(raw, "fallback.bin")
        assert "/" not in cleaned
        assert "\\" not in cleaned
        assert "\u0000" not in cleaned
        assert cleaned
        assert Path(cleaned).name == cleaned


def test_safe_join_keeps_paths_inside_the_destination(tmp_path) -> None:
    target = tmp_path / "Downloads"
    target.mkdir()
    safe = safe_join(target, "report.pdf")
    assert Path(safe).parent == target
    assert Path(safe).name == "report.pdf"


def test_browser_protocol_drops_credential_fields() -> None:
    normalized = normalize_download_request(
        {
            "type": "request_download",
            "request_id": "req-12345678",
            "browser": "chrome",
            "extension_id": CHROME_EXTENSION_ID,
            "url": "https://example.com/file.zip?token=SECRET",
            "filename": "file.zip",
            "cookie": "session=SECRET",
            "cookies": ["session=SECRET"],
            "authorization": "Bearer SECRET",
            "headers": {"Cookie": "session=SECRET"},
        }
    )
    assert "cookie" not in normalized
    assert "cookies" not in normalized
    assert "authorization" not in normalized
    assert "headers" not in normalized


def test_service_logs_redacted_urls(
    qt_app, tmp_path, monkeypatch, caplog
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    settings = AppSettings()
    settings.download_dir = str(tmp_path / "Downloads")
    Path(settings.download_dir).mkdir(parents=True)
    settings.start_immediately = False
    settings.location_config = DownloadLocationConfig(MODE_DEFAULT)
    manager = DownloadManager(settings)
    service = BrowserIntegrationService(
        settings,
        manager,
        descriptor_path=tmp_path / "runtime" / "security-bridge.json",
    )
    try:
        with caplog.at_level(logging.INFO, logger="integrations.service"):
            responses: list[dict] = []
            service.handle_request(
                {
                    "type": "request_download",
                    "request_id": "req-secret-01",
                    "browser": "chrome",
                    "extension_id": CHROME_EXTENSION_ID,
                    "url": (
                        "https://example.com/private/file.zip"
                        "?token=SUPERSECRET&session=COOKIEVALUE"
                    ),
                    "filename": "file.zip",
                },
                responses.append,
            )
        assert responses and responses[0]["ok"] is True
        messages = "\n".join(record.getMessage() for record in caplog.records)
        assert "SUPERSECRET" not in messages
        assert "COOKIEVALUE" not in messages
        assert "https://example.com/…" in messages
    finally:
        service.stop()
        manager.shutdown()
        settings.close()
