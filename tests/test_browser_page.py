"""Browser Assistant page: registration rows and live bridge reporting."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, Signal

from idm.core.settings import AppSettings
from idm.ui.pages.browser import BrowserIntegrationPage
from idm.ui.theme import ThemeManager


class FakeBridge(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.port = 49152
        self.connection_count = 0


class FakeService(QObject):
    bridge_activity = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.bridge = FakeBridge()

    @property
    def is_listening(self) -> bool:
        return True


@pytest.fixture
def page(qt_app, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    settings = AppSettings()
    service = FakeService()
    theme = ThemeManager(qt_app)
    instance = BrowserIntegrationPage(theme, settings, service)
    instance.resize(1100, 700)
    yield instance
    settings.close()


def test_every_supported_browser_has_a_row(page):
    assert set(page._rows) == {"chrome", "edge", "firefox", "brave", "opera"}
    assert page._rows["firefox"].status.text() == "Not checked"


def test_bridge_activity_is_reported_without_pressing_refresh(qt_app, page):
    page._refresh_bridge_status()
    assert "no browser connected yet" in page._bridge_status.text()

    page._service.bridge.connection_count = 1
    page._last_activity = ""
    page._on_bridge_activity("status_request")
    qt_app.processEvents()

    text = page._bridge_status.text()
    assert "127.0.0.1:49152" in text
    assert "1 browser connection active" in text
    assert "last request: status request" in text


def test_status_timer_only_runs_while_the_page_is_shown(page):
    assert page._status_timer.interval() == 4000

    page.show()
    assert page._status_timer.isActive()
    page.hide()
    assert not page._status_timer.isActive()
