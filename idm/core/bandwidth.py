"""Estimates how much download capacity the current connection really has.

A percentage limit is meaningless without a number to take the percentage of,
and a fixed line speed in a settings file is a guess: Wi-Fi, mobile hotspots
and shared office links all change through the day.  This module derives the
figure from what IDM actually moved, so the limit follows the link.
"""

from __future__ import annotations

import math
import time
from collections import deque

# Only samples inside this window count. A stale peak from this morning should
# not hold the limit up while the link is slower now.
DEFAULT_WINDOW_SECONDS = 180.0

# Samples arrive from the manager's 500 ms stats tick; anything faster is noise.
_MIN_SAMPLE_INTERVAL = 0.4

# A throttled transfer proves the link can carry *at least* what it carried,
# scaled back by the fraction it was limited to. Cap the inference so one
# lucky burst cannot inflate the estimate and then hold the limit high.
_MAX_THROTTLED_INFERENCE = 4.0

# The estimate is a high percentile rather than the maximum: a single huge
# sample from one fast mirror should not define the whole link.
_ESTIMATE_QUANTILE = 0.85

_MAX_SAMPLES = 512

# How the user wants bandwidth constrained.  "percent" is measured against the
# live estimate below instead of a number typed into a settings field.
SPEED_LIMIT_UNLIMITED = "unlimited"
SPEED_LIMIT_FIXED = "fixed"
SPEED_LIMIT_PERCENT = "percent"
SPEED_LIMIT_MODES = (SPEED_LIMIT_UNLIMITED, SPEED_LIMIT_FIXED, SPEED_LIMIT_PERCENT)

# Anything smaller is a stall, not a limit.
MIN_SPEED_LIMIT_PERCENT = 5

# A transfer within this fraction of its cap is being held by the cap, not by
# the link, so the reading says nothing about the real capacity.
LIMIT_BINDING_RATIO = 0.9

# How long the limiter is lifted when the user asks to see the real link. Short
# enough to be a click, long enough to average out one slow chunk.
MEASURE_WINDOW_SECONDS = 5.0


def normalize_speed_limit_mode(value: object, fixed_kbps: object = 0) -> str:
    """Accept a stored mode, falling back to what an older file implied.

    Releases before this one only had ``speed_limit_kbps``, so a non-zero value
    there still has to mean "limit at this rate" after the upgrade.
    """
    mode = str(value or "").strip().lower()
    if mode in SPEED_LIMIT_MODES:
        return mode
    try:
        return SPEED_LIMIT_FIXED if int(fixed_kbps or 0) > 0 else SPEED_LIMIT_UNLIMITED
    except (TypeError, ValueError):
        return SPEED_LIMIT_UNLIMITED


class LinkCapacityMeter:
    """Rolling estimate of the connection's download capacity."""

    def __init__(
        self,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        clock=time.monotonic,
    ) -> None:
        self._window = max(1.0, float(window_seconds))
        self._clock = clock
        self._samples: deque[tuple[float, float]] = deque(maxlen=_MAX_SAMPLES)
        self._estimate = 0.0
        self._last_sample = -math.inf

    # ------------------------------------------------------------------ input
    def add_sample(
        self,
        bytes_per_second: float,
        limit_fraction: float | None = None,
    ) -> bool:
        """Record one throughput observation.

        ``limit_fraction`` is the share of capacity the limiter allowed (0.6 for
        a 60 % limit); ``None`` means the transfer ran unthrottled and the
        reading is the link itself.  Returns True when the estimate moved.
        """
        now = self._clock()
        speed = max(0.0, float(bytes_per_second))
        if speed <= 0 or now - self._last_sample < _MIN_SAMPLE_INTERVAL:
            return False
        self._last_sample = now

        observed = speed
        if limit_fraction is not None and 0 < limit_fraction < 1:
            observed = min(speed / limit_fraction, speed * _MAX_THROTTLED_INFERENCE)

        self._samples.append((now, observed))
        self._trim(now)
        return self._recompute()

    def seed(self, kbps: float) -> None:
        """Start from the last saved estimate so a restart is not amnesia."""
        value = max(0.0, float(kbps)) * 1024.0
        if value <= 0:
            return
        self._estimate = value
        if self._samples:
            return
        now = self._clock()
        self._samples.append((now, value))

    def reset(self) -> None:
        self._samples.clear()
        self._estimate = 0.0
        self._last_sample = -math.inf

    # ------------------------------------------------------------------ output
    @property
    def estimate_bytes_per_second(self) -> float:
        if self._trim(self._clock()):
            self._recompute()
        return self._estimate

    @property
    def estimate_kbps(self) -> int:
        return round(self.estimate_bytes_per_second / 1024.0)

    @property
    def has_estimate(self) -> bool:
        return self.estimate_bytes_per_second > 0

    def limit_for_percent(self, percent: int) -> int:
        """Bytes per second that ``percent`` of the measured link allows."""
        share = max(0, min(100, int(percent))) / 100.0
        capacity = self.estimate_bytes_per_second
        if capacity <= 0 or share <= 0:
            return 0
        return int(capacity * share)

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    # ------------------------------------------------------------------ internals
    def _trim(self, now: float) -> bool:
        """Drop samples that fell out of the window. True if anything went."""
        cutoff = now - self._window
        trimmed = False
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()
            trimmed = True
        return trimmed

    def _recompute(self) -> bool:
        if not self._samples:
            changed = self._estimate != 0.0
            self._estimate = 0.0
            return changed
        values = sorted(value for _, value in self._samples)
        index = min(len(values) - 1, math.ceil(_ESTIMATE_QUANTILE * len(values)) - 1)
        candidate = values[max(0, index)]
        changed = not math.isclose(candidate, self._estimate, rel_tol=0.01)
        self._estimate = candidate
        return changed


__all__ = [
    "LIMIT_BINDING_RATIO",
    "MEASURE_WINDOW_SECONDS",
    "MIN_SPEED_LIMIT_PERCENT",
    "SPEED_LIMIT_FIXED",
    "SPEED_LIMIT_MODES",
    "SPEED_LIMIT_PERCENT",
    "SPEED_LIMIT_UNLIMITED",
    "LinkCapacityMeter",
    "normalize_speed_limit_mode",
]
