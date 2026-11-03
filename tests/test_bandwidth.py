"""Percentage bandwidth limiting built on a measured link, and the speed graph."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from idm.core.bandwidth import (
    SPEED_LIMIT_FIXED,
    SPEED_LIMIT_PERCENT,
    SPEED_LIMIT_UNLIMITED,
    LinkCapacityMeter,
    normalize_speed_limit_mode,
)
from idm.core.settings import AppSettings
from idm.engine.manager import DownloadManager
from idm.ui.components import SpeedGraph
from idm.ui.dialogs.progress import DownloadProgressDialog
from idm.ui.theme import ThemeManager


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _meter(window: float = 180.0) -> tuple[LinkCapacityMeter, FakeClock]:
    clock = FakeClock()
    return LinkCapacityMeter(window_seconds=window, clock=clock), clock


# ------------------------------------------------------------------ the meter
def test_unthrottled_samples_define_the_link():
    meter, clock = _meter()
    for _ in range(4):
        meter.add_sample(2_000_000.0)
        clock.advance(1.0)

    assert meter.estimate_bytes_per_second == pytest.approx(2_000_000.0, rel=0.05)


def test_a_throttled_transfer_is_scaled_back_up_to_the_real_capacity():
    meter, clock = _meter()
    # 60 % of the link was allowed and the transfer saturated that cap.
    for _ in range(4):
        meter.add_sample(600_000.0, limit_fraction=0.6)
        clock.advance(1.0)

    assert meter.estimate_bytes_per_second == pytest.approx(1_000_000.0, rel=0.05)


def test_one_lucky_burst_cannot_double_the_estimate():
    meter, clock = _meter()
    meter.add_sample(1_000_000.0, limit_fraction=0.1)
    clock.advance(1.0)

    # Inference is capped, so a reading cannot claim ten times what it moved.
    assert meter.estimate_bytes_per_second <= 4_000_000.0


def test_a_stale_peak_stops_holding_the_limit_up():
    meter, clock = _meter(window=30.0)
    for _ in range(3):
        meter.add_sample(3_000_000.0)
        clock.advance(1.0)
    assert meter.estimate_bytes_per_second > 0

    clock.advance(40.0)
    assert meter.estimate_bytes_per_second == 0.0


def test_the_estimate_ignores_the_noise_between_ticks():
    meter, clock = _meter()
    assert meter.add_sample(1_500_000.0) is True
    assert meter.add_sample(9_000_000.0) is False  # inside the sample interval
    clock.advance(0.5)
    assert meter.add_sample(9_000_000.0) is True


def test_seed_gives_a_restart_something_to_limit():
    meter, _clock = _meter()
    meter.seed(1_000)

    assert meter.estimate_kbps == 1_000
    assert meter.limit_for_percent(50) == 512_000  # 500 KB/s


def test_limit_for_percent_needs_a_measurement_and_clamps_input():
    meter, _clock = _meter()
    assert meter.limit_for_percent(50) == 0

    meter.seed(8_000)
    assert meter.limit_for_percent(25) == 2_048_000
    assert meter.limit_for_percent(0) == 0
    assert meter.limit_for_percent(150) == meter.estimate_bytes_per_second


# ------------------------------------------------------------------ stored mode
@pytest.mark.parametrize(
    "stored, kbps, expected",
    [
        (None, 0, SPEED_LIMIT_UNLIMITED),
        (None, 512, SPEED_LIMIT_FIXED),
        ("", 512, SPEED_LIMIT_FIXED),
        ("nonsense", 512, SPEED_LIMIT_FIXED),
        ("unlimited", 512, SPEED_LIMIT_UNLIMITED),
        (SPEED_LIMIT_PERCENT, 0, SPEED_LIMIT_PERCENT),
        (None, "broken", SPEED_LIMIT_UNLIMITED),
    ],
)
def test_older_settings_still_mean_the_same_thing(stored, kbps, expected):
    assert normalize_speed_limit_mode(stored, kbps) == expected


def test_the_new_keys_survive_a_save_cycle(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    settings = AppSettings()
    settings.update(
        {
            "speed_limit_mode": SPEED_LIMIT_PERCENT,
            "speed_limit_percent": 35,
            "measured_capacity_kbps": 9_000,
        }
    )
    settings.save()
    reloaded = AppSettings()
    assert (
        reloaded.speed_limit_mode,
        reloaded.speed_limit_percent,
        reloaded.measured_capacity_kbps,
    ) == (SPEED_LIMIT_PERCENT, 35, 9_000)
    reloaded.update({"speed_limit_percent": 2})  # below the floor
    assert reloaded.speed_limit_percent == 5
    settings.close()
    reloaded.close()


# ------------------------------------------------------------------ the engine
@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    instance = AppSettings()
    instance.download_dir = str(tmp_path / "downloads")
    Path(instance.download_dir).mkdir(parents=True, exist_ok=True)
    instance.start_immediately = False
    yield instance
    instance.close()


def test_fixed_mode_limits_exactly_what_the_user_typed(settings):
    settings.speed_limit_mode = SPEED_LIMIT_FIXED
    settings.speed_limit_kbps = 750
    manager = DownloadManager(settings)
    assert manager.global_limit_bytes == 750 * 1024
    manager.shutdown()


def test_percent_mode_uses_the_measured_link(settings):
    settings.speed_limit_mode = SPEED_LIMIT_PERCENT
    settings.speed_limit_percent = 25
    settings.measured_capacity_kbps = 8_000
    manager = DownloadManager(settings)

    assert manager.capacity_kbps == 8_000
    assert manager.global_limit_bytes == 2_000 * 1024
    manager.shutdown()


def test_percent_mode_without_a_measurement_does_not_invent_one(settings):
    settings.speed_limit_mode = SPEED_LIMIT_PERCENT
    settings.speed_limit_percent = 40
    manager = DownloadManager(settings)

    assert manager.capacity_kbps == 0
    assert manager.global_limit_bytes == 0
    manager.shutdown()


def test_unlimited_mode_ignores_the_legacy_fixed_value(settings):
    settings.speed_limit_mode = SPEED_LIMIT_UNLIMITED
    settings.speed_limit_kbps = 300
    manager = DownloadManager(settings)

    assert manager.global_limit_bytes == 0
    manager.shutdown()


def test_switching_modes_re_applies_the_limit(settings):
    settings.speed_limit_mode = SPEED_LIMIT_UNLIMITED
    manager = DownloadManager(settings)
    assert manager.global_limit_bytes == 0

    settings.speed_limit_mode = SPEED_LIMIT_FIXED
    settings.speed_limit_kbps = 128
    manager.apply_settings()
    assert manager.global_limit_bytes == 128 * 1024

    settings.speed_limit_mode = SPEED_LIMIT_PERCENT
    settings.speed_limit_percent = 50
    settings.measured_capacity_kbps = 4_000
    manager._capacity.seed(4_000)
    manager.apply_settings()
    assert manager.global_limit_bytes == 2_000 * 1024
    manager.shutdown()


def test_a_capped_transfer_does_not_measure_the_link_it_is_held_to(settings):
    settings.speed_limit_mode = SPEED_LIMIT_FIXED
    settings.speed_limit_kbps = 500
    manager = DownloadManager(settings)
    manager._capacity.reset()

    # A transfer pinned at the cap proves nothing about the link, so recording
    # it would let a 500 KB/s limit "measure" a 500 KB/s connection.
    manager._sample_capacity(1, 500 * 1024)
    assert manager.capacity_kbps == 0

    # A transfer running below the cap is limited by the server, so it counts.
    manager._sample_capacity(1, 200 * 1024)
    assert manager.capacity_kbps == pytest.approx(200, rel=0.05)
    manager.shutdown()


def test_measuring_needs_something_actually_downloading(settings):
    manager = DownloadManager(settings)
    assert manager.measure_capacity() is False
    assert manager.global_limit_bytes == 0
    manager.shutdown()


def test_measuring_lifts_the_limit_and_then_restores_it(settings, server, tmp_path):
    settings.speed_limit_mode = SPEED_LIMIT_FIXED
    settings.speed_limit_kbps = 500
    manager = DownloadManager(settings)
    assert manager.global_limit_bytes == 500 * 1024

    item = manager.add_download(
        server.url("/slow/8388608"), "big.bin", str(tmp_path), start_immediately=True
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not item.is_active:
        _pump(manager)
    assert item.is_active

    assert manager.measure_capacity(seconds=1.0) is True
    assert manager.global_limit_bytes == 0, "the cap must come off while measuring"

    deadline = time.monotonic() + 6
    while time.monotonic() < deadline and manager.global_limit_bytes == 0:
        _pump(manager)

    assert manager.global_limit_bytes == 500 * 1024, "the cap comes back afterwards"
    assert manager.capacity_kbps > 0
    manager.shutdown()


def _pump(manager) -> None:
    app = QApplication.instance() or QApplication([])
    manager._emit_stats()
    app.processEvents()
    time.sleep(0.05)


# ------------------------------------------------------------------ the graph
def test_the_graph_keeps_a_window_of_history(qt_app):
    graph = SpeedGraph(ThemeManager(qt_app), max_points=10)
    for value in range(20):
        graph.add_sample(float(value) * 1_000)

    assert graph.sample_count == 10
    assert graph.peak_bytes_per_second == 19_000
    assert graph.average_bytes_per_second == pytest.approx(14_500)
    graph.reset()
    assert graph.sample_count == 0


def _paint(graph: SpeedGraph, size: tuple[int, int] = (320, 120)) -> list[int]:
    """Render the widget offscreen and return a sampled grid of its pixels."""
    width, height = size
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(0)
    graph.render(image, QPoint(0, 0))
    return [
        image.pixelColor(x, y).rgba()
        for x in range(0, width, 2)
        for y in range(0, height, 2)
    ]


def test_the_graph_paints_without_a_single_sample(qt_app):
    graph = SpeedGraph(ThemeManager(qt_app))
    graph.resize(320, 120)

    pixels = _paint(graph)

    assert graph.sample_count == 0
    # No samples means no curve, but the empty surface is still drawn, so the
    # widget cannot render as a transparent hole in the dialog.
    assert sum(1 for pixel in pixels if pixel >> 24) > len(pixels) // 2


def test_a_plotted_curve_changes_what_the_widget_paints(qt_app):
    graph = SpeedGraph(ThemeManager(qt_app))
    graph.resize(320, 120)
    blank = _paint(graph)

    for value in (0, 400_000, 900_000, 600_000, 1_200_000):
        graph.add_sample(float(value))
    assert graph.sample_count == 5

    plotted = _paint(graph)
    changed = sum(1 for a, b in zip(blank, plotted, strict=True) if a != b)
    assert changed > 5, "the curve must actually reach the pixels"


def test_the_limit_line_follows_the_tighter_of_two_caps(qt_app, settings):
    settings.speed_limit_mode = SPEED_LIMIT_FIXED
    settings.speed_limit_kbps = 900
    manager = DownloadManager(settings)
    item = manager.add_download(
        "https://files.example.com/plot.bin",
        "plot.bin",
        settings.download_dir,
        start_immediately=False,
        speed_limit_kbps=300,
    )
    dialog = DownloadProgressDialog(manager, item.id, ThemeManager(qt_app))

    assert dialog._effective_limit(item) == 300 * 1024
    item.speed_limit_kbps = 0
    assert dialog._effective_limit(item) == 900 * 1024
    settings.speed_limit_mode = SPEED_LIMIT_UNLIMITED
    manager.apply_settings()
    assert dialog._effective_limit(item) == 0.0

    dialog.close()
    manager.shutdown()
