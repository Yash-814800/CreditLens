"""Request/response contracts for the Phase 6 applications API. CLAUDE.md:
Aadhaar/PAN/phone are never returned raw -- every response model here only
ever carries the already-masked/hashed forms the DB stores (Applicant never
stores a raw Aadhaar or PAN string at all, see api/v1/applications.py's
intake handler)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, Field

from app.schemas.explain import SummaryResult
from app.schemas.fraud import FraudReport
from app.schemas.scoring import (
    AdverseActionNotice,
    Decision,
    RecourseAction,
    SanitizationReport,
    ScoreBreakdown,
)


class KYCIntake(BaseModel):
    """Parsed from the multipart request's `kyc` JSON field."""

    full_name: str
    phone: str
    pan: str
    aadhaar: str
    declared_address: str | None = None
    stated_vocation: str | None = None
    requested_line_inr: float = Field(gt=0)
    consent_accepted: bool = Field(
        default=False,
        validation_alias=AliasChoices("consent_accepted", "consent_given"),
    )
    consent_text_version: str


class ConsentMetaResponse(BaseModel):
    text: str
    version: str
    sha256: str


class DemoPersonaSubmitRequest(BaseModel):
    consent_accepted: bool | None = None
    consent_text_version: str | None = None


class WithdrawConsentResponse(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    consent_withdrawn: bool
    withdrawn_at: datetime


class PurgeResponse(BaseModel):
    dry_run: bool
    eligible_applications: int
    applications_purged: int
    files_deleted: int
    application_ids: list[str]


class ApplicationSummary(BaseModel):
    id: uuid.UUID
    applicant_reference: str  # masked, e.g. "APP-1a2b...9f0e"
    requested_line_inr: float
    eligible_line_inr: float | None
    outcome: str | None
    final_outcome: str | None
    score: int | None
    fraud_severity: str | None
    stage: str
    created_at: datetime


class ApplicationListResponse(BaseModel):
    items: list[ApplicationSummary]
    total: int
    page: int
    page_size: int


class DocumentSummary(BaseModel):
    id: uuid.UUID
    doc_type: str
    mime: str
    extracted: dict[str, Any] | None
    extraction_confidence: float | None
    extraction_model: str | None
    forensic: dict[str, Any] | None


class PrecedentMatchOut(BaseModel):
    historical_id: uuid.UUID
    rank: int
    similarity: float
    defaulted: bool
    cohort: str | None


class PrecedentPanel(BaseModel):
    matches: list[PrecedentMatchOut]
    peer_default_rate: float
    peer_default_rate_weighted: float
    ci_lower: float
    ci_upper: float
    sample_size: int
    agrees_with_scorecard: bool | None


class ApplicationDetail(BaseModel):
    id: uuid.UUID
    applicant_reference: str
    applicant_name: str
    requested_line_inr: float
    eligible_line_inr: float | None
    status: str
    stage: str
    error_code: str | None
    outcome: str | None
    final_outcome: str | None
    overridden_by: uuid.UUID | None
    override_reason: str | None
    score: int | None
    fraud_severity: str | None
    data_completeness: float | None
    scorecard_version: str | None
    policy_version: str | None
    created_at: datetime
    completed_at: datetime | None

    documents: list[DocumentSummary]
    fraud_report: FraudReport | None
    sanitization_report: SanitizationReport | None
    score_breakdown: ScoreBreakdown | None
    decision: Decision | None
    precedents: PrecedentPanel | None
    recourse: list[RecourseAction]
    summary: SummaryResult | None
    notice: AdverseActionNotice | None


class OverrideRequest(BaseModel):
    outcome: str
    reason: str = Field(min_length=1)


class DemoPersonaInfo(BaseModel):
    persona_id: str
    expected_outcome: str
    notes: str
    docs_present: list[str]


class ScorecardMetaResponse(BaseModel):
    scorecard: dict[str, Any]
    policy: dict[str, Any]
