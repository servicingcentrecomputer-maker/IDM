"""Page link capture dialog behaviour tests."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from idm.ui.dialogs.page_links import PageLinksDialog
from idm.ui.theme import ThemeManager


def _payload(count: int = 3) -> dict:
    return {
        "page_url": "https://files.example.com/index.html",
        "page_title": "Example files",
        "browser_display": "Chrome",
        "links": [
            {"url": f"https://files.example.com/a{i}.zip", "filename": f"a{i}.zip"}
            for i in range(count)
        ],
    }


@pytest.fixture
def theme(qt_app):
    return ThemeManager(qt_app)


def test_opens_with_every_link_selected(qt_app, theme) -> None:
    dialog = PageLinksDialog(_payload(), theme)
    qt_app.processEvents()

    assert dialog.list.count() == 3
    assert dialog.count_label.text() == "3 of 3 links selected"
    assert dialog.download_button.isEnabled()
    assert [entry["url"] for entry in dialog.selected()] == [
        f"https://files.example.com/a{i}.zip" for i in range(3)
    ]
    dialog.deleteLater()


def test_unchecking_a_link_removes_it_from_the_result(qt_app, theme) -> None:
    dialog = PageLinksDialog(_payload(), theme)
    qt_app.processEvents()

    dialog.list.item(1).setCheckState(Qt.CheckState.Unchecked)
    qt_app.processEvents()

    assert dialog.count_label.text() == "2 of 3 links selected"
    assert [entry["filename"] for entry in dialog.selected()] == ["a0.zip", "a2.zip"]
    dialog.deleteLater()


def test_select_none_disables_the_download_button(qt_app, theme) -> None:
    dialog = PageLinksDialog(_payload(), theme)
    qt_app.processEvents()

    buttons = [
        button
        for button in dialog.findChildren(type(dialog.cancel_button))
        if button.text() == "Select none"
    ]
    buttons[0].click()
    qt_app.processEvents()

    assert dialog.count_label.text() == "0 of 3 links selected"
    assert not dialog.download_button.isEnabled()
    assert dialog.selected() == []
    dialog.deleteLater()


def test_select_all_restores_every_link(qt_app, theme) -> None:
    dialog = PageLinksDialog(_payload(12), theme)
    qt_app.processEvents()

    select_all = next(
        button
        for button in dialog.findChildren(type(dialog.cancel_button))
        if button.text() == "Select all"
    )
    select_all.click()
    qt_app.processEvents()
    assert dialog.count_label.text() == "12 of 12 links selected"

    dialog.list.item(0).setCheckState(Qt.CheckState.Unchecked)
    qt_app.processEvents()
    select_all.click()
    qt_app.processEvents()

    assert dialog.count_label.text() == "12 of 12 links selected"
    assert len(dialog.selected()) == 12
    dialog.deleteLater()


def test_show_page_title_and_tooltip(qt_app, theme) -> None:
    dialog = PageLinksDialog(_payload(1), theme)
    qt_app.processEvents()

    assert dialog.windowTitle() == "Links found on this page"
    assert dialog.list.item(0).toolTip() == "https://files.example.com/a0.zip"
    dialog.deleteLater()


def test_links_without_a_filename_are_still_listed(qt_app, theme) -> None:
    payload = {
        "page_url": "https://files.example.com/index.html",
        "links": [{"url": "https://files.example.com/plain.zip"}],
    }
    dialog = PageLinksDialog(payload, theme)
    qt_app.processEvents()

    assert dialog.list.item(0).text() == "https://files.example.com/plain.zip"
    assert dialog.selected() == [{"url": "https://files.example.com/plain.zip"}]
    dialog.deleteLater()


def test_entries_without_a_url_are_ignored(qt_app, theme) -> None:
    payload = {
        "page_title": "Mixed",
        "links": [
            {"url": "", "filename": "nope.zip"},
            {"url": "https://files.example.com/ok.zip", "filename": "ok.zip"},
            "not-a-dict",
        ],
    }
    dialog = PageLinksDialog(payload, theme)
    qt_app.processEvents()

    assert dialog.list.count() == 1
    assert dialog.count_label.text() == "1 of 1 links selected"
    dialog.deleteLater()
