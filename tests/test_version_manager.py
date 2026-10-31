"""Semantic version and update decision tests."""

from __future__ import annotations

import pytest

from idm.version import CURRENT_VERSION
from idm.updater.version_manager import (
    Version,
    VersionError,
    current_version,
    decide_update,
    is_newer,
)


def test_current_version_matches_the_release_source():
    assert str(current_version()) == CURRENT_VERSION
    assert current_version() == Version.parse(CURRENT_VERSION)


@pytest.mark.parametrize(
    "text",
    ["1.0.0", "0.0.0", "10.20.30", "1.0.0-alpha", "1.0.0-alpha.1", "1.0.0+build.5"],
)
def test_parse_accepts_semantic_versions(text):
    assert str(Version.parse(text)) == text


@pytest.mark.parametrize(
    "text",
    ["", "1", "1.0", "v1.0.0", "01.0.0", "1.00.0", "1.0.00", "1.0.0-01", "1.0.0-"],
)
def test_parse_rejects_invalid_versions(text):
    with pytest.raises(VersionError):
        Version.parse(text)


def test_release_is_newer_than_its_pre_releases():
    assert Version.parse("1.0.0") > Version.parse("1.0.0-rc.1")
    assert Version.parse("1.0.0-rc.2") > Version.parse("1.0.0-rc.1")
    assert Version.parse("1.0.0-beta") > Version.parse("1.0.0-alpha")
    assert Version.parse("1.0.0-alpha.10") > Version.parse("1.0.0-alpha.2")


def test_build_metadata_does_not_affect_ordering():
    assert Version.parse("1.0.0+one") == Version.parse("1.0.0+two")
    assert hash(Version.parse("1.0.0+one")) == hash(Version.parse("1.0.0+two"))


def test_is_newer():
    assert is_newer("1.1.0", "1.0.0")
    assert not is_newer("1.0.0", "1.0.0")
    assert not is_newer("0.9.0", "1.0.0")
    assert is_newer("2.0.0", "1.99.99")
    assert is_newer("1.1.0") == (Version.parse("1.1.0") > current_version())


def test_decide_update_no_update():
    decision = decide_update("1.0.0", "1.0.0", "1.0.0", False)
    assert not decision.update_available
    assert not decision.mandatory
    assert not decision.below_minimum
    assert not decision.installed_is_newer


def test_decide_update_available():
    decision = decide_update("1.0.0", "1.1.0", "1.0.0", False)
    assert decision.update_available
    assert not decision.mandatory
    assert not decision.below_minimum


def test_decide_update_mandatory_flag():
    decision = decide_update("1.0.0", "1.1.0", "1.0.0", True)
    assert decision.update_available
    assert decision.mandatory


def test_decide_update_below_minimum_forces_mandatory():
    decision = decide_update("1.0.0", "2.0.0", "1.5.0", False)
    assert decision.update_available
    assert decision.below_minimum
    assert decision.mandatory


def test_decide_update_never_downgrades():
    decision = decide_update("2.0.0", "1.9.0", "1.0.0", True)
    assert not decision.update_available
    assert not decision.mandatory
    assert decision.installed_is_newer


def test_decide_update_rejects_latest_older_than_minimum():
    with pytest.raises(VersionError):
        decide_update("1.0.0", "1.0.0", "1.1.0", False)
