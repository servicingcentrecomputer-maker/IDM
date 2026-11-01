"""Startup recovery after an interrupted or failed update.

The application cannot open its own settings before the SQLite database is
readable, so :mod:`main` restores a verified pre-update database copy when the
database is damaged.  Once settings are available this module classifies the
pending update, records the outcome and exposes the rollback plan that matches
the failed attempt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .errors import RollbackError, UpdateStateError
from .rollback import RollbackPlan, read_rollback_plan
from .state import (
    PendingUpdate,
    finalize_pending_update,
    read_pending_update,
)

logger = logging.getLogger(__name__)

_FAILED_STATUSES = {"not-installed", "version-mismatch", "database-error"}


@dataclass(frozen=True)
class StartupReport:
    status: str
    pending: PendingUpdate | None = None
    message: str = ""
    database_restored: bool = False

    @property
    def needs_attention(self) -> bool:
        return self.status in _FAILED_STATUSES

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"


def read_pending_safely() -> PendingUpdate | None:
    try:
        return read_pending_update()
    except UpdateStateError:
        logger.warning("The pending update state could not be read", exc_info=True)
        return None


def finalize_startup(
    settings, current_version: str, *, database_restored: bool = False
) -> StartupReport:
    """Record the outcome of the previous update attempt for this startup."""
    try:
        outcome = finalize_pending_update(settings, current_version)
    except UpdateStateError as exc:
        logger.warning("The pending update state could not be finalised", exc_info=True)
        return StartupReport(
            "state-error",
            None,
            f"The previous update state could not be read: {exc}",
            database_restored,
        )

    if outcome.pending is None:
        return StartupReport("none", None, "", database_restored)

    pending = outcome.pending
    if outcome.status == "succeeded":
        message = (
            f"IDM {pending.target_version} was reinstalled successfully."
            if pending.reinstall
            else f"IDM {pending.target_version} was installed successfully."
        )
        if database_restored:
            message += " The pre-update database backup was restored during startup."
        return StartupReport(
            outcome.status, pending, message, database_restored
        )

    message = outcome.message or (
        f"The reinstall of IDM {pending.target_version} did not finish."
        if pending.reinstall
        else f"The update to IDM {pending.target_version} did not finish."
    )
    if database_restored:
        message += " The pre-update database backup was restored during startup."
    return StartupReport(
        outcome.status, pending, message, database_restored
    )


def matching_rollback_plan(
    pending: PendingUpdate | None, path: Path | None = None
) -> RollbackPlan | None:
    """Return the verified rollback plan for ``pending``, if it is usable."""
    if pending is None or not pending.rollback_available:
        return None
    try:
        plan = read_rollback_plan(path)
    except RollbackError:
        logger.warning("No usable rollback plan is available", exc_info=True)
        return None
    if (
        plan.from_version != pending.from_version
        or plan.target_version != pending.target_version
    ):
        logger.warning(
            "The rollback plan belongs to a different update (%s → %s)",
            plan.from_version,
            plan.target_version,
        )
        return None
    return plan


__all__ = [
    "StartupReport",
    "finalize_startup",
    "matching_rollback_plan",
    "read_pending_safely",
]
