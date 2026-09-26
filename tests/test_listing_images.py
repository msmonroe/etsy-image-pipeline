from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from PIL import Image

import listing_images
from listing_images import ListingImageSpec, _spec_lines, generate_listing_images


def make_png(
    width: int,
    height: int,
    *,
    dpi: int = 300,
    transparent: bool = True,
) -> bytes:
    image = Image.new("RGBA", (width, height), (40, 80, 120, 255))
    if transparent:
        alpha = Image.new("L", (width, height), 255)
        alpha.paste(80, (0, 0, width // 2, height))
        image.putalpha(alpha)

    output = io.BytesIO()
    image.save(output, format="PNG", dpi=(dpi, dpi))
    return output.getvalue()


class ListingSpecsTests(unittest.TestCase):
    def test_spec_lines_include_delivery_size(self) -> None:
        lines = _spec_lines(
            (4600, 4500),
            300,
            True,
            file_size_bytes=18 * 1024 * 1024,
        )

        self.assertEqual(lines[0], "4600 × 4500 pixels")
        self.assertEqual(lines[1], "300 DPI metadata")
        self.assertEqual(lines[2], "Transparent background")
        self.assertEqual(lines[3], "18.00 MiB download")
        self.assertEqual(lines[4], "No physical item will be shipped")

    def test_generate_listing_images_uses_delivery_specs(self) -> None:
        master = make_png(800, 800)
        delivery = make_png(640, 620)

        with patch.object(
            listing_images,
            "specs_image",
            return_value=b"specs",
        ) as mocked_specs:
            generated = generate_listing_images(
                master,
                ["art.png"],
                width=600,
                height=500,
                jpeg_quality=80,
                specs_png=delivery,
            )

        self.assertIn("03_specs.jpg", generated)
        self.assertEqual(generated["03_specs.jpg"], b"specs")

        args = mocked_specs.call_args.args
        kwargs = mocked_specs.call_args.kwargs

        specs_art = args[0]
        spec = args[1]
        pixel_size = args[2]
        dpi = args[3]
        transparent = args[4]

        self.assertEqual(specs_art.size, (640, 620))
        self.assertIsInstance(spec, ListingImageSpec)
        self.assertEqual(pixel_size, (640, 620))
        self.assertEqual(dpi, 300)
        self.assertTrue(transparent)
        self.assertEqual(kwargs["file_size_bytes"], len(delivery))

    def test_generate_listing_images_falls_back_to_master_specs(self) -> None:
        master = make_png(700, 650)

        with patch.object(
            listing_images,
            "specs_image",
            return_value=b"specs",
        ) as mocked_specs:
            generate_listing_images(
                master,
                ["art.png"],
                width=600,
                height=500,
                jpeg_quality=80,
            )

        args = mocked_specs.call_args.args
        kwargs = mocked_specs.call_args.kwargs

        self.assertEqual(args[2], (700, 650))
        self.assertEqual(args[3], 300)
        self.assertTrue(args[4])
        self.assertIsNone(kwargs["file_size_bytes"])


if __name__ == "__main__":
    unittest.main()
