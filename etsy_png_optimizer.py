"""Etsy transparent PNG export at a predictable print resolution."""
from __future__ import annotations

import io
from PIL import Image

ETSY_MAX_BYTES = 20_000_000
DEFAULT_TARGET_BYTES = 19_000_000
DEFAULT_LONG_EDGE = 3600


class EtsyOptimizationError(ValueError):
    pass


def _encode(image: Image.Image) -> bytes:
    stream = io.BytesIO()
    image.save(stream, format="PNG", optimize=True, compress_level=9,
               dpi=(300, 300))
    return stream.getvalue()


def optimize_etsy_png(
    source: bytes,
    target_bytes: int = DEFAULT_TARGET_BYTES,
    long_edge: int = DEFAULT_LONG_EDGE,
) -> tuple[bytes, dict]:
    """Export at the requested long edge, preserving aspect ratio and alpha.

    A source smaller than the requested resolution must first pass through
    the actual upscaler; this export step never pretends interpolation adds detail.
    """
    if not 0 < target_bytes < ETSY_MAX_BYTES:
        raise ValueError("target_bytes must be below Etsy's 20 MB ceiling")
    if long_edge <= 0:
        raise ValueError("long_edge must be positive")
    with Image.open(io.BytesIO(source)) as opened:
        if opened.format != "PNG":
            raise EtsyOptimizationError("Expected PNG source")
        image = opened.convert("RGBA")
    original_size = image.size
    if image.getchannel("A").getextrema()[0] == 255:
        raise EtsyOptimizationError("Expected actual transparency in the PNG")
    if max(original_size) < long_edge:
        raise EtsyOptimizationError(
            f"Master is only {original_size[0]}x{original_size[1]}; "
            f"upscale to at least {long_edge}px on the longest side first"
        )
    ratio = long_edge / max(original_size)
    target_size = (
        max(1, round(original_size[0] * ratio)),
        max(1, round(original_size[1] * ratio)),
    )
    if target_size != original_size:
        image = image.resize(target_size, Image.Resampling.LANCZOS)
    result = _encode(image)
    if len(result) > target_bytes:
        raise EtsyOptimizationError(
            f"Requested {target_size[0]}x{target_size[1]} true-color PNG "
            f"is {len(result)} bytes, over {target_bytes}; "
            "send to Needs-Review rather than silently reducing resolution"
        )
    with Image.open(io.BytesIO(result)) as verified:
        verified.verify()
    return result, {
        "source_dimensions": list(original_size),
        "etsy_dimensions": list(target_size),
        "bytes": len(result),
        "has_transparency": True,
        "dpi": 300,
        "resized": target_size != original_size,
    }
