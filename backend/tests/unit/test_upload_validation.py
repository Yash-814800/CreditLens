import io

import pytest
from PIL import Image

from app.services.ingestion.storage import object_key
from app.services.ingestion.validation import (
    MAX_IMAGE_PIXELS,
    UploadValidationError,
    sha256_hex,
    validate_csv_hardened,
    validate_extension,
    validate_image_content,
    validate_magic_bytes,
    validate_mime,
    validate_size,
)

pytestmark = pytest.mark.unit


def _png_bytes(size: tuple[int, int] = (10, 10)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "red").save(buf, format="PNG")
    return buf.getvalue()


class TestExtensionAndMime:
    def test_gig_payout_accepts_png(self):
        assert validate_extension("GIG_PAYOUT", "screenshot.png") == ".png"

    def test_bank_statement_rejects_png(self):
        with pytest.raises(UploadValidationError):
            validate_extension("BANK_STATEMENT", "statement.png")

    def test_unknown_doc_type_rejects_everything(self):
        with pytest.raises(UploadValidationError):
            validate_extension("NOT_A_TYPE", "x.png")

    def test_mime_must_match_allowlist(self):
        with pytest.raises(UploadValidationError):
            validate_mime("GIG_PAYOUT", "application/pdf")
        validate_mime("GIG_PAYOUT", "image/png")


class TestSize:
    def test_empty_file_rejected(self):
        with pytest.raises(UploadValidationError):
            validate_size(b"", max_bytes=1000)

    def test_oversized_file_rejected(self):
        with pytest.raises(UploadValidationError):
            validate_size(b"x" * 100, max_bytes=50)

    def test_within_limit_ok(self):
        validate_size(b"x" * 50, max_bytes=50)


class TestMagicBytes:
    def test_fake_pdf_rejected(self):
        with pytest.raises(UploadValidationError):
            validate_magic_bytes("UTILITY_BILL", ".pdf", b"not really a pdf")

    def test_real_pdf_header_accepted(self):
        validate_magic_bytes("UTILITY_BILL", ".pdf", b"%PDF-1.4\n...")

    def test_fake_png_rejected(self):
        with pytest.raises(UploadValidationError):
            validate_magic_bytes("GIG_PAYOUT", ".png", b"\x00\x00\x00")

    def test_real_png_accepted(self):
        validate_magic_bytes("GIG_PAYOUT", ".png", _png_bytes())


class TestImageContent:
    def test_valid_image_passes(self):
        validate_image_content(_png_bytes())

    def test_truncated_image_rejected(self):
        with pytest.raises(UploadValidationError):
            validate_image_content(_png_bytes()[:20])

    def test_huge_declared_dimensions_rejected(self, monkeypatch):
        # A crafted PNG header claiming an enormous size should be rejected by
        # the MAX_IMAGE_PIXELS guard rather than actually decoded.
        huge = Image.new("RGB", (1, 1))
        buf = io.BytesIO()
        huge.save(buf, format="PNG")
        # Directly exercise the guard logic: Pillow itself would refuse to
        # allocate a real huge image in a test, so assert the constant is wired
        # into validate_image_content via monkeypatching Image.MAX_IMAGE_PIXELS
        # to something the tiny fixture already exceeds.
        monkeypatch.setattr("app.services.ingestion.validation.MAX_IMAGE_PIXELS", 0)
        with pytest.raises(UploadValidationError):
            validate_image_content(_png_bytes((10, 10)))
        assert MAX_IMAGE_PIXELS == 40_000_000  # module constant itself unchanged


class TestShaAndKeys:
    def test_sha256_is_deterministic(self):
        data = b"hello world"
        assert sha256_hex(data) == sha256_hex(data)
        assert len(sha256_hex(data)) == 64

    def test_object_key_never_uses_client_filename(self):
        import uuid

        app_id = uuid.uuid4()
        key = object_key(app_id, "../../etc/passwd.png")
        assert "passwd" not in key
        assert "etc" not in key
        assert key.startswith(f"applications/{app_id}/")
        assert key.endswith(".png")


class TestCsvHardening:
    def _sample_csv(self) -> str:
        return (
            "account_holder,Test User\n"
            "account_number_masked,XXXXXXXX1234\n"
            "bank,Demo Sahakari Bank\n"
            "period_from,2026-01-01\n"
            "period_to,2026-01-03\n"
            "\n"
            "date,narration,ref,debit,credit,balance\n"
            "2026-01-01,ATM WDL,1,100.00,,900.00\n"
            "2026-01-02,SALARY,2,,500.00,1400.00\n"
        )

    def test_parses_metadata_and_rows(self):
        meta, rows = validate_csv_hardened(self._sample_csv())
        assert meta["account_holder"] == "Test User"
        assert len(rows) == 2
        assert rows[0]["narration"] == "ATM WDL"

    def test_formula_injection_neutralised(self):
        csv_text = self._sample_csv().replace("ATM WDL", "=cmd|'/c calc'!A1")
        meta, rows = validate_csv_hardened(csv_text)
        assert rows[0]["narration"].startswith("'=")

    def test_too_few_lines_rejected(self):
        with pytest.raises(UploadValidationError):
            validate_csv_hardened("just,one,line")

    def test_oversized_field_rejected(self):
        csv_text = self._sample_csv().replace("ATM WDL", "A" * 1000)
        with pytest.raises(UploadValidationError):
            validate_csv_hardened(csv_text)

    def test_too_many_rows_rejected(self, monkeypatch):
        monkeypatch.setattr("app.services.ingestion.validation.MAX_CSV_ROWS", 1)
        with pytest.raises(UploadValidationError):
            validate_csv_hardened(self._sample_csv())
