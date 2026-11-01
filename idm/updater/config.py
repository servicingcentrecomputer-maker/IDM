"""Update endpoint and trust configuration.

This module combines, in order of precedence:

1. environment variables (managed deployments and tests),
2. values saved in Options → Updates,
3. the baked-in production defaults in the top-level :mod:`config` module.

Trusted download hosts always include the hosts declared in ``config.py`` and
the host that serves the manifest.  Additional CDN hosts can be supplied with
``IDM_UPDATE_TRUSTED_HOSTS``.
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

import config as app_config

from .errors import UpdateConfigurationError

ENV_MANIFEST_URL = "IDM_UPDATE_MANIFEST_URL"
ENV_PUBLISHER = "IDM_UPDATE_PUBLISHER"
ENV_CHANNEL = "IDM_UPDATE_CHANNEL"
ENV_TRUSTED_HOSTS = "IDM_UPDATE_TRUSTED_HOSTS"
ENV_MANIFEST_PUBLIC_KEY = "IDM_UPDATE_MANIFEST_PUBLIC_KEY"

VALID_CHANNELS = frozenset({"stable", "beta"})

GITHUB_MANIFEST_HOSTS = frozenset(app_config.ALLOWED_MANIFEST_HOSTS)
GITHUB_ASSET_HOSTS = tuple(app_config.ALLOWED_DOWNLOAD_HOSTS)

DEFAULT_CONNECT_TIMEOUT = float(app_config.UPDATE_CONNECT_TIMEOUT)
DEFAULT_READ_TIMEOUT = float(app_config.UPDATE_READ_TIMEOUT)
DEFAULT_MAX_MANIFEST_BYTES = int(app_config.UPDATE_MAX_MANIFEST_BYTES)
DEFAULT_MAX_INSTALLER_BYTES = int(app_config.UPDATE_MAX_INSTALLER_BYTES)


@dataclass(frozen=True)
class UpdateConfig:
    manifest_url: str
    expected_publisher: str
    trusted_hosts: tuple[str, ...]
    channel: str = "stable"
    manifest_public_key: str = ""
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    read_timeout: float = DEFAULT_READ_TIMEOUT
    max_manifest_bytes: int = DEFAULT_MAX_MANIFEST_BYTES
    max_installer_bytes: int = DEFAULT_MAX_INSTALLER_BYTES

    @property
    def timeout(self) -> tuple[float, float]:
        return (self.connect_timeout, self.read_timeout)

    @property
    def configured(self) -> bool:
        return bool(self.manifest_url)

    @property
    def installation_supported(self) -> bool:
        """True when an installer can be verified and installed automatically."""
        return bool(
            self.manifest_url
            and (self.expected_publisher or self.manifest_public_key)
        )

    @property
    def signature_required(self) -> bool:
        return bool(self.manifest_public_key)

    def require_endpoint(self) -> None:
        if not self.manifest_url:
            raise UpdateConfigurationError(
                "No update server is configured. Set GITHUB_OWNER in config.py, "
                "or set the manifest URL in Options → Updates, or define the "
                "IDM_UPDATE_MANIFEST_URL environment variable."
            )

    def require_install_trust(self) -> None:
        if self.manifest_url and (self.expected_publisher or self.manifest_public_key):
            return
        raise UpdateConfigurationError(
            "Automatic installation needs a trusted update signature. Configure "
            "a manifest public key or an Authenticode publisher in "
            "Options → Updates."
        )


def build_update_config(
    manifest_url: str = "",
    expected_publisher: str = "",
    channel: str = "",
    manifest_public_key: str = "",
    environ: dict[str, str] | None = None,
) -> UpdateConfig:
    """Combine environment overrides with saved settings and build defaults."""
    environment = os.environ if environ is None else environ

    url = _pick(
        environment.get(ENV_MANIFEST_URL), manifest_url, app_config.UPDATE_MANIFEST_URL
    )
    publisher = _pick(
        environment.get(ENV_PUBLISHER),
        expected_publisher,
        app_config.EXPECTED_PUBLISHER,
    )
    selected_channel = normalize_channel(
        _pick(
            environment.get(ENV_CHANNEL), channel, app_config.UPDATE_CHANNEL
        )
    )
    public_key = _pick(
        environment.get(ENV_MANIFEST_PUBLIC_KEY),
        manifest_public_key,
        app_config.MANIFEST_PUBLIC_KEY,
    )
    extra = _parse_hosts(environment.get(ENV_TRUSTED_HOSTS, ""))

    hosts: list[str] = []
    for entry in (
        *app_config.ALLOWED_DOWNLOAD_HOSTS,
        *app_config.ALLOWED_MANIFEST_HOSTS,
        *extra,
    ):
        _add_host(hosts, entry)
    host = url_host(url)
    if host:
        _add_host(hosts, host)
    if host in GITHUB_MANIFEST_HOSTS:
        for github_host in GITHUB_ASSET_HOSTS:
            _add_host(hosts, github_host)

    return UpdateConfig(
        manifest_url=url,
        expected_publisher=publisher,
        trusted_hosts=tuple(hosts),
        channel=selected_channel,
        manifest_public_key=public_key,
    )


def normalize_channel(value: str) -> str:
    channel = (value or "").strip().lower()
    if channel not in VALID_CHANNELS:
        raise UpdateConfigurationError(
            f"“{value}” is not a supported update channel. Use stable or beta."
        )
    return channel


def url_host(url: str) -> str:
    try:
        parsed = urlsplit(url.strip())
        hostname = parsed.hostname
    except ValueError:
        return ""
    return normalize_host(hostname or "")


def normalize_host(host: str) -> str:
    return host.strip().rstrip(".").casefold()


def host_is_trusted(host: str, trusted_hosts: tuple[str, ...]) -> bool:
    normalized = normalize_host(host)
    return bool(normalized) and normalized in {
        normalize_host(entry) for entry in trusted_hosts
    }


def is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _pick(environment_value: str | None, saved: str, default: str) -> str:
    value = (environment_value or "").strip()
    if value:
        return value
    value = (saved or "").strip()
    if value:
        return value
    return (default or "").strip()


def _add_host(hosts: list[str], value: str) -> None:
    host = normalize_host(value)
    if host and host not in hosts:
        hosts.append(host)


def _parse_hosts(value: str) -> tuple[str, ...]:
    hosts: list[str] = []
    for entry in value.replace(";", ",").split(","):
        host = normalize_host(entry)
        if host and host not in hosts:
            hosts.append(host)
    return tuple(hosts)
