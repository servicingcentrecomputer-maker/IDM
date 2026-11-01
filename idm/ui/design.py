"""Design tokens shared by every IDM surface.

The tokens are intentionally framework-light so both QSS (theme.py) and
custom-painted widgets (delegates, charts, toggles) use the same scale.
All values are final: components must not invent their own spacing, radii or
animation timings.
"""

from __future__ import annotations

import ctypes
import logging
import sys

from dataclasses import dataclass

logger = logging.getLogger(__name__)

FONT_FAMILY = '"Segoe UI"'
MONO_FAMILY = '"Cascadia Mono", "Consolas", monospace'

SPACING: dict[str, int] = {
    "none": 0,
    "xxs": 2,
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 24,
    "xxl": 32,
    "xxxl": 40,
}

RADIUS: dict[str, str] = {
    "none": "0px",
    "xs": "6px",
    "sm": "8px",
    "md": "10px",
    "lg": "14px",
    "xl": "18px",
    "pill": "14px",
}

RADIUS_PX: dict[str, int] = {
    key: int(value.rstrip("px")) for key, value in RADIUS.items()
}

# (pixel size, weight) pairs consumed by QSS font declarations.
TYPOGRAPHY: dict[str, tuple[int, int]] = {
    "micro": (10, 700),
    "caption": (11, 400),
    "label": (10, 700),
    "small": (12, 400),
    "body": (13, 400),
    "body_strong": (13, 600),
    "subtitle": (14, 600),
    "title": (17, 600),
    "heading": (20, 600),
    "display": (28, 700),
}

MOTION: dict[str, int] = {
    "instant": 0,
    "fast": 140,
    "normal": 210,
    "slow": 300,
}

ICON_SIZE: dict[str, int] = {
    "xs": 12,
    "sm": 14,
    "md": 16,
    "lg": 18,
    "xl": 22,
    "xxl": 26,
    "hero": 32,
}

ELEVATION: dict[str, tuple[int, int, int]] = {
    # blur radius, y offset, colour alpha (0-255) against palette.shadow
    "flat": (0, 0, 0),
    "card": (24, 4, 24),
    "raised": (36, 10, 44),
}

# Windows reuses SPI_GETCLIENTAREAANIMATION for the "Animation effects"
# accessibility switch in Settings > Accessibility > Visual effects.
_SPI_GETCLIENTAREAANIMATION = 0x1042

_animations_enabled = True


@dataclass(frozen=True)
class SurfaceStyle:
    """Derived numbers for custom painters and window chrome."""

    page_margin: int = SPACING["xl"]
    card_radius: int = int(RADIUS["lg"].rstrip("px"))
    card_padding: int = SPACING["lg"]
    row_height: int = 64
    control_height: int = 36
    toolbar_height: int = 72
    sidebar_expanded: int = 240
    sidebar_collapsed: int = 68


SURFACE = SurfaceStyle()


def system_reduced_motion() -> bool:
    """True when Windows accessibility settings disable animations."""
    if sys.platform != "win32":
        return False
    try:
        enabled = ctypes.c_int(1)
        ok = ctypes.windll.user32.SystemParametersInfoW(
            _SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0
        )
        if not ok:
            return False
        return not bool(enabled.value)
    except Exception:
        logger.debug("Could not read the animation preference", exc_info=True)
        return False


def set_animations_enabled(enabled: bool) -> None:
    """Called once settings are known; combines user and OS preferences."""
    global _animations_enabled
    _animations_enabled = bool(enabled) and not system_reduced_motion()


def animations_enabled() -> bool:
    return _animations_enabled


def duration(name: str = "normal") -> int:
    if not _animations_enabled:
        return 0
    return MOTION.get(name, MOTION["normal"])


def shadow_effect(widget, level: str = "card"):
    """Return a configured drop shadow, or None when shadows are disabled."""
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QGraphicsDropShadowEffect

    blur, offset, alpha = ELEVATION.get(level, ELEVATION["card"])
    if not _animations_enabled or blur == 0 or alpha == 0:
        return None
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, offset)
    effect.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(effect)
    return effect


__all__ = [
    "ELEVATION",
    "FONT_FAMILY",
    "ICON_SIZE",
    "MONO_FAMILY",
    "MOTION",
    "RADIUS",
    "RADIUS_PX",
    "SPACING",
    "SURFACE",
    "TYPOGRAPHY",
    "animations_enabled",
    "duration",
    "set_animations_enabled",
    "shadow_effect",
    "system_reduced_motion",
]
