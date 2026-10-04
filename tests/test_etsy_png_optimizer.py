from __future__ import annotations

import io
import pytest
from PIL import Image
from etsy_png_optimizer import EtsyOptimizationError, optimize_etsy_png


def _png(size=(128, 128), alpha=True):
    im = Image.new("RGBA", size, (160, 40, 20, 255))
    if alpha:
        im.putpixel((0, 0), (0, 0, 0, 0))
    out = io.BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


def test_square_export_preserves_alpha_and_300_dpi():
    result, info = optimize_etsy_png(_png((128, 128)), long_edge=128)
    with Image.open(io.BytesIO(result)) as image:
        assert image.mode == "RGBA"
        assert image.getchannel("A").getextrema()[0] == 0
        assert image.info["dpi"][0] == pytest.approx(300, abs=1)
        assert image.size == (128, 128)
    assert info["resized"] is False


def test_landscape_export_preserves_aspect_ratio():
    data, info = optimize_etsy_png(_png((200, 100)), long_edge=100)
    assert info["etsy_dimensions"] == [100, 50]
    with Image.open(io.BytesIO(data)) as image:
        assert image.size == (100, 50)


def test_rejects_low_resolution_master():
    with pytest.raises(EtsyOptimizationError, match="upscale"):
        optimize_etsy_png(_png((128, 128)), long_edge=3600)


def test_rejects_no_transparency():
    with pytest.raises(EtsyOptimizationError, match="transparency"):
        optimize_etsy_png(_png(alpha=False), long_edge=128)


def test_rejects_oversize_at_required_resolution(monkeypatch):
    import etsy_png_optimizer as opt
    monkeypatch.setattr(opt, "_encode", lambda image: b"x" * 2000)
    with pytest.raises(EtsyOptimizationError, match="Needs-Review"):
        optimize_etsy_png(_png(), target_bytes=1500, long_edge=128)
