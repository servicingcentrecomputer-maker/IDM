"""Pure decision helpers for the background update check schedule.

The Qt wrapper (:mod:`idm.ui.update_scheduler`) only runs timers; every rule
about when a check is allowed lives here so it can be unit tested without a
running application.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

MIN_INTERVAL_HOURS = 1
MAX_INTERVAL_HOURS = 168


@dataclass(frozen=True)
class ScheduleDecision:
    should_check: bool
    reason: str
    next_due: datetime | None = None


def parse_timestamp(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def clamp_interval(hours: int | float) -> int:
    try:
        value = int(hours)
    except (TypeError, ValueError):
        return 24
    return max(MIN_INTERVAL_HOURS, min(MAX_INTERVAL_HOURS, value))


def evaluate_schedule(
    *,
    enabled: bool,
    configured: bool,
    interval_hours: int,
    last_check: str | datetime | None,
    now: datetime | None = None,
    active_downloads: int = 0,
) -> ScheduleDecision:
    """Decide whether a background check may run right now."""
    moment = _now(now)
    if not enabled:
        return ScheduleDecision(False, "disabled")
    if not configured:
        return ScheduleDecision(False, "not-configured")
    if active_downloads > 0:
        return ScheduleDecision(False, "downloads-active")

    last = last_check if isinstance(last_check, datetime) else parse_timestamp(
        last_check or ""
    )
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    interval = timedelta(hours=clamp_interval(interval_hours))
    if last is None:
        return ScheduleDecision(True, "never-checked", moment)
    next_due = last + interval
    if moment >= next_due:
        return ScheduleDecision(True, "due", moment)
    return ScheduleDecision(False, "not-due", next_due)


def reminder_active(
    *,
    remind_after: str,
    remind_version: str,
    latest_version: str,
    now: datetime | None = None,
) -> bool:
    """True while “Remind me later” suppresses a notification for a version."""
    if not remind_after or not remind_version:
        return False
    if remind_version.strip() != str(latest_version).strip():
        return False
    moment = _now(now)
    until = parse_timestamp(remind_after)
    return until is not None and moment < until


def _now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
