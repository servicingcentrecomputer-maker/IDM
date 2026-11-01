"""Backwards-compatible import for the Download File Info dialog.

Older builds exposed ``AddDownloadDialog`` from this module.  The dialog is
now called “Download File Info”; the alias keeps existing integrations and
tests working without changing behaviour.
"""

from __future__ import annotations

from .download_file_info import AddDownloadDialog

__all__ = ["AddDownloadDialog"]
