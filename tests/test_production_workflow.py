import io
import pytest
from PIL import Image
from production_workflow import (plan_export, export_png, validate_downloads,
                                 validate_cut_design, ETSY_MAX_BYTES)


def sample_png(size=(4500, 4500)):
    out = io.BytesIO()
    Image.new("RGBA", size, (0, 120, 60, 0)).save(out, "PNG")
    return out.getvalue()


def test_skip_upscale_when_source_sufficient():
    plan = plan_export((4600, 4600), "clipart")
    assert not plan.upscale and plan.scale == 1


def test_upscale_when_needed_without_distortion():
    plan = plan_export((1024, 1024), "clipart")
    assert plan.upscale and plan.scale == 5


def test_shirt_requires_portrait_target():
    assert plan_export((4500, 4500), "shirt").upscale


def test_export_preserves_alpha_and_dpi():
    with Image.open(io.BytesIO(export_png(sample_png(), (3000, 3000)))) as img:
        assert img.size == (3000, 3000)
        assert img.getchannel("A").getextrema() == (0, 0)
        assert img.info["dpi"][0] == pytest.approx(300, abs=1)


def test_export_refuses_fake_resolution():
    with pytest.raises(ValueError, match="upscale"):
        export_png(sample_png((100, 100)), (3000, 3000))


def test_etsy_limits_and_duplicate_names():
    validate_downloads([("art.zip", b"ok")])
    with pytest.raises(ValueError, match="1 to 5"):
        validate_downloads([(str(i)+".zip", b"x") for i in range(6)])
    with pytest.raises(ValueError, match="oversized"):
        validate_downloads([("big.zip", b"x" * (ETSY_MAX_BYTES + 1))])
    with pytest.raises(ValueError, match="duplicate"):
        validate_downloads([("a.zip", b"x"), ("a.zip", b"y")])


def test_cut_ready_requires_qc():
    validate_cut_design(closed_paths=True, overlapping_paths=False, simplified=True)
    with pytest.raises(ValueError):
        validate_cut_design(closed_paths=False, overlapping_paths=False, simplified=True)
    with pytest.raises(ValueError):
        validate_downloads([("illustration.png", b"x")], cut_ready=True)
