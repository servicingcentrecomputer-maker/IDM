"""Logging configuration shared by every module."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from .paths import ensure_app_layout, log_file
from .url_utils import scrub_secrets

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


class SecretRedactionFilter(logging.Filter):
    """Strip credentials from every line before it reaches a handler.

    Proxy URLs, transport exceptions and server replies all end up in the log
    verbatim.  A user's password must not be readable in a support file, and a
    per-callsite reminder is not something an unrelated module will remember.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # a record that cannot format still has to be logged
            return True
        scrubbed = scrub_secrets(message)
        if scrubbed != message:
            record.msg = scrubbed
            record.args = ()
        return True


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if getattr(root, "_idm_configured", False):
        return

    ensure_app_layout()
    root.setLevel(logging.DEBUG)
    redaction = SecretRedactionFilter()

    file_handler = RotatingFileHandler(
        log_file(), maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    file_handler.addFilter(redaction)

    root.addHandler(file_handler)

    # A windowed PyInstaller build has no console: sys.stderr is None.
    if sys.stderr is not None:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(level)
        console_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        console_handler.addFilter(redaction)
        root.addHandler(console_handler)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    root._idm_configured = True  # type: ignore[attr-defined]
