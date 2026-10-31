"""Thread-safe global download rate limiter."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class SpeedLimiter:
    """A cooperative leaky-bucket limiter shared by all download workers."""

    def __init__(self, limit_bytes_per_second: int = 0) -> None:
        self._lock = threading.Lock()
        self._limit = 0
        self._next_slot = time.monotonic()
        self.set_limit_bytes(limit_bytes_per_second)

    def set_limit_bytes(self, limit_bytes_per_second: int) -> None:
        with self._lock:
            self._limit = max(0, int(limit_bytes_per_second))
            self._next_slot = time.monotonic()

    def set_limit_kbps(self, kbps: int) -> None:
        self.set_limit_bytes(max(0, int(kbps)) * 1024)

    @property
    def limit_bytes_per_second(self) -> int:
        with self._lock:
            return self._limit

    def throttle(self, byte_count: int, interrupted: Callable[[], bool] | None = None) -> bool:
        """Sleep until ``byte_count`` bytes fit the budget.

        Returns False when ``interrupted`` becomes true while waiting.
        """
        if byte_count <= 0:
            return True
        with self._lock:
            limit = self._limit
            if limit <= 0:
                return True
            now = time.monotonic()
            start = max(self._next_slot, now)
            self._next_slot = start + byte_count / limit
            deadline = self._next_slot

        remaining = deadline - time.monotonic()
        while remaining > 0:
            if interrupted is not None and interrupted():
                return False
            time.sleep(min(0.1, remaining))
            remaining = deadline - time.monotonic()
        return True
