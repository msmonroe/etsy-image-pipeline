"""Etsy PNG export at a predictable print resolution."""
from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
from pathlib import Path
from PIL import Image

ETSY_MAX_BYTES = 20_000_000
DEFAULT_TARGET_BYTES = 19_900_000
DEFAULT_LONG_EDGE = 3600


class EtsyOptimizationError(ValueError):
    pass


def _encode(image: Image.Image) -> bytes:
    stream = io.BytesIO()
    # RGB is lossless for fully opaque artwork and avoids a redundant alpha plane.
    if image.getchannel("A").getextrema() == (255, 255):
        image = image.convert("RGB")
    image.save(stream, format="PNG", optimize=True, compress_level=9,
               dpi=(300, 300))
    return stream.getvalue()


def _try_oxipng(data: bytes) -> bytes:
    """Optional lossless second pass; never replace with larger or invalid data."""
    exe = shutil.which("oxipng")
    if not exe:
        return data
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "etsy.png"
            path.write_bytes(data)
            subprocess.run([exe, "-o", "4", "--strip", "safe", "--", str(path)],
                           check=True, capture_output=True, timeout=180)
            candidate = path.read_bytes()
            if len(candidate) < len(data):
                with Image.open(io.BytesIO(candidate)) as checked:
                    checked.verify()
                return candidate
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return data


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
    has_transparency = image.getchannel("A").getextrema()[0] < 255
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
        result = _try_oxipng(result)
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
        "has_transparency": has_transparency,
        "dpi": 300,
        "resized": target_size != original_size,
    }
