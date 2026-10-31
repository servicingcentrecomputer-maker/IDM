"""Progress, speed and ETA calculation for update downloads."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TransferMetrics:
    percent: int
    speed_bps: float
    eta_seconds: int | None


def compute_metrics(
    done: int, total: int | None, elapsed_seconds: float
) -> TransferMetrics:
    done = max(0, int(done))
    elapsed = max(0.0, float(elapsed_seconds))
    speed = done / elapsed if elapsed > 0.05 else 0.0

    if total is None or total <= 0:
        return TransferMetrics(percent=0, speed_bps=speed, eta_seconds=None)

    total = int(total)
    percent = max(0, min(100, int(done * 100 / total)))
    remaining = max(0, total - done)
    eta = int(round(remaining / speed)) if speed > 0 and remaining else 0
    return TransferMetrics(percent=percent, speed_bps=speed, eta_seconds=eta)


def describe_metrics(
    done: int,
    total: int | None,
    elapsed_seconds: float,
    format_size,
    format_speed,
) -> str:
    """Build the compact “42% · 3.1 MB of 7.4 MB · 1.2 MB/s · 00:08 left” text."""
    metrics = compute_metrics(done, total, elapsed_seconds)
    if total is None or total <= 0:
        parts = [format_size(done)]
    else:
        parts = [
            f"{metrics.percent}%",
            f"{format_size(done)} of {format_size(total)}",
        ]
    if metrics.speed_bps > 0:
        parts.append(format_speed(metrics.speed_bps))
    if metrics.eta_seconds is not None and metrics.eta_seconds > 0:
        parts.append(f"{format_eta(metrics.eta_seconds)} left")
    return "  ·  ".join(parts)


def format_eta(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
