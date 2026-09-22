"""Perceptual hashing + the Postgres bit-Hamming-distance query that finds
syndicate-ring document reuse across OTHER applicants (CLAUDE.md Phase 4).

Storage note: `documents.phash` is `BIT(256)` (imagehash.phash(hash_size=16)
== a 16x16 bit array == 256 bits). SQLAlchemy's asyncpg dialect binds BIT
parameters through asyncpg's own bit codec, which requires an
`asyncpg.BitString` (NOT a plain Python str) -- confirmed empirically before
writing this module (a bare str raises `TypeError: a bytes-like object is
required, not 'str'` deep inside asyncpg's protocol layer). Every function
here that touches the DB works in `asyncpg.BitString`; `str` (a flat 256-char
'0'/'1' string) is only used as a human-readable/serialisable form at the
boundary (JSON evidence payloads, test fixtures).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import asyncpg
import imagehash
from PIL import Image
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

PHASH_SIZE = 16  # -> 16*16 = 256 bits, matches documents.phash BIT(256)


def compute_phash_bits(image: Image.Image) -> str:
    """Returns the perceptual hash as a 256-character '0'/'1' string."""
    h = imagehash.phash(image, hash_size=PHASH_SIZE)
    return "".join("1" if bit else "0" for bit in h.hash.flatten())


def bits_to_bitstring(bits: str) -> asyncpg.BitString:
    return asyncpg.BitString.from_int(int(bits, 2), len(bits))


def bitstring_to_bits(value: asyncpg.BitString) -> str:
    return value.as_string().replace(" ", "")


def hamming_distance(a: str, b: str) -> int:
    if len(a) != len(b):
        raise ValueError(f"phash length mismatch: {len(a)} vs {len(b)}")
    return sum(x != y for x, y in zip(a, b, strict=True))


@dataclass(frozen=True)
class CollisionCandidate:
    document_id: uuid.UUID
    application_id: uuid.UUID
    applicant_id: uuid.UUID
    doc_type: str
    sha256: str
    extracted: dict | None
    hamming_distance: int
    sha256_match: bool


async def find_collision_candidates(
    session: AsyncSession,
    *,
    doc_type: str,
    query_phash_bits: str,
    query_sha256: str,
    exclude_applicant_id: uuid.UUID,
    max_distance: int,
) -> list[CollisionCandidate]:
    """Documents belonging to OTHER applicants (never the same applicant --
    an applicant re-uploading their own bill is not a syndicate signal) that
    are either byte-identical (sha256 match) or a near-duplicate image
    (Hamming distance <= max_distance) of the same doc_type, using real
    PostgreSQL bit ops (`#` = XOR, `bit_count` = popcount) so the comparison
    runs inside the database rather than pulling every document's phash back
    to Python."""
    query_bitstring = bits_to_bitstring(query_phash_bits)
    result = await session.execute(
        text(
            """
            SELECT
                d.id AS document_id,
                d.application_id AS application_id,
                a.applicant_id AS applicant_id,
                d.sha256 AS sha256,
                d.extracted AS extracted,
                bit_count(d.phash # :query_phash) AS hamming_distance
            FROM documents d
            JOIN applications a ON a.id = d.application_id
            WHERE d.doc_type = :doc_type
              AND d.phash IS NOT NULL
              AND a.applicant_id != :exclude_applicant_id
              AND (bit_count(d.phash # :query_phash) <= :max_distance OR d.sha256 = :sha256)
            ORDER BY hamming_distance ASC
            """
        ),
        {
            "query_phash": query_bitstring,
            "doc_type": doc_type,
            "exclude_applicant_id": exclude_applicant_id,
            "max_distance": max_distance,
            "sha256": query_sha256,
        },
    )
    return [
        CollisionCandidate(
            document_id=row.document_id,
            application_id=row.application_id,
            applicant_id=row.applicant_id,
            doc_type=doc_type,
            sha256=row.sha256,
            extracted=row.extracted,
            hamming_distance=row.hamming_distance,
            sha256_match=row.sha256 == query_sha256,
        )
        for row in result
    ]
