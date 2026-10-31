"""Background update schedule decisions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from idm.updater.schedule import (
    clamp_interval,
    evaluate_schedule,
    parse_timestamp,
    reminder_active,
)

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def _evaluate(**overrides):
    values = {
        "enabled": True,
        "configured": True,
        "interval_hours": 24,
        "last_check": "",
        "now": NOW,
        "active_downloads": 0,
    }
    values.update(overrides)
    return evaluate_schedule(**values)


def test_disabled_schedule_does_not_check():
    decision = _evaluate(enabled=False)
    assert decision.should_check is False
    assert decision.reason == "disabled"


def test_unconfigured_schedule_does_not_check():
    decision = _evaluate(configured=False)
    assert decision.should_check is False
    assert decision.reason == "not-configured"


def test_active_downloads_postpone_the_check():
    decision = _evaluate(active_downloads=2)
    assert decision.should_check is False
    assert decision.reason == "downloads-active"


def test_never_checked_runs_now():
    decision = _evaluate(last_check="")
    assert decision.should_check is True
    assert decision.reason == "never-checked"


def test_due_after_interval():
    last = (NOW - timedelta(hours=25)).isoformat()
    decision = _evaluate(last_check=last)
    assert decision.should_check is True
    assert decision.reason == "due"


def test_not_due_before_interval():
    last = (NOW - timedelta(hours=2)).isoformat()
    decision = _evaluate(last_check=last)
    assert decision.should_check is False
    assert decision.reason == "not-due"
    assert decision.next_due == datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)


def test_naive_timestamps_are_treated_as_utc():
    decision = _evaluate(last_check="2026-11-01T11:30:00")
    assert decision.should_check is False
    assert decision.reason == "not-due"


def test_interval_is_clamped():
    assert clamp_interval(0) == 1
    assert clamp_interval(10_000) == 168
    assert clamp_interval("bad") == 24


def test_parse_timestamp_accepts_zulu_and_rejects_garbage():
    parsed = parse_timestamp("2026-11-01T10:00:00Z")
    assert parsed == datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
    assert parse_timestamp("not a date") is None
    assert parse_timestamp("") is None


def test_reminder_suppresses_only_the_same_version_until_it_expires():
    until = (NOW + timedelta(hours=6)).isoformat()
    assert reminder_active(
        remind_after=until, remind_version="1.1.0", latest_version="1.1.0", now=NOW
    )
    assert not reminder_active(
        remind_after=until, remind_version="1.0.0", latest_version="1.1.0", now=NOW
    )
    assert not reminder_active(
        remind_after=(NOW - timedelta(minutes=1)).isoformat(),
        remind_version="1.1.0",
        latest_version="1.1.0",
        now=NOW,
    )
    assert not reminder_active(
        remind_after="", remind_version="", latest_version="1.1.0", now=NOW
    )
