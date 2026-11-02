"""Application-wide constants."""

from .version import (
    APP_AUTHOR,
    APP_COPYRIGHT,
    APP_DESCRIPTION,
    APP_NAME,
    APP_VERSION,
    CURRENT_VERSION,
)

__all__ = [
    "APP_AUTHOR",
    "APP_COPYRIGHT",
    "APP_DESCRIPTION",
    "APP_NAME",
    "APP_USER_AGENT",
    "APP_VERSION",
    "CATEGORIES",
    "CATEGORY_COMPRESSED",
    "CATEGORY_DOCUMENTS",
    "CATEGORY_GENERAL",
    "CATEGORY_IMAGES",
    "CATEGORY_MUSIC",
    "CATEGORY_OTHER",
    "CATEGORY_PROGRAMS",
    "CATEGORY_VIDEOS",
    "CURRENT_VERSION",
    "CUSTOM_CATEGORY_PREFIX",
    "custom_category_key",
    "custom_category_name",
]

APP_USER_AGENT = f"IDM/{APP_VERSION} (Windows NT 10.0; Win64; x64)"

# Kept separate from "%APPDATA%\IDM" because the commercial Internet Download
# Manager uses that directory, including a downloads folder and idm.log.
APP_DATA_DIR_NAME = "IDM Download Manager"

CATEGORY_GENERAL = "General"
CATEGORY_DOCUMENTS = "Documents"
CATEGORY_MUSIC = "Music"
CATEGORY_VIDEOS = "Videos"
CATEGORY_PROGRAMS = "Programs"
CATEGORY_COMPRESSED = "Compressed"
CATEGORY_IMAGES = "Images"
CATEGORY_OTHER = "Other"

CATEGORIES = (
    CATEGORY_GENERAL,
    CATEGORY_COMPRESSED,
    CATEGORY_DOCUMENTS,
    CATEGORY_MUSIC,
    CATEGORY_VIDEOS,
    CATEGORY_PROGRAMS,
    CATEGORY_IMAGES,
    CATEGORY_OTHER,
)

_BUILTIN_CATEGORY_NAMES = frozenset(CATEGORIES)

_EXTENSION_GROUPS = {
    CATEGORY_DOCUMENTS: (
        "doc", "docx", "xls", "xlsx", "ppt", "pptx", "pdf", "txt", "rtf", "odt",
        "ods", "odp", "csv", "epub", "mobi", "md", "pages", "numbers", "key",
    ),
    CATEGORY_MUSIC: (
        "mp3", "wav", "flac", "aac", "ogg", "oga", "m4a", "wma", "opus", "aiff",
        "mid", "midi", "amr",
    ),
    CATEGORY_VIDEOS: (
        "mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v", "mpg", "mpeg",
        "3gp", "ts", "m2ts",
    ),
    CATEGORY_PROGRAMS: (
        "exe", "msi", "msix", "appx", "bat", "cmd", "ps1", "apk", "jar", "dmg",
        "pkg", "deb", "rpm", "appimage", "iso", "img",
    ),
    CATEGORY_COMPRESSED: (
        "zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "xz", "zst", "cab", "lz",
        "lzma", "arj", "z",
    ),
    CATEGORY_IMAGES: (
        "jpg", "jpeg", "png", "gif", "webp", "bmp", "svg", "tif", "tiff",
        "ico", "heic", "heif", "avif", "raw", "psd",
    ),
}

EXTENSION_TO_CATEGORY = {
    extension: category
    for category, extensions in _EXTENSION_GROUPS.items()
    for extension in extensions
}

CUSTOM_CATEGORY_PREFIX = "custom:"


def custom_category_key(name: str) -> str:
    return f"{CUSTOM_CATEGORY_PREFIX}{name}"


def custom_category_name(key: str) -> str:
    if key.startswith(CUSTOM_CATEGORY_PREFIX):
        return key[len(CUSTOM_CATEGORY_PREFIX):]
    return ""


CATEGORY_FILTER_KEYS = {
    "general": CATEGORY_GENERAL,
    "documents": CATEGORY_DOCUMENTS,
    "music": CATEGORY_MUSIC,
    "videos": CATEGORY_VIDEOS,
    "programs": CATEGORY_PROGRAMS,
    "compressed": CATEGORY_COMPRESSED,
    "images": CATEGORY_IMAGES,
    "other": CATEGORY_OTHER,
}

PRIORITY_HIGH = 0
PRIORITY_NORMAL = 1
PRIORITY_LOW = 2
PRIORITIES = {
    "High": PRIORITY_HIGH,
    "Normal": PRIORITY_NORMAL,
    "Low": PRIORITY_LOW,
}

CHUNK_SIZE = 64 * 1024
MIN_SPEED_LIMIT_KBPS = 0
MAX_SPEED_LIMIT_KBPS = 1024 * 1024
