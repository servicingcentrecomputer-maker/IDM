"""Progress/speed/ETA formatting for update downloads."""

from __future__ import annotations

from idm.core.url_utils import format_size, format_speed
from idm.updater.download_metrics import (
    compute_metrics,
    describe_metrics,
    format_eta,
)


def test_compute_metrics_percent_speed_and_eta():
    metrics = compute_metrics(5 * 1024 * 1024, 10 * 1024 * 1024, 10.0)
    assert metrics.percent == 50
    assert metrics.speed_bps == 512 * 1024
    assert metrics.eta_seconds == 10


def test_unknown_total_reports_speed_without_percent():
    metrics = compute_metrics(1024, None, 1.0)
    assert metrics.percent == 0
    assert metrics.eta_seconds is None
    assert metrics.speed_bps == 1024


def test_zero_elapsed_does_not_divide_by_zero():
    metrics = compute_metrics(1024, 2048, 0.0)
    assert metrics.speed_bps == 0
    assert metrics.eta_seconds == 0


def test_describe_metrics_with_total():
    text = describe_metrics(
        5 * 1024 * 1024, 10 * 1024 * 1024, 10.0, format_size, format_speed
    )
    assert text.startswith("50%")
    assert " of " in text
    assert "left" in text


def test_describe_metrics_without_total():
    text = describe_metrics(4096, None, 1.0, format_size, format_speed)
    assert "%" not in text
    assert text


def test_format_eta():
    assert format_eta(8) == "00:08"
    assert format_eta(65) == "01:05"
    assert format_eta(3661) == "1:01:01"
    assert format_eta(-5) == "00:00"
