"""Conservative, product-aware exports and Etsy download preflight."""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from PIL import Image

ETSY_MAX_FILES = 5
ETSY_MAX_BYTES = 20_000_000
TARGETS = {
    "clipart": (4500, 4500),
    "sticker": (3000, 3000),
    "shirt": (4500, 5400),
    "wall_3x4": (3600, 4800),
}
RASTER_FORMATS = {".png", ".jpg", ".jpeg", ".pdf"}
VECTOR_FORMATS = {".svg", ".eps"}
CUT_FORMATS = {".svg", ".dxf"}


@dataclass(frozen=True)
class ExportPlan:
    product: str
    target: tuple[int, int]
    upscale: bool
    scale: int
    print_dpi: int = 300


def plan_export(source_size: tuple[int, int], product: str) -> ExportPlan:
    """Never enlarge an adequate source; use aspect-preserving integer upscale."""
    if product not in TARGETS:
        raise ValueError(f"Unknown product type: {product}")
    w, h = source_size
    if min(w, h) <= 0:
        raise ValueError("Source dimensions must be positive")
    target = TARGETS[product]
    scale = max(1, -(-target[0] // w), -(-target[1] // h))
    return ExportPlan(product, target, scale > 1, scale)


def export_png(source: bytes, target: tuple[int, int], *, allow_enlarge: bool = False) -> bytes:
    """Fit without distortion; do not pretend interpolation adds genuine detail."""
    with Image.open(io.BytesIO(source)) as original:
        image = original.convert("RGBA")
        if min(target) <= 0:
            raise ValueError("Invalid export dimensions")
        if not allow_enlarge and (image.width < target[0] or image.height < target[1]):
            raise ValueError("Source too small: upscale and QC first")
        image.thumbnail(target, Image.Resampling.LANCZOS)
        result = io.BytesIO()
        image.save(result, format="PNG", optimize=True, dpi=(300, 300))
        return result.getvalue()


def validate_downloads(files: list[tuple[str, bytes]], *, cut_ready: bool = False) -> None:
    """Validate actual upload payloads before any Etsy network request."""
    if not 1 <= len(files) <= ETSY_MAX_FILES:
        raise ValueError("Etsy allows 1 to 5 download files")
    names = set()
    for filename, payload in files:
        name = Path(filename).name
        if not name or name in names:
            raise ValueError("Empty or duplicate download filename")
        names.add(name)
        if not payload or len(payload) > ETSY_MAX_BYTES:
            raise ValueError(f"Empty or oversized download: {name}")
        if cut_ready and Path(name).suffix.lower() not in CUT_FORMATS | {".zip"}:
            raise ValueError(f"Not a cutting format: {name}")


def validate_cut_design(*, closed_paths: bool, overlapping_paths: bool,
                        simplified: bool) -> None:
    """DXF is a separate cutter-QC product, never an automatic raster conversion."""
    if not (closed_paths and simplified) or overlapping_paths:
        raise ValueError("Cut design requires simplified, closed, non-overlapping paths")
