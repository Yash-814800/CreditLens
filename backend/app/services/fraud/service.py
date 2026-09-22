"""Orchestrator: `run_fraud_checks()` is the single entry point Phase 6's
pipeline calls into (CLAUDE.md Phase 4 output contract). Everything else in
this package is a building block this module composes into one FraudReport.

Design note on why this is async and takes a DB session + storage backend
(unlike the pure `scoring/features.py` and `scoring/scorecard.py` modules):
the pHash SYNDICATE check is inherently a cross-applicant DATABASE query (is
this image a near-duplicate of some OTHER applicant's document?), and the
tamper-radar heatmap is a generated artifact that has to be persisted
somewhere the UI (Phase 7) can stream it back from. Every individual check
function this module calls, though, stays pure and independently testable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from rapidfuzz import fuzz
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.extraction import GigPayoutExtraction, UtilityBillExtraction
from app.schemas.fraud import DocumentRadar, Finding, FraudReport, GraphEdge
from app.services.extraction.guardrails import MIN_CONFIDENCE_FOR_TRUST, GuardrailFinding
from app.services.extraction.rasterize import load_original_image
from app.services.fraud import cross_field, semantic_checks
from app.services.fraud.metadata_forensics import check_metadata
from app.services.fraud.phash import compute_phash_bits, find_collision_candidates
from app.services.fraud.policy import load_fraud_policy
from app.services.fraud.tamper_radar import run_tamper_radar
from app.services.ingestion.bank_parser import BankStatementData, account_last4
from app.services.ingestion.storage import StorageBackend, object_key

IMAGE_DOC_TYPES = ("GIG_PAYOUT", "UTILITY_BILL")  # the only doc types phash/tamper-radar apply to

# Mirrors pipeline.py's _IDENTITY_FAIL_CHECK_NAMES -- these two checks feed a
# SEPARATE, dedicated policy gate (decision.py's identity_check_status,
# derived in pipeline.py) that already caps the outcome at REFER (RC08) on
# its own. They are still recorded as ordinary Findings (evidence, UI, audit)
# and still carry their own fraud_policy_v1.yaml penalty for display, but are
# EXCLUDED from the trust_score/severity aggregate below.
#
# Found and fixed during Phase 6 verification: persona P07 (bill AND bank
# holder name mismatched vs KYC, PLUS a payout-account-last4 mismatch -- its
# own designed, documented scenario, see data/demo_pack/P07/expected.json)
# produced three legitimate MEDIUM findings whose combined penalty collapsed
# trust_score to 0, which _aggregate_severity then read as an overall HIGH
# severity -- and "fraud severity HIGH -> DECLINE" is evaluated BEFORE the
# identity gate in decision.py's rule order, so P07 was hard-DECLINEd instead
# of the persona's designed REFER. Document-authenticity signals (RC07: is
# this document forged/tampered/reused?) and identity-mismatch signals (RC08:
# does this document even belong to the applicant?) are answering different
# questions and are already routed to different reason codes and different
# policy gates -- letting one silently escalate into the other's hard-DECLINE
# path was the bug, not a case for re-tuning severity_bands' cutoffs (which
# would just move the same collision to a different combination of findings).
IDENTITY_CHECK_NAMES = frozenset({"cross_field_name", "cross_field_payout_account"})


@dataclass
class FraudDocumentInput:
    """Everything one document contributes to the fraud layer. `parsed` is a
    GigPayoutExtraction / UtilityBillExtraction / BankStatementData depending
    on doc_type -- callers build this from the same objects Phase 3's
    extraction/bank-parser services already produced, no re-parsing here."""

    document_id: uuid.UUID
    doc_type: str
    mime: str
    file_bytes: bytes
    sha256: str
    parsed: GigPayoutExtraction | UtilityBillExtraction | BankStatementData
    extraction_confidence: float | None = None
    guardrail_findings: list[GuardrailFinding] = field(default_factory=list)


@dataclass
class FraudCheckContext:
    application_id: uuid.UUID
    applicant_id: uuid.UUID
    applicant_name: str
    documents: list[FraudDocumentInput]
    declared_address: str | None = None
    stated_vocation: str | None = None
    # Computed by Phase 3's feature builder (app/services/scoring/features.py)
    # and passed in here -- the fraud layer judges it against a policy
    # threshold rather than recomputing bank/gig totals itself.
    income_reconciliation_ratio: float | None = None


def _guardrail_to_finding(gf: GuardrailFinding, policy: dict, document_id: uuid.UUID) -> Finding:
    if gf.check_name in ("prompt_injection_pattern", "model_flagged_instruction_text"):
        penalty_key = "injection_suspected"
    elif gf.check_name == "self_consistency_disagreement":
        penalty_key = "self_consistency_disagreement"
    else:
        penalty_key = "arithmetic_violation"

    return Finding(
        check_name=gf.check_name,
        severity=gf.severity,
        penalty_points=policy["penalties"].get(penalty_key, 15),
        message=gf.message,
        evidence=gf.evidence,
        document_id=document_id,
    )


def _low_confidence_finding(doc: FraudDocumentInput, policy: dict) -> Finding | None:
    if doc.extraction_confidence is None or doc.extraction_confidence >= MIN_CONFIDENCE_FOR_TRUST:
        return None
    return Finding(
        check_name="low_confidence_extraction",
        severity="LOW",
        penalty_points=policy["penalties"]["low_confidence_extraction"],
        message=(
            f"Extraction confidence ({doc.extraction_confidence:.2f}) is below the "
            f"trust threshold ({MIN_CONFIDENCE_FOR_TRUST}); some fields may be illegible."
        ),
        evidence={"extraction_confidence": doc.extraction_confidence},
        document_id=doc.document_id,
    )


async def _run_phash_check(
    session: AsyncSession,
    doc: FraudDocumentInput,
    ctx: FraudCheckContext,
    policy: dict,
) -> tuple[str, list[Finding], list[GraphEdge]]:
    """Returns (this document's own phash bits, findings, graph edges)."""
    image = load_original_image(doc.file_bytes, doc.mime)
    phash_bits = compute_phash_bits(image)

    near_dup_threshold = policy["phash"]["near_duplicate_threshold"]
    template_threshold = policy["phash"]["template_similarity_max_distance"]
    identifier_fields = policy["corroboration"]["identifier_fields"].get(doc.doc_type, [])
    name_corroboration_min = policy["corroboration"]["name_match_corroboration_min_score"]

    candidates = await find_collision_candidates(
        session,
        doc_type=doc.doc_type,
        query_phash_bits=phash_bits,
        query_sha256=doc.sha256,
        exclude_applicant_id=ctx.applicant_id,
        max_distance=template_threshold,
    )

    findings: list[Finding] = []
    edges: list[GraphEdge] = []
    own_holder_name = _holder_name(doc.parsed, doc.doc_type)
    own_identifiers = {f: _extracted_str(doc.parsed, f) for f in identifier_fields}

    for cand in candidates:
        near_duplicate = cand.sha256_match or cand.hamming_distance <= near_dup_threshold
        candidate_holder_name = _extracted_holder_name_from_dict(cand.extracted, doc.doc_type)
        name_corroborated = bool(
            own_holder_name
            and candidate_holder_name
            and fuzz.token_sort_ratio(own_holder_name, candidate_holder_name)
            >= name_corroboration_min
        )
        identifier_corroborated = any(
            own_identifiers.get(f)
            and cand.extracted
            and cand.extracted.get(f, {}).get("value") == own_identifiers.get(f)
            for f in identifier_fields
        )
        corroborated = name_corroborated or identifier_corroborated

        edges.append(
            GraphEdge(
                applicant_a=ctx.applicant_id,
                applicant_b=cand.applicant_id,
                doc_type=doc.doc_type,
                hamming_distance=cand.hamming_distance,
                sha256_match=cand.sha256_match,
                corroborated=corroborated,
            )
        )

        if near_duplicate and corroborated:
            findings.append(
                Finding(
                    check_name="phash_collision",
                    severity="HIGH",
                    penalty_points=policy["penalties"]["phash_high"],
                    message=(
                        "This document is a near-duplicate or byte-identical copy of a "
                        "document already on file for a DIFFERENT applicant, corroborated "
                        "by a matching identity signal -- consistent with a document-reuse "
                        "(syndicate) ring."
                    ),
                    evidence={
                        "other_applicant_id": str(cand.applicant_id),
                        "other_application_id": str(cand.application_id),
                        "other_document_id": str(cand.document_id),
                        "hamming_distance": cand.hamming_distance,
                        "sha256_match": cand.sha256_match,
                        "name_corroborated": name_corroborated,
                        "identifier_corroborated": identifier_corroborated,
                    },
                    document_id=doc.document_id,
                )
            )
        elif near_duplicate:
            findings.append(
                Finding(
                    check_name="phash_collision",
                    severity="MEDIUM",
                    penalty_points=policy["penalties"]["phash_medium"],
                    message=(
                        "This document is a near-duplicate of a document already on file "
                        "for a different applicant, but no corroborating identity match was "
                        "found -- may be a legitimate shared template."
                    ),
                    evidence={
                        "other_applicant_id": str(cand.applicant_id),
                        "other_application_id": str(cand.application_id),
                        "other_document_id": str(cand.document_id),
                        "hamming_distance": cand.hamming_distance,
                        "sha256_match": cand.sha256_match,
                    },
                    document_id=doc.document_id,
                )
            )
        else:
            findings.append(
                Finding(
                    check_name="phash_collision",
                    severity="LOW",
                    penalty_points=policy["penalties"]["phash_low_informational"],
                    message=(
                        "This document shares visual template similarity with another "
                        "applicant's document (e.g. the same utility's bill layout); "
                        "informational only."
                    ),
                    evidence={
                        "other_applicant_id": str(cand.applicant_id),
                        "other_application_id": str(cand.application_id),
                        "other_document_id": str(cand.document_id),
                        "hamming_distance": cand.hamming_distance,
                    },
                    document_id=doc.document_id,
                )
            )

    return phash_bits, findings, edges


def _holder_name(
    parsed: GigPayoutExtraction | UtilityBillExtraction | BankStatementData, doc_type: str
) -> str | None:
    if doc_type == "GIG_PAYOUT" and isinstance(parsed, GigPayoutExtraction):
        return parsed.partner_name.value
    if doc_type == "UTILITY_BILL" and isinstance(parsed, UtilityBillExtraction):
        return parsed.consumer_name.value
    return None


def _extracted_str(
    parsed: GigPayoutExtraction | UtilityBillExtraction | BankStatementData, field_name: str
) -> str | None:
    value = getattr(parsed, field_name, None)
    return value.value if value is not None else None


def _extracted_holder_name_from_dict(extracted: dict | None, doc_type: str) -> str | None:
    if not extracted:
        return None
    key = "partner_name" if doc_type == "GIG_PAYOUT" else "consumer_name"
    field = extracted.get(key)
    return field.get("value") if isinstance(field, dict) else None


async def run_fraud_checks(
    session: AsyncSession,
    storage: StorageBackend,
    ctx: FraudCheckContext,
    *,
    policy: dict | None = None,
) -> FraudReport:
    policy = policy or load_fraud_policy()

    findings: list[Finding] = []
    radars: list[DocumentRadar] = []
    graph_edges: list[GraphEdge] = []

    gig_payout = next((d for d in ctx.documents if d.doc_type == "GIG_PAYOUT"), None)
    bank_statement = next((d for d in ctx.documents if d.doc_type == "BANK_STATEMENT"), None)

    platform_names = (
        [gig_payout.parsed.platform_name.value]
        if gig_payout
        and isinstance(gig_payout.parsed, GigPayoutExtraction)
        and gig_payout.parsed.platform_name.value
        else []
    )
    bank_last4 = (
        account_last4(bank_statement.parsed.account_number_masked)
        if bank_statement and isinstance(bank_statement.parsed, BankStatementData)
        else None
    )
    payout_last4 = (
        gig_payout.parsed.payout_account_last4.value
        if gig_payout and isinstance(gig_payout.parsed, GigPayoutExtraction)
        else None
    )

    for doc in ctx.documents:
        for gf in doc.guardrail_findings:
            findings.append(_guardrail_to_finding(gf, policy, doc.document_id))
        low_conf = _low_confidence_finding(doc, policy)
        if low_conf:
            findings.append(low_conf)

        if doc.doc_type in IMAGE_DOC_TYPES:
            _, phash_findings, edges = await _run_phash_check(session, doc, ctx, policy)
            findings.extend(phash_findings)
            graph_edges.extend(edges)

            image = load_original_image(doc.file_bytes, doc.mime)
            radar, radar_finding, heatmap_bytes = run_tamper_radar(
                image, mime=doc.mime, policy=policy
            )
            radar.document_id = doc.document_id
            radar.doc_type = doc.doc_type
            if radar_finding:
                radar_finding.document_id = doc.document_id
                findings.append(radar_finding)
            heatmap_key = object_key(ctx.application_id, f"{doc.document_id}-heatmap.png")
            await storage.put(heatmap_key, heatmap_bytes, "image/png")
            radar.heatmap_storage_key = heatmap_key
            radars.append(radar)

            metadata_finding = check_metadata(
                file_bytes=doc.file_bytes, mime=doc.mime, policy=policy, document_id=doc.document_id
            )
            if metadata_finding:
                findings.append(metadata_finding)

        if doc.doc_type == "GIG_PAYOUT" and isinstance(doc.parsed, GigPayoutExtraction):
            findings.extend(
                semantic_checks.check_gig_payout(
                    doc.parsed, policy=policy, document_id=doc.document_id
                )
            )
            name_finding = cross_field.name_similarity_finding(
                label="KYC name vs. gig-payout partner name",
                name_a=ctx.applicant_name,
                name_b=doc.parsed.partner_name.value,
                policy=policy,
            )
            if name_finding:
                findings.append(name_finding)

        elif doc.doc_type == "UTILITY_BILL" and isinstance(doc.parsed, UtilityBillExtraction):
            findings.extend(
                semantic_checks.check_utility_bill(
                    doc.parsed, policy=policy, document_id=doc.document_id
                )
            )
            name_finding = cross_field.name_similarity_finding(
                label="KYC name vs. utility bill consumer name",
                name_a=ctx.applicant_name,
                name_b=doc.parsed.consumer_name.value,
                policy=policy,
            )
            if name_finding:
                findings.append(name_finding)
            address_finding = cross_field.address_similarity_finding(
                declared_address=ctx.declared_address,
                document_address=doc.parsed.service_address.value,
                policy=policy,
            )
            if address_finding:
                findings.append(address_finding)

        elif doc.doc_type == "BANK_STATEMENT" and isinstance(doc.parsed, BankStatementData):
            findings.extend(
                semantic_checks.check_bank_statement(
                    doc.parsed, policy=policy, document_id=doc.document_id
                )
            )
            name_finding = cross_field.name_similarity_finding(
                label="KYC name vs. bank account holder",
                name_a=ctx.applicant_name,
                name_b=doc.parsed.account_holder,
                policy=policy,
            )
            if name_finding:
                findings.append(name_finding)

    vocation_finding = cross_field.vocation_platform_finding(
        stated_vocation=ctx.stated_vocation, platform_names=platform_names, policy=policy
    )
    if vocation_finding:
        findings.append(vocation_finding)

    payout_mismatch = cross_field.payout_account_mismatch_finding(
        payout_account_last4=payout_last4, bank_account_last4=bank_last4, policy=policy
    )
    if payout_mismatch:
        findings.append(payout_mismatch)

    income_finding = cross_field.income_reconciliation_finding(
        income_reconciliation_ratio=ctx.income_reconciliation_ratio, policy=policy
    )
    if income_finding:
        findings.append(income_finding)

    scoring_penalty = sum(
        f.penalty_points for f in findings if f.check_name not in IDENTITY_CHECK_NAMES
    )
    trust_score = max(0, min(100, 100 - scoring_penalty))
    severity = _aggregate_severity(findings, trust_score, policy)

    return FraudReport(
        findings=findings,
        per_document_radar=radars,
        trust_score=trust_score,
        authenticity_score=round(trust_score / 100, 4),
        severity=severity,
        graph_edges=graph_edges,
    )


def _aggregate_severity(findings: list[Finding], trust_score: int, policy: dict) -> str:
    """Any single HIGH finding forces HIGH regardless of the numeric score
    (fraud_policy_v1.yaml's documented override: a corroborated collision or a
    blatant tamper should never be diluted by an otherwise-clean file).
    Deliberately NOT a symmetric override for MEDIUM findings: tamper_radar
    (see docs/fraud_eval.md) has a real, measured false-positive rate at its
    MEDIUM band on ordinary clean documents, so ONE isolated MEDIUM finding on
    an otherwise high-trust-score application must not by itself cap the
    whole application's severity -- the additive trust_score, which already
    reflects that finding's penalty proportionately, decides everything below
    HIGH."""
    bands = policy["severity_bands"]
    if any(f.severity == "HIGH" for f in findings):
        return "HIGH"
    if trust_score <= bands["high_max_trust_score"]:
        return "HIGH"
    if trust_score <= bands["medium_max_trust_score"]:
        return "MEDIUM"
    if any(f.severity in ("LOW", "MEDIUM") for f in findings):
        return "LOW"
    return "NONE"
