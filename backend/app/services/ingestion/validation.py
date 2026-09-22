"""Upload validation. CLAUDE.md: treat every uploaded document as untrusted
input. Every check here fails closed (raises) rather than best-effort-cleans,
so a rejected file never reaches extraction or storage.
"""

from __future__ import annotations

import hashlib
import io

from PIL import Image

# Reasonable per-doc-type allowlists derived from what datagen actually produces
# (Phase 2) and what Phase 3's extraction/parsing code actually handles.
ALLOWED_EXTENSIONS: dict[str, frozenset[str]] = {
    "GIG_PAYOUT": frozenset({".png", ".jpg", ".jpeg"}),
    "UTILITY_BILL": frozenset({".png", ".jpg", ".jpeg", ".pdf"}),
    "BANK_STATEMENT": frozenset({".csv"}),
}

ALLOWED_MIME: dict[str, frozenset[str]] = {
    "GIG_PAYOUT": frozenset({"image/png", "image/jpeg"}),
    "UTILITY_BILL": frozenset({"image/png", "image/jpeg", "application/pdf"}),
    "BANK_STATEMENT": frozenset({"text/csv", "application/vnd.ms-excel", "text/plain"}),
}

_PDF_MAGIC = b"%PDF-"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"

# Decompression-bomb guard: refuse to even decode an image above this many pixels.
MAX_IMAGE_PIXELS = 40_000_000  # ~40 megapixels; well above the ~1080x2400 screenshots we expect

MAX_CSV_ROWS = 5_000
MAX_CSV_FIELD_LEN = 500

# Characters that make a spreadsheet application (Excel/LibreOffice/Sheets)
# interpret a CSV cell as a formula -- CSV/formula-injection defense.
_FORMULA_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


class UploadValidationError(ValueError):
    """Raised for any upload that fails validation. Callers must translate this
    into a 4xx response, never a 500 -- see app/core/errors.py."""


def validate_extension(doc_type: str, filename: str) -> str:
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    allowed = ALLOWED_EXTENSIONS.get(doc_type, frozenset())
    if ext not in allowed:
        raise UploadValidationError(
            f"{doc_type} does not accept extension {ext or '(none)'}; allowed: {sorted(allowed)}"
        )
    return ext


def validate_mime(doc_type: str, mime: str) -> None:
    allowed = ALLOWED_MIME.get(doc_type, frozenset())
    if mime not in allowed:
        raise UploadValidationError(f"{doc_type} does not accept content-type {mime!r}")


def validate_size(data: bytes, max_bytes: int) -> None:
    if len(data) == 0:
        raise UploadValidationError("uploaded file is empty")
    if len(data) > max_bytes:
        raise UploadValidationError(f"file is {len(data)} bytes, exceeds limit of {max_bytes}")


def validate_magic_bytes(doc_type: str, ext: str, data: bytes) -> None:
    """Confirm the file's actual bytes match its claimed type -- a client can lie
    about extension/content-type, but can't cheaply fake the header bytes a
    trusted parser (Pillow/PyMuPDF) will insist on anyway."""
    if ext == ".pdf":
        if not data.startswith(_PDF_MAGIC):
            raise UploadValidationError("file claims .pdf but is missing the %PDF- header")
        return
    if ext == ".png":
        if not data.startswith(_PNG_MAGIC):
            raise UploadValidationError("file claims .png but is missing the PNG magic header")
        return
    if ext in (".jpg", ".jpeg"):
        if not data.startswith(_JPEG_MAGIC):
            raise UploadValidationError("file claims .jpg but is missing the JPEG magic header")
        return
    # .csv has no magic bytes to check; validate_csv_hardened() below does the
    # equivalent work of proving the content is actually parseable, safe CSV.


def validate_image_content(data: bytes) -> None:
    """Pillow's own `verify()` plus a decompression-bomb pixel-count guard.
    Raises UploadValidationError on anything that isn't a genuine, bounded
    image -- truncated files, zip bombs disguised as PNGs, polyglot files, etc.
    """
    original_max = Image.MAX_IMAGE_PIXELS
    try:
        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
    except Exception as exc:  # Pillow raises a variety of exception types here
        raise UploadValidationError(f"not a valid/safe image: {exc}") from exc
    finally:
        Image.MAX_IMAGE_PIXELS = original_max


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_csv_hardened(text: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Parse a bank-statement CSV defensively: bounded row/field counts, and
    formula-injection prefixes are neutralised (never executed -- this app never
    opens the file in a spreadsheet, but exported CSVs/JSON built from these
    values might end up pasted into one downstream, so we sanitise at the
    trust boundary rather than assume every consumer is safe).

    Returns (metadata, transaction_rows).
    """
    import csv as csv_module

    lines = text.splitlines()
    if len(lines) < 2:
        raise UploadValidationError("bank CSV has no transaction rows")

    # First block: `key,value` metadata lines up to the first blank line.
    meta: dict[str, str] = {}
    idx = 0
    for idx, line in enumerate(lines):  # noqa: B007 -- idx is used after the loop below
        if not line.strip():
            break
        parts = line.split(",", 1)
        if len(parts) == 2:
            meta[parts[0].strip()] = _sanitize_csv_field(parts[1].strip())
    else:
        raise UploadValidationError("bank CSV metadata block never terminates with a blank line")

    body_lines = lines[idx + 1 :]
    if not body_lines:
        raise UploadValidationError("bank CSV has a metadata block but no transaction table")
    if len(body_lines) - 1 > MAX_CSV_ROWS:  # -1 for the header row
        raise UploadValidationError(f"bank CSV has more than {MAX_CSV_ROWS} transaction rows")

    reader = csv_module.DictReader(body_lines)
    rows: list[dict[str, str]] = []
    for raw_row in reader:
        clean_row = {}
        for key, value in raw_row.items():
            if value is not None and len(value) > MAX_CSV_FIELD_LEN:
                raise UploadValidationError(f"CSV field {key!r} exceeds {MAX_CSV_FIELD_LEN} chars")
            clean_row[key] = _sanitize_csv_field(value or "")
        rows.append(clean_row)

    return meta, rows


def _sanitize_csv_field(value: str) -> str:
    if value and value[0] in _FORMULA_INJECTION_PREFIXES:
        return "'" + value  # neutralise: a leading apostrophe forces text interpretation
    return value
