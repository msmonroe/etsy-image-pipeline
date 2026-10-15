"""Deterministic product-use mockups compositing the original approved PNG.

These are illustrative scenes, not photographs of finished merchandise.
"""
from __future__ import annotations

import io
from PIL import Image, ImageDraw, ImageFilter, ImageFont


def _font(size: int, bold: bool = False):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _art(canvas: Image.Image, source: Image.Image, bounds: tuple[int, int, int, int]):
    """Preserve source pixels/alpha: resize and composite, never redraw."""
    x0, y0, x1, y1 = bounds
    item = source.convert("RGBA").copy()
    bbox = item.getchannel("A").getbbox()
    if bbox:
        item = item.crop(bbox)
    item.thumbnail((x1 - x0, y1 - y0), Image.Resampling.LANCZOS)
    x = x0 + (x1 - x0 - item.width) // 2
    y = y0 + (y1 - y0 - item.height) // 2
    canvas.alpha_composite(item, (x, y))


def _scene(source: Image.Image, kind: str) -> Image.Image:
    """Draw two paper-product illustrations and a tote/mug pair for inspiration."""
    w, h = 1200, 1000
    bg = (102, 76, 57, 255)
    canvas = Image.new("RGBA", (w, h), bg)
    draw = ImageDraw.Draw(canvas)
    # Rustic tabletop with subtle wood grain.
    for y in range(0, h, 13):
        shade = 90 + (y * 17 % 23)
        draw.line((0, y, w, y), fill=(shade, 68, 50, 255), width=2)
    if kind == "journal":
        draw.rounded_rectangle((95, 100, 1100, 870), 24, fill=(215, 187, 145),
                               outline=(95, 70, 45), width=9)
        draw.rounded_rectangle((135, 128, 600, 828), 12, fill=(235, 217, 183))
        draw.rounded_rectangle((610, 128, 1060, 828), 12, fill=(241, 226, 197))
        draw.line((603, 135, 603, 828), fill=(120, 95, 70), width=8)
        for y in range(225, 780, 52):
            draw.line((180, y, 530, y), fill=(201, 177, 145), width=2)
        _art(canvas, source, (630, 180, 1035, 735))
        draw.text((172, 155), "WOODLAND NOTES", font=_font(36, True), fill=(82, 61, 44))
    elif kind == "card":
        draw.rounded_rectangle((180, 170, 1040, 825), 12, fill=(172, 133, 95),
                               outline=(118, 89, 62), width=9)
        draw.polygon([(215, 210), (620, 510), (1005, 210)], fill=(191, 152, 110))
        draw.rounded_rectangle((300, 80, 940, 760), 9, fill=(250, 243, 223))
        _art(canvas, source, (345, 135, 895, 615))
        draw.text((422, 640), "A LITTLE FOREST MAGIC", font=_font(27, True),
                  fill=(87, 68, 47))
    elif kind == "tote":
        draw.arc((410, 105, 780, 480), 180, 360, fill=(219, 201, 164), width=54)
        draw.rounded_rectangle((290, 290, 920, 900), 16, fill=(235, 222, 193),
                               outline=(191, 171, 134), width=9)
        _art(canvas, source, (365, 340, 850, 815))
    elif kind == "mug":
        draw.ellipse((795, 325, 1080, 695), outline=(235, 231, 219), width=78)
        draw.rounded_rectangle((310, 255, 885, 815), 65, fill=(244, 241, 230),
                               outline=(206, 202, 191), width=10)
        _art(canvas, source, (370, 310, 820, 750))
    return canvas


def _final(scene: Image.Image, title: str, width: int, height: int, quality: int) -> bytes:
    # All mockups explicitly disclose they are examples, not included goods.
    frame = Image.new("RGB", (1200, 1000), (247, 239, 224))
    scene = scene.convert("RGB")
    scene.thumbnail((1200, 805), Image.Resampling.LANCZOS)
    frame.paste(scene, ((1200 - scene.width) // 2, 0))
    d = ImageDraw.Draw(frame)
    d.text((45, 830), title, font=_font(44, True), fill=(57, 49, 39))
    d.text((45, 897), "DIGITAL PNG ONLY  |  MOCKUP FOR INSPIRATION",
           font=_font(27, True), fill=(95, 65, 45))
    frame = frame.resize((width, height), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    frame.save(out, "JPEG", quality=quality, optimize=True, dpi=(72, 72))
    return out.getvalue()


def generate_mockups(source: Image.Image, width: int, height: int,
                     quality: int) -> dict[str, bytes]:
    journal = _scene(source, "journal")
    card = _scene(source, "card")
    collage = Image.new("RGBA", (1200, 1000), (243, 234, 214, 255))
    for kind, box in [
        ("journal", (0, 0, 600, 400)),
        ("card", (600, 0, 1200, 400)),
        ("tote", (0, 400, 600, 800)),
        ("mug", (600, 400, 1200, 800)),
    ]:
        x0, y0, x1, y1 = box
        tile = _scene(source, kind).resize((x1 - x0, y1 - y0), Image.Resampling.LANCZOS)
        collage.alpha_composite(tile, (x0, y0))
    return {
        "05_journal_mockup.jpg": _final(journal, "JUNK JOURNAL INSPIRATION", width, height, quality),
        "06_card_mockup.jpg": _final(card, "GREETING CARD INSPIRATION", width, height, quality),
        "07_uses_collage.jpg": _final(collage, "WAYS TO USE YOUR PNG", width, height, quality),
    }
