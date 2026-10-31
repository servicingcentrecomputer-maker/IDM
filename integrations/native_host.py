"""Native messaging host for Chrome, Edge and Firefox.

The browser starts this executable, writes one or more length-prefixed JSON
messages to stdin and reads length-prefixed JSON responses from stdout.
Nothing except protocol frames is ever written to stdout; all diagnostics go
to a rotating log file and to stderr.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from integrations import NATIVE_HOST_VERSION, PROTOCOL_VERSION  # noqa: E402
from integrations.browser_detector import (  # noqa: E402
    browser_display_name,
    detect_calling_browser,
)
from integrations.message_handler import NativeHostMessageHandler  # noqa: E402
from integrations.paths import native_log_file  # noqa: E402
from integrations.protocol import (  # noqa: E402
    MAX_MESSAGE_BYTES,
    ProtocolError,
    read_message,
    response_error,
    write_message,
)

logger = logging.getLogger("idm.native_host")


def _setup_logging() -> None:
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    try:
        path = native_log_file()
        handler = logging.handlers.RotatingFileHandler(
            str(path),
            maxBytes=1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(formatter)
        handler.setLevel(logging.INFO)
        logger.addHandler(handler)
    except OSError:
        pass

    stderr_handler = logging.StreamHandler(stream=sys.stderr)
    stderr_handler.setFormatter(formatter)
    stderr_handler.setLevel(logging.WARNING)
    logger.addHandler(stderr_handler)


def run() -> int:
    _setup_logging()
    detected = detect_calling_browser()
    logger.info(
        "Native host %s started (pid=%s, protocol=%s, detected browser=%s)",
        NATIVE_HOST_VERSION,
        os.getpid(),
        PROTOCOL_VERSION,
        browser_display_name(detected) if detected else "unknown",
    )

    handler = NativeHostMessageHandler(detected_browser=detected)
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    while True:
        try:
            message = read_message(stdin)
        except ProtocolError as exc:
            logger.warning("Invalid native message frame: %s", exc)
            try:
                write_message(
                    stdout,
                    response_error(None, exc.code, str(exc)),
                )
            except (BrokenPipeError, OSError):
                pass
            return 2
        if message is None:
            logger.info("Browser closed the native messaging channel")
            return 0

        try:
            response = handler.handle(message)
        except Exception:
            logger.exception("Unhandled native message failure")
            response = response_error(
                None, "internal_error", "The IDM native host failed."
            )

        try:
            write_message(stdout, response)
        except (BrokenPipeError, OSError):
            logger.info("Browser closed stdout while responding")
            return 0
        except Exception:
            logger.exception("Could not encode a native message response")
            return 3


def main(argv: list[str] | None = None) -> int:
    del argv  # Chrome/Edge/Firefox may pass origin and window arguments.
    try:
        return run()
    except KeyboardInterrupt:
        return 0
    except Exception:
        logger.exception("Native host terminated unexpectedly")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
