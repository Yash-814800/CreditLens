import io

import pytest
from PIL import Image

from app.services.extraction.rasterize import MAX_LONG_SIDE_PX, rasterize_to_image_bytes
from tests.paths import SYNTH_DIR

pytestmark = pytest.mark.unit

SYNTH_UTILITY_PDFS = sorted((SYNTH_DIR / "documents" / "utility_bill" / "clean").glob("*.pdf"))


class TestImageRasterization:
    def test_small_image_passes_through_unscaled(self):
        img = Image.new("RGB", (200, 100), "red")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        out = rasterize_to_image_bytes(buf.getvalue(), "image/png")
        result = Image.open(io.BytesIO(out))
        assert result.size == (200, 100)
        assert result.format == "JPEG"

    def test_oversized_image_is_downscaled(self):
        img = Image.new("RGB", (4000, 1000), "blue")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        out = rasterize_to_image_bytes(buf.getvalue(), "image/png")
        result = Image.open(io.BytesIO(out))
        assert max(result.size) == MAX_LONG_SIDE_PX
        assert result.size[1] == round(1000 * MAX_LONG_SIDE_PX / 4000)


@pytest.mark.skipif(
    not SYNTH_UTILITY_PDFS, reason="data/synth corpus not generated (run `make datagen`)"
)
class TestPdfRasterization:
    def test_pdf_first_page_rasterizes_to_jpeg(self):
        pdf_bytes = SYNTH_UTILITY_PDFS[0].read_bytes()
        out = rasterize_to_image_bytes(pdf_bytes, "application/pdf")
        result = Image.open(io.BytesIO(out))
        assert result.format == "JPEG"
        assert result.width > 0 and result.height > 0
