"""Release note categorisation for the notification window."""

from __future__ import annotations

from idm.updater.release_notes import (
    SECTION_FIXES,
    SECTION_GENERAL,
    SECTION_NEW,
    SECTION_PERFORMANCE,
    SECTION_SECURITY,
    categorize_notes,
    notes_plain_text,
)


def test_categorize_notes_groups_prefixed_lines_in_display_order():
    sections = categorize_notes(
        "Security: verified signatures\n"
        "Performance: faster resume\n"
        "- New: signed manifests\n"
        "Fix: queue ordering\n"
        "Plain change"
    )
    names = [name for name, _entries in sections]
    assert names == [
        SECTION_NEW,
        SECTION_PERFORMANCE,
        SECTION_SECURITY,
        SECTION_FIXES,
        SECTION_GENERAL,
    ]
    mapping = dict(sections)
    assert mapping[SECTION_NEW] == ["signed manifests"]
    assert mapping[SECTION_GENERAL] == ["Plain change"]


def test_categorize_notes_keeps_unknown_prefixes_general():
    sections = categorize_notes("Nonsense: value\nAnother line")
    assert sections == [(SECTION_GENERAL, ["Nonsense: value", "Another line"])]


def test_categorize_notes_handles_empty_text():
    assert categorize_notes("") == []
    assert categorize_notes(None) == []


def test_notes_plain_text_strips_blank_lines():
    assert notes_plain_text(" a \n\n  b  \n") == "a\nb"
