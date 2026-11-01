"""Central update configuration for the IDM desktop application.

This is the only place where the update endpoint and trust anchors are
declared.  Do not hardcode update URLs anywhere else.

The endpoint and manifest signing key are configured for the public IDM
repository.  ``EXPECTED_PUBLISHER`` intentionally remains empty until a
CA-issued Authenticode code-signing certificate is available.  Automatic
installation is still available without it: the installer is trusted because
its SHA-256 digest comes from the Ed25519-signed manifest.  When a publisher
is configured, a valid Authenticode signature is required as well.

``UPDATE_MANIFEST_URL`` is derived from the GitHub owner, repository, branch
and manifest path, so renaming the repository does not require editing any
Python module.

Environment overrides are handled in :mod:`idm.updater.config`:
``IDM_UPDATE_MANIFEST_URL``, ``IDM_UPDATE_PUBLISHER``,
``IDM_UPDATE_CHANNEL``, ``IDM_UPDATE_TRUSTED_HOSTS`` and
``IDM_UPDATE_MANIFEST_PUBLIC_KEY``.
"""

from __future__ import annotations

# Single source of truth for the version; also used by build_windows.ps1.
from idm.version import APP_NAME, CURRENT_VERSION

__all__ = [
    "ALLOWED_DOWNLOAD_HOSTS",
    "ALLOWED_MANIFEST_HOSTS",
    "APP_NAME",
    "CURRENT_VERSION",
    "EXPECTED_PUBLISHER",
    "GITHUB_MANIFEST_BRANCH",
    "GITHUB_MANIFEST_PATH",
    "GITHUB_OWNER",
    "GITHUB_REPO",
    "MANIFEST_PUBLIC_KEY",
    "UPDATE_CHANNEL",
    "UPDATE_CONNECT_TIMEOUT",
    "UPDATE_MANIFEST_URL",
    "UPDATE_MAX_INSTALLER_BYTES",
    "UPDATE_MAX_MANIFEST_BYTES",
    "UPDATE_READ_TIMEOUT",
]

# ---------------------------------------------------------------------------
# GitHub update server
# ---------------------------------------------------------------------------

# Public GitHub account that owns the repository holding the signed manifest.
GITHUB_OWNER = "servicingcentrecomputer-maker"

GITHUB_REPO = "IDM"
GITHUB_MANIFEST_BRANCH = "main"
GITHUB_MANIFEST_PATH = "update/latest.json"

# Public, unauthenticated HTTPS endpoint.  No token or credential is ever sent
# by the desktop application.
UPDATE_MANIFEST_URL = (
    f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/"
    f"{GITHUB_MANIFEST_BRANCH}/{GITHUB_MANIFEST_PATH}"
    if GITHUB_OWNER
    else ""
)

# The manifest itself is served by raw.githubusercontent.com.  GitHub release
# assets are served from github.com and then redirect to one of the asset CDN
# hosts below.  Downloads from any other host are rejected.
ALLOWED_MANIFEST_HOSTS = [
    "raw.githubusercontent.com",
    "github.com",
    "api.github.com",
]

ALLOWED_DOWNLOAD_HOSTS = [
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
]

# ---------------------------------------------------------------------------
# Release trust
# ---------------------------------------------------------------------------

# Optional additional trust anchor: the exact Authenticode signer name reported
# by Windows for IDM_Setup.exe.  Empty until a CA-issued code-signing certificate
# is available.  Automatic installation still works through the Ed25519-signed
# manifest and SHA-256; when this is set, a matching signature is also required.
EXPECTED_PUBLISHER = ""

# Base64 (standard alphabet) of the raw 32-byte Ed25519 public key used to sign
# latest.json.  Every manifest must carry a valid ``manifest_signature`` or the
# check fails.  The matching private key is kept offline outside this
# repository; generate a pair with ``scripts/sign_manifest.py keygen``.
MANIFEST_PUBLIC_KEY = "IOPAnTyv1RFStYfuTPmK61Rvpf9HzzvFM4Q+FALboK8="

# "stable" accepts only stable manifests.  "beta" accepts beta and stable
# manifests.  The channel can also be chosen in Options -> Updates.
UPDATE_CHANNEL = "stable"

# ---------------------------------------------------------------------------
# Network limits
# ---------------------------------------------------------------------------

UPDATE_CONNECT_TIMEOUT = 10.0
UPDATE_READ_TIMEOUT = 30.0
UPDATE_MAX_MANIFEST_BYTES = 512 * 1024
UPDATE_MAX_INSTALLER_BYTES = 512 * 1024 * 1024
