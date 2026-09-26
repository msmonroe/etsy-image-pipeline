from __future__ import annotations

import io
import random
import unittest

from PIL import Image

from etsy_delivery import create_etsy_delivery_png


def make_rgba_png(width: int, height: int, noisy: bool = False) -> bytes:
    image = Image.new("RGBA", (width, height), (30, 60, 90, 255))

    if noisy:
        rng = random.Random(12345)
        pixels = bytearray()
        for _ in range(width * height):
            pixels.extend(
                (
                    rng.randrange(256),
                    rng.randrange(256),
                    rng.randrange(256),
                    rng.randrange(64, 256),
                )
            )
        image = Image.frombytes("RGBA", (width, height), bytes(pixels))
    else:
        # Ensure the image really contains transparency.
        alpha = Image.new("L", (width, height), 255)
        alpha.paste(80, (0, 0, width // 2, height))
        image.putalpha(alpha)

    output = io.BytesIO()
    image.save(output, format="PNG", dpi=(300, 300))
    return output.getvalue()


class EtsyDeliveryTests(unittest.TestCase):
    def test_keeps_dimensions_when_master_already_fits(self) -> None:
        master = make_rgba_png(600, 500)

        result = create_etsy_delivery_png(
            master,
            max_file_bytes=2 * 1024 * 1024,
            min_dimension=300,
        )

        self.assertEqual((result.width, result.height), (600, 500))
        self.assertEqual(result.size_bytes, len(result.png_bytes))

        with Image.open(io.BytesIO(result.png_bytes)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.mode, "RGBA")
            self.assertLess(image.getchannel("A").getextrema()[0], 255)
            dpi = image.info.get("dpi")
            self.assertIsNotNone(dpi)
            self.assertAlmostEqual(dpi[0], 300, delta=1)
            self.assertAlmostEqual(dpi[1], 300, delta=1)

    def test_resizes_until_file_fits_limit(self) -> None:
        master = make_rgba_png(700, 560, noisy=True)
        max_bytes = 450_000

        result = create_etsy_delivery_png(
            master,
            max_file_bytes=max_bytes,
            min_dimension=250,
            resize_step=0.90,
        )

        self.assertLessEqual(result.size_bytes, max_bytes)
        self.assertLess(result.width, 700)
        self.assertLess(result.height, 560)
        self.assertGreaterEqual(min(result.width, result.height), 250)

        original_ratio = 700 / 560
        output_ratio = result.width / result.height
        self.assertAlmostEqual(output_ratio, original_ratio, delta=0.01)

        with Image.open(io.BytesIO(result.png_bytes)) as image:
            self.assertEqual(image.mode, "RGBA")
            self.assertLess(image.getchannel("A").getextrema()[0], 255)

    def test_refuses_to_shrink_below_minimum_dimension(self) -> None:
        master = make_rgba_png(500, 500, noisy=True)

        with self.assertRaisesRegex(
            ValueError,
            "Could not fit PNG under Etsy delivery limit",
        ):
            create_etsy_delivery_png(
                master,
                max_file_bytes=1_000,
                min_dimension=450,
                resize_step=0.90,
            )

    def test_rejects_invalid_configuration(self) -> None:
        master = make_rgba_png(100, 100)

        with self.assertRaisesRegex(ValueError, "max_file_bytes"):
            create_etsy_delivery_png(master, max_file_bytes=0)

        with self.assertRaisesRegex(ValueError, "min_dimension"):
            create_etsy_delivery_png(
                master,
                max_file_bytes=1_000_000,
                min_dimension=0,
            )

        for bad_step in (0.79, 1.0, 1.1):
            with self.subTest(resize_step=bad_step):
                with self.assertRaisesRegex(ValueError, "resize_step"):
                    create_etsy_delivery_png(
                        master,
                        max_file_bytes=1_000_000,
                        min_dimension=10,
                        resize_step=bad_step,
                    )


if __name__ == "__main__":
    unittest.main()
