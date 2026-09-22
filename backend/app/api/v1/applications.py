"""The core applications API (Phase 6): intake, listing, full result,
document streaming, human override, and the adverse-action notice. Every
document is served only through this authenticated API (CLAUDE.md: no public
URLs), and Aadhaar/PAN/phone never appear in any response here -- Applicant
itself has no raw column for any of the three (see db/models.py), only the
hashed/masked forms `_intake_applicant()` below computes.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import CurrentUser, require_roles
from app.core.config import settings
from app.core.consent import get_consent_document
from app.core.logging import get_logger
from app.core.security import hmac_sha256_hex, mask_pan, phone_last4
from app.db.models import (
    Applicant,
    Application,
    DecisionArtifact,
    Document,
    FraudFinding,
    HistoricalBorrower,
    PrecedentMatch,
    ScorecardResult,
)
from app.db.session import async_session_factory, get_session
from app.pipeline import process_application
from app.schemas.applications import (
    ApplicationDetail,
    ApplicationListResponse,
    ApplicationSummary,
    ConsentMetaResponse,
    DocumentSummary,
    KYCIntake,
    OverrideRequest,
    PrecedentMatchOut,
    PrecedentPanel,
    WithdrawConsentResponse,
)
from app.schemas.explain import SummaryResult
from app.schemas.fraud import DocumentRadar, FraudReport, GraphEdge
from app.schemas.scoring import (
    AdverseActionNotice,
    Decision,
    RecourseAction,
    SanitizationReport,
    ScoreBreakdown,
    ScoreFactor,
)
from app.services.audit.service import append_event
from app.services.ingestion.storage import build_storage_backend, object_key
from app.services.ingestion.validation import (
    ALLOWED_MIME,
    UploadValidationError,
    sha256_hex,
    validate_csv_hardened,
    validate_extension,
    validate_image_content,
    validate_magic_bytes,
    validate_mime,
    validate_size,
)
from app.services.scoring.decision import load_policy
from app.services.scoring.recourse import recommend_recourse

router = APIRouter(prefix="/api/v1/applications", tags=["applications"])
logger = get_logger(__name__)

_read_roles = require_roles("underwriter", "auditor", "admin")
_write_roles = require_roles("underwriter", "admin")

_DOC_FIELD_TYPES = (
    ("gig_payout", "GIG_PAYOUT"),
    ("utility_bill", "UTILITY_BILL"),
    ("bank_statement", "BANK_STATEMENT"),
)


def _mask_applicant_reference(applicant_id: uuid.UUID) -> str:
    s = str(applicant_id)
    return f"APP-{s[:4]}...{s[-4:]}"


def _validate_and_check(doc_type: str, filename: str, data: bytes) -> str:
    ext = validate_extension(doc_type, filename)
    validate_size(data, settings.max_upload_bytes)
    validate_magic_bytes(doc_type, ext, data)
    if doc_type == "BANK_STATEMENT":
        validate_csv_hardened(data.decode("utf-8", errors="replace"))
    elif ext != ".pdf":
        validate_image_content(data)
    return ext


async def _run_pipeline_background(application_id: uuid.UUID) -> None:
    """process_application() already persists stage=FAILED + error_code on
    any exception (see pipeline.py) -- this wrapper only stops that exception
    from propagating further into FastAPI's BackgroundTasks runner, which
    would otherwise just log it to stderr with no application-level context."""
    async with async_session_factory() as session:
        storage = build_storage_backend(settings)
        try:
            await process_application(application_id, session, storage, settings)
        except Exception:
            logger.exception("pipeline_background_task_failed", application_id=str(application_id))


@router.post("", status_code=202)
async def create_application(
    background_tasks: BackgroundTasks,
    kyc: str = Form(...),
    gig_payout: UploadFile | None = File(None),
    utility_bill: UploadFile | None = File(None),
    bank_statement: UploadFile | None = File(None),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(_write_roles),
) -> dict[str, str]:
    try:
        kyc_data = KYCIntake.model_validate(json.loads(kyc))
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(422, f"invalid kyc payload: {exc}") from exc
    active_consent = get_consent_document()
    if not kyc_data.consent_accepted:
        raise HTTPException(422, "consent_accepted must be true to submit an application")
    if kyc_data.consent_text_version != active_consent.version:
        raise HTTPException(
            422,
            f"stale or invalid consent_text_version {kyc_data.consent_text_version!r}; "
            f"active version is {active_consent.version!r}",
        )

    uploads = {
        "GIG_PAYOUT": gig_payout,
        "UTILITY_BILL": utility_bill,
        "BANK_STATEMENT": bank_statement,
    }
    if not any(uploads.values()):
        raise HTTPException(422, "at least one document must be submitted")

    now = datetime.now(UTC)
    applicant = Applicant(
        name=kyc_data.full_name,
        phone_hash=hmac_sha256_hex(kyc_data.phone, settings.hmac_pepper),
        phone_last4=phone_last4(kyc_data.phone),
        pan_hash=hmac_sha256_hex(kyc_data.pan, settings.hmac_pepper),
        pan_masked=mask_pan(kyc_data.pan),
        aadhaar_hash=hmac_sha256_hex(kyc_data.aadhaar, settings.hmac_pepper),
        declared_address=kyc_data.declared_address,
        stated_vocation=kyc_data.stated_vocation,
        consent_at=now,
        consent_text_version=kyc_data.consent_text_version,
        consent_text_sha256=active_consent.sha256,
    )
    session.add(applicant)
    await session.flush()

    application = Application(
        applicant_id=applicant.id, requested_line_inr=kyc_data.requested_line_inr
    )
    session.add(application)
    await session.flush()

    storage = build_storage_backend(settings)
    doc_types_submitted: list[str] = []
    try:
        for doc_type, upload in uploads.items():
            if upload is None:
                continue
            data = await upload.read()
            ext = _validate_and_check(doc_type, upload.filename or "", data)
            mime = upload.content_type or sorted(ALLOWED_MIME[doc_type])[0]
            validate_mime(doc_type, mime)
            key = object_key(application.id, upload.filename or f"doc{ext}")
            await storage.put(key, data, mime)
            session.add(
                Document(
                    application_id=application.id,
                    doc_type=doc_type,
                    storage_key=key,
                    sha256=sha256_hex(data),
                    mime=mime,
                    size_bytes=len(data),
                )
            )
            doc_types_submitted.append(doc_type)
    except UploadValidationError as exc:
        await session.rollback()
        raise HTTPException(422, str(exc)) from exc

    await session.commit()
    await append_event(
        session,
        event_type="APPLICATION_SUBMITTED",
        actor=user.email,
        application_id=str(application.id),
        applicant_id=str(applicant.id),
        payload={
            "requested_line_inr": kyc_data.requested_line_inr,
            "docs_submitted": doc_types_submitted,
            "consent_at": now.isoformat(),
            "consent_text_version": kyc_data.consent_text_version,
            "consent_text_sha256": active_consent.sha256,
        },
    )
    await session.commit()

    background_tasks.add_task(_run_pipeline_background, application.id)
    return {"id": str(application.id)}


@router.get("", response_model=ApplicationListResponse)
async def list_applications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    _user: CurrentUser = Depends(_read_roles),
) -> ApplicationListResponse:
    total = await session.scalar(select(func.count()).select_from(Application))
    rows = (
        await session.execute(
            select(Application, Applicant)
            .join(Applicant, Applicant.id == Application.applicant_id)
            .order_by(Application.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    items = [
        ApplicationSummary(
            id=app_row.id,
            applicant_reference=_mask_applicant_reference(applicant_row.id),
            requested_line_inr=float(app_row.requested_line_inr),
            eligible_line_inr=float(app_row.eligible_line_inr)
            if app_row.eligible_line_inr is not None
            else None,
            outcome=app_row.outcome,
            final_outcome=app_row.final_outcome,
            score=app_row.score,
            fraud_severity=app_row.fraud_severity,
            stage=app_row.stage,
            created_at=app_row.created_at,
        )
        for app_row, applicant_row in rows
    ]
    return ApplicationListResponse(items=items, total=total or 0, page=page, page_size=page_size)


async def _load_application_or_404(session: AsyncSession, application_id: uuid.UUID) -> Application:
    application = await session.get(Application, application_id)
    if application is None:
        raise HTTPException(404, "application not found")
    return application


def _fraud_report_from_db(
    findings: list[FraudFinding],
    documents: list[Document],
    authenticity_score: float | None,
    fraud_severity: str | None,
    applicant_id: uuid.UUID,
) -> FraudReport:
    doc_type_by_id = {d.id: d.doc_type for d in documents}
    findings_out = [
        {
            "check_name": f.check_name,
            "severity": f.severity,
            "penalty_points": f.penalty,
            "message": f.message,
            "evidence": f.evidence or {},
            "document_id": f.document_id,
        }
        for f in findings
    ]
    radars = [DocumentRadar(**d.forensic) for d in documents if d.forensic]
    graph_edges: list[GraphEdge] = []
    for f in findings:
        if (
            f.check_name != "phash_collision"
            or not f.evidence
            or "other_applicant_id" not in f.evidence
        ):
            continue
        graph_edges.append(
            GraphEdge(
                applicant_a=applicant_id,
                applicant_b=uuid.UUID(f.evidence["other_applicant_id"]),
                doc_type=doc_type_by_id.get(f.document_id, "GIG_PAYOUT"),
                hamming_distance=f.evidence.get("hamming_distance", 0),
                sha256_match=f.evidence.get("sha256_match", False),
                corroborated=bool(
                    f.evidence.get("name_corroborated") or f.evidence.get("identifier_corroborated")
                )
                or f.severity == "HIGH",
            )
        )
    trust_score = round(authenticity_score * 100) if authenticity_score is not None else 100
    return FraudReport(
        findings=findings_out,
        per_document_radar=radars,
        trust_score=trust_score,
        authenticity_score=authenticity_score if authenticity_score is not None else 1.0,
        severity=fraud_severity or "NONE",
        graph_edges=graph_edges,
    )


@router.get("/{application_id}", response_model=ApplicationDetail)
async def get_application(
    application_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _user: CurrentUser = Depends(_read_roles),
) -> ApplicationDetail:
    application = await _load_application_or_404(session, application_id)
    applicant = await session.get(Applicant, application.applicant_id)
    if applicant is None:
        raise HTTPException(status_code=404, detail="Applicant record not found for application")

    documents = (
        (await session.execute(select(Document).where(Document.application_id == application_id)))
        .scalars()
        .all()
    )
    findings = (
        (
            await session.execute(
                select(FraudFinding).where(FraudFinding.application_id == application_id)
            )
        )
        .scalars()
        .all()
    )
    scorecard_row = await session.scalar(
        select(ScorecardResult).where(ScorecardResult.application_id == application_id)
    )
    precedent_rows = (
        await session.execute(
            select(PrecedentMatch, HistoricalBorrower)
            .join(HistoricalBorrower, HistoricalBorrower.id == PrecedentMatch.historical_id)
            .where(PrecedentMatch.application_id == application_id)
            .order_by(PrecedentMatch.rank)
        )
    ).all()
    artifacts = (
        (
            await session.execute(
                select(DecisionArtifact).where(DecisionArtifact.application_id == application_id)
            )
        )
        .scalars()
        .all()
    )
    decision_artifact = next((a for a in artifacts if a.kind == "decision"), None)
    summary_artifact = next((a for a in artifacts if a.kind == "summary"), None)
    notice_artifact = next((a for a in artifacts if a.kind == "notice"), None)
    precedent_signal_artifact = next((a for a in artifacts if a.kind == "precedent_signal"), None)

    authenticity_score = (
        (scorecard_row.features or {}).get("authenticity_score") if scorecard_row else None
    )
    fraud_report = _fraud_report_from_db(
        list(findings),
        list(documents),
        authenticity_score,
        application.fraud_severity,
        applicant.id,
    )

    score_breakdown = None
    recourse: list[RecourseAction] = []
    if scorecard_row is not None:
        factors = [ScoreFactor(**f) for f in scorecard_row.factors.get("items", [])]
        score_breakdown = ScoreBreakdown(
            version=scorecard_row.version,
            base=scorecard_row.base,
            total=scorecard_row.total,
            factors=factors,
            data_completeness=float(application.data_completeness)
            if application.data_completeness is not None
            else 0.0,
        )
        if application.outcome and application.outcome != "APPROVE":
            recourse = recommend_recourse(scorecard_row.features, score_breakdown)

    decision = Decision(**decision_artifact.content) if decision_artifact else None
    summary = SummaryResult(**summary_artifact.content) if summary_artifact else None
    notice = AdverseActionNotice(**notice_artifact.content) if notice_artifact else None

    sanitization_report = None
    if scorecard_row is not None:
        sanitization_report = SanitizationReport(
            removed=[], allowed=list(scorecard_row.features.keys())
        )  # the full removed-field list lives in the audit log (GUARDRAIL_APPLIED); see /audit

    precedents = None
    if precedent_rows and precedent_signal_artifact is not None:
        agrees = True
        if decision is not None:
            agrees = not any(
                ("two_signal:" in r or "TWO_SIGNAL_" in r)
                and ("downgraded" in r.lower() or "upgraded" in r.lower() or "TWO_SIGNAL_" in r)
                for r in decision.rules_fired
            )
        matches_out = [
            PrecedentMatchOut(
                historical_id=pm.historical_id,
                rank=pm.rank,
                similarity=float(pm.similarity),
                defaulted=hb.defaulted,
                cohort=hb.cohort,
            )
            for pm, hb in precedent_rows
        ]
        sig = precedent_signal_artifact.content
        precedents = PrecedentPanel(
            matches=matches_out,
            peer_default_rate=sig["peer_default_rate"],
            peer_default_rate_weighted=sig["peer_default_rate_weighted"],
            ci_lower=sig["ci_lower"],
            ci_upper=sig["ci_upper"],
            sample_size=sig["sample_size"],
            agrees_with_scorecard=agrees,
        )

    return ApplicationDetail(
        id=application.id,
        applicant_reference=_mask_applicant_reference(applicant.id),
        applicant_name=applicant.name,
        requested_line_inr=float(application.requested_line_inr),
        eligible_line_inr=float(application.eligible_line_inr)
        if application.eligible_line_inr is not None
        else None,
        status=application.status,
        stage=application.stage,
        error_code=application.error_code,
        outcome=application.outcome,
        final_outcome=application.final_outcome,
        overridden_by=application.overridden_by,
        override_reason=application.override_reason,
        score=application.score,
        fraud_severity=application.fraud_severity,
        data_completeness=float(application.data_completeness)
        if application.data_completeness is not None
        else None,
        scorecard_version=application.scorecard_version,
        policy_version=application.policy_version,
        created_at=application.created_at,
        completed_at=application.completed_at,
        documents=[
            DocumentSummary(
                id=d.id,
                doc_type=d.doc_type,
                mime=d.mime,
                extracted=d.extracted,
                extraction_confidence=float(d.extraction_confidence)
                if d.extraction_confidence is not None
                else None,
                extraction_model=d.extraction_model,
                forensic=d.forensic,
            )
            for d in documents
        ],
        fraud_report=fraud_report,
        sanitization_report=sanitization_report,
        score_breakdown=score_breakdown,
        decision=decision,
        precedents=precedents,
        recourse=recourse,
        summary=summary,
        notice=notice,
    )


@router.get("/{application_id}/documents/{document_id}/file")
async def get_document_file(
    application_id: uuid.UUID,
    document_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _user: CurrentUser = Depends(_read_roles),
) -> Response:
    document = await session.get(Document, document_id)
    if document is None or document.application_id != application_id:
        raise HTTPException(404, "document not found")
    storage = build_storage_backend(settings)
    data = await storage.get(document.storage_key)
    return Response(content=data, media_type=document.mime)


@router.get("/{application_id}/documents/{document_id}/overlay")
async def get_document_overlay(
    application_id: uuid.UUID,
    document_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _user: CurrentUser = Depends(_read_roles),
) -> Response:
    document = await session.get(Document, document_id)
    if document is None or document.application_id != application_id:
        raise HTTPException(404, "document not found")
    if not document.forensic or not document.forensic.get("heatmap_storage_key"):
        raise HTTPException(404, "no tamper-radar overlay for this document")
    storage = build_storage_backend(settings)
    data = await storage.get(document.forensic["heatmap_storage_key"])
    return Response(content=data, media_type="image/png")


@router.post("/{application_id}/override")
async def override_decision(
    application_id: uuid.UUID,
    body: OverrideRequest,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(_write_roles),
) -> dict[str, Any]:
    application = await _load_application_or_404(session, application_id)
    if body.outcome not in ("APPROVE", "REFER", "DECLINE"):
        raise HTTPException(422, "outcome must be one of APPROVE, REFER, DECLINE")

    system_outcome = application.outcome
    application.final_outcome = body.outcome
    application.overridden_by = uuid.UUID(user.id)
    application.override_reason = body.reason
    await append_event(
        session,
        event_type="DECISION_OVERRIDDEN",
        actor=user.email,
        application_id=str(application.id),
        applicant_id=str(application.applicant_id),
        payload={
            "system_outcome": system_outcome,
            "final_outcome": body.outcome,
            "reason": body.reason,
        },
    )
    await session.commit()
    return {
        "id": str(application.id),
        "system_outcome": system_outcome,
        "final_outcome": body.outcome,
    }


@router.get("/{application_id}/notice", response_model=AdverseActionNotice)
async def get_notice(
    application_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _user: CurrentUser = Depends(_read_roles),
) -> AdverseActionNotice:
    artifact = await session.scalar(
        select(DecisionArtifact).where(
            DecisionArtifact.application_id == application_id, DecisionArtifact.kind == "notice"
        )
    )
    if artifact is None:
        raise HTTPException(404, "no notice generated for this application yet")
    return AdverseActionNotice(**artifact.content)


@router.post("/{application_id}/withdraw-consent", response_model=WithdrawConsentResponse)
async def withdraw_consent(
    application_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(_write_roles),
) -> WithdrawConsentResponse:
    application = await session.get(Application, application_id)
    if application is None:
        raise HTTPException(404, "application not found")
    applicant = await session.get(Applicant, application.applicant_id)
    if applicant is None:
        raise HTTPException(404, "applicant not found")

    now = datetime.now(UTC)
    if applicant.consent_withdrawn_at is None:
        applicant.consent_withdrawn_at = now
        await append_event(
            session,
            event_type="CONSENT_WITHDRAWN",
            actor=user.email,
            application_id=str(application.id),
            applicant_id=str(applicant.id),
            payload={"withdrawn_at": now.isoformat()},
        )
        await session.commit()
    return WithdrawConsentResponse(
        id=application.id,
        application_id=application.id,
        consent_withdrawn=True,
        withdrawn_at=applicant.consent_withdrawn_at,
    )


meta_router = APIRouter(prefix="/api/v1/meta", tags=["meta"])


@meta_router.get("/consent", response_model=ConsentMetaResponse)
async def get_consent_meta() -> ConsentMetaResponse:
    doc = get_consent_document()
    return ConsentMetaResponse(text=doc.text, version=doc.version, sha256=doc.sha256)


@meta_router.get("/scorecard")
async def get_scorecard_meta(_user: CurrentUser = Depends(_read_roles)) -> dict[str, Any]:
    from app.services.scoring.scorecard import load_scorecard

    return {"scorecard": load_scorecard(), "policy": load_policy()}


fraud_router = APIRouter(prefix="/api/v1/fraud", tags=["fraud"])


@fraud_router.get("/graph")
async def get_fraud_graph(
    session: AsyncSession = Depends(get_session), _user: CurrentUser = Depends(_read_roles)
) -> dict[str, Any]:
    """Reconstructs the document-reuse graph from `phash_collision` findings
    already persisted in fraud_findings -- no separate graph table exists;
    every edge's corroboration evidence is already in `evidence` (see
    app/services/fraud/service.py's `_run_phash_check`)."""
    rows = (
        await session.execute(
            select(FraudFinding, Application, Document)
            .join(Application, Application.id == FraudFinding.application_id)
            .join(Document, Document.id == FraudFinding.document_id)
            .where(FraudFinding.check_name == "phash_collision")
        )
    ).all()
    edges = []
    for finding, application, document in rows:
        if not finding.evidence or "other_applicant_id" not in finding.evidence:
            continue
        edges.append(
            {
                "applicant_a": str(application.applicant_id),
                "applicant_b": finding.evidence["other_applicant_id"],
                "doc_type": document.doc_type,
                "hamming_distance": finding.evidence.get("hamming_distance"),
                "sha256_match": finding.evidence.get("sha256_match", False),
                "severity": finding.severity,
                "corroborated": bool(
                    finding.evidence.get("name_corroborated")
                    or finding.evidence.get("identifier_corroborated")
                )
                or finding.severity == "HIGH",
            }
        )
    return {"edges": edges}
