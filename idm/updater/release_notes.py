"""Turn flat release-note text into the sections shown by the update dialog."""

from __future__ import annotations

SECTION_NEW = "New features"
SECTION_PERFORMANCE = "Performance"
SECTION_SECURITY = "Security"
SECTION_FIXES = "Bug fixes"
SECTION_GENERAL = "Changes"

_PREFIXES = {
    "new": SECTION_NEW,
    "feature": SECTION_NEW,
    "features": SECTION_NEW,
    "improvement": SECTION_PERFORMANCE,
    "improvements": SECTION_PERFORMANCE,
    "performance": SECTION_PERFORMANCE,
    "security": SECTION_SECURITY,
    "fix": SECTION_FIXES,
    "fixes": SECTION_FIXES,
    "bug fix": SECTION_FIXES,
    "bug fixes": SECTION_FIXES,
}

_ORDER = (
    SECTION_NEW,
    SECTION_PERFORMANCE,
    SECTION_SECURITY,
    SECTION_FIXES,
    SECTION_GENERAL,
)


def categorize_notes(text: str) -> list[tuple[str, list[str]]]:
    """Group lines such as ``Performance: faster resume`` into sections.

    Lines without a recognised prefix are kept in the general section, so
    older manifests that use plain bullets still render correctly.
    """
    groups: dict[str, list[str]] = {}
    for raw in str(text or "").splitlines():
        line = raw.strip().lstrip("-*•").strip()
        if not line:
            continue
        section, entry = _split_prefixed(line)
        groups.setdefault(section, []).append(entry)
    return [(name, groups[name]) for name in _ORDER if groups.get(name)]


def notes_plain_text(text: str) -> str:
    return "\n".join(
        line.strip()
        for line in str(text or "").splitlines()
        if line.strip()
    )


def _split_prefixed(line: str) -> tuple[str, str]:
    if ":" in line:
        prefix, rest = line.split(":", 1)
        section = _PREFIXES.get(prefix.strip().casefold())
        if section and rest.strip():
            return section, rest.strip()
    return SECTION_GENERAL, line
