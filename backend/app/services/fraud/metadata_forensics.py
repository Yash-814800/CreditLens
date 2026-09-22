"""Metadata forensics (CLAUDE.md Phase 4 check #4): does the file itself carry
an editing-tool fingerprint?

FALSE-POSITIVE RISK, stated honestly up front (per CLAUDE.md rule 4): plenty
of legitimate scanning/photo apps also stamp an EXIF Software tag or a PDF
Producer during entirely honest use, and a from-scratch synthetic render's
absence of any editor tag proves nothing either way. This check is therefore
never sufficient alone for a HIGH-severity finding (see fraud_policy_v1.yaml's
penalty for `metadata_suspicious`, deliberately smaller than a corroborated
pHash collision or an arithmetic violation) -- it is one corroborating signal
among several, exactly as CLAUDE.md's Inscribe-style multi-signal design
intends.
"""

from __future__ import annotations

import io
import uuid

import fitz  # PyMuPDF
from PIL import Image

from app.schemas.fraud import Finding


def _extract_exif_software(image_bytes: bytes) -> str | None:
    try:
        img = Image.open(io.BytesIO(image_bytes))
        exif = img.getexif()
    except Exception:
        return None
    value = exif.get(0x0131)  # EXIF "Software" tag
    return str(value) if value else None


def _extract_pdf_producer_creator(pdf_bytes: bytes) -> tuple[str | None, str | None]:
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            meta = doc.metadata or {}
            return meta.get("producer") or None, meta.get("creator") or None
        finally:
            doc.close()
    except Exception:
        return None, None


def check_metadata(
    *, file_bytes: bytes, mime: str, policy: dict, document_id: uuid.UUID | None = None
) -> Finding | None:
    suspicious_tags: list[str] = policy["metadata"]["suspicious_software_tags"]

    tag_value: str | None = None
    source_field: str | None = None
    if mime in ("image/jpeg", "image/jpg"):
        tag_value = _extract_exif_software(file_bytes)
        source_field = "EXIF Software"
    elif mime == "application/pdf":
        producer, creator = _extract_pdf_producer_creator(file_bytes)
        tag_value = producer or creator
        source_field = "PDF Producer/Creator"
    else:
        return None  # PNG and other formats carry no comparable tag we check here

    if not tag_value:
        return None

    matched = next((tag for tag in suspicious_tags if tag.lower() in tag_value.lower()), None)
    if not matched:
        return None

    return Finding(
        check_name="metadata_forensics",
        severity="LOW",
        penalty_points=policy["penalties"]["metadata_suspicious"],
        message=(
            f"{source_field} metadata references a known editing tool "
            f"({tag_value!r}). Not conclusive on its own -- see check documentation."
        ),
        evidence={"field": source_field, "value": tag_value, "matched_tool": matched},
        document_id=document_id,
    )
