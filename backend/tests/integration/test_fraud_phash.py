import json
import uuid

import pytest
from PIL import Image, ImageDraw
from sqlalchemy import text

from app.services.fraud.phash import (
    bits_to_bitstring,
    compute_phash_bits,
    find_collision_candidates,
)

pytestmark = pytest.mark.integration


def _image(seed_text: str) -> Image.Image:
    img = Image.new("RGB", (400, 500), "white")
    d = ImageDraw.Draw(img)
    d.text((20, 20), seed_text, fill="black")
    d.rectangle([50, 200, 350, 400], outline="black", width=3)
    return img


async def _insert_document(
    session,
    *,
    applicant_name: str,
    doc_type: str,
    phash_bits: str,
    sha256: str,
    extracted: dict | None = None,
):
    applicant_id = uuid.uuid4()
    application_id = uuid.uuid4()
    document_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO applicants (id, name) VALUES (:id, :name)"),
        {"id": applicant_id, "name": applicant_name},
    )
    await session.execute(
        text(
            "INSERT INTO applications (id, applicant_id, requested_line_inr) "
            "VALUES (:id, :applicant_id, 10000)"
        ),
        {"id": application_id, "applicant_id": applicant_id},
    )
    await session.execute(
        text(
            "INSERT INTO documents "
            "(id, application_id, doc_type, storage_key, sha256, mime, "
            "size_bytes, phash, extracted) "
            "VALUES "
            "(:id, :application_id, :doc_type, 'test/key.jpg', :sha256, "
            "'image/jpeg', 100, :phash, :extracted)"
        ),
        {
            "id": document_id,
            "application_id": application_id,
            "doc_type": doc_type,
            "sha256": sha256,
            "phash": bits_to_bitstring(phash_bits),
            "extracted": json.dumps(extracted) if extracted else None,
        },
    )
    return applicant_id, application_id, document_id


@pytest.fixture
async def other_applicant_document(db_session):
    """A document belonging to a DIFFERENT applicant, already on file --
    the target of a collision query. Cleaned up via cascade delete."""
    image = _image("original document")
    phash_bits = compute_phash_bits(image)
    applicant_id, application_id, document_id = await _insert_document(
        db_session,
        applicant_name="Original Applicant",
        doc_type="UTILITY_BILL",
        phash_bits=phash_bits,
        sha256="a" * 64,
        extracted={"consumer_number": {"value": "CN-ORIGINAL"}},
    )
    await db_session.commit()
    yield {"applicant_id": applicant_id, "phash_bits": phash_bits, "image": image}
    await db_session.execute(text("DELETE FROM applicants WHERE id = :id"), {"id": applicant_id})
    await db_session.commit()


@pytest.mark.asyncio
async def test_near_duplicate_from_different_applicant_is_found(
    db_session, other_applicant_document
):
    query_bits = other_applicant_document["phash_bits"]  # identical image -> distance 0
    candidates = await find_collision_candidates(
        db_session,
        doc_type="UTILITY_BILL",
        query_phash_bits=query_bits,
        query_sha256="b" * 64,
        exclude_applicant_id=uuid.uuid4(),  # some other, unrelated applicant
        max_distance=10,
    )
    assert len(candidates) == 1
    assert candidates[0].hamming_distance == 0
    assert candidates[0].applicant_id == other_applicant_document["applicant_id"]


@pytest.mark.asyncio
async def test_same_applicant_own_document_is_excluded(db_session, other_applicant_document):
    query_bits = other_applicant_document["phash_bits"]
    candidates = await find_collision_candidates(
        db_session,
        doc_type="UTILITY_BILL",
        query_phash_bits=query_bits,
        query_sha256="b" * 64,
        exclude_applicant_id=other_applicant_document["applicant_id"],  # itself
        max_distance=10,
    )
    assert candidates == []


@pytest.mark.asyncio
async def test_unrelated_image_beyond_threshold_is_not_found(db_session, other_applicant_document):
    unrelated_image = Image.new("RGB", (400, 500), "black")  # very different from the fixture image
    unrelated_bits = compute_phash_bits(unrelated_image)
    from app.services.fraud.phash import hamming_distance

    assert hamming_distance(unrelated_bits, other_applicant_document["phash_bits"]) > 10

    candidates = await find_collision_candidates(
        db_session,
        doc_type="UTILITY_BILL",
        query_phash_bits=unrelated_bits,
        query_sha256="c" * 64,
        exclude_applicant_id=uuid.uuid4(),
        max_distance=10,
    )
    assert candidates == []


@pytest.mark.asyncio
async def test_exact_sha256_match_is_found_even_beyond_hamming_threshold(
    db_session, other_applicant_document
):
    # A different-looking image but a byte-identical file (sha256 match) must
    # still surface -- the query's OR condition, not just the Hamming distance.
    unrelated_image = Image.new("RGB", (400, 500), "black")
    unrelated_bits = compute_phash_bits(unrelated_image)
    from app.services.fraud.phash import hamming_distance

    assert hamming_distance(unrelated_bits, other_applicant_document["phash_bits"]) > 10

    candidates = await find_collision_candidates(
        db_session,
        doc_type="UTILITY_BILL",
        query_phash_bits=unrelated_bits,
        query_sha256="a" * 64,  # matches the fixture's own sha256
        exclude_applicant_id=uuid.uuid4(),
        max_distance=10,
    )
    assert len(candidates) == 1
    assert candidates[0].sha256_match is True


@pytest.mark.asyncio
async def test_different_doc_type_is_not_matched(db_session, other_applicant_document):
    query_bits = other_applicant_document["phash_bits"]
    candidates = await find_collision_candidates(
        db_session,
        doc_type="GIG_PAYOUT",  # fixture document is UTILITY_BILL
        query_phash_bits=query_bits,
        query_sha256="b" * 64,
        exclude_applicant_id=uuid.uuid4(),
        max_distance=10,
    )
    assert candidates == []
