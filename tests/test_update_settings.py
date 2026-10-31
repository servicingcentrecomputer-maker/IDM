"""Update-related application settings."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from idm.core.settings import AppSettings
from idm.updater.schedule import parse_timestamp


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    instance = AppSettings()
    yield instance
    instance.close()


def test_update_defaults(settings):
    assert settings.update_auto_check is True
    assert settings.update_check_interval_hours == 24
    assert settings.update_auto_download is False
    assert settings.update_ask_before_install is True
    assert settings.update_notify is True
    assert settings.update_last_check == ""
    assert settings.update_last_success == ""


def test_update_values_are_clamped_and_persisted(settings, tmp_path, monkeypatch):
    settings.update(
        {
            "update_auto_check": False,
            "update_check_interval_hours": 0,
            "update_auto_download": True,
            "update_ask_before_install": False,
            "update_notify": False,
        }
    )
    settings.save()
    assert settings.update_check_interval_hours == 1

    settings.update({"update_check_interval_hours": 10_000})
    settings.save()
    assert settings.update_check_interval_hours == 168

    settings.close()
    reloaded = AppSettings()
    try:
        assert reloaded.update_auto_check is False
        assert reloaded.update_check_interval_hours == 168
        assert reloaded.update_auto_download is True
        assert reloaded.update_ask_before_install is False
        assert reloaded.update_notify is False
    finally:
        reloaded.close()


def test_reminders_and_success_are_recorded(settings):
    settings.remind_later("1.1.0", 24)
    assert settings.update_remind_version == "1.1.0"
    until = parse_timestamp(settings.update_remind_after)
    assert until is not None
    assert until > datetime.now(timezone.utc)

    settings.note_update_success("1.1.0")
    assert settings.update_last_success_version == "1.1.0"
    assert parse_timestamp(settings.update_last_success) is not None
    assert settings.update_remind_after == ""
    assert settings.update_remind_version == ""

    settings.note_update_check()
    assert parse_timestamp(settings.update_last_check) is not None


def test_snapshot_is_json_safe_and_complete(settings):
    snapshot = settings.snapshot()
    assert snapshot["update_auto_check"] is True
    assert snapshot["update_check_interval_hours"] == 24
    assert isinstance(snapshot["download_type_rules"], list)
    assert all(isinstance(value, (str, int, float, bool, list, dict, type(None))) for value in snapshot.values())
