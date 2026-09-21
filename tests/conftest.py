from __future__ import annotations

import io

import pytest
from PIL import Image


@pytest.fixture
def png_bytes():
    def make(size=(10, 10), transparent=False):
        image = Image.new("RGBA", size, (20, 40, 60, 255))
        if transparent:
            image.putpixel((0, 0), (20, 40, 60, 0))
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()

    return make
