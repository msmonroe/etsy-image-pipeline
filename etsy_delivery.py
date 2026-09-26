from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image


@dataclass(frozen=True)
class DeliveryResult:
    png_bytes: bytes
    width: int
    height: int
    size_bytes: int


def _save_png(image: Image.Image, dpi: int = 300) -> bytes:
    output = io.BytesIO()
    image.save(
        output,
        format="PNG",
        optimize=True,
        compress_level=9,
        dpi=(dpi, dpi),
    )
    return output.getvalue()


def create_etsy_delivery_png(
    master_png: bytes,
    max_file_bytes: int,
    min_dimension: int = 4000,
    dpi: int = 300,
    resize_step: float = 0.97,
) -> DeliveryResult:
    """Create an Etsy-safe PNG while preserving transparency and aspect ratio.

    The master is first losslessly re-encoded. If it is still too large, the
    image is reduced in small steps until it fits under max_file_bytes. The
    function refuses to shrink either dimension below min_dimension.
    """
    if max_file_bytes <= 0:
        raise ValueError("max_file_bytes must be greater than zero")
    if min_dimension <= 0:
        raise ValueError("min_dimension must be greater than zero")
    if not 0.80 <= resize_step < 1.0:
        raise ValueError("resize_step must be between 0.80 and 1.0")

    with Image.open(io.BytesIO(master_png)) as source:
        image = source.convert("RGBA")
        payload = _save_png(image, dpi=dpi)
        width, height = image.size

        if len(payload) <= max_file_bytes:
            return DeliveryResult(payload, width, height, len(payload))

        while True:
            next_width = max(1, int(round(width * resize_step)))
            next_height = max(1, int(round(height * resize_step)))

            if min(next_width, next_height) < min_dimension:
                raise ValueError(
                    "Could not fit PNG under Etsy delivery limit without "
                    f"shrinking below {min_dimension}px. "
                    f"Last attempt: {width}x{height}, {len(payload) / (1024 * 1024):.2f} MiB"
                )

            image = image.resize(
                (next_width, next_height),
                Image.Resampling.LANCZOS,
            )
            width, height = image.size
            payload = _save_png(image, dpi=dpi)

            if len(payload) <= max_file_bytes:
                return DeliveryResult(payload, width, height, len(payload))
