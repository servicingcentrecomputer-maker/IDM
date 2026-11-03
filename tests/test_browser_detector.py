"""Browser detection: calling-process attribution and installed-browser probing."""

from __future__ import annotations

import pytest

from integrations import browser_detector, registration

# pid -> (parent pid, executable name) as the Toolhelp snapshot reports it.
# PID 1 is always IDM_NativeHost.exe, because that is the process asking.
_CHAINS = {
    "chrome": {1: (2, "IDM_NativeHost.exe"), 2: (3, "chrome.exe"), 3: (0, "explorer.exe")},
    "edge": {1: (2, "IDM_NativeHost.exe"), 2: (3, "msedge.exe"), 3: (0, "explorer.exe")},
    "firefox": {1: (2, "IDM_NativeHost.exe"), 2: (3, "Firefox.exe"), 3: (0, "explorer.exe")},
    "brave": {1: (2, "IDM_NativeHost.exe"), 2: (3, "brave.exe"), 3: (0, "explorer.exe")},
    "opera": {1: (2, "IDM_NativeHost.exe"), 2: (3, "opera.exe"), 3: (0, "explorer.exe")},
}


@pytest.mark.parametrize("browser", registration.SUPPORTED_BROWSERS)
def test_calling_browser_is_recognised_for_every_supported_browser(browser) -> None:
    """The native host must attribute a download to the browser that asked."""
    assert browser_detector._browser_from_chain(1, _CHAINS[browser]) == browser


def test_opera_launcher_is_attributed_to_opera() -> None:
    """Opera starts the browser through a launcher that stays in the chain."""
    table = {
        1: (2, "IDM_NativeHost.exe"),
        2: (3, "opera_launcher.exe"),
        3: (0, "explorer.exe"),
    }
    assert browser_detector._browser_from_chain(1, table) == "opera"


def test_an_unknown_chain_returns_empty_instead_of_guessing() -> None:
    table = {1: (2, "notepad.exe"), 2: (3, "explorer.exe")}
    assert browser_detector._browser_from_chain(1, table) == ""


def test_a_cyclic_process_table_does_not_hang() -> None:
    table = {1: (2, "a.exe"), 2: (1, "b.exe")}
    assert browser_detector._browser_from_chain(1, table) == ""


def test_a_missing_parent_stops_the_walk() -> None:
    table = {1: (99, "child.exe")}
    assert browser_detector._browser_from_chain(1, table) == ""


def test_display_names_exist_for_every_supported_browser() -> None:
    for browser in registration.SUPPORTED_BROWSERS:
        name = browser_detector.browser_display_name(browser)
        assert name and name != browser
    assert browser_detector.browser_display_name("") == "Unknown"


def test_process_names_and_registry_roots_cover_the_same_browsers() -> None:
    """A browser with a registry root but no process name is never attributed."""
    assert set(browser_detector._PROCESS_NAMES.values()) == set(
        registration.SUPPORTED_BROWSERS
    )
