"""About/update panel UI tests (offscreen)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from idm.ui.dialogs.about import AboutDialog
from idm.ui.dialogs.update import UpdatePanel
from idm.ui.theme import ThemeManager
from idm.updater.config import UpdateConfig
from idm.updater.update_checker import UpdateCheckResult
from idm.updater.version_manager import Version
from tests.update_helpers import (
    MANIFEST_URL,
    TRUSTED_HOST,
    installer_bytes,
    make_manifest,
)


@pytest.fixture
def theme(qt_app):
    manager = ThemeManager(qt_app)
    manager.set_mode("classic")
    yield manager
    manager.set_mode("classic")


@pytest.fixture
def panel(qt_app, theme):
    settings = SimpleNamespace(update_manifest_url="", update_publisher="")
    widget = UpdatePanel(settings, theme, lambda _request: None)
    widget.show()
    qt_app.processEvents()
    yield widget
    widget.shutdown()
    widget.hide()
    widget.deleteLater()
    qt_app.processEvents()


def _result(
    *,
    current: str = "1.0.0",
    latest: str = "1.1.0",
    available: bool = True,
    mandatory: bool = False,
    installed_is_newer: bool = False,
) -> UpdateCheckResult:
    manifest = make_manifest(
        installer_bytes(latest), latest_version=latest, mandatory=mandatory
    )
    return UpdateCheckResult(
        manifest=manifest,
        current_version=Version.parse(current),
        latest_version=Version.parse(latest),
        update_available=available,
        mandatory=mandatory,
        below_minimum=False,
        installed_is_newer=installed_is_newer,
    )


def test_unconfigured_updates_explain_how_to_configure(panel):
    assert panel._status.text() == "Not checked yet."
    panel.check_for_updates()
    assert panel._status.text() == "Updates are not configured."
    assert "Options" in panel._detail.text()
    assert panel._detail.text().strip()
    assert panel._latest_value.text() == "—"
    assert panel._update_button.isHidden()


def test_no_update_shows_required_exact_text(panel):
    panel._on_check_succeeded(_result(available=False))
    assert panel._status.text() == "You are using the latest version of IDM."
    assert not panel._notes.isHidden()
    assert "Faster resume" in panel._notes.toPlainText()
    assert panel._update_button.isHidden()
    assert not panel._latest_value._enabled_link


def test_update_available_shows_details_and_button(panel):
    panel._on_check_succeeded(_result())
    assert panel._status.text() == "New version available."
    assert panel._latest_value.text() == "1.1.0"
    assert panel._latest_value._enabled_link
    assert panel._latest_value.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert panel._release_date.text() == "Released 2026-10-31"
    assert not panel._update_button.isHidden()
    assert not panel._notes.isHidden()
    assert not panel._notes_label.isHidden()
    assert "VERSION 1.1.0" in panel._notes_label.text()
    assert panel._mandatory_label.isHidden()


def test_mandatory_update_is_still_consensual(panel):
    panel._on_check_succeeded(_result(mandatory=True))
    assert not panel._mandatory_label.isHidden()
    assert "required" in panel._detail.text()
    assert "consent" in panel._detail.text()


def test_installed_version_newer_than_latest(panel):
    panel._on_check_succeeded(
        _result(current="2.0.0", latest="1.1.0", available=False, installed_is_newer=True)
    )
    assert panel._status.text() == "You are using the latest version of IDM."
    assert "newer" in panel._detail.text()
    assert panel._update_button.isHidden()


def test_check_failure_allows_retry(panel):
    panel._on_check_failed("The update server did not respond in time.")
    assert panel._status.text() == "Update failed."
    assert panel._detail.text() == "The update server did not respond in time."
    assert not panel._retry_button.isHidden()
    assert panel._update_button.isHidden()
    assert panel._latest_value.text() == "—"


def test_preflight_requires_publisher(panel):
    panel._result = _result()
    panel._config = UpdateConfig(
        manifest_url=MANIFEST_URL,
        expected_publisher="",
        trusted_hosts=(TRUSTED_HOST,),
    )
    assert panel._preflight_install() is False
    assert panel._status.text() == "Updates are not configured."
    assert "publisher" in panel._detail.text().lower()


def test_preflight_requires_updater_component(panel, monkeypatch):
    panel._result = _result()
    panel._config = UpdateConfig(
        manifest_url=MANIFEST_URL,
        expected_publisher="IDM",
        trusted_hosts=(TRUSTED_HOST,),
    )
    monkeypatch.setattr("idm.ui.dialogs.update.updater_executable", lambda: None)
    assert panel._preflight_install() is False
    assert panel._status.text() == "The Updater component is missing."
    assert "build_windows.ps1" in panel._detail.text()


def test_preflight_accepts_configured_publisher_and_updater(panel, monkeypatch, tmp_path):
    updater = tmp_path / "IDM_Updater.exe"
    updater.write_bytes(b"binary")
    panel._result = _result()
    panel._config = UpdateConfig(
        manifest_url=MANIFEST_URL,
        expected_publisher="IDM",
        trusted_hosts=(TRUSTED_HOST,),
    )
    monkeypatch.setattr(
        "idm.ui.dialogs.update.updater_executable", lambda: updater
    )
    assert panel._preflight_install() is True


def test_latest_version_link_opens_install_prompt(qt_app, theme, monkeypatch):
    prompts: list[bool] = []
    monkeypatch.setattr(
        UpdatePanel, "_prompt_install", lambda _self: prompts.append(True)
    )
    settings = SimpleNamespace(update_manifest_url="", update_publisher="")
    widget = UpdatePanel(settings, theme, lambda _request: None)
    try:
        widget.show()
        widget._on_check_succeeded(_result())
        QTest.mouseClick(widget._latest_value, Qt.MouseButton.LeftButton)
        qt_app.processEvents()
        assert prompts == [True]
    finally:
        widget.shutdown()
        widget.hide()
        widget.deleteLater()
        qt_app.processEvents()


def test_about_dialog_hosts_the_update_panel(qt_app, theme):
    settings = SimpleNamespace(update_manifest_url="", update_publisher="")
    dialog = AboutDialog(theme, None, settings=settings)
    dialog.show()
    qt_app.processEvents()
    assert "About IDM" in dialog.windowTitle()
    assert dialog.update_panel._status.text() == "Not checked yet."
    dialog.check_now()
    qt_app.processEvents()
    assert dialog.update_panel._status.text() == "Updates are not configured."
    dialog.accept()
    qt_app.processEvents()
    assert not dialog.isVisible()
    dialog.deleteLater()
