"""End-to-end run_fraud_checks() tests against real persona/corpus documents
and a real Postgres pHash query (CLAUDE.md Phase 4 DONE WHEN: P05 then P06
yields a HIGH collision finding on P06 with evidence; P01 yields NONE/LOW;
a same-template hard-negative pair does not yield HIGH).
"""

import csv
import hashlib
import json
import uuid

import pytest
from sqlalchemy import text

from app.services.extraction.llm_client import build_extraction_from_truth
from app.services.extraction.rasterize import load_original_image
from app.services.fraud.phash import bits_to_bitstring, compute_phash_bits
from app.services.fraud.policy import load_fraud_policy
from app.services.fraud.service import FraudCheckContext, FraudDocumentInput, run_fraud_checks
from app.services.ingestion.bank_parser import parse_bank_csv
from app.services.ingestion.storage import LocalStorage
from tests.paths import DEMO_PACK, SYNTH_DIR

pytestmark = pytest.mark.integration


def _persona_file(persona: str, glob: str):
    return next(
        p for p in (DEMO_PACK / persona).glob(f"{glob}.*") if not p.name.endswith(".truth.json")
    )


def _persona_truth(persona: str, glob: str) -> dict:
    matches = list((DEMO_PACK / persona).glob(f"{glob}.*.truth.json"))
    return json.loads(matches[0].read_text())


def _mime_for(path) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".pdf": "application/pdf",
        ".csv": "text/csv",
    }[path.suffix.lower()]


def _kyc(persona: str) -> dict:
    return json.loads((DEMO_PACK / persona / "kyc.json").read_text())


async def _insert_persona_document(
    session, *, applicant_name: str, doc_type: str, path, extracted: dict
):
    data = path.read_bytes()
    mime = _mime_for(path)
    image = load_original_image(data, mime)
    phash_bits = compute_phash_bits(image)
    sha256 = hashlib.sha256(data).hexdigest()

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
            "(:id, :application_id, :doc_type, 'test/key', :sha256, "
            ":mime, :size, :phash, :extracted)"
        ),
        {
            "id": document_id,
            "application_id": application_id,
            "doc_type": doc_type,
            "sha256": sha256,
            "mime": mime,
            "size": len(data),
            "phash": bits_to_bitstring(phash_bits),
            "extracted": json.dumps(extracted),
        },
    )
    return applicant_id


def _build_doc_input(persona: str, doc_type: str, glob: str) -> FraudDocumentInput:
    path = _persona_file(persona, glob)
    data = path.read_bytes()
    mime = _mime_for(path)
    if doc_type == "BANK_STATEMENT":
        parsed = parse_bank_csv(data.decode())
    else:
        truth = _persona_truth(persona, glob)
        parsed = build_extraction_from_truth(doc_type, truth["visible_fields"])
    return FraudDocumentInput(
        document_id=uuid.uuid4(),
        doc_type=doc_type,
        mime=mime,
        file_bytes=data,
        sha256=hashlib.sha256(data).hexdigest(),
        parsed=parsed,
        extraction_confidence=1.0,
    )


@pytest.fixture
def local_storage(tmp_path):
    return LocalStorage(root=tmp_path / "fraud_test_storage")


@pytest.fixture
def policy():
    return load_fraud_policy()


@pytest.mark.asyncio
async def test_p06_utility_bill_collides_with_p05_on_file(db_session, local_storage, policy):
    """P06's utility bill visibly carries P05's identity (a copy-move reuse of
    P05's real document) -- this is the syndicate-ring collision demo."""
    p05_path = _persona_file("P05", "utility_bill")
    p05_truth = _persona_truth("P05", "utility_bill")
    p05_extraction = build_extraction_from_truth("UTILITY_BILL", p05_truth["visible_fields"])
    p05_applicant_id = await _insert_persona_document(
        db_session,
        applicant_name=_kyc("P05")["full_name"],
        doc_type="UTILITY_BILL",
        path=p05_path,
        extracted=p05_extraction.model_dump(),
    )
    await db_session.commit()

    try:
        p06_kyc = _kyc("P06")
        ctx = FraudCheckContext(
            application_id=uuid.uuid4(),
            applicant_id=uuid.uuid4(),
            applicant_name=p06_kyc["full_name"],
            documents=[_build_doc_input("P06", "UTILITY_BILL", "utility_bill")],
            declared_address=p06_kyc["declared_address"],
            stated_vocation=p06_kyc["stated_vocation"],
        )
        report = await run_fraud_checks(db_session, local_storage, ctx, policy=policy)

        assert report.severity == "HIGH"
        collision_findings = [f for f in report.findings if f.check_name == "phash_collision"]
        assert any(f.severity == "HIGH" for f in collision_findings)
        high_finding = next(f for f in collision_findings if f.severity == "HIGH")
        assert high_finding.evidence["other_applicant_id"] == str(p05_applicant_id)
        assert report.graph_edges and any(e.corroborated for e in report.graph_edges)
    finally:
        await db_session.execute(
            text("DELETE FROM applicants WHERE id = :id"), {"id": p05_applicant_id}
        )
        await db_session.commit()


@pytest.mark.asyncio
async def test_p01_clean_applicant_is_not_high_severity(db_session, local_storage, policy):
    kyc = _kyc("P01")
    docs = [
        _build_doc_input("P01", "GIG_PAYOUT", "gig_payout"),
        _build_doc_input("P01", "UTILITY_BILL", "utility_bill"),
        _build_doc_input("P01", "BANK_STATEMENT", "bank_statement"),
    ]
    ctx = FraudCheckContext(
        application_id=uuid.uuid4(),
        applicant_id=uuid.uuid4(),
        applicant_name=kyc["full_name"],
        documents=docs,
        declared_address=kyc["declared_address"],
        stated_vocation=kyc["stated_vocation"],
    )
    report = await run_fraud_checks(db_session, local_storage, ctx, policy=policy)
    assert report.severity in ("NONE", "LOW")
    assert not any(f.severity == "HIGH" for f in report.findings)


@pytest.mark.asyncio
@pytest.mark.skipif(
    not (SYNTH_DIR / "manifest.csv").exists(),
    reason="data/synth corpus not generated (run `make datagen`)",
)
async def test_same_template_hard_negative_is_not_high(db_session, local_storage, policy):
    """Two DIFFERENT applicants' legitimate bills from the same utility
    template (this corpus's hard-negative fixture) must not reach HIGH --
    CLAUDE.md Phase 4's explicit false-positive-risk requirement."""
    rows = list(csv.DictReader((SYNTH_DIR / "manifest.csv").open()))

    hard_negatives = [r for r in rows if r["hard_negative_group"] and r["split"] == "test"]
    assert len(hard_negatives) >= 2
    row_a, row_b = hard_negatives[0], hard_negatives[1]

    def _resolve(row):
        return SYNTH_DIR / "documents" / "utility_bill" / "clean" / row["filename"]

    path_a, path_b = _resolve(row_a), _resolve(row_b)
    truth_a = json.loads(path_a.with_name(path_a.name + ".truth.json").read_text())
    truth_b = json.loads(path_b.with_name(path_b.name + ".truth.json").read_text())
    extraction_a = build_extraction_from_truth("UTILITY_BILL", truth_a["visible_fields"])

    applicant_a_id = await _insert_persona_document(
        db_session,
        applicant_name=truth_a["visible_fields"]["consumer_name"],
        doc_type="UTILITY_BILL",
        path=path_a,
        extracted=extraction_a.model_dump(),
    )
    await db_session.commit()

    try:
        extraction_b = build_extraction_from_truth("UTILITY_BILL", truth_b["visible_fields"])
        data_b = path_b.read_bytes()
        ctx = FraudCheckContext(
            application_id=uuid.uuid4(),
            applicant_id=uuid.uuid4(),
            applicant_name=truth_b["visible_fields"]["consumer_name"],  # own name matches own bill
            documents=[
                FraudDocumentInput(
                    document_id=uuid.uuid4(),
                    doc_type="UTILITY_BILL",
                    mime=_mime_for(path_b),
                    file_bytes=data_b,
                    sha256=hashlib.sha256(data_b).hexdigest(),
                    parsed=extraction_b,
                    extraction_confidence=1.0,
                )
            ],
        )
        report = await run_fraud_checks(db_session, local_storage, ctx, policy=policy)
        assert report.severity != "HIGH"
        assert not any(
            f.check_name == "phash_collision" and f.severity == "HIGH" for f in report.findings
        )
    finally:
        await db_session.execute(
            text("DELETE FROM applicants WHERE id = :id"), {"id": applicant_a_id}
        )
        await db_session.commit()


@pytest.mark.asyncio
async def test_run_fraud_checks_is_idempotent(db_session, local_storage, policy):
    kyc = _kyc("P01")
    ctx = FraudCheckContext(
        application_id=uuid.uuid4(),
        applicant_id=uuid.uuid4(),
        applicant_name=kyc["full_name"],
        documents=[_build_doc_input("P01", "UTILITY_BILL", "utility_bill")],
        declared_address=kyc["declared_address"],
        stated_vocation=kyc["stated_vocation"],
    )
    report1 = await run_fraud_checks(db_session, local_storage, ctx, policy=policy)
    report2 = await run_fraud_checks(db_session, local_storage, ctx, policy=policy)
    assert report1.trust_score == report2.trust_score
    assert report1.severity == report2.severity
    assert len(report1.findings) == len(report2.findings)
