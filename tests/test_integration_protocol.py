"""Native messaging framing, validation and duplicate protection."""

from __future__ import annotations

import io
import json
import struct

import pytest

from integrations.protocol import (
    DuplicateTracker,
    MAX_CAPTURE_LINKS,
    MAX_MESSAGE_BYTES,
    ProtocolError,
    ValidationError,
    decode_line,
    encode_line,
    encode_message,
    normalize_capture_request,
    normalize_download_request,
    read_message,
    require_browser,
    require_extension_id,
    require_request_id,
    response_error,
    response_ok,
    validate_filename,
    validate_http_url,
    validate_media_kind,
    validate_mime,
    validate_page_title,
    validate_quality_label,
    validate_referrer,
    validate_total_bytes,
    write_message,
)


def _stream(data: bytes) -> io.BytesIO:
    return io.BytesIO(data)


def test_message_round_trip_preserves_unicode() -> None:
    message = {"type": "status", "name": "Grüße – 日本語", "n": 3}
    encoded = encode_message(message)
    length = struct.unpack("<I", encoded[:4])[0]
    assert length == len(encoded) - 4
    assert read_message(_stream(encoded)) == message
    assert read_message(_stream(encoded)) is not None
    assert read_message(_stream(b"")) is None


def test_write_message_flushes_and_is_readable() -> None:
    buffer = io.BytesIO()
    write_message(buffer, {"ok": True})
    assert read_message(_stream(buffer.getvalue())) == {"ok": True}


def test_read_message_rejects_truncated_header() -> None:
    with pytest.raises(ProtocolError) as caught:
        read_message(_stream(b"\x01\x00"))
    assert caught.value.code == "truncated_message"


def test_read_message_rejects_truncated_body() -> None:
    payload = b'{"type":"status"}'
    data = struct.pack("<I", len(payload) + 10) + payload
    with pytest.raises(ProtocolError) as caught:
        read_message(_stream(data))
    assert caught.value.code == "truncated_message"


def test_read_message_rejects_empty_frame() -> None:
    with pytest.raises(ProtocolError) as caught:
        read_message(_stream(struct.pack("<I", 0)))
    assert caught.value.code == "empty_message"


def test_read_message_rejects_oversized_frame_without_allocating() -> None:
    data = struct.pack("<I", MAX_MESSAGE_BYTES + 1)
    with pytest.raises(ProtocolError) as caught:
        read_message(_stream(data))
    assert caught.value.code == "message_too_large"


def test_read_message_rejects_invalid_json_and_non_objects() -> None:
    payload = b"not json"
    with pytest.raises(ProtocolError):
        read_message(_stream(struct.pack("<I", len(payload)) + payload))

    payload = b"[1, 2, 3]"
    with pytest.raises(ProtocolError):
        read_message(_stream(struct.pack("<I", len(payload)) + payload))


def test_encode_message_refuses_oversized_payload() -> None:
    with pytest.raises(ProtocolError) as caught:
        encode_message({"blob": "x" * (MAX_MESSAGE_BYTES + 1)})
    assert caught.value.code == "message_too_large"


def test_bridge_line_round_trip_and_size_limit() -> None:
    message = {"type": "hello", "text": "hello\nworld"}
    assert decode_line(encode_line(message)) == message
    with pytest.raises(ProtocolError):
        decode_line(b"x" * (MAX_MESSAGE_BYTES + 1))
    with pytest.raises(ProtocolError):
        decode_line(b"{")
    with pytest.raises(ProtocolError):
        decode_line(b"[]")


def test_request_id_validation() -> None:
    assert require_request_id({"request_id": "req-01:abcdef"}) == "req-01:abcdef"
    for bad in ("short", "", "has space", "slash/id-123456", None):
        with pytest.raises(ValidationError):
            require_request_id({"request_id": bad})


def test_browser_and_extension_validation() -> None:
    assert require_browser({"browser": "Chrome"}) == "chrome"
    for browser in ("brave", "opera"):
        assert require_browser({"browser": browser.upper()}) == browser
    with pytest.raises(ValidationError) as caught:
        require_browser({"browser": "safari"})
    assert caught.value.code == "unsupported_browser"

    assert require_extension_id({"extension_id": "idm@example.local"}) == (
        "idm@example.local"
    )
    with pytest.raises(ValidationError):
        require_extension_id({"extension_id": "bad id"})


def test_every_module_agrees_on_the_supported_browsers() -> None:
    """A browser missing from one list silently breaks its integration."""
    from integrations import browser_detector, registration
    from integrations.protocol import SUPPORTED_BROWSERS as PROTOCOL_BROWSERS

    assert PROTOCOL_BROWSERS == browser_detector.SUPPORTED_BROWSERS
    assert PROTOCOL_BROWSERS == registration.SUPPORTED_BROWSERS


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/file.bin",
        "http://example.com/a?b=1",
        "HTTPS://example.com/",
    ],
)
def test_validate_http_url_accepts_http_and_https(url: str) -> None:
    assert validate_http_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/file.bin",
        "file:///C:/Windows/win.ini",
        "javascript:alert(1)",
        "data:text/plain,hello",
        "https://user:pass@example.com/file",
        "https://example.com/file with spaces",
        "not a url",
        "",
        None,
    ],
)
def test_validate_http_url_rejects_unsafe_urls(url) -> None:
    with pytest.raises(ValidationError):
        validate_http_url(url)


def test_referrer_validation_is_optional_but_strict() -> None:
    assert validate_referrer(None) == ""
    assert validate_referrer("") == ""
    assert validate_referrer("https://example.com/page") == (
        "https://example.com/page"
    )
    with pytest.raises(ValidationError):
        validate_referrer("file:///C:/secret.txt")


def test_filename_validation_rejects_paths_and_reserved_names() -> None:
    assert validate_filename("report.pdf") == "report.pdf"
    assert validate_filename(None) == ""
    for bad in ("../escape.bin", "sub/dir.bin", "C:\\evil.bin", "a:b", "..", "CON.txt"):
        with pytest.raises(ValidationError):
            validate_filename(bad)


def test_mime_and_total_bytes_validation() -> None:
    assert validate_mime("application/octet-stream") == "application/octet-stream"
    assert validate_mime("") == ""
    with pytest.raises(ValidationError):
        validate_mime("text")
    assert validate_total_bytes(None) is None
    assert validate_total_bytes(1234) == 1234
    for bad in (True, "1234", -1, 10**16):
        with pytest.raises(ValidationError):
            validate_total_bytes(bad)


def _download_message(**overrides):
    message = {
        "type": "request_download",
        "request_id": "req-12345678",
        "browser": "chrome",
        "extension_id": "abcd",
        "client_version": "1.0.0",
        "url": "https://example.com/file.zip",
        "filename": "file.zip",
        "referrer": "https://example.com/page",
        "mime": "application/zip",
        "total_bytes": 2048,
    }
    message.update(overrides)
    return message


def test_normalize_download_request_strips_to_allowlisted_fields() -> None:
    message = _download_message(extra="ignored")
    normalized = normalize_download_request(message)
    assert normalized == {
        "type": "request_download",
        "request_id": "req-12345678",
        "browser": "chrome",
        "extension_id": "abcd",
        "client_version": "1.0.0",
        "url": "https://example.com/file.zip",
        "filename": "file.zip",
        "referrer": "https://example.com/page",
        "page_url": "",
        "mime": "application/zip",
        "total_bytes": 2048,
        "ask_folder": False,
        "page_title": "",
        "media_kind": "",
        "quality_label": "",
        "duration_seconds": None,
        "detected_by": "",
    }
    assert "extra" not in normalized


def test_media_metadata_is_validated_and_normalized() -> None:
    normalized = normalize_download_request(
        _download_message(
            page_url="https://example.com/watch",
            page_title="  Sample clip  ",
            media_kind="VIDEO",
            quality_label="1080p",
            duration_seconds=93,
            detected_by="media",
        )
    )
    assert normalized["page_url"] == "https://example.com/watch"
    assert normalized["page_title"] == "Sample clip"
    assert normalized["media_kind"] == "video"
    assert normalized["quality_label"] == "1080p"
    assert normalized["duration_seconds"] == 93
    assert normalized["detected_by"] == "media"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("page_title", "bad\x00title"),
        ("page_title", "x" * 513),
        ("media_kind", "stream"),
        ("quality_label", "x" * 65),
        ("duration_seconds", -1),
        ("duration_seconds", True),
        ("duration_seconds", "93"),
        ("detected_by", "scraping"),
    ],
)
def test_invalid_media_metadata_is_rejected(field: str, value) -> None:
    with pytest.raises(ValidationError):
        normalize_download_request(_download_message(**{field: value}))


def test_media_helpers_accept_only_known_values() -> None:
    assert validate_media_kind(None) == ""
    assert validate_media_kind("AUDIO") == "audio"
    assert validate_page_title(None) == ""
    assert validate_quality_label(None) == ""
    assert validate_total_bytes(None) is None
    with pytest.raises(ValidationError):
        validate_media_kind("movie")


def test_ask_folder_is_an_optional_boolean() -> None:
    assert normalize_download_request(_download_message())["ask_folder"] is False
    assert (
        normalize_download_request(_download_message(ask_folder=True))["ask_folder"]
        is True
    )
    for bad in ("yes", 1, 0, {}, []):
        with pytest.raises(ValidationError):
            normalize_download_request(_download_message(ask_folder=bad))


def test_normalize_download_request_requires_download_type() -> None:
    with pytest.raises(ValidationError) as caught:
        normalize_download_request(_download_message(type="status"))
    assert caught.value.code == "unsupported_type"


def test_normalize_download_request_rejects_missing_url() -> None:
    with pytest.raises(ValidationError):
        normalize_download_request(_download_message(url=""))


def test_duplicate_tracker_expires_and_bounds_entries() -> None:
    tracker = DuplicateTracker(ttl_seconds=10, limit=16)
    response = response_ok("req-12345678", "download_accepted")
    tracker.put("req-12345678", response, now=100.0)
    cached = tracker.get("req-12345678", now=105.0)
    assert cached == response
    assert cached is not response  # callers cannot mutate the cache
    assert tracker.get("req-12345678", now=111.0) is None

    for index in range(40):
        tracker.put(f"req-{index:08d}", response, now=200.0 + index)
    # The tracker never grows past its configured bound.
    assert tracker.get("req-00000000", now=201.0) is None
    assert tracker.get("req-00000039", now=240.0) == response
    tracker.clear()
    assert tracker.get("req-00000039", now=240.0) is None


def test_response_helpers_have_stable_shape() -> None:
    ok = response_ok("req-12345678", "status", connected=True)
    assert ok["ok"] is True
    assert ok["protocol"] == 2
    assert ok["request_id"] == "req-12345678"
    assert ok["connected"] is True

    error = response_error(None, "invalid_url", "bad", retryable=True)
    assert error["ok"] is False
    assert error["type"] == "error"
    assert error["request_id"] == ""
    assert error["error"] == {
        "code": "invalid_url",
        "message": "bad",
        "retryable": True,
    }
    assert json.dumps(ok)  # always JSON serialisable


# ---------------------------------------------------------------------------
# Page link capture
# ---------------------------------------------------------------------------


def _capture_message(**overrides):
    message = {
        "type": "capture_page_links",
        "request_id": "req-capture01",
        "browser": "chrome",
        "extension_id": "abcd",
        "client_version": "1.0.0",
        "page_url": "https://example.com/index.html",
        "page_title": "Example index",
        "links": [
            {"url": "https://example.com/files/a.zip", "filename": "a.zip"},
            {"url": "https://example.com/files/b.pdf"},
        ],
    }
    message.update(overrides)
    return message


def test_normalize_capture_request_keeps_allowlisted_fields() -> None:
    normalized = normalize_capture_request(_capture_message(extra="ignored"))
    assert normalized == {
        "type": "capture_page_links",
        "request_id": "req-capture01",
        "browser": "chrome",
        "extension_id": "abcd",
        "client_version": "1.0.0",
        "page_url": "https://example.com/index.html",
        "page_title": "Example index",
        "links": [
            {"url": "https://example.com/files/a.zip", "filename": "a.zip"},
            {"url": "https://example.com/files/b.pdf", "filename": ""},
        ],
    }
    assert "extra" not in normalized


def test_capture_drops_links_that_cannot_be_downloaded() -> None:
    message = _capture_message(
        links=[
            {"url": "https://example.com/a.zip"},
            {"url": "mailto:someone@example.com"},
            {"url": "javascript:alert(1)"},
            {"url": "#section-two"},
            {"url": ""},
            "not a url",
            None,
        ]
    )
    normalized = normalize_capture_request(message)
    assert normalized["links"] == [
        {"url": "https://example.com/a.zip", "filename": ""}
    ]


def test_capture_deduplicates_repeated_links() -> None:
    message = _capture_message(
        links=[
            {"url": "https://example.com/a.zip"},
            {"url": "https://example.com/a.zip"},
            {"url": "https://example.com/b.zip"},
        ]
    )
    normalized = normalize_capture_request(message)
    assert [link["url"] for link in normalized["links"]] == [
        "https://example.com/a.zip",
        "https://example.com/b.zip",
    ]


def test_capture_keeps_a_safe_name_and_drops_an_unsafe_one() -> None:
    message = _capture_message(
        links=[
            {"url": "https://example.com/a.zip", "filename": "../escape.zip"},
            {"url": "https://example.com/b.zip", "filename": "b.zip"},
        ]
    )
    normalized = normalize_capture_request(message)
    assert normalized["links"][0]["filename"] == ""
    assert normalized["links"][1]["filename"] == "b.zip"


@pytest.mark.parametrize(
    ("links", "code"),
    [
        ([], "no_links"),
        ("https://example.com/a.zip", "no_links"),
        (None, "no_links"),
        ([{"url": "mailto:someone@example.com"}], "no_capturable_links"),
        ([{"no_url": True}], "no_capturable_links"),
    ],
)
def test_capture_needs_downloadable_links(links, code) -> None:
    with pytest.raises(ValidationError) as caught:
        normalize_capture_request(_capture_message(links=links))
    assert caught.value.code == code


def test_capture_refuses_an_overlong_page() -> None:
    links = [
        {"url": f"https://example.com/f{i}.zip"}
        for i in range(MAX_CAPTURE_LINKS + 1)
    ]
    with pytest.raises(ValidationError) as caught:
        normalize_capture_request(_capture_message(links=links))
    assert caught.value.code == "too_many_links"

    # Exactly at the limit is accepted.
    accepted = normalize_capture_request(_capture_message(links=links[:-1]))
    assert len(accepted["links"]) == MAX_CAPTURE_LINKS


def test_capture_validates_the_page_and_the_request_shape() -> None:
    with pytest.raises(ValidationError) as caught:
        normalize_capture_request(_capture_message(type="request_download"))
    assert caught.value.code == "unsupported_type"

    with pytest.raises(ValidationError):
        normalize_capture_request(_capture_message(browser="safari"))

    with pytest.raises(ValidationError) as caught:
        normalize_capture_request(_capture_message(page_url="file:///C:/page.html"))
    assert caught.value.code == "invalid_referrer"

    with pytest.raises(ValidationError):
        normalize_capture_request(_capture_message(request_id="short"))

    with pytest.raises(ValidationError):
        normalize_capture_request("not a dict")
