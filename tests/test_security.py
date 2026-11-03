"""Security-focused checks for links, file names and browser metadata."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from downloads.location_manager import MODE_DEFAULT, DownloadLocationConfig, safe_join
from idm.core.logging_setup import SecretRedactionFilter
from idm.core.settings import AppSettings
from idm.core.url_utils import (
    InvalidUrlError,
    redact_url,
    sanitize_filename,
    scrub_secrets,
    validate_url,
)
from idm.engine.manager import DownloadManager
from idm.engine.worker import _clean_error
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
        "mailto:someone@example.com",
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


def test_scrub_secrets_drops_credentials_from_free_form_text() -> None:
    proxy = scrub_secrets("Tunnel failed for http://Jawad:s3cr3t@proxy.local:8080")
    assert "s3cr3t" not in proxy
    assert proxy == "Tunnel failed for http://[redacted]@proxy.local:8080"

    query = scrub_secrets(
        "https://cdn.example.com/file.zip?token=abc123&size=10&api_key=zzz"
    )
    assert "abc123" not in query and "zzz" not in query
    assert "size=10" in query

    header = scrub_secrets("Authorization: Bearer eyJhbGciOi.eyJzdWIiOi rest")
    assert "eyJhbGciOi" not in header
    assert header.endswith("Bearer [redacted] rest")

    # Servers echo the parameter back in prose, not only inside a query string.
    prose = scrub_secrets("server rejected the request, token=SEKRIT9 (http 401)")
    assert "SEKRIT9" not in prose
    assert "http 401" in prose


def test_scrub_secrets_keeps_ordinary_text_and_empty_input() -> None:
    plain = "Remote end closed the connection at 14:02 (size=4096, retry in 5s)"
    assert scrub_secrets(plain) == plain
    assert scrub_secrets("") == ""


def test_secret_redaction_filter_rewrites_the_record_it_accepts() -> None:
    record = logging.LogRecord(
        "idm.engine.worker",
        logging.ERROR,
        "worker.py",
        12,
        "proxy %s refused: %s",
        ("http://Jawad:s3cr3t@p.local", "token=SEKRIT"),
        None,
    )
    assert SecretRedactionFilter().filter(record) is True
    message = record.getMessage()
    assert "s3cr3t" not in message
    assert "SEKRIT" not in message
    assert "p.local" in message


def test_unformattable_record_is_still_logged() -> None:
    record = logging.LogRecord(
        "idm", logging.ERROR, "x.py", 1, "one placeholder: %s", ("a", "b"), None
    )
    with pytest.raises(TypeError):
        record.getMessage()
    assert SecretRedactionFilter().filter(record) is True


def test_worker_error_text_is_scrubbed_before_reaching_the_list() -> None:
    failure = _clean_error(ValueError("cannot reach ftp://user:pw@files.example.com"))
    assert "pw@" not in failure
    assert "files.example.com" in failure

    assert _clean_error(RuntimeError("  ")) == "RuntimeError"
