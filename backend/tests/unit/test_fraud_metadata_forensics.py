import io

import fitz  # PyMuPDF
import pytest
from PIL import Image

from app.services.fraud.metadata_forensics import check_metadata
from app.services.fraud.policy import load_fraud_policy

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def policy():
    return load_fraud_policy()


def _jpeg_bytes(*, software: str | None = None) -> bytes:
    img = Image.new("RGB", (100, 100), "white")
    buf = io.BytesIO()
    kwargs = {}
    if software is not None:
        exif = Image.Exif()
        exif[0x0131] = software
        kwargs["exif"] = exif
    img.save(buf, format="JPEG", quality=90, **kwargs)
    return buf.getvalue()


class TestMetadataForensics:
    def test_no_software_tag_is_not_flagged(self, policy):
        assert check_metadata(file_bytes=_jpeg_bytes(), mime="image/jpeg", policy=policy) is None

    def test_benign_software_tag_is_not_flagged(self, policy):
        assert (
            check_metadata(
                file_bytes=_jpeg_bytes(software="MyPhone Camera v3"),
                mime="image/jpeg",
                policy=policy,
            )
            is None
        )

    def test_known_editor_tag_is_flagged(self, policy):
        finding = check_metadata(
            file_bytes=_jpeg_bytes(software="Adobe Photoshop 25.0"),
            mime="image/jpeg",
            policy=policy,
        )
        assert finding is not None
        assert finding.severity == "LOW"
        assert finding.evidence["matched_tool"] == "Adobe Photoshop"

    def test_png_is_not_checked(self, policy):
        img = Image.new("RGB", (100, 100), "white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        assert check_metadata(file_bytes=buf.getvalue(), mime="image/png", policy=policy) is None

    def test_corrupt_image_bytes_do_not_raise(self, policy):
        assert (
            check_metadata(file_bytes=b"not a real image", mime="image/jpeg", policy=policy) is None
        )

    def test_corrupt_pdf_bytes_do_not_raise(self, policy):
        assert (
            check_metadata(file_bytes=b"not a real pdf", mime="application/pdf", policy=policy)
            is None
        )

    def _pdf_bytes(self, *, producer: str | None = None, creator: str | None = None) -> bytes:
        doc = fitz.open()
        doc.new_page()
        metadata = {}
        if producer is not None:
            metadata["producer"] = producer
        if creator is not None:
            metadata["creator"] = creator
        if metadata:
            doc.set_metadata(metadata)
        data = doc.tobytes()
        doc.close()
        return data

    def test_pdf_with_no_producer_or_creator_is_not_flagged(self, policy):
        result = check_metadata(file_bytes=self._pdf_bytes(), mime="application/pdf", policy=policy)
        assert result is None

    def test_pdf_benign_producer_is_not_flagged(self, policy):
        assert (
            check_metadata(
                file_bytes=self._pdf_bytes(producer="ReportLab PDF Library"),
                mime="application/pdf",
                policy=policy,
            )
            is None
        )

    def test_pdf_known_editor_producer_is_flagged(self, policy):
        finding = check_metadata(
            file_bytes=self._pdf_bytes(producer="Adobe Photoshop 25.0"),
            mime="application/pdf",
            policy=policy,
        )
        assert finding is not None
        assert finding.evidence["field"] == "PDF Producer/Creator"
        assert finding.evidence["matched_tool"] == "Adobe Photoshop"

    def test_pdf_falls_back_to_creator_when_producer_absent(self, policy):
        finding = check_metadata(
            file_bytes=self._pdf_bytes(creator="Adobe Photoshop 25.0"),
            mime="application/pdf",
            policy=policy,
        )
        assert finding is not None
        assert finding.evidence["value"] == "Adobe Photoshop 25.0"

    def test_unsupported_mime_is_not_checked(self, policy):
        assert check_metadata(file_bytes=b"1,2,3\n4,5,6\n", mime="text/csv", policy=policy) is None
