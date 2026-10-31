"""App data layout tests."""

from __future__ import annotations

from pathlib import Path

from idm.constants import APP_DATA_DIR_NAME
from idm.core.paths import (
    app_data_dir,
    database_file,
    default_download_dir,
    ensure_app_layout,
    log_file,
    schedules_file,
    settings_file,
)


def test_ensure_app_layout_uses_an_isolated_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))

    ensure_app_layout()

    root = Path(tmp_path / "appdata") / APP_DATA_DIR_NAME
    assert root.name == "IDM Download Manager"
    assert root.parent.name == "appdata"
    for name in ("database", "logs", "settings", "downloads"):
        assert (root / name).is_dir()
    assert database_file().parent == root / "database"
    assert log_file().parent == root / "logs"
    assert settings_file().parent == root / "settings"
    assert schedules_file().parent == root / "settings"


def test_commercial_idm_folder_is_not_touched(tmp_path, monkeypatch):
    appdata = tmp_path / "appdata"
    shared = appdata / "IDM"
    shared.mkdir(parents=True)
    (shared / "idm.log").write_text("commercial product log", encoding="utf-8")
    (shared / "downloads").mkdir()
    (shared / "downloads" / "user-file.bin").write_bytes(b"user data")
    before = sorted(
        (path.relative_to(shared).as_posix(), path.is_dir())
        for path in shared.rglob("*")
    )

    monkeypatch.setenv("APPDATA", str(appdata))
    ensure_app_layout()

    after = sorted(
        (path.relative_to(shared).as_posix(), path.is_dir())
        for path in shared.rglob("*")
    )
    assert after == before
    assert (shared / "idm.log").read_text(encoding="utf-8") == "commercial product log"
    assert not (shared / "database").exists()
    assert not (Path(default_download_dir()).is_relative_to(shared))


def test_default_download_dir_is_inside_app_data(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))

    assert Path(default_download_dir()) == app_data_dir() / "downloads"
    assert Path(default_download_dir()).is_dir()
