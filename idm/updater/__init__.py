"""Version checking and automatic updates for IDM.

The modules in this package are deliberately free of PySide6 imports so the
standalone ``IDM_Updater.exe`` can verify and install packages without loading
the Qt runtime.
"""

from __future__ import annotations

from .errors import (
    ChannelMismatchError,
    DownloadCancelled,
    DownloadError,
    HashMismatchError,
    ManifestError,
    NetworkError,
    SignatureVerificationError,
    UpdateConfigurationError,
    UpdateError,
    UpdaterError,
)

__all__ = [
    "ChannelMismatchError",
    "DownloadCancelled",
    "DownloadError",
    "HashMismatchError",
    "ManifestError",
    "NetworkError",
    "SignatureVerificationError",
    "UpdateConfigurationError",
    "UpdateError",
    "UpdaterError",
]
