"""The end-to-end underwriting pipeline (Phase 6): the one place every prior
phase's service gets wired together into a single application's decision.

`process_application()` walks the exact Stage sequence CLAUDE.md's domain
contracts define (EXTRACTING -> FRAUD_CHECK -> SANITIZING -> SCORING ->
PRECEDENT_MATCH -> DECIDING -> SUMMARIZING -> COMPLETE), persisting the
`stage` column after every step (so a poller -- Phase 7's progress stepper --
can show live progress), and writing an audit event at each step. Any
exception anywhere leaves the application in stage=FAILED with an
`error_code` rather than a half-written decision -- CLAUDE.md's explicit
"never a half-written decision" requirement.

Idempotent by design: every stage that inserts child rows (fraud_findings,
scorecard_results, precedent_matches) deletes this application's existing
rows first, so re-running process_application() on the same application_id
(e.g. after a transient failure) never accumulates duplicates.

Run via FastAPI `BackgroundTasks` (see api/v1/applications.py) for this
hackathon-scoped single-node deployment. A real deployment would run this
as a worker consuming a real queue (SQS, per CLAUDE.md's AWS stack) so a
backend process restart can't silently drop an in-flight application --
documented here and in docs/deployment.md (Phase 9), not solved in this
phase.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.config import settings as default_settings
from app.db.models import (
    Applicant,
    Application,
    DecisionArtifact,
    Document,
    FraudFinding,
    ScorecardResult,
)
from app.schemas.extraction import EXTRACTION_SCHEMAS, GigPayoutExtraction, UtilityBillExtraction
from app.services.audit.service import append_event
from app.services.explain.adverse_action import build_adverse_action_notice
from app.services.explain.summary import generate_summary
from app.services.extraction.factory import build_extraction_service
from app.services.extraction.guardrails import GuardrailFinding
from app.services.extraction.rasterize import load_original_image
from app.services.extraction.truth_lookup import UnrecognizedMockDocument, lookup_truth_fields
from app.services.fraud.phash import bits_to_bitstring, compute_phash_bits
from app.services.fraud.policy import load_fraud_policy
from app.services.fraud.service import (
    IDENTITY_CHECK_NAMES,
    FraudCheckContext,
    FraudDocumentInput,
    run_fraud_checks,
)
from app.services.guardrails.sanitizer import sanitize
from app.services.ingestion.bank_parser import (
    BankStatementData,
    analyze_bank_statement,
    parse_bank_csv,
)
from app.services.ingestion.storage import StorageBackend
from app.services.scoring.decision import decide, load_policy
from app.services.scoring.features import build_features
from app.services.scoring.recourse import recommend_recourse
from app.services.scoring.scorecard import compute_score, load_scorecard
from app.services.vectors.embedder import embed_features
from app.services.vectors.precedents import find_precedents, persist_precedent_matches

log = structlog.get_logger(__name__)

IMAGE_DOC_TYPES = ("GIG_PAYOUT", "UTILITY_BILL")

# Cross-field findings that mean "the identity story doesn't line up" for the
# policy engine's identity_gate (app/services/scoring/decision.py) -- both are
# emitted at MEDIUM severity only on an actual mismatch, never on a borderline
# "warn" band (see app/services/fraud/cross_field.py). Single source of truth
# lives in fraud/service.py (IDENTITY_CHECK_NAMES) -- imported, not
# redeclared, since that module also excludes these same checks from the
# trust_score/severity aggregate for the reason documented there.
_IDENTITY_FAIL_CHECK_NAMES = IDENTITY_CHECK_NAMES


class PipelineError(RuntimeError):
    """Wraps any stage failure with a short, stable error_code for the
    `applications.error_code` column -- never a raw stack trace (CLAUDE.md's
    error-model discipline applies here too, not just at the API boundary)."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


@dataclass
class _ParsedDocument:
    document: Document
    parsed: GigPayoutExtraction | UtilityBillExtraction | BankStatementData
    extraction_confidence: float | None
    guardrail_findings: list[GuardrailFinding]


async def _set_stage(session: AsyncSession, application: Application, stage: str) -> None:
    application.stage = stage
    await session.commit()


async def _extracting_stage(
    session: AsyncSession,
    *,
    application: Application,
    documents: list[Document],
    storage: StorageBackend,
    settings: Settings,
) -> list[_ParsedDocument]:
    extraction_service = build_extraction_service(settings)
    parsed_docs: list[_ParsedDocument] = []

    for doc in documents:
        file_bytes = await storage.get(doc.storage_key)

        if doc.doc_type == "BANK_STATEMENT":
            stmt = parse_bank_csv(file_bytes.decode("utf-8"))
            doc.extracted = {
                "account_holder": stmt.account_holder,
                "account_number_masked": stmt.account_number_masked,
                "bank": stmt.bank,
                "period_from": stmt.period_from.isoformat(),
                "period_to": stmt.period_to.isoformat(),
                "transaction_count": len(stmt.transactions),
            }
            doc.extraction_confidence = 1.0
            doc.extraction_model = "deterministic_parser"
            parsed_docs.append(
                _ParsedDocument(
                    document=doc, parsed=stmt, extraction_confidence=1.0, guardrail_findings=[]
                )
            )
            await append_event(
                session,
                event_type="DOCUMENT_EXTRACTED",
                actor="pipeline",
                application_id=str(application.id),
                applicant_id=str(application.applicant_id),
                payload={"document_id": str(doc.id), "doc_type": doc.doc_type, "source": "parser"},
            )
            continue

        truth_fields = None
        if settings.mock_llm:
            try:
                truth_fields = lookup_truth_fields(doc.sha256)
            except UnrecognizedMockDocument as exc:
                raise PipelineError("EXTRACTION_MOCK_UNRECOGNIZED_DOCUMENT", str(exc)) from exc

        outcome = await extraction_service.extract_document(
            doc_type=doc.doc_type,
            file_bytes=file_bytes,
            mime=doc.mime,
            sha256=doc.sha256,
            truth_fields=truth_fields,
        )
        schema = EXTRACTION_SCHEMAS[doc.doc_type]
        parsed = schema.model_validate(outcome.data)

        image = load_original_image(file_bytes, doc.mime)
        phash_bits = compute_phash_bits(image)
        doc.phash = bits_to_bitstring(phash_bits)
        doc.extracted = outcome.data
        doc.extraction_confidence = outcome.extraction_confidence
        doc.extraction_model = outcome.model

        parsed_docs.append(
            _ParsedDocument(
                document=doc,
                parsed=parsed,
                extraction_confidence=outcome.extraction_confidence,
                guardrail_findings=outcome.findings,
            )
        )
        await append_event(
            session,
            event_type="DOCUMENT_EXTRACTED",
            actor="pipeline",
            application_id=str(application.id),
            applicant_id=str(application.applicant_id),
            payload={
                "document_id": str(doc.id),
                "doc_type": doc.doc_type,
                "source": outcome.source,
                "model": outcome.model,
                "prompt_version": outcome.prompt_version,
                "sampling_params": outcome.sampling_params,
                "extraction_confidence": outcome.extraction_confidence,
            },
        )

    await session.commit()
    return parsed_docs


def _find_parsed(parsed_docs: list[_ParsedDocument], doc_type: str) -> _ParsedDocument | None:
    return next((p for p in parsed_docs if p.document.doc_type == doc_type), None)


async def _fraud_check_stage(
    session: AsyncSession,
    storage: StorageBackend,
    *,
    application: Application,
    applicant: Applicant,
    parsed_docs: list[_ParsedDocument],
    income_reconciliation_ratio: float | None,
):
    fraud_policy = load_fraud_policy()
    doc_inputs = []
    for p in parsed_docs:
        file_bytes = await storage.get(p.document.storage_key)
        doc_inputs.append(
            FraudDocumentInput(
                document_id=p.document.id,
                doc_type=p.document.doc_type,
                mime=p.document.mime,
                file_bytes=file_bytes,
                sha256=p.document.sha256,
                parsed=p.parsed,
                extraction_confidence=p.extraction_confidence,
                guardrail_findings=p.guardrail_findings,
            )
        )

    ctx = FraudCheckContext(
        application_id=application.id,
        applicant_id=application.applicant_id,
        applicant_name=applicant.name,
        documents=doc_inputs,
        declared_address=applicant.declared_address,
        stated_vocation=applicant.stated_vocation,
        income_reconciliation_ratio=income_reconciliation_ratio,
    )
    report = await run_fraud_checks(session, storage, ctx, policy=fraud_policy)

    await session.execute(delete(FraudFinding).where(FraudFinding.application_id == application.id))
    for finding in report.findings:
        session.add(
            FraudFinding(
                application_id=application.id,
                document_id=finding.document_id,
                check_name=finding.check_name,
                severity=finding.severity,
                penalty=finding.penalty_points,
                evidence=finding.evidence,
                message=finding.message,
            )
        )

    radar_by_doc = {r.document_id: r for r in report.per_document_radar if r.document_id}
    for p in parsed_docs:
        radar = radar_by_doc.get(p.document.id)
        if radar:
            p.document.forensic = radar.model_dump(mode="json")

    application.fraud_severity = report.severity
    await session.commit()

    await append_event(
        session,
        event_type="FRAUD_CHECKED",
        actor="pipeline",
        application_id=str(application.id),
        applicant_id=str(application.applicant_id),
        payload={
            "trust_score": report.trust_score,
            "severity": report.severity,
            "finding_count": len(report.findings),
            "finding_check_names": [f.check_name for f in report.findings],
        },
    )
    await session.commit()
    return report


def _identity_check_status(fraud_findings: list) -> str:
    for f in fraud_findings:
        if f.check_name in _IDENTITY_FAIL_CHECK_NAMES and f.severity == "MEDIUM":
            return "FAIL"
    return "PASS"


async def process_application(
    application_id: uuid.UUID,
    session: AsyncSession,
    storage: StorageBackend,
    settings: Settings | None = None,
) -> None:
    settings = settings or default_settings
    application = await session.get(Application, application_id)
    if application is None:
        raise ValueError(f"no application with id={application_id}")
    applicant = await session.get(Applicant, application.applicant_id)
    if applicant is None:
        raise ValueError(f"application {application_id} has no applicant row")

    documents = (
        (await session.execute(select(Document).where(Document.application_id == application_id)))
        .scalars()
        .all()
    )

    # Idempotency: a re-run (e.g. after a transient failure) must not
    # accumulate duplicate decision/summary/notice/precedent-signal rows
    # alongside fraud_findings/scorecard_results/precedent_matches, which
    # each already delete-then-insert inside their own stage helper.
    await session.execute(
        delete(DecisionArtifact).where(DecisionArtifact.application_id == application_id)
    )
    await session.commit()

    try:
        await _set_stage(session, application, "EXTRACTING")
        parsed_docs = await _extracting_stage(
            session,
            application=application,
            documents=list(documents),
            storage=storage,
            settings=settings,
        )

        gig_p = _find_parsed(parsed_docs, "GIG_PAYOUT")
        util_p = _find_parsed(parsed_docs, "UTILITY_BILL")
        bank_p = _find_parsed(parsed_docs, "BANK_STATEMENT")

        gig_payout = (
            gig_p.parsed if gig_p and isinstance(gig_p.parsed, GigPayoutExtraction) else None
        )
        utility_bill = (
            util_p.parsed if util_p and isinstance(util_p.parsed, UtilityBillExtraction) else None
        )
        bank_stmt = (
            bank_p.parsed if bank_p and isinstance(bank_p.parsed, BankStatementData) else None
        )

        bank_metrics = None
        bank_period_days = None
        if bank_stmt is not None:
            bank_metrics = analyze_bank_statement(
                bank_stmt, gig_platform_name=gig_payout.platform_name.value if gig_payout else None
            )
            bank_period_days = (bank_stmt.period_to - bank_stmt.period_from).days + 1

        pre_features = build_features(
            gig_payout=gig_payout,
            utility_bill=utility_bill,
            bank_metrics=bank_metrics,
            bank_period_days=bank_period_days,
        )

        await _set_stage(session, application, "FRAUD_CHECK")
        fraud_report = await _fraud_check_stage(
            session,
            storage,
            application=application,
            applicant=applicant,
            parsed_docs=parsed_docs,
            income_reconciliation_ratio=pre_features["income_reconciliation_ratio"],
        )

        await _set_stage(session, application, "SANITIZING")
        raw_context: dict[str, Any] = {
            **pre_features,
            "authenticity_score": fraud_report.authenticity_score,
            "full_name": applicant.name,
            "declared_address": applicant.declared_address,
            "stated_vocation": applicant.stated_vocation,
            "requested_line_inr": float(application.requested_line_inr),
        }
        scoring_input, sanitization_report = sanitize(raw_context)
        await append_event(
            session,
            event_type="GUARDRAIL_APPLIED",
            actor="pipeline",
            application_id=str(application.id),
            applicant_id=str(application.applicant_id),
            payload={"sanitization_report": sanitization_report.model_dump()},
        )
        await session.commit()

        await _set_stage(session, application, "SCORING")
        scorecard_cfg = load_scorecard()
        breakdown = compute_score(scoring_input, scorecard_cfg)
        await session.execute(
            delete(ScorecardResult).where(ScorecardResult.application_id == application.id)
        )
        session.add(
            ScorecardResult(
                application_id=application.id,
                features=scoring_input,
                factors={"items": [f.model_dump() for f in breakdown.factors]},
                base=breakdown.base,
                total=breakdown.total,
                version=breakdown.version,
            )
        )
        await append_event(
            session,
            event_type="SCORED",
            actor="pipeline",
            application_id=str(application.id),
            applicant_id=str(application.applicant_id),
            payload={
                "total": breakdown.total,
                "version": breakdown.version,
                "data_completeness": breakdown.data_completeness,
            },
        )
        await session.commit()

        await _set_stage(session, application, "PRECEDENT_MATCH")
        embedding = embed_features(scoring_input)
        precedent_result = await find_precedents(session, embedding=embedding)
        await persist_precedent_matches(
            session, application_id=application.id, result=precedent_result
        )
        precedent_signal = (
            precedent_result.to_signal() if precedent_result.sample_size > 0 else None
        )
        session.add(
            DecisionArtifact(
                application_id=application.id,
                kind="precedent_signal",
                content={
                    "peer_default_rate": precedent_result.peer_default_rate,
                    "peer_default_rate_weighted": precedent_result.peer_default_rate_weighted,
                    "ci_lower": precedent_result.ci_lower,
                    "ci_upper": precedent_result.ci_upper,
                    "sample_size": precedent_result.sample_size,
                },
                source="pgvector_knn",
            )
        )
        await append_event(
            session,
            event_type="PRECEDENTS_MATCHED",
            actor="pipeline",
            application_id=str(application.id),
            applicant_id=str(application.applicant_id),
            payload={
                "sample_size": precedent_result.sample_size,
                "peer_default_rate": precedent_result.peer_default_rate,
                "peer_default_rate_weighted": precedent_result.peer_default_rate_weighted,
                "ci_lower": precedent_result.ci_lower,
                "ci_upper": precedent_result.ci_upper,
            },
        )
        await session.commit()

        await _set_stage(session, application, "DECIDING")
        identity_check_status = _identity_check_status(fraud_report.findings)
        suspected_instruction_text = any(
            getattr(p.parsed, "suspected_instruction_text", False)
            or any(
                gf.check_name in ("prompt_injection_pattern", "model_flagged_instruction_text")
                for gf in p.guardrail_findings
            )
            for p in parsed_docs
        )

        llm_confidences = [
            p.extraction_confidence
            for p in parsed_docs
            if p.document.doc_type in IMAGE_DOC_TYPES and p.extraction_confidence is not None
        ]
        min_extraction_confidence = min(llm_confidences) if llm_confidences else None

        decision = decide(
            score_breakdown=breakdown,
            fraud_severity=fraud_report.severity,
            identity_check_status=identity_check_status,
            suspected_instruction_text=suspected_instruction_text,
            requested_line_inr=float(application.requested_line_inr),
            verified_monthly_income_inr=scoring_input.get("verified_monthly_income_inr"),
            min_extraction_confidence=min_extraction_confidence,
            precedent_signal=precedent_signal,
        )

        application.outcome = decision.outcome
        application.final_outcome = decision.outcome
        application.score = breakdown.total
        application.eligible_line_inr = decision.eligible_line_inr
        application.data_completeness = breakdown.data_completeness
        application.scorecard_version = breakdown.version
        application.policy_version = load_policy()["version"]

        session.add(
            DecisionArtifact(
                application_id=application.id,
                kind="decision",
                content=decision.model_dump(),
                source="policy_engine",
            )
        )
        await append_event(
            session,
            event_type="DECISION_MADE",
            actor="pipeline",
            application_id=str(application.id),
            applicant_id=str(application.applicant_id),
            payload={
                "outcome": decision.outcome,
                "score": decision.score,
                "reason_codes": decision.reason_codes,
                "eligible_line_inr": decision.eligible_line_inr,
            },
        )
        await session.commit()

        await _set_stage(session, application, "SUMMARIZING")
        recourse_actions = (
            recommend_recourse(scoring_input, breakdown) if decision.outcome != "APPROVE" else []
        )
        top_factors = sorted(
            (f for f in breakdown.factors if f.points != 0),
            key=lambda f: abs(f.points),
            reverse=True,
        )[:3]
        computed_values = {
            "outcome": decision.outcome,
            "score": breakdown.total,
            "fraud_severity": fraud_report.severity,
            "trust_score": fraud_report.trust_score,
            "data_completeness": breakdown.data_completeness,
            "eligible_line_inr": decision.eligible_line_inr,
            "requested_line_inr": float(application.requested_line_inr),
            "reason_codes": decision.reason_codes,
            "top_factors": [
                {"name": f.name, "points": f.points, "bin_label": f.bin_label} for f in top_factors
            ],
            "precedent": (
                {
                    "peer_default_rate": precedent_result.peer_default_rate,
                    "sample_size": precedent_result.sample_size,
                }
                if precedent_result.sample_size > 0
                else None
            ),
            "top_recourse": (
                {"text": recourse_actions[0].text, "points_gain": recourse_actions[0].points_gain}
                if recourse_actions
                else None
            ),
        }
        summary = await generate_summary(computed_values, settings=settings)
        session.add(
            DecisionArtifact(
                application_id=application.id,
                kind="summary",
                content=summary.model_dump(),
                model=summary.model,
                prompt_version=summary.prompt_version,
                source=summary.source,
            )
        )
        await append_event(
            session,
            event_type="SUMMARY_GENERATED",
            actor="pipeline",
            application_id=str(application.id),
            applicant_id=str(application.applicant_id),
            payload={
                "source": summary.source,
                "model": summary.model,
                "verified": summary.verified,
            },
        )

        policy_cfg = load_policy()
        notice = build_adverse_action_notice(
            applicant_id=str(application.applicant_id),
            decision=decision,
            reason_code_text=policy_cfg["reason_code_text"],
            recourse_actions=recourse_actions,
        )
        session.add(
            DecisionArtifact(
                application_id=application.id,
                kind="notice",
                content=notice.model_dump(),
                source="template",
            )
        )
        await append_event(
            session,
            event_type="NOTICE_GENERATED",
            actor="pipeline",
            application_id=str(application.id),
            applicant_id=str(application.applicant_id),
            payload={"decision": notice.decision},
        )
        await session.commit()

        application.stage = "COMPLETE"
        application.completed_at = datetime.now(UTC)
        await session.commit()

    except Exception as exc:  # noqa: BLE001 -- deliberately broad: any stage failure must land safely in FAILED
        await session.rollback()
        application = await session.get(Application, application_id)
        error_code = (
            exc.error_code if isinstance(exc, PipelineError) else "PIPELINE_UNEXPECTED_ERROR"
        )
        log.error(
            "pipeline_failed",
            application_id=str(application_id),
            error_code=error_code,
            error=str(exc),
        )
        if application is not None:
            application.stage = "FAILED"
            application.error_code = error_code
            await session.commit()
        raise
