"""Regenerate Windows and installer branding assets from assets/logo.svg.

Run with a Python environment that has PySide6 and Pillow installed::

    python tools/generate_branding_assets.py

Outputs:
    assets/logo/idm.ico                Multi-resolution Windows icon
    assets/logo/idm.png               256 px RGBA logo
    installer/assets/wizard-large.bmp Inno Setup large wizard image (164x314)
    installer/assets/wizard-small.bmp Inno Setup small wizard image (55x55)
"""

from __future__ import annotations

import io
import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageDraw, ImageFont
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1]
LOGO_SVG = ROOT / "assets" / "logo.svg"
LOGO_DIR = ROOT / "assets" / "logo"
INSTALLER_ASSETS = ROOT / "installer" / "assets"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from idm.constants import APP_VERSION  # noqa: E402

BRAND_BLUE = "#1D5BEA"
BRAND_BLUE_LIGHT = "#3F7BFF"
TEXT_DARK = "#0E1726"
TEXT_MUTED = "#526079"
BACKGROUND = "#F4F7FD"

ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def render_logo(size: int) -> Image.Image:
    renderer = QSvgRenderer(str(LOGO_SVG))
    if not renderer.isValid():
        raise RuntimeError(f"Could not load {LOGO_SVG}")

    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()

    raw = image.constBits().tobytes()
    return Image.frombytes("RGBA", (size, size), raw, "raw", "BGRA")


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _bmp_frame(image: Image.Image) -> bytes:
    image = image.convert("RGBA")
    width, height = image.size
    pixels = image.tobytes()
    rows = []
    for y in range(height - 1, -1, -1):
        source = pixels[y * width * 4 : (y + 1) * width * 4]
        row = bytearray(width * 4)
        for x in range(width):
            offset = x * 4
            red, green, blue, alpha = source[offset : offset + 4]
            row[offset] = blue
            row[offset + 1] = green
            row[offset + 2] = red
            row[offset + 3] = alpha
        rows.append(bytes(row))
    bitmap = b"".join(rows)
    mask_row_bytes = ((width + 31) // 32) * 4
    mask = b"\x00" * (mask_row_bytes * height)
    header = struct.pack(
        "<IiiHHIIiiII",
        40,
        width,
        height * 2,
        1,
        32,
        0,
        len(bitmap) + len(mask),
        0,
        0,
        0,
        0,
    )
    return header + bitmap + mask


def write_ico(path: Path) -> None:
    frames = []
    for size in ICON_SIZES:
        image = render_logo(size)
        payload = _png_bytes(image) if size >= 256 else _bmp_frame(image)
        frames.append((size, size, payload))

    offset = 6 + 16 * len(frames)
    entries = bytearray()
    blobs = bytearray()
    for width, height, payload in frames:
        entries.extend(
            struct.pack(
                "<BBBBHHII",
                0 if width >= 256 else width,
                0 if height >= 256 else height,
                0,
                0,
                1,
                32,
                len(payload),
                offset,
            )
        )
        blobs.extend(payload)
        offset += len(payload)
    path.write_bytes(struct.pack("<HHH", 0, 1, len(frames)) + entries + blobs)


def load_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    candidates = (
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / name,
        Path(r"C:\Windows\Fonts") / name,
    )
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def centered_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    y: int,
    font: ImageFont.FreeTypeFont,
    fill: str,
    width: int,
) -> None:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    draw.text(
        ((width - (right - left)) / 2 - left, y - top),
        text,
        font=font,
        fill=fill,
    )


def build_wizard_large(logo: Image.Image) -> Image.Image:
    width, height = 164, 314
    image = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(image)

    # Soft vertical gradient behind the logo.
    for y in range(180):
        ratio = y / 179
        color = tuple(
            int(start + (end - start) * ratio)
            for start, end in zip((233, 240, 253), (248, 250, 255))
        )
        draw.line((0, y, width, y), fill=color)

    draw.rectangle((0, height - 8, width, height), fill=BRAND_BLUE)

    logo_size = 92
    scaled = logo.resize((logo_size, logo_size), Image.Resampling.LANCZOS)
    image.paste(scaled, ((width - logo_size) // 2, 38), scaled)

    title_font = load_font("segoeuib.ttf", 30)
    tagline_font = load_font("segoeui.ttf", 10)
    centered_text(draw, "IDM", 150, title_font, BRAND_BLUE, width)
    centered_text(
        draw, "Internet Download", 190, tagline_font, TEXT_MUTED, width
    )
    centered_text(draw, "Manager", 204, tagline_font, TEXT_MUTED, width)

    draw.line((30, 232, width - 30, 232), fill="#DCE5F4", width=1)
    version_font = load_font("segoeui.ttf", 9)
    centered_text(
        draw, f"Version {APP_VERSION}", 246, version_font, TEXT_MUTED, width
    )
    return image


def build_wizard_small(logo: Image.Image) -> Image.Image:
    size = 55
    image = Image.new("RGB", (size, size), "#FFFFFF")
    logo_size = 47
    scaled = logo.resize((logo_size, logo_size), Image.Resampling.LANCZOS)
    image.paste(scaled, ((size - logo_size) // 2, (size - logo_size) // 2), scaled)
    return image


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication([])

    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    INSTALLER_ASSETS.mkdir(parents=True, exist_ok=True)

    logo_256 = render_logo(256)
    logo_256.save(LOGO_DIR / "idm.png", format="PNG")
    write_ico(LOGO_DIR / "idm.ico")

    build_wizard_large(render_logo(512)).save(
        INSTALLER_ASSETS / "wizard-large.bmp", format="BMP"
    )
    build_wizard_small(render_logo(128)).save(
        INSTALLER_ASSETS / "wizard-small.bmp", format="BMP"
    )

    if app is not None and QGuiApplication.instance() is app:
        app.quit()

    print(f"logo:    {LOGO_DIR / 'idm.png'}")
    print(f"icon:    {LOGO_DIR / 'idm.ico'}")
    print(f"wizard:  {INSTALLER_ASSETS / 'wizard-large.bmp'}")
    print(f"wizard:  {INSTALLER_ASSETS / 'wizard-small.bmp'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
