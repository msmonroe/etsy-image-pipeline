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


def test_optimizer_preserves_alpha_and_300_dpi():
    result, info = optimize_etsy_png(_png(), target_bytes=500_000)
    with Image.open(io.BytesIO(result)) as image:
        assert image.mode == "RGBA"
        assert image.getchannel("A").getextrema()[0] == 0
        assert image.info["dpi"][0] == pytest.approx(300, abs=1)
        assert image.size == (128, 128)
    assert info["resized"] is False


def test_optimizer_downsizes_only_if_necessary(monkeypatch):
    import etsy_png_optimizer as opt
    actual = opt._encode
    def oversized_at_full_size(image):
        if image.width > 64:
            return b"x" * 2000
        return actual(image)
    monkeypatch.setattr(opt, "_encode", oversized_at_full_size)
    data, info = optimize_etsy_png(_png((128, 128)), target_bytes=1500,
                                    widths=(64,))
    assert info["etsy_dimensions"] == [64, 64]
    assert len(data) < 1500


def test_optimizer_fails_closed_if_no_transparency():
    with pytest.raises(EtsyOptimizationError, match="transparency"):
        optimize_etsy_png(_png(alpha=False))


def test_optimizer_fails_closed_if_no_candidate_fits(monkeypatch):
    import etsy_png_optimizer as opt
    monkeypatch.setattr(opt, "_encode", lambda image: b"x" * 2000)
    with pytest.raises(EtsyOptimizationError, match="Cannot fit"):
        optimize_etsy_png(_png(), target_bytes=1500, widths=(64,))
