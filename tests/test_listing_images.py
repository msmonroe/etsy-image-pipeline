from __future__ import annotations

import io

from PIL import Image
import pytest
from pydantic import ValidationError

from listing_images import ListingImageSpec, generate_listing_images


def test_generate_listing_images_returns_expected_assets(png_bytes):
    source = png_bytes((120, 120), transparent=True)
    generated = generate_listing_images(
        source,
        ["gamer_corgi.png"],
        width=600,
        height=500,
        jpeg_quality=80,
    )

    assert set(generated) == {
        "01_hero.jpg",
        "02_detail.jpg",
        "03_specs.jpg",
        "04_included.jpg",
    }

    for payload in generated.values():
        with Image.open(io.BytesIO(payload)) as image:
            assert image.format == "JPEG"
            assert image.size == (600, 500)


def test_listing_spec_is_pydantic_validated():
    with pytest.raises(ValidationError):
        ListingImageSpec(width=0, height=500, jpeg_quality=80)
