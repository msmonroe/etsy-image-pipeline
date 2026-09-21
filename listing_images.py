from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Iterable

from PIL import Image, ImageDraw, ImageFilter, ImageFont


class ListingImageSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    width: int = Field(default=2400, gt=0)
    height: int = Field(default=2000, gt=0)
    jpeg_quality: int = Field(default=90, ge=1, le=100)


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _jpeg_bytes(image: Image.Image, quality: int) -> bytes:
    output = io.BytesIO()
    image.convert("RGB").save(
        output,
        format="JPEG",
        quality=quality,
        optimize=True,
        progressive=True,
        dpi=(72, 72),
    )
    return output.getvalue()


def _contain_rgba(image: Image.Image, max_size: tuple[int, int]) -> Image.Image:
    rgba = image.convert("RGBA")
    rgba.thumbnail(max_size, Image.Resampling.LANCZOS)
    return rgba


def _center(
    canvas: Image.Image,
    item: Image.Image,
    y_offset: int = 0,
) -> tuple[int, int]:
    return (
        (canvas.width - item.width) // 2,
        (canvas.height - item.height) // 2 + y_offset,
    )


def _shadowed_art(
    canvas: Image.Image,
    art: Image.Image,
    max_size: tuple[int, int],
    y_offset: int = 0,
) -> None:
    item = _contain_rgba(art, max_size)
    x, y = _center(canvas, item, y_offset=y_offset)

    alpha = item.getchannel("A")
    shadow_mask = Image.new("L", canvas.size, 0)
    shadow_mask.paste(alpha, (x + 28, y + 36))
    shadow_mask = shadow_mask.filter(ImageFilter.GaussianBlur(26))

    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 85))
    shadow.putalpha(shadow_mask)
    canvas.alpha_composite(shadow)
    canvas.alpha_composite(item, (x, y))


def _wrap(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []

    for word in words:
        candidate = " ".join(current + [word])
        box = draw.textbbox((0, 0), candidate, font=font)
        if box[2] - box[0] <= max_width or not current:
            current.append(word)
        else:
            lines.append(" ".join(current))
            current = [word]

    if current:
        lines.append(" ".join(current))
    return lines


def _draw_centered_lines(
    draw: ImageDraw.ImageDraw,
    lines: Iterable[str],
    y: int,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
    width: int,
    line_gap: int = 18,
) -> int:
    cursor = y
    for line in lines:
        box = draw.textbbox((0, 0), line, font=font)
        tw = box[2] - box[0]
        th = box[3] - box[1]
        draw.text(((width - tw) // 2, cursor), line, font=font, fill=fill)
        cursor += th + line_gap
    return cursor


def hero_image(art: Image.Image, spec: ListingImageSpec) -> bytes:
    canvas = Image.new("RGBA", (spec.width, spec.height), (246, 244, 239, 255))
    _shadowed_art(canvas, art, (1700, 1600), y_offset=-10)
    return _jpeg_bytes(canvas, spec.jpeg_quality)


def detail_image(art: Image.Image, spec: ListingImageSpec) -> bytes:
    canvas = Image.new("RGBA", (spec.width, spec.height), (34, 34, 38, 255))
    item = art.convert("RGBA")
    bbox = item.getbbox()
    if bbox:
        item = item.crop(bbox)
    item.thumbnail((2100, 1780), Image.Resampling.LANCZOS)
    x, y = _center(canvas, item)
    canvas.alpha_composite(item, (x, y))
    return _jpeg_bytes(canvas, spec.jpeg_quality)


def specs_image(
    art: Image.Image,
    spec: ListingImageSpec,
    pixel_size: tuple[int, int],
    dpi: int,
    transparent: bool,
) -> bytes:
    canvas = Image.new("RGBA", (spec.width, spec.height), (250, 250, 247, 255))
    draw = ImageDraw.Draw(canvas)

    margin_x = max(90, spec.width // 24)
    top = max(100, spec.height // 18)
    bottom = max(110, spec.height // 18)
    gutter = max(90, spec.width // 30)

    left_width = int(spec.width * 0.45)
    right_x = margin_x + left_width + gutter
    right_width = spec.width - right_x - margin_x

    item = _contain_rgba(
        art,
        (
            left_width - max(80, spec.width // 30),
            spec.height - top - bottom,
        ),
    )
    art_x = margin_x + (left_width - item.width) // 2
    art_y = top + (spec.height - top - bottom - item.height) // 2

    alpha = item.getchannel("A")
    shadow_mask = Image.new("L", canvas.size, 0)
    shadow_mask.paste(alpha, (art_x + 24, art_y + 30))
    shadow_mask = shadow_mask.filter(ImageFilter.GaussianBlur(24))
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 80))
    shadow.putalpha(shadow_mask)
    canvas.alpha_composite(shadow)
    canvas.alpha_composite(item, (art_x, art_y))

    divider_x = margin_x + left_width + gutter // 2
    draw.line(
        (divider_x, top, divider_x, spec.height - bottom),
        fill=(210, 210, 205, 255),
        width=max(3, spec.width // 800),
    )

    title_font = _font(max(58, spec.width // 34), bold=True)
    body_font = _font(max(42, spec.width // 48))
    small_font = _font(max(30, spec.width // 68))

    title = "DIGITAL PNG DOWNLOAD"
    title_lines = _wrap(draw, title, title_font, right_width)
    y = top + max(40, spec.height // 40)
    for line in title_lines:
        box = draw.textbbox((0, 0), line, font=title_font)
        draw.text(
            (right_x, y),
            line,
            font=title_font,
            fill=(31, 31, 34),
        )
        y += (box[3] - box[1]) + max(18, spec.height // 100)

    y += max(50, spec.height // 28)

    bullets = [
        f"{pixel_size[0]} × {pixel_size[1]} pixels",
        f"{dpi} DPI metadata",
        "Transparent background" if transparent else "Opaque background",
        "No physical item will be shipped",
    ]
    bullet_gap = max(34, spec.height // 42)
    for bullet in bullets:
        lines = _wrap(draw, bullet, body_font, right_width)
        for line in lines:
            box = draw.textbbox((0, 0), line, font=body_font)
            draw.text(
                (right_x, y),
                line,
                font=body_font,
                fill=(58, 58, 63),
            )
            y += (box[3] - box[1]) + max(10, spec.height // 140)
        y += bullet_gap

    footer = (
        "Production file shown for reference. "
        "Listing preview is flattened to JPEG."
    )
    footer_lines = _wrap(draw, footer, small_font, right_width)
    footer_y = spec.height - bottom - max(110, spec.height // 10)
    for line in footer_lines:
        box = draw.textbbox((0, 0), line, font=small_font)
        draw.text(
            (right_x, footer_y),
            line,
            font=small_font,
            fill=(95, 95, 100),
        )
        footer_y += (box[3] - box[1]) + max(8, spec.height // 160)

    return _jpeg_bytes(canvas, spec.jpeg_quality)


def included_image(
    art: Image.Image,
    spec: ListingImageSpec,
    digital_filenames: list[str],
) -> bytes:
    canvas = Image.new("RGBA", (spec.width, spec.height), (239, 242, 244, 255))
    _shadowed_art(canvas, art, (900, 1000), y_offset=-300)

    draw = ImageDraw.Draw(canvas)
    title_font = _font(88, bold=True)
    body_font = _font(48)
    small_font = _font(40)

    title = "WHAT'S INCLUDED"
    box = draw.textbbox((0, 0), title, font=title_font)
    draw.text(
        ((spec.width - (box[2] - box[0])) // 2, 1180),
        title,
        font=title_font,
        fill=(29, 34, 38),
    )

    shown = digital_filenames[:5] or ["High-resolution PNG file"]
    y = 1350
    for filename in shown:
        label = filename if len(filename) <= 58 else filename[:55] + "..."
        lines = _wrap(draw, f"• {label}", body_font, 1950)
        y = (
            _draw_centered_lines(
                draw, lines, y, body_font, (55, 60, 65), spec.width, 10
            )
            + 16
        )

    note = "Instant digital download • No physical product"
    lines = _wrap(draw, note, small_font, 2000)
    _draw_centered_lines(
        draw, lines, 1860, small_font, (91, 96, 101), spec.width, 8
    )
    return _jpeg_bytes(canvas, spec.jpeg_quality)


def generate_listing_images(
    source_png: bytes,
    digital_filenames: list[str],
    width: int = 2400,
    height: int = 2000,
    jpeg_quality: int = 90,
) -> dict[str, bytes]:
    spec = ListingImageSpec(
        width=width,
        height=height,
        jpeg_quality=jpeg_quality,
    )

    with Image.open(io.BytesIO(source_png)) as image:
        art = image.convert("RGBA")
        pixel_size = art.size
        dpi_info = image.info.get("dpi")
        dpi = int(round(dpi_info[0])) if dpi_info else 300
        transparent = art.getchannel("A").getextrema()[0] < 255

        return {
            "01_hero.jpg": hero_image(art, spec),
            "02_detail.jpg": detail_image(art, spec),
            "03_specs.jpg": specs_image(
                art, spec, pixel_size, dpi, transparent
            ),
            "04_included.jpg": included_image(
                art, spec, digital_filenames
            ),
        }
