"""HTTPS retrieval and comparison of the release manifest."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import requests

from .config import UpdateConfig, host_is_trusted, is_ip_literal
from .errors import (
    ChannelMismatchError,
    NetworkError,
    UpdateConfigurationError,
)
from .manifest_validator import UpdateManifest
from .version_manager import Version, VersionError, current_version, decide_update

logger = logging.getLogger(__name__)

_READ_CHUNK = 64 * 1024
_REQUEST_HEADERS = {
    "Accept": "application/json",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


@dataclass(frozen=True)
class UpdateCheckResult:
    manifest: UpdateManifest
    current_version: Version
    latest_version: Version
    update_available: bool
    mandatory: bool
    below_minimum: bool
    installed_is_newer: bool


def fetch_manifest(
    config: UpdateConfig, session: requests.Session | None = None
) -> UpdateManifest:
    """Download and validate the manifest from the configured endpoint."""
    config.require_endpoint()
    _validate_endpoint(config.manifest_url, config)

    own_session = session is None
    client = session if session is not None else requests.Session()
    if own_session:
        client.headers.update(_REQUEST_HEADERS)

    try:
        try:
            response = client.get(
                config.manifest_url,
                timeout=config.timeout,
                stream=True,
                allow_redirects=True,
                headers=_REQUEST_HEADERS,
            )
        except requests.Timeout as exc:
            raise NetworkError(
                "The update server did not respond in time. Check your "
                "connection and try again."
            ) from exc
        except requests.exceptions.SSLError as exc:
            raise NetworkError(
                "A secure HTTPS connection to the update server could not be "
                "established."
            ) from exc
        except requests.ConnectionError as exc:
            raise NetworkError(
                "Could not connect to the update server. Check your internet "
                "connection."
            ) from exc
        except requests.RequestException as exc:
            raise NetworkError(
                "The update server request failed before a response arrived."
            ) from exc

        try:
            _validate_response_chain(response, config)
            status = int(getattr(response, "status_code", 0))
            if status != 200:
                raise NetworkError(
                    f"The update server returned HTTP {status} instead of the "
                    "release manifest."
                )

            declared = _content_length(response)
            if declared is not None and declared > config.max_manifest_bytes:
                raise NetworkError("The release manifest is unexpectedly large.")

            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=_READ_CHUNK):
                if not chunk:
                    continue
                total += len(chunk)
                if total > config.max_manifest_bytes:
                    raise NetworkError(
                        "The release manifest is unexpectedly large."
                    )
                chunks.append(chunk)
        finally:
            try:
                response.close()
            except Exception:
                logger.debug("Could not close the manifest response", exc_info=True)
    finally:
        if own_session:
            client.close()

    payload = b"".join(chunks)
    logger.info(
        "Fetched update manifest from %s (%d bytes)",
        _safe_url_for_log(config.manifest_url),
        len(payload),
    )
    return UpdateManifest.from_json(
        payload,
        config.trusted_hosts,
        max_bytes=config.max_manifest_bytes,
        public_key=config.manifest_public_key,
    )


def check_for_updates(
    config: UpdateConfig,
    current: str | Version | None = None,
    session: requests.Session | None = None,
) -> UpdateCheckResult:
    manifest = fetch_manifest(config, session=session)
    _validate_channel(config, manifest)
    current_value = current_version() if current is None else _to_version(current)
    try:
        decision = decide_update(
            current_value,
            manifest.latest,
            manifest.minimum_supported,
            manifest.mandatory,
        )
    except VersionError as exc:
        raise UpdateConfigurationError(str(exc)) from exc

    logger.info(
        "Update check: installed=%s latest=%s available=%s mandatory=%s",
        decision.current,
        decision.latest,
        decision.update_available,
        decision.mandatory,
    )
    return UpdateCheckResult(
        manifest=manifest,
        current_version=decision.current,
        latest_version=decision.latest,
        update_available=decision.update_available,
        mandatory=decision.mandatory,
        below_minimum=decision.below_minimum,
        installed_is_newer=decision.installed_is_newer,
    )


def _to_version(value: str | Version) -> Version:
    return value if isinstance(value, Version) else Version.parse(value)


def _validate_channel(config: UpdateConfig, manifest: UpdateManifest) -> None:
    if config.channel == "stable" and manifest.channel != "stable":
        raise ChannelMismatchError(
            "This installation follows the stable channel, but the update "
            "server is publishing the beta channel. Switch to beta in "
            "Options → Updates to receive it."
        )
    if config.channel not in {"stable", "beta"}:
        raise UpdateConfigurationError(
            f"“{config.channel}” is not a supported update channel."
        )


def _validate_endpoint(url: str, config: UpdateConfig) -> None:
    try:
        parsed = urlsplit(url)
        _ = parsed.port
    except ValueError as exc:
        raise UpdateConfigurationError(
            "The configured update manifest URL is invalid."
        ) from exc
    if parsed.scheme != "https":
        raise UpdateConfigurationError(
            "The update manifest URL must use HTTPS."
        )
    if not parsed.hostname:
        raise UpdateConfigurationError(
            "The update manifest URL does not contain a host name."
        )
    if parsed.username is not None or parsed.password is not None:
        raise UpdateConfigurationError(
            "The update manifest URL must not contain embedded credentials."
        )
    if is_ip_literal(parsed.hostname):
        raise UpdateConfigurationError(
            "The update manifest URL must use a DNS host name, not an IP address."
        )
    if not host_is_trusted(parsed.hostname, config.trusted_hosts):
        raise UpdateConfigurationError(
            "The update manifest host is not trusted by this installation."
        )


def _validate_response_chain(response, config: UpdateConfig) -> None:
    for hop in getattr(response, "history", ()) or ():
        _validate_hop(hop.url, config)
        location = (getattr(hop, "headers", {}) or {}).get("Location")
        if location:
            _validate_hop(urljoin(hop.url, location), config)
    _validate_hop(getattr(response, "url", ""), config)


def _validate_hop(url: str, config: UpdateConfig) -> None:
    if not url:
        raise NetworkError("The update server returned an empty redirect target.")
    try:
        parsed = urlsplit(url)
        _ = parsed.port
    except ValueError as exc:
        raise NetworkError("The update server returned an invalid redirect.") from exc
    if parsed.scheme != "https" or not parsed.hostname:
        raise NetworkError(
            "The update server redirected to an insecure address. HTTPS is "
            "required."
        )
    if parsed.username is not None or parsed.password is not None:
        raise NetworkError(
            "The update server redirected to an address with embedded credentials."
        )
    if not host_is_trusted(parsed.hostname, config.trusted_hosts):
        raise NetworkError(
            "The update server redirected to an untrusted host "
            f"“{parsed.hostname}”."
        )


def _content_length(response) -> int | None:
    value = (getattr(response, "headers", {}) or {}).get("Content-Length")
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _safe_url_for_log(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return "<invalid URL>"
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
