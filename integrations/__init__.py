"""Browser integration shared by the IDM desktop application and native host.

Only the Qt-free modules in this package are imported by
``integrations.native_host``: the native messaging host is a separate,
windowless process started by Chrome, Edge or Firefox and must not load
PySide6.
"""

from __future__ import annotations

NATIVE_HOST_NAME = "com.idm.native"
PROTOCOL_VERSION = 2
NATIVE_HOST_VERSION = "3.6.2"

__all__ = ["NATIVE_HOST_NAME", "NATIVE_HOST_VERSION", "PROTOCOL_VERSION"]
