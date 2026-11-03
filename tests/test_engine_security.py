"""Engine-level guards: platform policy and destination folder validation."""

from __future__ import annotations

import pytest

from idm.core.settings import AppSettings
from idm.engine.manager import DownloadManager


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    settings = AppSettings()
    instance = DownloadManager(settings)
    yield instance
    instance.shutdown()
    settings.close()


def test_restricted_platform_page_is_blocked(manager, tmp_path):
    with pytest.raises(ValueError) as captured:
        manager.add_download(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "video.mp4",
            str(tmp_path),
            start_immediately=False,
        )

    assert "YouTube" in str(captured.value)
    assert manager.items() == []


def test_direct_media_file_is_still_allowed(manager, tmp_path):
    item = manager.add_download(
        "https://www.youtube.com/direct/clip.mp4",
        "clip.mp4",
        str(tmp_path),
        start_immediately=False,
    )

    assert item.id in [existing.id for existing in manager.items()]


def test_traversal_and_relative_folders_are_rejected(manager, tmp_path):
    for folder in (rf"{tmp_path}\..\..\Windows", "relative/downloads", ""):
        with pytest.raises(ValueError):
            manager.add_download(
                "https://example.com/package.zip", "package.zip", folder,
                start_immediately=False,
            )

    assert manager.items() == []


def test_a_missing_but_valid_folder_is_created(manager, tmp_path):
    destination = tmp_path / "New" / "Subfolder"
    item = manager.add_download(
        "https://example.com/tool.exe", "tool.exe", str(destination),
        start_immediately=False,
    )

    assert item.folder == str(destination.resolve())
    assert destination.is_dir()
