"""Validation of the release manifest served by the update server.

The manifest is the root of trust for an update.  Every field is validated,
unknown fields are rejected, the channel must match the installation, and an
optional Ed25519 signature can authenticate the whole document with a public
key embedded in the application.

Signed payload: canonical JSON of every field except ``manifest_signature``:
``json.dumps(data_without_signature, sort_keys=True, separators=(",", ":"),
ensure_ascii=False)`` encoded as UTF-8.  ``scripts/sign_manifest.py`` produces
exactly this representation.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urlsplit

from ..version import APP_NAME
from .config import (
    DEFAULT_MAX_MANIFEST_BYTES,
    host_is_trusted,
    is_ip_literal,
    url_host,
)
from .errors import ManifestError
from .version_manager import Version, VersionError

logger = logging.getLogger(__name__)

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_MAX_RELEASE_NOTES = 20_000
_MAX_URL_LENGTH = 2048
_MAX_SIGNATURE_LENGTH = 4096
_MAX_PACKAGE_SIZE = 8 * 1024 * 1024 * 1024

MANIFEST_FIELDS = frozenset(
    {
        "app_name",
        "channel",
        "latest_version",
        "minimum_supported_version",
        "release_date",
        "release_notes",
        "download_url",
        "sha256",
        "package_size",
        "mandatory",
        "manifest_signature",
    }
)


@dataclass(frozen=True)
class UpdateManifest:
    app_name: str
    channel: str
    latest_version: str
    minimum_supported_version: str
    release_date: str
    release_notes: str
    download_url: str
    sha256: str
    package_size: int | None = None
    mandatory: bool = False
    manifest_signature: str = ""

    @property
    def latest(self) -> Version:
        return Version.parse(self.latest_version)

    @property
    def minimum_supported(self) -> Version:
        return Version.parse(self.minimum_supported_version)

    def to_dict(self) -> dict:
        data = {
            "app_name": self.app_name,
            "channel": self.channel,
            "latest_version": self.latest_version,
            "minimum_supported_version": self.minimum_supported_version,
            "release_date": self.release_date,
            "release_notes": self.release_notes,
            "download_url": self.download_url,
            "sha256": self.sha256,
            "mandatory": self.mandatory,
            "manifest_signature": self.manifest_signature,
        }
        if self.package_size is not None:
            data["package_size"] = self.package_size
        return data

    @classmethod
    def from_json(
        cls,
        text: str | bytes,
        trusted_hosts: tuple[str, ...],
        max_bytes: int = DEFAULT_MAX_MANIFEST_BYTES,
        public_key: str = "",
    ) -> UpdateManifest:
        if isinstance(text, bytes):
            if len(text) > max_bytes:
                raise ManifestError("The update manifest is too large.")
            try:
                text = text.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise ManifestError(
                    "The update manifest is not valid UTF-8 text."
                ) from exc
        else:
            text = text.removeprefix("\ufeff")
            if len(text.encode("utf-8")) > max_bytes:
                raise ManifestError("The update manifest is too large.")

        try:
            data = json.loads(
                text,
                object_pairs_hook=_strict_object,
                parse_constant=_reject_constant,
            )
        except ManifestError:
            raise
        except json.JSONDecodeError as exc:
            raise ManifestError(
                f"The update manifest is not valid JSON: {exc.msg}."
            ) from exc
        return cls.from_dict(data, trusted_hosts, public_key=public_key)

    @classmethod
    def from_dict(
        cls,
        data: object,
        trusted_hosts: tuple[str, ...],
        public_key: str = "",
    ) -> UpdateManifest:
        if not isinstance(data, dict):
            raise ManifestError("The update manifest must be a JSON object.")

        unknown = set(data) - MANIFEST_FIELDS
        if unknown:
            names = ", ".join(sorted(str(name) for name in unknown))
            raise ManifestError(
                f"The update manifest contains unsupported field(s): {names}."
            )

        signature = _require_signature_field(data)
        verify_manifest_signature(data, signature, public_key)

        app_name = _require_text(data, "app_name")
        if app_name != APP_NAME:
            raise ManifestError(
                f"This update is for “{app_name}”, not {APP_NAME}."
            )

        channel = _read_channel(_require_text(data, "channel"))

        latest_text = _require_text(data, "latest_version")
        minimum_text = _require_text(data, "minimum_supported_version")
        try:
            latest = Version.parse(latest_text)
            minimum = Version.parse(minimum_text)
        except VersionError as exc:
            raise ManifestError(str(exc)) from exc
        if minimum > latest:
            raise ManifestError(
                "minimum_supported_version cannot be newer than latest_version."
            )

        release_date = _normalize_release_date(_require_text(data, "release_date"))
        release_notes = _normalize_notes(data.get("release_notes"))

        download_url = _validate_download_url(
            _require_text(data, "download_url"), trusted_hosts
        )

        sha_text = _require_text(data, "sha256").strip().lower()
        if not _SHA256_RE.fullmatch(sha_text):
            raise ManifestError(
                "sha256 must be exactly 64 hexadecimal characters."
            )

        package_size = _read_package_size(data.get("package_size"))

        mandatory = data.get("mandatory")
        if not isinstance(mandatory, bool):
            raise ManifestError("mandatory must be true or false.")

        return cls(
            app_name=app_name,
            channel=channel,
            latest_version=str(latest),
            minimum_supported_version=str(minimum),
            release_date=release_date,
            release_notes=release_notes,
            download_url=download_url,
            sha256=sha_text,
            package_size=package_size,
            mandatory=mandatory,
            manifest_signature=signature,
        )


def canonical_manifest_bytes(data: dict) -> bytes:
    """Return the exact bytes covered by ``manifest_signature``."""
    payload = {
        key: value for key, value in data.items() if key != "manifest_signature"
    }
    text = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return text.encode("utf-8")


def _strict_object(pairs: list[tuple[str, object]]) -> dict:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError(
                f"The update manifest contains the duplicate field “{key}”."
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ManifestError(
        f"The update manifest contains the unsupported JSON constant {value}."
    )


def _require_signature_field(data: dict) -> str:
    if "manifest_signature" not in data:
        raise ManifestError(
            "“manifest_signature” is required. Use an empty string for an "
            "unsigned manifest."
        )
    value = data.get("manifest_signature")
    if not isinstance(value, str):
        raise ManifestError("manifest_signature must be a base64 string.")
    signature = value.strip()
    if len(signature) > _MAX_SIGNATURE_LENGTH:
        raise ManifestError("manifest_signature is too long.")
    return signature


def verify_manifest_signature(
    data: dict, signature: str, public_key: str
) -> None:
    """Verify a manifest signature when a public key is configured.

    An empty ``public_key`` disables verification; a non-empty signature is
    then accepted but reported as unverified.  When a key is configured, an
    empty or invalid signature is a hard failure.
    """
    key_text = (public_key or "").strip()
    if not key_text:
        if signature:
            logger.warning(
                "The manifest is signed but no manifest public key is "
                "configured; the signature was not verified."
            )
        return
    if not signature:
        raise ManifestError(
            "The update manifest is unsigned, but this build requires a signed "
            "manifest."
        )

    key_bytes = _decode_base64(key_text, "MANIFEST_PUBLIC_KEY")
    if len(key_bytes) != 32:
        raise ManifestError(
            "MANIFEST_PUBLIC_KEY must decode to exactly 32 Ed25519 public key "
            "bytes."
        )
    signature_bytes = _decode_base64(signature, "manifest_signature")

    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
    except ImportError as exc:
        raise ManifestError(
            "Signed manifests are required, but the cryptography package is "
            "not available in this installation."
        ) from exc

    try:
        verifier = Ed25519PublicKey.from_public_bytes(key_bytes)
        verifier.verify(signature_bytes, canonical_manifest_bytes(data))
    except InvalidSignature as exc:
        raise ManifestError(
            "The update manifest signature is invalid. The manifest was "
            "modified or signed with a different key."
        ) from exc
    except (ValueError, TypeError) as exc:
        raise ManifestError(
            "The update manifest signature could not be verified."
        ) from exc


def _decode_base64(value: str, field: str) -> bytes:
    compact = "".join(value.split())
    try:
        return base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ManifestError(f"{field} is not valid base64 text.") from exc


def _read_channel(value: str) -> str:
    if value not in {"stable", "beta"}:
        raise ManifestError("channel must be either “stable” or “beta”.")
    return value


def _require_text(data: dict, key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"“{key}” is required and must be a non-empty string.")
    return value.strip()


def _read_package_size(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestError("package_size must be a whole number of bytes.")
    if value <= 0 or value > _MAX_PACKAGE_SIZE:
        raise ManifestError("package_size is outside the supported range.")
    return int(value)


def _normalize_release_date(value: str) -> str:
    text = value.strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError as exc:
        raise ManifestError(
            "release_date must be an ISO 8601 date such as 2026-10-31."
        ) from exc


def _normalize_notes(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        notes = value
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        notes = "\n".join(value)
    else:
        raise ManifestError(
            "release_notes must be a string or a list of strings."
        )
    notes = notes.replace("\x00", "").strip()
    if len(notes) > _MAX_RELEASE_NOTES:
        raise ManifestError("release_notes is too long.")
    return notes


def _validate_download_url(url: str, trusted_hosts: tuple[str, ...]) -> str:
    if len(url) > _MAX_URL_LENGTH:
        raise ManifestError("download_url is too long.")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ManifestError("download_url is not a valid URL.") from exc

    if parsed.scheme != "https":
        raise ManifestError("download_url must use HTTPS.")
    if not parsed.hostname:
        raise ManifestError("download_url does not contain a host name.")
    if parsed.username is not None or parsed.password is not None:
        raise ManifestError("download_url must not contain credentials.")
    if parsed.fragment:
        raise ManifestError("download_url must not contain a fragment.")
    if is_ip_literal(parsed.hostname):
        raise ManifestError(
            "download_url must use a DNS host name, not an IP address."
        )
    if port is not None and not (1 <= port <= 65535):
        raise ManifestError("download_url has an invalid port.")
    host = parsed.hostname
    if not host_is_trusted(host, trusted_hosts):
        raise ManifestError(
            f"The download host “{url_host(url)}” is not trusted. Add it to "
            "IDM_UPDATE_TRUSTED_HOSTS if it belongs to the configured publisher."
        )
    if not parsed.path.lower().endswith(".exe"):
        raise ManifestError(
            "download_url must point to the Windows installer (.exe)."
        )
    return url
