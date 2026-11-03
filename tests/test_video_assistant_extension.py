"""IDM Video Assistant manifest, assets and detector checks."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from integrations.browser_registry import CHROME_EXTENSION_ID
from idm.version import CURRENT_VERSION
from scripts import package_video_assistant as video_packaging
from scripts.package_extensions import extension_id_from_key

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "BrowserExtension" / "IDMVideoAssistant"
REQUIRED_FILES = (
    "manifest.json",
    "background.js",
    "content.js",
    "popup.html",
    "popup.css",
    "popup.js",
    "media-detector.js",
    "native-messaging.js",
    "README.md",
    "InstallationGuide.md",
    "icons/icon16.png",
    "icons/icon32.png",
    "icons/icon48.png",
    "icons/icon128.png",
)


def _manifest() -> dict:
    return json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))


def test_required_assets_exist() -> None:
    for relative in REQUIRED_FILES:
        path = EXTENSION / relative
        assert path.is_file(), f"missing {relative}"
        assert path.stat().st_size > 0, f"empty {relative}"


def test_manifest_is_minimal_mv3() -> None:
    manifest = _manifest()
    assert manifest["manifest_version"] == 3
    assert manifest["name"] == "IDM Video Assistant"
    assert manifest["version"] == CURRENT_VERSION
    assert manifest["background"] == {"service_worker": "background.js"}
    assert manifest["action"]["default_popup"] == "popup.html"
    assert extension_id_from_key(manifest["key"]) == CHROME_EXTENSION_ID
    assert set(manifest) == {
        "manifest_version",
        "name",
        "short_name",
        "version",
        "description",
        "minimum_chrome_version",
        "key",
        "icons",
        "action",
        "background",
        "content_scripts",
        "permissions",
    }
    # Minimum permissions: no history, tabs, cookies, webRequest or host grants.
    permissions = manifest["permissions"]
    assert permissions == [
        "nativeMessaging",
        "downloads",
        "contextMenus",
        "storage",
        "activeTab",
    ]
    for prohibited in (
        "history",
        "tabs",
        "cookies",
        "webRequest",
        "webRequestBlocking",
        "management",
        "debugger",
        "proxy",
    ):
        assert prohibited not in permissions
    assert "host_permissions" not in manifest
    scripts = manifest["content_scripts"]
    assert len(scripts) == 1
    assert set(scripts[0]["matches"]) == {"http://*/*", "https://*/*"}
    assert scripts[0]["js"] == ["media-detector.js", "content.js"]
    assert scripts[0]["all_frames"] is True


def test_no_dynamic_code_or_shell_access() -> None:
    for script in EXTENSION.glob("*.js"):
        text = script.read_text(encoding="utf-8")
        assert "eval(" not in text, f"{script.name} uses eval"
        assert "new Function" not in text, f"{script.name} builds code dynamically"
        assert "child_process" not in text
        assert "execSync" not in text


def test_popup_ids_and_message_routes_line_up() -> None:
    html = (EXTENSION / "popup.html").read_text(encoding="utf-8")
    popup = (EXTENSION / "popup.js").read_text(encoding="utf-8")
    background = (EXTENSION / "background.js").read_text(encoding="utf-8")

    ids = set(re.findall(r'id="([^"]+)"', html))
    used = set(re.findall(r'getElementById\("([^"]+)"\)', popup))
    assert not used - ids, f"popup.js refers to missing elements: {used - ids}"
    for identifier in ids:
        assert html.count(f'id="{identifier}"') == 1, f"duplicate id {identifier}"

    sent = set(re.findall(r'"(idm:[A-Za-z]+)"', popup))
    routed = set(re.findall(r'"(idm:[A-Za-z]+)"', background))
    assert sent <= routed, f"unrouted popup messages: {sent - routed}"


def test_background_uses_the_registered_host_and_protocol_fields() -> None:
    native = (EXTENSION / "native-messaging.js").read_text(encoding="utf-8")
    background = (EXTENSION / "background.js").read_text(encoding="utf-8")
    assert 'const HOST_NAME = "com.idm.native";' in native
    assert 'type: "request_download"' in native
    for field in (
        "page_url",
        "page_title",
        "media_kind",
        "quality_label",
        "duration_seconds",
        "detected_by",
    ):
        assert field in native
    assert "importScripts(\"media-detector.js\", \"native-messaging.js\")" in background


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_detector_and_native_request_harness() -> None:
    result = subprocess.run(
        ["node", str(ROOT / "tests" / "video_assistant_harness.js")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "video assistant harness passed" in result.stdout


def test_page_capture_is_wired_through_every_layer() -> None:
    """Popup button -> background route -> content handler -> native request."""
    detector = (EXTENSION / "media-detector.js").read_text(encoding="utf-8")
    native = (EXTENSION / "native-messaging.js").read_text(encoding="utf-8")
    content = (EXTENSION / "content.js").read_text(encoding="utf-8")
    background = (EXTENSION / "background.js").read_text(encoding="utf-8")
    popup = (EXTENSION / "popup.js").read_text(encoding="utf-8")
    html = (EXTENSION / "popup.html").read_text(encoding="utf-8")

    assert 'id="capture-links"' in html
    assert 'getElementById("capture-links")' in popup
    assert '"idm:capturePage"' in popup
    assert 'type === "idm:capturePage"' in background
    assert '"idm:collectLinks"' in background
    assert 'message.type === "idm:collectLinks"' in content
    assert "function buildCaptureRequest" in native
    assert '"capture_page_links"' in native
    assert "function collectLinks" in detector

    # The extension must never offer more links than the native host accepts.
    from integrations.protocol import MAX_CAPTURE_LINKS

    assert re.search(r"MAX_CAPTURE_LINKS = (\d+)", native).group(1) == str(
        MAX_CAPTURE_LINKS
    )
    assert re.search(r"MAX_CAPTURE_LINKS = (\d+)", detector).group(1) == str(
        MAX_CAPTURE_LINKS
    )


def test_youtube_official_options_are_wired_into_the_popup() -> None:
    detector = (EXTENSION / "media-detector.js").read_text(encoding="utf-8")
    popup = (EXTENSION / "popup.js").read_text(encoding="utf-8")
    html = (EXTENSION / "popup.html").read_text(encoding="utf-8")
    guide = (EXTENSION / "InstallationGuide.md").read_text(encoding="utf-8")

    assert "function officialOptionsFor" in detector
    assert "https://www.youtube.com/premium" in detector
    assert "https://music.youtube.com/premium" in detector
    assert "https://studio.youtube.com" in detector
    assert "https://support.google.com/youtube/answer/56100" in detector
    assert "function renderOfficial" in popup
    assert "idm:openPage" in popup
    assert 'id="official-list"' in html
    assert "chrome://extensions" in guide
    assert "edge://extensions" in guide
    assert "Load unpacked" in guide


def test_unpacked_zip_is_valid_and_deterministic(tmp_path: Path) -> None:
    info = video_packaging.validate_extension()
    first = video_packaging.build_package(info, tmp_path / "one")
    second = video_packaging.build_package(info, tmp_path / "two")

    assert first["sha256"] == second["sha256"]
    assert len(first["sha256"]) == 64
    archive = first["archive"]
    assert archive.name == f"IDM_Video_Assistant_{info['version']}.zip"
    with zipfile.ZipFile(archive) as package:
        names = set(package.namelist())
        assert "manifest.json" in names
        assert "README.md" in names
        assert "InstallationGuide.md" in names
        assert "icons/icon128.png" in names
        assert not any(name.endswith(".crx") for name in names)
        assert not any("__pycache__" in name for name in names)
        manifest = json.loads(package.read("manifest.json"))
        assert manifest["version"] == info["version"]

