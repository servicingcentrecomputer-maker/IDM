"""Proxy, server-authentication and timeout configuration.

The module is Qt-free so the download engine, the UI and the tests all build
the same network profile.  Passwords are read from the Windows Credential
Manager through :mod:`idm.core.credentials`; they are never part of settings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

from .credentials import CredentialError, get_secret, target_name

logger = logging.getLogger(__name__)

PROXY_MODES = ("system", "direct", "manual")
SITE_AUTH_SCHEMES = ("basic", "digest")
DEFAULT_CONNECT_TIMEOUT = 15.0
DEFAULT_READ_TIMEOUT = 30.0
MAX_SITE_AUTH_ENTRIES = 100
MIN_TIMEOUT = 3.0
MAX_CONNECT_TIMEOUT = 120.0
MAX_READ_TIMEOUT = 300.0

_PROXY_SCOPE = "proxy"
_SITE_SCOPE = "site"


@dataclass(frozen=True)
class NetworkProfile:
    """Everything a worker needs to reach one URL."""

    proxies: dict[str, str] | None = None
    trust_env: bool = True
    auth: tuple[str, str, str] | None = None
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    read_timeout: float = DEFAULT_READ_TIMEOUT

    @property
    def timeout(self) -> tuple[float, float]:
        return self.connect_timeout, self.read_timeout


def _coerce_timeout(value, default: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number <= 0:
        return default
    return max(MIN_TIMEOUT, min(number, maximum))


def connect_timeout(settings) -> float:
    return _coerce_timeout(
        getattr(settings, "connect_timeout", DEFAULT_CONNECT_TIMEOUT),
        DEFAULT_CONNECT_TIMEOUT,
        MAX_CONNECT_TIMEOUT,
    )


def read_timeout(settings) -> float:
    return _coerce_timeout(
        getattr(settings, "read_timeout", DEFAULT_READ_TIMEOUT),
        DEFAULT_READ_TIMEOUT,
        MAX_READ_TIMEOUT,
    )


def valid_proxy_host(host: str) -> bool:
    text = str(host or "").strip()
    if not text or any(character.isspace() for character in text):
        return False
    if any(character in text for character in "/@#?"):
        return False
    try:
        parsed = urlsplit(f"//{text}")
        return bool(parsed.hostname)
    except ValueError:
        return False


def normalize_site_auth(value) -> list[dict[str, str]]:
    """Return safe ``host/username/scheme`` entries without any password."""
    if not isinstance(value, list):
        return []
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in value[:MAX_SITE_AUTH_ENTRIES]:
        if not isinstance(raw, dict):
            continue
        host = str(raw.get("host") or "").strip().lower()
        username = str(raw.get("username") or "").strip()
        scheme = str(raw.get("scheme") or "basic").strip().lower()
        if not valid_proxy_host(host) or not username:
            continue
        if any(ord(character) < 32 for character in username):
            continue
        if scheme not in SITE_AUTH_SCHEMES:
            scheme = "basic"
        if host in seen:
            continue
        seen.add(host)
        entries.append(
            {
                "host": host,
                "username": username[:513],
                "scheme": scheme,
            }
        )
    return entries


def normalize_proxy_mode(value) -> str:
    mode = str(value or "system").strip().lower()
    return mode if mode in PROXY_MODES else "system"


def proxy_password(settings) -> str:
    try:
        stored = get_secret(_PROXY_SCOPE, "default")
    except CredentialError:
        logger.warning("Could not read the proxy credential", exc_info=True)
        return ""
    return stored[1] if stored else ""


def set_proxy_password(username: str, password: str) -> None:
    from .credentials import set_secret

    set_secret(_PROXY_SCOPE, "default", username, password)


def clear_proxy_password() -> bool:
    from .credentials import delete_secret

    return delete_secret(_PROXY_SCOPE, "default")


def build_proxy_url(settings) -> str:
    """Return a percent-encoded proxy URL, or an empty string when invalid."""
    host = str(getattr(settings, "proxy_host", "") or "").strip()
    if not valid_proxy_host(host):
        return ""
    try:
        port = int(getattr(settings, "proxy_port", 8080))
    except (TypeError, ValueError):
        return ""
    if not 1 <= port <= 65535:
        return ""
    credentials = ""
    if bool(getattr(settings, "proxy_use_auth", False)):
        username = str(getattr(settings, "proxy_username", "") or "").strip()
        password = proxy_password(settings)
        if username and password:
            credentials = f"{quote(username, safe='')}:{quote(password, safe='')}@"
    return f"http://{credentials}{host}:{port}"


def bypasses_proxy(host: str, bypass: str) -> bool:
    """Match a host against a comma-separated Windows-style bypass list."""
    name = str(host or "").strip().lower().strip(".")
    if not name:
        return False
    for raw in str(bypass or "").replace(";", ",").split(","):
        pattern = raw.strip().lower()
        if not pattern:
            continue
        if pattern == "*":
            return True
        if pattern.startswith("*."):
            pattern = pattern[2:]
        pattern = pattern.split(":", 1)[0].strip(".")
        if not pattern:
            continue
        if name == pattern or name.endswith(f".{pattern}"):
            return True
    return False


def proxy_settings(settings, host: str) -> tuple[dict[str, str] | None, bool]:
    """Return ``(proxies, trust_env)`` for the given destination host."""
    mode = normalize_proxy_mode(getattr(settings, "proxy_mode", "system"))
    if mode == "direct":
        return {}, False
    if mode == "system":
        # requests reads the Windows proxy configuration from the environment
        # (including the registry) when trust_env is enabled.
        return None, True
    if bypasses_proxy(host, str(getattr(settings, "proxy_bypass", "") or "")):
        return {}, False
    proxy = build_proxy_url(settings)
    if not proxy:
        return None, True
    return {"http": proxy, "https": proxy}, False


def site_auth_for(settings, url: str) -> tuple[str, str, str] | None:
    """Return ``(username, password, scheme)`` for a stored site entry."""
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return None
    if not host:
        return None
    entries = normalize_site_auth(getattr(settings, "site_auth", []))
    entry = next((item for item in entries if item["host"] == host), None)
    if entry is None:
        return None
    try:
        stored = get_secret(_SITE_SCOPE, host)
    except CredentialError:
        logger.warning("Could not read the saved authentication for %s", host)
        return None
    if stored is None:
        return None
    username, password = stored
    if not password:
        return None
    return username or entry["username"], password, entry["scheme"]


def set_site_password(host: str, username: str, password: str) -> None:
    from .credentials import set_secret

    set_secret(_SITE_SCOPE, host.strip().lower(), username, password)


def clear_site_password(host: str) -> bool:
    from .credentials import delete_secret

    return delete_secret(_SITE_SCOPE, host.strip().lower())


def has_site_password(host: str) -> bool:
    from .credentials import has_secret

    return has_secret(_SITE_SCOPE, host.strip().lower())


def network_profile(settings, url: str) -> NetworkProfile:
    host = ""
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        host = ""
    proxies, trust_env = proxy_settings(settings, host)
    return NetworkProfile(
        proxies=proxies,
        trust_env=trust_env,
        auth=site_auth_for(settings, url),
        connect_timeout=connect_timeout(settings),
        read_timeout=read_timeout(settings),
    )


def credential_target(scope: str, name: str) -> str:
    """Expose the target name for diagnostics and tests."""
    return target_name(scope, name)


__all__ = [
    "DEFAULT_CONNECT_TIMEOUT",
    "DEFAULT_READ_TIMEOUT",
    "MAX_CONNECT_TIMEOUT",
    "MAX_READ_TIMEOUT",
    "MIN_TIMEOUT",
    "NetworkProfile",
    "PROXY_MODES",
    "SITE_AUTH_SCHEMES",
    "build_proxy_url",
    "bypasses_proxy",
    "clear_proxy_password",
    "clear_site_password",
    "connect_timeout",
    "credential_target",
    "has_site_password",
    "network_profile",
    "normalize_proxy_mode",
    "normalize_site_auth",
    "proxy_password",
    "proxy_settings",
    "read_timeout",
    "set_proxy_password",
    "set_site_password",
    "site_auth_for",
    "valid_proxy_host",
]
