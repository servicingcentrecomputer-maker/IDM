"""Logging configuration shared by every module."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from .paths import ensure_app_layout, log_file

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if getattr(root, "_idm_configured", False):
        return

    ensure_app_layout()
    root.setLevel(logging.DEBUG)

    file_handler = RotatingFileHandler(
        log_file(), maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))

    root.addHandler(file_handler)

    # A windowed PyInstaller build has no console: sys.stderr is None.
    if sys.stderr is not None:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(level)
        console_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        root.addHandler(console_handler)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    root._idm_configured = True  # type: ignore[attr-defined]
