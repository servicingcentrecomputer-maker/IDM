"""Regenerate browser-extension icons from the application logo."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "logo" / "idm.png"
BROWSERS = ("chrome", "edge", "firefox")
SIZES = (16, 32, 48, 128)


def main() -> int:
    if not SOURCE.is_file():
        print(f"Source logo not found: {SOURCE}", file=sys.stderr)
        return 1
    with Image.open(SOURCE) as source:
        image = source.convert("RGBA")
        for browser in BROWSERS:
            folder = ROOT / "extensions" / browser / "icons"
            folder.mkdir(parents=True, exist_ok=True)
            for size in SIZES:
                icon = image.resize((size, size), Image.Resampling.LANCZOS)
                icon.save(folder / f"icon{size}.png", "PNG", optimize=True)
            print(f"Updated {folder.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
