"""Create an Etsy-safe transparent PNG without altering the upscaled master."""
from __future__ import annotations

import io
from PIL import Image

# Etsy uses decimal MB. Leave headroom for metadata and future platform changes.
ETSY_MAX_BYTES = 20_000_000
DEFAULT_TARGET_BYTES = 19_000_000


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
    widths: tuple[int, ...] = (4500, 3600, 3000),
) -> tuple[bytes, dict]:
    """Lossless PNG encoding, then proportional downscaling only when needed.

    Preserve the original alpha and RGB mode, with no palette reduction or
    JPEG conversion. Never silently return an oversized or undersized file.
    """
    if not 0 < target_bytes < ETSY_MAX_BYTES:
        raise ValueError("target_bytes must be below Etsy's 20 MB ceiling")
    with Image.open(io.BytesIO(source)) as opened:
        if opened.format != "PNG":
            raise EtsyOptimizationError("Expected PNG source")
        image = opened.convert("RGBA")
    original_size = image.size
    has_alpha = image.getchannel("A").getextrema()[0] < 255
    if not has_alpha:
        raise EtsyOptimizationError("Expected actual transparency in the PNG")

    # First try the original dimensions with a stronger lossless compressor.
    candidates = [image]
    for width in widths:
        if width <= 0:
            raise ValueError("widths must be positive")
        if max(original_size) > width:
            ratio = width / max(original_size)
            size = (max(1, round(original_size[0] * ratio)),
                    max(1, round(original_size[1] * ratio)))
            if size != candidates[-1].size:
                candidates.append(image.resize(size, Image.Resampling.LANCZOS))

    for candidate in candidates:
        data = _encode(candidate)
        if len(data) <= target_bytes:
            with Image.open(io.BytesIO(data)) as verified:
                verified.verify()
            return data, {
                "source_dimensions": list(original_size),
                "etsy_dimensions": list(candidate.size),
                "bytes": len(data),
                "has_transparency": True,
                "dpi": 300,
                "resized": candidate.size != original_size,
            }
    raise EtsyOptimizationError(
        "Cannot fit a true-color transparent PNG under the Etsy limit "
        "without going below the configured minimum resolution. "
        "Review manually; master is unchanged."
    )
