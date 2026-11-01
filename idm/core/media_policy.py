"""Platform policy for video links.

IDM only downloads files that the user is authorised to fetch directly.  Web
pages on streaming platforms are not media files and often rely on access
controls; IDM recognises those URLs so the interface can explain the
restriction and offer to open the official page instead.

Nothing in this module inspects, decrypts, extracts or bypasses anything.  It
performs a host-name comparison and a file-extension check.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from .media import SUPPORTED_MEDIA_EXTENSIONS

# Recognised streaming and social platforms.  The value is the display name.
RESTRICTED_PLATFORMS: dict[str, str] = {
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "music.youtube.com": "YouTube Music",
    "vimeo.com": "Vimeo",
    "dailymotion.com": "Dailymotion",
    "twitch.tv": "Twitch",
    "netflix.com": "Netflix",
    "hulu.com": "Hulu",
    "primevideo.com": "Prime Video",
    "amazon.com": "Prime Video",
    "disneyplus.com": "Disney+",
    "max.com": "Max",
    "hbomax.com": "Max",
    "peacocktv.com": "Peacock",
    "paramountplus.com": "Paramount+",
    "tiktok.com": "TikTok",
    "instagram.com": "Instagram",
    "facebook.com": "Facebook",
    "x.com": "X",
    "twitter.com": "X",
    "soundcloud.com": "SoundCloud",
    "spotify.com": "Spotify",
}

_RESTRICTION_TEXT = (
    "IDM cannot download {platform} pages directly. This application does not "
    "bypass access controls, protected streams or platform download "
    "restrictions. Use {platform}'s own download or offline option, or add a "
    "direct MP4/WebM link you are authorised to download."
)


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().strip(".")
    except ValueError:
        return ""


def _direct_media_extension(url: str) -> bool:
    try:
        suffix = Path(urlparse(url).path).suffix.lower().lstrip(".")
    except ValueError:
        return False
    return suffix in SUPPORTED_MEDIA_EXTENSIONS


def restricted_platform(url: str) -> str | None:
    """Return the platform name for a restricted page URL, else ``None``.

    Direct links to an MP4/WebM file are allowed even on a platform host; the
    URL then still has to pass the ordinary HTTP validation and server policy.
    """
    host = _host(url)
    if not host or _direct_media_extension(url):
        return None
    for domain, name in RESTRICTED_PLATFORMS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return None


def restriction_message(platform: str) -> str:
    return _RESTRICTION_TEXT.format(platform=platform)


__all__ = ["RESTRICTED_PLATFORMS", "restricted_platform", "restriction_message"]
