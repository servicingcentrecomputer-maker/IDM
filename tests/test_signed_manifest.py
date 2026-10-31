"""Ed25519 signed-manifest tests."""

from __future__ import annotations

import base64

import pytest

from idm.updater.errors import ManifestError
from idm.updater.manifest_validator import (
    UpdateManifest,
    canonical_manifest_bytes,
)
from tests.update_helpers import manifest_data

cryptography = pytest.importorskip("cryptography")
from cryptography.exceptions import InvalidSignature  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: E402
    Ed25519PrivateKey,
)

TRUSTED = ("updates.example.com",)


@pytest.fixture
def keypair():
    private = Ed25519PrivateKey.generate()
    public_raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return private, base64.b64encode(public_raw).decode("ascii")


def _signed(data: dict, private) -> dict:
    unsigned = {
        key: value for key, value in data.items() if key != "manifest_signature"
    }
    signature = private.sign(canonical_manifest_bytes(unsigned))
    data = dict(data)
    data["manifest_signature"] = base64.b64encode(signature).decode("ascii")
    return data


def test_valid_signed_manifest_is_accepted(keypair):
    private, public = keypair
    manifest = UpdateManifest.from_dict(
        _signed(manifest_data(), private), TRUSTED, public_key=public
    )
    assert manifest.latest_version == "1.1.0"
    assert manifest.manifest_signature


def test_signed_manifest_rejects_tampering(keypair):
    private, public = keypair
    data = _signed(manifest_data(), private)
    data["latest_version"] = "9.9.9"
    with pytest.raises(ManifestError, match="signature is invalid"):
        UpdateManifest.from_dict(data, TRUSTED, public_key=public)


def test_signed_manifest_rejects_wrong_key(keypair):
    private, _public = keypair
    other = Ed25519PrivateKey.generate()
    other_public = base64.b64encode(
        other.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")
    with pytest.raises(ManifestError, match="signature is invalid"):
        UpdateManifest.from_dict(
            _signed(manifest_data(), private), TRUSTED, public_key=other_public
        )


def test_required_key_rejects_unsigned_manifest(keypair):
    _private, public = keypair
    with pytest.raises(ManifestError, match="unsigned"):
        UpdateManifest.from_dict(manifest_data(), TRUSTED, public_key=public)


def test_invalid_public_key_length_is_rejected(keypair):
    private, _public = keypair
    short_key = base64.b64encode(b"too-short").decode("ascii")
    with pytest.raises(ManifestError, match="32 Ed25519"):
        UpdateManifest.from_dict(
            _signed(manifest_data(), private), TRUSTED, public_key=short_key
        )


def test_invalid_base64_signature_is_rejected(keypair):
    _private, public = keypair
    data = manifest_data()
    data["manifest_signature"] = "not base64!"
    with pytest.raises(ManifestError, match="base64"):
        UpdateManifest.from_dict(data, TRUSTED, public_key=public)


def test_canonical_bytes_ignore_signature_and_key_order(keypair):
    private, public = keypair
    data = _signed(manifest_data(), private)
    reordered = dict(reversed(list(data.items())))
    assert canonical_manifest_bytes(data) == canonical_manifest_bytes(reordered)

    signature = base64.b64decode(data["manifest_signature"])
    verifier = private.public_key()
    verifier.verify(signature, canonical_manifest_bytes(data))
    with pytest.raises(InvalidSignature):
        verifier.verify(
            signature, canonical_manifest_bytes(manifest_data(latest_version="9.9.9"))
        )


def test_unsigned_mode_accepts_empty_signature():
    manifest = UpdateManifest.from_dict(manifest_data(), TRUSTED, public_key="")
    assert manifest.manifest_signature == ""
