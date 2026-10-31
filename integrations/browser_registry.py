"""Extension allowlisting and native messaging manifest generation.

Chrome and Edge identify an extension by the origin derived from its public
key (or the ID assigned by the store).  Firefox uses the stable Gecko ID from
``browser_specific_settings.gecko.id``.  The build embeds development keys so
an unpacked extension keeps the same ID across reloads; production store IDs
can be supplied with the ``IDM_*_EXTENSION_ID`` environment variables or the
registration script's command line.

The native host repeats this allowlist check after reading a message.  Registry
based registration alone is not treated as sufficient authorisation.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

NATIVE_HOST_NAME = "com.idm.native"

# Development public key.  The private key was discarded: it is only used to
# pin the derived unpacked-extension ID, never to sign extension packages.
CHROME_EXTENSION_KEY = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAxMBWooa8cUWb3Z9DA9OIaxkA"
    "ZipKE0252MaPnEFTCGArf8OISPlhl4hp0+u3MtUM/8qQ6iC/Iz7czGSyqcwuQr+EuDfF"
    "ZVtDtChxAroien9msK4gGs8WnnAhMEKC7UuVVyg9n45EEa2u7gHUsD11iYBFX0veE8J"
    "utak78MAwe/CIhhCWFyQCubIdW7T5e2agZ5ZgXX+pozZ54tmJFGdSt0OrUo/y/K3u1A"
    "fu2nEvW+vtV+SLIRUOxg3gBx0B4tKAbplNaH0lKeNqILs5eo89i7/fD2pj+73o2HrTS"
    "Y1WZT2mpR0EHke+QccQDHcQaqSSKaZMNoqwq2TwiQyAt7PBdwIDAQAB"
)
CHROME_EXTENSION_ID = "ljckgbgnolmopacdgmmgaijleadcmpgn"

EDGE_EXTENSION_KEY = CHROME_EXTENSION_KEY
EDGE_EXTENSION_ID = CHROME_EXTENSION_ID

FIREFOX_EXTENSION_ID = "idm-browser-integration@idm.local"

_ENV_KEYS = {
    "chrome": "IDM_CHROME_EXTENSION_ID",
    "edge": "IDM_EDGE_EXTENSION_ID",
    "firefox": "IDM_FIREFOX_EXTENSION_ID",
}

_BUILTIN_IDS = {
    "chrome": CHROME_EXTENSION_ID,
    "edge": EDGE_EXTENSION_ID,
    "firefox": FIREFOX_EXTENSION_ID,
}


def extension_id_for(browser: str, environ: Mapping[str, str] | None = None) -> str:
    """Return the allowlisted extension ID for a browser."""
    key = _ENV_KEYS.get(browser)
    if key is None:
        raise ValueError(f"Unsupported browser: {browser}")
    environment = os.environ if environ is None else environ
    override = str(environment.get(key, "")).strip()
    return override or _BUILTIN_IDS[browser]


def builtin_extension_id(browser: str) -> str:
    return _BUILTIN_IDS[browser]


def extension_origin(browser: str, environ: Mapping[str, str] | None = None) -> str:
    if browser == "firefox":
        return extension_id_for(browser, environ)
    return f"chrome-extension://{extension_id_for(browser, environ)}/"


def is_allowed_extension(
    browser: str,
    extension_id: str,
    environ: Mapping[str, str] | None = None,
) -> bool:
    if browser not in _BUILTIN_IDS or not extension_id:
        return False
    expected = extension_id_for(browser, environ)
    # Chrome/Edge runtime IDs are case-insensitive in practice, Firefox IDs
    # are not; compare exactly for Firefox and casefolded elsewhere.
    if browser == "firefox":
        return extension_id == expected
    return extension_id.casefold() == expected.casefold()


def native_manifest(
    browser: str,
    host_path: str | Path,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build a browser-specific native messaging host manifest."""
    path = Path(host_path)
    if not path.is_absolute():
        raise ValueError("The native host path must be absolute.")
    manifest: dict[str, Any] = {
        "name": NATIVE_HOST_NAME,
        "description": "IDM Internet Download Manager browser integration",
        "path": str(path),
        "type": "stdio",
    }
    if browser in {"chrome", "edge"}:
        manifest["allowed_origins"] = [extension_origin(browser, environ)]
    elif browser == "firefox":
        manifest["allowed_extensions"] = [extension_id_for(browser, environ)]
    else:
        raise ValueError(f"Unsupported browser: {browser}")
    return manifest


def validate_native_manifest(
    manifest: Any, browser: str, host_path: str | Path | None = None
) -> list[str]:
    """Return a list of problems with a manifest (empty when valid)."""
    problems: list[str] = []
    if not isinstance(manifest, dict):
        return ["The manifest must be a JSON object."]
    if manifest.get("name") != NATIVE_HOST_NAME:
        problems.append(f"name must be {NATIVE_HOST_NAME}.")
    if manifest.get("type") != "stdio":
        problems.append("type must be stdio.")
    path = manifest.get("path")
    if not isinstance(path, str) or not Path(path).is_absolute():
        problems.append("path must be an absolute path.")
    elif host_path is not None and Path(path) != Path(host_path):
        problems.append("path does not match the installed native host.")
    if browser in {"chrome", "edge"}:
        origins = manifest.get("allowed_origins")
        if not isinstance(origins, list) or not origins:
            problems.append("allowed_origins must be a non-empty list.")
        elif any(
            not isinstance(origin, str)
            or not origin.startswith("chrome-extension://")
            or not origin.endswith("/")
            for origin in origins
        ):
            problems.append("allowed_origins contains an invalid origin.")
    elif browser == "firefox":
        allowed = manifest.get("allowed_extensions")
        if not isinstance(allowed, list) or not allowed:
            problems.append("allowed_extensions must be a non-empty list.")
        elif any(not isinstance(item, str) or not item for item in allowed):
            problems.append("allowed_extensions contains an invalid ID.")
    else:
        problems.append(f"Unsupported browser: {browser}")
    return problems


__all__ = [
    "CHROME_EXTENSION_ID",
    "CHROME_EXTENSION_KEY",
    "EDGE_EXTENSION_ID",
    "EDGE_EXTENSION_KEY",
    "FIREFOX_EXTENSION_ID",
    "NATIVE_HOST_NAME",
    "builtin_extension_id",
    "extension_id_for",
    "extension_origin",
    "is_allowed_extension",
    "native_manifest",
    "validate_native_manifest",
]
