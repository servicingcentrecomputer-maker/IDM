"""Original SVG icon set and application branding."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from ..constants import (
    CATEGORY_COMPRESSED,
    CATEGORY_DOCUMENTS,
    CATEGORY_GENERAL,
    CATEGORY_IMAGES,
    CATEGORY_MUSIC,
    CATEGORY_OTHER,
    CATEGORY_PROGRAMS,
    CATEGORY_VIDEOS,
)
from ..core.paths import asset_path

_SVG_BODIES: dict[str, str] = {
    "add": (
        '<path d="M12 4v10"/><path d="m7.5 10.5 4.5 4.5 4.5-4.5"/>'
        '<path d="M5 20h14"/>'
    ),
    "resume": '<path d="M8 5.2v13.6L19 12z" fill="{color}" stroke="none"/>',
    "resume_all": (
        '<path d="M6 5.5v13l8-6.5z" fill="{color}" stroke="none"/>'
        '<path d="M13 5.5v13l8-6.5z" fill="{color}" stroke="none"/>'
    ),
    "pause": (
        '<rect x="8" y="5" width="3.2" height="14" rx="1.4" fill="{color}" stroke="none"/>'
        '<rect x="13" y="5" width="3.2" height="14" rx="1.4" fill="{color}" stroke="none"/>'
    ),
    "pause_all": (
        '<rect x="3.5" y="5" width="2.6" height="14" rx="1.1" fill="{color}" stroke="none"/>'
        '<rect x="8.5" y="5" width="2.6" height="14" rx="1.1" fill="{color}" stroke="none"/>'
        '<rect x="14" y="5" width="2.6" height="14" rx="1.1" fill="{color}" stroke="none"/>'
        '<rect x="19" y="5" width="2.6" height="14" rx="1.1" fill="{color}" stroke="none"/>'
    ),
    "stop": '<rect x="7" y="7" width="10" height="10" rx="2" fill="{color}" stroke="none"/>',
    "stop_all": (
        '<rect x="4.5" y="7" width="6.5" height="10" rx="1.6" fill="{color}" stroke="none"/>'
        '<rect x="13" y="7" width="6.5" height="10" rx="1.6" fill="{color}" stroke="none"/>'
    ),
    "delete": (
        '<path d="M4 7h16"/><path d="M9 7V4.8a.8.8 0 0 1 .8-.8h4.4a.8.8 0 0 1 .8.8V7"/>'
        '<path d="M6.5 7l.8 12.2a1.8 1.8 0 0 0 1.8 1.8h5.8a1.8 1.8 0 0 0 1.8-1.8L17.5 7"/>'
        '<path d="M10 11v6M14 11v6"/>'
    ),
    "delete_completed": (
        '<path d="M4 7h12"/><path d="M8 7V4.8a.8.8 0 0 1 .8-.8h3.4a.8.8 0 0 1 .8.8V7"/>'
        '<path d="M6.5 7l.7 12.2a1.8 1.8 0 0 0 1.8 1.8h3.5"/>'
        '<path d="m14 17 2 2 4-4"/>'
    ),
    "options": (
        '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/>'
        '<circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>'
    ),
    "scheduler": '<circle cx="12" cy="12" r="8.2"/><path d="M12 7.5V12l3 2"/>',
    "queue": (
        '<path d="M9 6h11M9 12h11M9 18h11"/>'
        '<circle cx="4.5" cy="6" r="1.2" fill="{color}" stroke="none"/>'
        '<circle cx="4.5" cy="12" r="1.2" fill="{color}" stroke="none"/>'
        '<circle cx="4.5" cy="18" r="1.2" fill="{color}" stroke="none"/>'
    ),
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 4 4"/>',
    "folder": '<path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2.5h6.5a2 2 0 0 1 2 2v7.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
    "folder_open": (
        '<path d="M3.5 8V6.5a2 2 0 0 1 2-2h3.6l1.8 2.3h6.6a2 2 0 0 1 2 2V10"/>'
        '<path d="M4 10h16l-2.2 8H6.2z"/>'
    ),
    "copy": (
        '<rect x="9" y="9" width="10" height="11" rx="2"/>'
        '<path d="M15 5.5A1.5 1.5 0 0 0 13.5 4h-7A1.5 1.5 0 0 0 5 5.5v9A1.5 1.5 0 0 0 6.5 16"/>'
    ),
    "grid": (
        '<rect x="4" y="4" width="6.5" height="6.5" rx="1.8"/>'
        '<rect x="13.5" y="4" width="6.5" height="6.5" rx="1.8"/>'
        '<rect x="4" y="13.5" width="6.5" height="6.5" rx="1.8"/>'
        '<rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.8"/>'
    ),
    "check_circle": '<circle cx="12" cy="12" r="8.2"/><path d="m8.4 12.4 2.4 2.4 4.8-5"/>',
    "file_text": (
        '<path d="M7 3.5h6.5L18 8v12.5H7z"/><path d="M13.5 3.5V8H18"/>'
        '<path d="M9.5 12h6M9.5 15h4.5"/>'
    ),
    "file": '<path d="M7 3.5h6.5L18 8v12.5H7z"/><path d="M13.5 3.5V8H18"/>',
    "music": (
        '<path d="M9 18V7l9-2v9"/>'
        '<circle cx="6.5" cy="18" r="2.5"/><circle cx="15.5" cy="16" r="2.5"/>'
    ),
    "video": (
        '<rect x="3.5" y="6" width="17" height="12" rx="2.5"/>'
        '<path d="m10.5 9.5 4.5 2.5-4.5 2.5z" fill="{color}" stroke="none"/>'
    ),
    "app": (
        '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M4 9h16"/>'
        '<path d="M8 6.5h.01M10.5 6.5h.01"/>'
    ),
    "archive": (
        '<path d="M4 7.5h16V20H4z"/><path d="M3 4h18v3.5H3z"/>'
        '<path d="M10 11.5h4V14h-4z"/>'
    ),
    "image": (
        '<rect x="4" y="5" width="16" height="14" rx="2"/>'
        '<circle cx="9" cy="9.5" r="1.4"/>'
        '<path d="m5 17 4.5-4.5L13 16l2.5-2.5L19 17"/>'
    ),
    "sun": (
        '<circle cx="12" cy="12" r="4.2"/>'
        '<path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2'
        'M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M18.7 5.3l-1.4 1.4M6.7 17.3l-1.4 1.4"/>'
    ),
    "moon": '<path d="M19.5 14.2A8.2 8.2 0 0 1 9.8 4.5a8.2 8.2 0 1 0 9.7 9.7z"/>',
    "link": (
        '<path d="M10 13a5 5 0 0 0 7.1.1l2-2a5 5 0 0 0-7.1-7.1l-1.1 1.1"/>'
        '<path d="M14 11a5 5 0 0 0-7.1-.1l-2 2A5 5 0 0 0 12 20l1.1-1.1"/>'
    ),
    "arrow_up": '<path d="M12 19V5"/><path d="m6 11 6-6 6 6"/>',
    "arrow_down": '<path d="M12 5v14"/><path d="m6 13 6 6 6-6"/>',
    "download": (
        '<path d="M12 4v10"/><path d="m7.5 9.5 4.5 4.5 4.5-4.5"/>'
        '<path d="M5 20h14"/>'
    ),
    "import": (
        '<path d="M12 3v10"/><path d="m8 9 4 4 4-4"/>'
        '<path d="M4 15v4h16v-4"/>'
    ),
    "export": (
        '<path d="M12 13V3"/><path d="m8 7 4-4 4 4"/>'
        '<path d="M4 15v4h16v-4"/>'
    ),
    "exit": (
        '<path d="M10 4H5v16h5"/><path d="m14 8 4 4-4 4"/>'
        '<path d="M18 12H9"/>'
    ),
    "layout": (
        '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/>'
        '<path d="M3.5 9h17"/><path d="M7 6.8h.01M10 6.8h.01"/>'
    ),
    "sidebar": (
        '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/>'
        '<path d="M9 4.5v15"/><path d="M5.5 8h1.5M5.5 11h1.5"/>'
    ),
    "more": (
        '<circle cx="6" cy="12" r="1.5" fill="{color}" stroke="none"/>'
        '<circle cx="12" cy="12" r="1.5" fill="{color}" stroke="none"/>'
        '<circle cx="18" cy="12" r="1.5" fill="{color}" stroke="none"/>'
    ),
    "status": (
        '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/>'
        '<path d="M3.5 15.5h17"/><path d="M6 18h.01"/>'
    ),
    "palette": (
        '<path d="M12 3a9 9 0 1 0 0 18h1.4a2.3 2.3 0 0 0 0-4.6H12a2.2 2.2 0 0 1 0-4.4h4.2A4.8 4.8 0 0 0 12 3z"/>'
        '<circle cx="7.6" cy="9" r=".9" fill="{color}" stroke="none"/>'
        '<circle cx="10" cy="6.7" r=".9" fill="{color}" stroke="none"/>'
        '<circle cx="14" cy="6.7" r=".9" fill="{color}" stroke="none"/>'
        '<circle cx="7.1" cy="12.6" r=".9" fill="{color}" stroke="none"/>'
    ),
    "help": (
        '<circle cx="12" cy="12" r="8.2"/>'
        '<path d="M9.7 9.4a2.35 2.35 0 1 1 3.3 2.2c-.6.3-1 .9-1 1.6v.3"/>'
        '<path d="M12 16.8h.01"/>'
    ),
    "info": (
        '<circle cx="12" cy="12" r="8.2"/><path d="M12 11v5"/>'
        '<path d="M12 7.8h.01"/>'
    ),
    "connection": (
        '<circle cx="6" cy="12" r="2.2"/><circle cx="18" cy="6" r="2.2"/>'
        '<circle cx="18" cy="18" r="2.2"/>'
        '<path d="m8 11 8-4M8 13l8 4"/>'
    ),
    "analytics": (
        '<path d="M4 20h16"/><path d="M7 20v-6M12 20V8M17 20v-9"/>'
        '<path d="M5.5 9.5 9 6l3 2.5 5.5-4"/>'
    ),
    "gauge": (
        '<path d="M4 16.5a8 8 0 1 1 16 0"/>'
        '<path d="m12 16.5 3.8-4.8"/><circle cx="12" cy="16.5" r="1.4"/>'
    ),
    "bell": (
        '<path d="M6.5 10a5.5 5.5 0 0 1 11 0c0 4 1.5 5.5 1.5 5.5H5S6.5 14 6.5 10z"/>'
        '<path d="M10 19a2.2 2.2 0 0 0 4 0"/>'
    ),
    "refresh": (
        '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/>'
        '<path d="M19.5 4.5V9H15"/>'
    ),
    "globe": (
        '<circle cx="12" cy="12" r="8.2"/><path d="M3.8 12h16.4"/>'
        '<path d="M12 3.8c2.5 2.4 3.8 5.2 3.8 8.2s-1.3 5.8-3.8 8.2c-2.5-2.4-3.8-5.2-3.8-8.2S9.5 6.2 12 3.8z"/>'
    ),
    "shield": (
        '<path d="M12 3.5 19 6v5.4c0 4.5-3 7.4-7 9.1-4-1.7-7-4.6-7-9.1V6z"/>'
        '<path d="m8.8 11.8 2.2 2.2 4.2-4.4"/>'
    ),
    "external": (
        '<path d="M13.5 5H19v5.5"/><path d="M19 5l-7.5 7.5"/>'
        '<path d="M17 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-10A1.5 1.5 0 0 1 4 18.5v-10A1.5 1.5 0 0 1 5.5 7H10"/>'
    ),
    "play": '<path d="M8 5.2v13.6L19 12z" fill="{color}" stroke="none"/>',
    "sparkle": (
        '<path d="M12 4.5 13.6 9l4.4 1.6-4.4 1.6L12 16.7l-1.6-4.5L6 10.6 10.4 9z"/>'
        '<path d="M18.5 16.5v3M17 18h3"/>'
    ),
    "database": (
        '<ellipse cx="12" cy="6" rx="7" ry="2.8"/>'
        '<path d="M5 6v6c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8V6"/>'
        '<path d="M5 12v6c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8v-6"/>'
    ),
    "clock": '<circle cx="12" cy="12" r="8.2"/><path d="M12 7.5V12l3 2"/>',
}

CATEGORY_ICON_NAMES = {
    CATEGORY_GENERAL: "download",
    CATEGORY_DOCUMENTS: "file_text",
    CATEGORY_MUSIC: "music",
    CATEGORY_VIDEOS: "video",
    CATEGORY_PROGRAMS: "app",
    CATEGORY_COMPRESSED: "archive",
    CATEGORY_IMAGES: "image",
    CATEGORY_OTHER: "file",
}

CATEGORY_COLORS = {
    CATEGORY_GENERAL: "#4E8FD8",
    CATEGORY_DOCUMENTS: "#5B9CFF",
    CATEGORY_MUSIC: "#E879B9",
    CATEGORY_VIDEOS: "#A78BFA",
    CATEGORY_PROGRAMS: "#3ECF9A",
    CATEGORY_COMPRESSED: "#F2B84B",
    CATEGORY_IMAGES: "#57B6C9",
    CATEGORY_OTHER: "#8D9BB0",
}

_icon_cache: dict[tuple[str, str, int], QIcon] = {}
_toolbar_cache: dict[tuple[str, int], QIcon] = {}
_app_icon: QIcon | None = None
_logo_cache: dict[int, QPixmap] = {}

_TOOLBAR_FALLBACK = {
    "add_url": ("add", "#1683D8"),
    "resume": ("resume", "#2F9E63"),
    "resume_all": ("resume_all", "#2F9E63"),
    "pause": ("pause", "#D99A28"),
    "stop": ("stop", "#C94343"),
    "stop_all": ("stop_all", "#C94343"),
    "delete": ("delete", "#C94343"),
    "delete_completed": ("delete_completed", "#C94343"),
    "options": ("options", "#5B6B80"),
    "scheduler": ("scheduler", "#1683D8"),
    "queue": ("queue", "#4B7399"),
}


def _render_svg(svg: str, width: int, height: int) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, width, height))
    painter.end()
    return pixmap


def icon(name: str, color: str, size: int = 20) -> QIcon:
    key = (name, color, size)
    cached = _icon_cache.get(key)
    if cached is not None:
        return cached

    body = _SVG_BODIES.get(name, _SVG_BODIES["file"]).replace("{color}", color)
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        'fill="none" stroke="' + color + '" stroke-width="1.8" stroke-linecap="round" '
        'stroke-linejoin="round">' + body + "</svg>"
    )

    result = QIcon()
    for scale in (1, 2):
        pixmap = _render_svg(svg, size * scale, size * scale)
        if scale > 1:
            pixmap.setDevicePixelRatio(float(scale))
        result.addPixmap(pixmap)
    _icon_cache[key] = result
    return result


def toolbar_icon(name: str, size: int = 26) -> QIcon:
    """Load a full-colour toolbar icon from assets/icons/toolbar."""
    key = (name, size)
    cached = _toolbar_cache.get(key)
    if cached is not None:
        return cached

    path = asset_path("icons", "toolbar", f"{name}.svg")
    if path.exists():
        renderer = QSvgRenderer(str(path))
        result = QIcon()
        for scale in (1, 2):
            pixmap = QPixmap(size * scale, size * scale)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            renderer.render(painter, QRectF(0, 0, size * scale, size * scale))
            painter.end()
            if scale > 1:
                pixmap.setDevicePixelRatio(float(scale))
            result.addPixmap(pixmap)
        _toolbar_cache[key] = result
        return result

    fallback = _TOOLBAR_FALLBACK.get(name, ("file", "#5B6B80"))
    return icon(fallback[0], fallback[1], size)


def category_icon(category: str, color: str | None = None, size: int = 20) -> QIcon:
    name = CATEGORY_ICON_NAMES.get(category, "file")
    return icon(name, color or CATEGORY_COLORS.get(category, "#8D9BB0"), size)


def category_color(category: str) -> str:
    return CATEGORY_COLORS.get(category, CATEGORY_COLORS[CATEGORY_OTHER])


def logo_pixmap(size: int = 64) -> QPixmap:
    cached = _logo_cache.get(size)
    if cached is not None:
        return cached
    renderer = QSvgRenderer(str(asset_path("logo.svg")))
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, size * 2, size * 2))
    painter.end()
    pixmap.setDevicePixelRatio(2.0)
    _logo_cache[size] = pixmap
    return pixmap


def app_icon() -> QIcon:
    global _app_icon
    if _app_icon is not None:
        return _app_icon
    result = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        result.addPixmap(logo_pixmap(size))
    _app_icon = result
    return result


def clear_icon_cache() -> None:
    _icon_cache.clear()
    _toolbar_cache.clear()
