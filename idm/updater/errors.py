"""Exceptions raised by the update subsystem."""

from __future__ import annotations


class UpdateError(Exception):
    """Base class for user-presentable update failures."""


class UpdateConfigurationError(UpdateError):
    """The update endpoint, publisher or trusted hosts are not configured."""


class NetworkError(UpdateError):
    """The update server could not be reached or returned an invalid response."""


class ManifestError(UpdateError):
    """The release manifest is malformed or fails security validation."""


class ChannelMismatchError(UpdateError):
    """The manifest belongs to a channel this installation does not follow."""


class DownloadError(UpdateError):
    """The installer could not be downloaded."""


class DownloadCancelled(UpdateError):
    """The user cancelled the download."""


class HashMismatchError(DownloadError):
    """The downloaded installer does not match the manifest SHA-256."""


class SignatureVerificationError(UpdateError):
    """The installer is unsigned, has an invalid signature or a wrong publisher."""


class UpdaterError(UpdateError):
    """The standalone updater could not complete the installation."""
