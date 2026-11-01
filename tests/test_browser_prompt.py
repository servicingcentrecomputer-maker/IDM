"""Browser requests routed through the interactive Download File Info dialog."""

from __future__ import annotations

from pathlib import Path

import pytest

from downloads.location_manager import MODE_DEFAULT, DownloadLocationConfig
from idm.core.settings import AppSettings
from idm.engine.manager import DownloadManager
from idm.models.download_item import DownloadStatus
from integrations.browser_registry import CHROME_EXTENSION_ID
from integrations.service import BrowserIntegrationService


def request(**overrides):
    values = {
        "type": "request_download",
        "request_id": "req-prompt-0001",
        "browser": "chrome",
        "extension_id": CHROME_EXTENSION_ID,
        "url": "https://example.com/file.zip",
        "filename": "file.zip",
    }
    values.update(overrides)
    return values


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    instance = AppSettings()
    instance.download_dir = str(tmp_path / "Downloads")
    Path(instance.download_dir).mkdir(parents=True)
    instance.start_immediately = True
    instance.location_config = DownloadLocationConfig(MODE_DEFAULT)
    yield instance
    instance.close()


@pytest.fixture
def manager(qt_app, settings):
    instance = DownloadManager(settings)
    yield instance
    instance.shutdown()


def make_service(settings, manager, tmp_path, prompt):
    return BrowserIntegrationService(
        settings,
        manager,
        download_prompt=prompt,
        descriptor_path=tmp_path / "runtime" / "prompt-bridge.json",
    )


def call(service, payload):
    responses: list[dict] = []
    service.handle_request(payload, responses.append)
    assert responses, "the service must answer every request"
    return responses[0]


def test_accepting_the_dialog_creates_the_task(
    qt_app, settings, manager, tmp_path
) -> None:
    target = tmp_path / "Chosen"
    target.mkdir()
    captured: list[tuple[dict, dict]] = []

    def prompt(payload, submit):
        values = {
            "url": payload["url"],
            "filename": "renamed.zip",
            "folder": str(target),
            "category": "Compressed",
            "priority": 1,
            "start_immediately": False,
            "download_later": True,
            "description": "Saved from Chrome",
        }
        item = submit(dict(values))
        captured.append((payload, item))
        return values, item

    service = make_service(settings, manager, tmp_path, prompt)
    try:
        response = call(
            service,
            request(
                url="https://example.com/archive.zip",
                filename="archive.zip",
                referrer="https://example.com/page",
                mime="application/zip",
                total_bytes=4096,
                page_url="https://example.com/page",
                page_title="Downloads",
                quality_label="",
                detected_by="browser",
            ),
        )
    finally:
        service.stop()

    assert response["ok"] is True, response.get("error")
    assert response["type"] == "download_accepted"
    assert response["download"]["filename"] == "renamed.zip"
    assert response["download"]["folder"] == str(target)

    payload, item = captured[0]
    assert payload["url"] == "https://example.com/archive.zip"
    assert payload["filename"] == "archive.zip"
    assert payload["category"] == "Compressed"
    assert payload["content_type"] == "application/zip"
    assert payload["total_bytes"] == 4096
    assert payload["source_browser"] == "chrome"
    assert payload["referrer"] == "https://example.com/page"
    assert payload["page_url"] == "https://example.com/page"
    assert payload["page_title"] == "Downloads"

    stored = manager.get(item.id)
    assert stored is not None
    assert stored.description == "Saved from Chrome"
    assert stored.queued_later is True
    assert stored.status == DownloadStatus.QUEUED
    assert stored.source_browser == "chrome"
    assert stored.referrer == "https://example.com/page"
    assert stored.content_type == "application/zip"
    assert stored.page_title == "Downloads"


def test_cancelling_the_dialog_answers_cancelled(
    qt_app, settings, manager, tmp_path
) -> None:
    calls: list[dict] = []

    def prompt(payload, _submit):
        calls.append(payload)
        return None

    service = make_service(settings, manager, tmp_path, prompt)
    try:
        response = call(
            service,
            request(url="https://example.com/cancelled.zip", filename="cancelled.zip"),
        )
    finally:
        service.stop()

    assert response["ok"] is False
    assert response["error"]["code"] == "cancelled"
    assert manager.items() == []
    assert len(calls) == 1


def test_duplicate_browser_url_skips_the_dialog(
    qt_app, settings, manager, tmp_path
) -> None:
    existing = manager.add_download(
        "https://example.com/file.zip",
        "file.zip",
        settings.download_dir,
        start_immediately=False,
    )
    prompts: list[dict] = []

    def prompt(payload, _submit):
        prompts.append(payload)
        return None

    service = make_service(settings, manager, tmp_path, prompt)
    try:
        response = call(service, request())
    finally:
        service.stop()

    assert response["ok"] is True
    assert response["duplicate"] is True
    assert response["download"]["id"] == existing.id
    assert prompts == []
    assert len(manager.items()) == 1


def test_ask_folder_is_forwarded_to_the_dialog(
    qt_app, settings, manager, tmp_path
) -> None:
    captured: list[dict] = []
    target = tmp_path / "Picked"
    target.mkdir()

    def prompt(payload, submit):
        captured.append(payload)
        values = {
            "url": payload["url"],
            "filename": payload["filename"],
            "folder": str(target),
            "category": payload["category"],
            "start_immediately": True,
            "download_later": False,
        }
        return values, submit(dict(values))

    service = make_service(settings, manager, tmp_path, prompt)
    try:
        response = call(
            service,
            request(
                url="https://example.com/movie.mkv",
                filename="movie.mkv",
                ask_folder=True,
            ),
        )
    finally:
        service.stop()

    assert response["ok"] is True
    assert captured[0]["ask_folder"] is True
    assert captured[0]["category"] == "Videos"
    assert response["download"]["folder"] == str(target)


def test_reentrant_request_is_queued_not_recursed(
    qt_app, settings, manager, tmp_path
) -> None:
    nested: list[dict] = []
    status_request = {
        "type": "status",
        "request_id": "req-nested-01",
        "browser": "chrome",
        "extension_id": CHROME_EXTENSION_ID,
    }

    def prompt(payload, submit):
        service.handle_request(status_request, nested.append)
        assert nested == [], "the nested request must wait for the dialog"
        values = {
            "url": payload["url"],
            "filename": payload["filename"],
            "folder": settings.download_dir,
            "category": payload["category"],
            "start_immediately": True,
            "download_later": False,
        }
        return values, submit(dict(values))

    service = make_service(settings, manager, tmp_path, prompt)
    try:
        response = call(service, request(url="https://example.com/nested.bin"))
    finally:
        service.stop()

    assert response["ok"] is True
    assert len(nested) == 1
    assert nested[0]["ok"] is True
    assert nested[0]["type"] == "status"
