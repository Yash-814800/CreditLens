"""Turn an uploaded document's raw bytes into a single RGB image ready to send
to the vision model: PDFs are rasterised (PyMuPDF), oversized images are
downscaled, and everything is re-encoded as JPEG to keep the payload small."""

from __future__ import annotations

import io

import fitz  # PyMuPDF
from PIL import Image

RASTER_DPI = 200
MAX_PDF_PAGES = 2
MAX_LONG_SIDE_PX = 2048
JPEG_QUALITY = 88


def rasterize_to_image_bytes(data: bytes, mime: str) -> bytes:
    """Returns JPEG bytes of a single representative page/image, downscaled to
    at most MAX_LONG_SIDE_PX on the long side, ready for base64 encoding."""
    if mime == "application/pdf":
        image = _rasterize_pdf_first_page(data)
    else:
        image = Image.open(io.BytesIO(data))
        image.load()

    image = image.convert("RGB")
    image = _downscale(image, MAX_LONG_SIDE_PX)

    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()


def load_original_image(data: bytes, mime: str) -> Image.Image:
    """Returns the document's first page/image at its ORIGINAL resolution and
    without the JPEG re-encode that rasterize_to_image_bytes() applies for the
    vision model. Phase 4's forensics (ELA, noise-residual, pHash) need the
    document's actual compression history, not a freshly re-compressed copy of
    it -- re-encoding here would erase exactly the artifact ELA is looking for."""
    if mime == "application/pdf":
        return _rasterize_pdf_first_page(data).convert("RGB")
    image = Image.open(io.BytesIO(data))
    image.load()
    return image.convert("RGB")


def _rasterize_pdf_first_page(data: bytes) -> Image.Image:
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        if doc.page_count == 0:
            raise ValueError("PDF has no pages")
        page = doc.load_page(
            0
        )  # first of at most MAX_PDF_PAGES considered; we only need page 1's content
        zoom = RASTER_DPI / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        return Image.open(io.BytesIO(pixmap.tobytes("png")))
    finally:
        doc.close()


def _downscale(image: Image.Image, max_long_side: int) -> Image.Image:
    long_side = max(image.width, image.height)
    if long_side <= max_long_side:
        return image
    scale = max_long_side / long_side
    new_size = (round(image.width * scale), round(image.height * scale))
    return image.resize(new_size, Image.LANCZOS)
