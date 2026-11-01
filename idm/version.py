"""Single source of truth for the application version and identity.

Everything that needs the installed version imports it from here.  The build
automation reads ``CURRENT_VERSION`` directly and refuses to package the
application when the installer metadata has drifted from this file.
"""

from __future__ import annotations

APP_NAME = "IDM"
APP_DESCRIPTION = "Internet Download Manager"
APP_AUTHOR = "IDM"
APP_COPYRIGHT = "Copyright (C) 2026 IDM. All rights reserved."

# Semantic versioning: MAJOR.MINOR.PATCH (optionally -prerelease).
CURRENT_VERSION = "3.0.0"

# Backwards-compatible aliases used throughout the application.
APP_VERSION = CURRENT_VERSION
