"""Semantic version parsing, comparison and update decisions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import total_ordering

from ..version import CURRENT_VERSION

_VERSION_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?"
    r"(?:\+(?P<build>[0-9A-Za-z.-]+))?$"
)
_PRERELEASE_RE = re.compile(r"^[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*$")
_BUILD_RE = _PRERELEASE_RE


class VersionError(ValueError):
    """The text is not a valid semantic version."""


@total_ordering
@dataclass(frozen=True, eq=False)
class Version:
    major: int
    minor: int
    patch: int
    prerelease: tuple[int | str, ...] = ()
    build: str = ""

    @classmethod
    def parse(cls, text: str) -> Version:
        if not isinstance(text, str):
            raise VersionError("A version must be a string.")
        value = text.strip()
        match = _VERSION_RE.fullmatch(value)
        if match is None:
            raise VersionError(
                f"“{text}” is not a semantic version (expected MAJOR.MINOR.PATCH)."
            )

        prerelease: tuple[int | str, ...] = ()
        raw_prerelease = match.group("prerelease")
        if raw_prerelease:
            if not _PRERELEASE_RE.fullmatch(raw_prerelease):
                raise VersionError(f"“{text}” has an invalid pre-release suffix.")
            identifiers: list[int | str] = []
            for identifier in raw_prerelease.split("."):
                if identifier.isdigit():
                    if len(identifier) > 1 and identifier.startswith("0"):
                        raise VersionError(
                            f"“{text}” has a numeric pre-release identifier "
                            "with a leading zero."
                        )
                    identifiers.append(int(identifier))
                else:
                    identifiers.append(identifier)
            prerelease = tuple(identifiers)

        build = match.group("build") or ""
        if build and not _BUILD_RE.fullmatch(build):
            raise VersionError(f"“{text}” has invalid build metadata.")

        return cls(
            major=int(match.group("major")),
            minor=int(match.group("minor")),
            patch=int(match.group("patch")),
            prerelease=prerelease,
            build=build,
        )

    def __str__(self) -> str:
        value = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            value += "-" + ".".join(str(part) for part in self.prerelease)
        if self.build:
            value += "+" + self.build
        return value

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._compare_key() == other._compare_key()

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._compare_key() < other._compare_key()

    def __hash__(self) -> int:
        return hash(self._compare_key())

    def _compare_key(self) -> tuple:
        # Build metadata is ignored, as required by Semantic Versioning 2.0.0.
        # A release sorts after all of its pre-releases.
        if not self.prerelease:
            prerelease_key = (1,)
        else:
            parts: list[tuple[int, int | str]] = [(0, "")]
            for identifier in self.prerelease:
                if isinstance(identifier, int):
                    parts.append((0, identifier))
                else:
                    parts.append((1, identifier))
            prerelease_key = (0, tuple(parts))
        return (self.major, self.minor, self.patch, prerelease_key)


def current_version() -> Version:
    return Version.parse(CURRENT_VERSION)


def is_newer(candidate: str | Version, current: str | Version | None = None) -> bool:
    candidate_version = _coerce(candidate)
    current_value = current_version() if current is None else _coerce(current)
    return candidate_version > current_value


def _coerce(value: str | Version) -> Version:
    return value if isinstance(value, Version) else Version.parse(value)


@dataclass(frozen=True)
class UpdateDecision:
    current: Version
    latest: Version
    update_available: bool
    mandatory: bool
    below_minimum: bool
    installed_is_newer: bool


def decide_update(
    current: str | Version,
    latest: str | Version,
    minimum_supported: str | Version,
    mandatory: bool,
) -> UpdateDecision:
    """Decide whether ``latest`` should be offered.

    Downgrades are never offered.  Versions below ``minimum_supported`` force
    the update to be treated as mandatory.
    """
    current_version_value = _coerce(current)
    latest_version = _coerce(latest)
    minimum = _coerce(minimum_supported)

    if latest_version < minimum:
        raise VersionError(
            "The manifest's latest version is older than its minimum supported "
            "version."
        )

    installed_is_newer = current_version_value > latest_version
    update_available = latest_version > current_version_value
    below_minimum = current_version_value < minimum
    return UpdateDecision(
        current=current_version_value,
        latest=latest_version,
        update_available=update_available,
        mandatory=bool(update_available and (mandatory or below_minimum)),
        below_minimum=below_minimum,
        installed_is_newer=installed_is_newer,
    )
