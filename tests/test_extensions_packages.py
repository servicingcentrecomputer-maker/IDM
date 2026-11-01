"""Extension manifests, store packages and build/installer integration."""

from __future__ import annotations

import base64
import json
import zipfile
from pathlib import Path

import pytest

from scripts import package_extensions as packaging
from integrations.browser_registry import (
    CHROME_EXTENSION_ID,
    EDGE_EXTENSION_ID,
    FIREFOX_EXTENSION_ID,
)
from idm.version import CURRENT_VERSION

ROOT = Path(__file__).resolve().parents[1]
BROWSERS = ("chrome", "edge", "firefox")


@pytest.mark.parametrize("browser", BROWSERS)
def test_extension_validation_passes(browser: str) -> None:
    info = packaging.validate_extension(browser)
    manifest = info["manifest"]
    assert manifest["name"]
    assert manifest["version"].count(".") == 2
    assert manifest["permissions"] == [
        permission
        for permission in manifest["permissions"]
    ]
    assert {"nativeMessaging", "downloads", "storage"} <= set(
        manifest["permissions"]
    )
    assert len(manifest["permissions"]) <= 6


def test_chrome_and_edge_are_mv3_with_the_pinned_key() -> None:
    for browser in ("chrome", "edge"):
        manifest = packaging.validate_extension(browser)["manifest"]
        assert manifest["manifest_version"] == 3
        assert manifest["background"] == {"service_worker": "background.js"}
        assert packaging.extension_id_from_key(manifest["key"]) == CHROME_EXTENSION_ID
        assert manifest["minimum_chrome_version"]
        assert "browser_specific_settings" not in manifest

    edge = packaging.validate_extension("edge")["manifest"]
    assert "Edge" in edge["name"]
    assert packaging.extension_id_from_key(edge["key"]) == EDGE_EXTENSION_ID


def test_firefox_is_mv2_with_a_stable_gecko_id() -> None:
    manifest = packaging.validate_extension("firefox")["manifest"]
    assert manifest["manifest_version"] == 2
    gecko = manifest["browser_specific_settings"]["gecko"]
    assert gecko["id"] == FIREFOX_EXTENSION_ID
    assert gecko["strict_min_version"]
    assert manifest["background"] == {
        "scripts": ["background.js"],
        "persistent": True,
    }
    assert manifest["permissions"] == [
        "nativeMessaging",
        "downloads",
        "menus",
        "storage",
    ]


@pytest.mark.parametrize("browser", BROWSERS)
def test_background_declares_its_browser_and_native_host(browser: str) -> None:
    text = (ROOT / "extensions" / browser / "background.js").read_text(
        encoding="utf-8"
    )
    assert f'const BROWSER = "{browser}";' in text
    assert 'const HOST_NAME = "com.idm.native";' in text
    assert 'type: "request_download"' in text
    assert "ask_folder" in text
    # Users choose a folder for every browser download unless they turn the
    # popup toggle off.
    assert "const DEFAULT_ASK_FOLDER = true;" in text
    assert "idm-download-link-to" in text


@pytest.mark.parametrize("browser", BROWSERS)
def test_popup_assets_are_present_and_reference_the_host(browser: str) -> None:
    folder = ROOT / "extensions" / browser
    html = (folder / "popup.html").read_text(encoding="utf-8")
    script = (folder / "popup.js").read_text(encoding="utf-8")
    background = (folder / "background.js").read_text(encoding="utf-8")
    assert "Test Connection" in html
    assert "Open IDM" in html
    assert "Ask where to save" in html
    assert "idm:testConnection" in script
    assert "idm:getState" in script
    # Preferences are written straight to extension storage so the toggles do
    # not depend on a wake-up round trip through the background worker.
    assert "storage.local.set" in script
    assert "autoIntercept" in script
    assert "askFolder" in script
    assert "askFolder: true" in script
    assert "storage.onChanged" in background


def test_manual_key_derivation_matches_the_manifest() -> None:
    manifest = json.loads(
        (ROOT / "extensions" / "chrome" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    raw = base64.b64decode(manifest["key"])
    assert packaging.extension_id_from_key(manifest["key"]) == CHROME_EXTENSION_ID
    assert len(raw) > 256


def test_packages_are_deterministic_and_store_ready(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    assert packaging.main(["--output-dir", str(first)]) == 0
    assert packaging.main(["--output-dir", str(second)]) == 0

    for browser, filename in packaging.PACKAGES.items():
        archive = first / filename
        assert archive.is_file()
        assert archive.read_bytes() == (second / filename).read_bytes()

        with zipfile.ZipFile(archive) as package:
            names = package.namelist()
            assert "manifest.json" in names
            assert "background.js" in names
            assert "popup.html" in names
            for icon in ("icons/icon16.png", "icons/icon32.png", "icons/icon48.png", "icons/icon128.png"):
                assert icon in names
            assert not any("__pycache__" in name for name in names)
            packaged_manifest = json.loads(package.read("manifest.json"))
            assert packaged_manifest["version"] == packaging.validate_extension(
                browser
            )["version"]


def test_installer_registers_each_browser_and_ships_extension_zips() -> None:
    text = (ROOT / "installer" / "IDM_Setup.iss").read_text(encoding="utf-8")
    assert "IDM_NativeHost.exe" in text
    assert r"Software\Google\Chrome\NativeMessagingHosts" in text
    assert r"Software\Microsoft\Edge\NativeMessagingHosts" in text
    assert r"Software\Mozilla\NativeMessagingHosts" in text
    assert CHROME_EXTENSION_ID in text
    assert FIREFOX_EXTENSION_ID in text
    assert "browser-extensions" in text
    assert "uninsdeletevalue uninsdeletekeyifempty" in text
    # Extensions are shipped as archives and as the unpacked V3 assistant,
    # never silently installed.
    assert "dist-extensions\\*.zip" in text
    assert r"BrowserExtension\IDMVideoAssistant\*" in text
    assert "chrome-extension://" in text
    assert "allowed_extensions" in text
    assert "OutputBaseFilename=IDM-Setup-{#MyAppVersion}" in text
    assert f'#define MyAppVersion "{CURRENT_VERSION}"' in text


def test_package_release_uses_the_versioned_installer_name() -> None:
    from scripts import package_release

    assert package_release.read_source_version(ROOT) == CURRENT_VERSION
    package_release.validate_versions(ROOT, CURRENT_VERSION)


def test_pyinstaller_build_includes_the_native_host() -> None:
    spec = (ROOT / "IDM.spec").read_text(encoding="utf-8")
    assert "native_host_main.py" in spec
    assert "IDM_NativeHost" in spec
    assert "integrations.native_host" in spec
    assert "version_info_native_host.txt" in spec

    script = (ROOT / "build_windows.ps1").read_text(encoding="utf-8")
    assert "package_extensions.py" in script
    assert "dist-extensions" in script
    assert "IDM_NativeHost.exe" in script
