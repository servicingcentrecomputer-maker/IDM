"""Extension allowlist and native messaging manifest tests."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest

from integrations import browser_registry
from integrations.browser_registry import (
    CHROME_EXTENSION_ID,
    CHROME_EXTENSION_KEY,
    EDGE_EXTENSION_ID,
    FIREFOX_EXTENSION_ID,
    NATIVE_HOST_NAME,
    extension_id_for,
    extension_origin,
    is_allowed_extension,
    native_manifest,
    validate_native_manifest,
)


def _derive_id(key: str) -> str:
    digest = hashlib.sha256(base64.b64decode(key)).hexdigest()[:32]
    return "".join(chr(ord("a") + int(char, 16)) for char in digest)


def test_embedded_chrome_key_derives_the_pinned_id() -> None:
    assert _derive_id(CHROME_EXTENSION_KEY) == CHROME_EXTENSION_ID
    assert EDGE_EXTENSION_ID == CHROME_EXTENSION_ID


def test_extension_id_for_uses_environment_override() -> None:
    assert extension_id_for("chrome", {}) == CHROME_EXTENSION_ID
    assert extension_id_for("edge", {}) == EDGE_EXTENSION_ID
    assert extension_id_for("firefox", {}) == FIREFOX_EXTENSION_ID
    override = "abcdefghijklmnopabcdefghijklmnop"
    assert extension_id_for("chrome", {"IDM_CHROME_EXTENSION_ID": override}) == override
    # Blank overrides fall back to the built-in ID.
    assert extension_id_for("edge", {"IDM_EDGE_EXTENSION_ID": "  "}) == EDGE_EXTENSION_ID
    with pytest.raises(ValueError):
        extension_id_for("safari", {})


def test_extension_origin_is_browser_specific() -> None:
    assert extension_origin("chrome", {}) == (
        f"chrome-extension://{CHROME_EXTENSION_ID}/"
    )
    assert extension_origin("firefox", {}) == FIREFOX_EXTENSION_ID


def test_allowed_extension_matching() -> None:
    assert is_allowed_extension("chrome", CHROME_EXTENSION_ID, {})
    assert is_allowed_extension("chrome", CHROME_EXTENSION_ID.upper(), {})
    assert is_allowed_extension("firefox", FIREFOX_EXTENSION_ID, {})
    assert not is_allowed_extension(
        "firefox", FIREFOX_EXTENSION_ID.upper(), {}
    )
    assert not is_allowed_extension("chrome", "unrelatedextensionid", {})
    assert not is_allowed_extension("safari", "anything", {})
    assert not is_allowed_extension("chrome", "", {})


def test_native_manifest_shape_per_browser(tmp_path: Path) -> None:
    host = tmp_path / "IDM_NativeHost.exe"
    host.write_bytes(b"binary")

    chrome = native_manifest("chrome", host, {})
    assert chrome["name"] == NATIVE_HOST_NAME
    assert chrome["type"] == "stdio"
    assert Path(chrome["path"]) == host
    assert chrome["allowed_origins"] == [
        f"chrome-extension://{CHROME_EXTENSION_ID}/"
    ]

    edge = native_manifest("edge", host, {})
    assert edge["allowed_origins"] == [f"chrome-extension://{EDGE_EXTENSION_ID}/"]

    firefox = native_manifest("firefox", host, {})
    assert firefox["allowed_extensions"] == [FIREFOX_EXTENSION_ID]
    assert "allowed_origins" not in firefox

    with pytest.raises(ValueError):
        native_manifest("chrome", Path("relative.exe"), {})
    with pytest.raises(ValueError):
        native_manifest("safari", host, {})


def test_validate_native_manifest_reports_problems(tmp_path: Path) -> None:
    host = tmp_path / "IDM_NativeHost.exe"
    host.write_bytes(b"binary")

    assert validate_native_manifest(native_manifest("chrome", host, {}), "chrome") == []
    assert validate_native_manifest(native_manifest("firefox", host, {}), "firefox") == []

    assert validate_native_manifest(
        native_manifest("chrome", host, {}), "firefox"
    ), "Chrome manifest must not validate as Firefox"

    assert validate_native_manifest("not a dict", "chrome")
    assert validate_native_manifest(
        {"name": "other", "type": "stdio", "path": str(host), "allowed_origins": []},
        "chrome",
    )


def test_validation_checks_path_and_origins(tmp_path: Path) -> None:
    host = tmp_path / "IDM_NativeHost.exe"
    host.write_bytes(b"binary")
    manifest = native_manifest("chrome", host, {})

    assert "path does not match" in " ".join(
        validate_native_manifest(manifest, "chrome", tmp_path / "other.exe")
    )

    invalid = dict(manifest)
    invalid["allowed_origins"] = ["https://example.com/"]
    assert any("allowed_origins" in problem for problem in validate_native_manifest(invalid, "chrome"))

    invalid = dict(manifest)
    invalid["allowed_origins"] = "chrome-extension://x/"
    assert validate_native_manifest(invalid, "chrome")

    firefox = native_manifest("firefox", host, {})
    invalid = dict(firefox)
    invalid["allowed_extensions"] = []
    assert validate_native_manifest(invalid, "firefox")

    invalid = dict(firefox)
    invalid["allowed_extensions"] = [""]
    assert validate_native_manifest(invalid, "firefox")


def test_builtin_ids_are_documented() -> None:
    assert browser_registry.builtin_extension_id("chrome") == CHROME_EXTENSION_ID
    assert browser_registry.builtin_extension_id("edge") == EDGE_EXTENSION_ID
    assert browser_registry.builtin_extension_id("firefox") == FIREFOX_EXTENSION_ID
