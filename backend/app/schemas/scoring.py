"""Output contracts for the pure decision core (Phase 5): sanitizer, scorecard,
policy, and recourse. Every one of these is JSON-serialisable so Phase 6's
pipeline can persist them verbatim into `scorecard_results`/`decision_artifacts`
and Phase 7's "How this scorecard works" / Decision Console panels can render
them directly -- CLAUDE.md rule 3 (no black-box decisioning) means every number
an underwriter sees must trace back to one of these structured objects, never
free text.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RemovedField(BaseModel):
    """One field the sanitizer stripped before scoring, and why. Phase 7's
    Responsible-AI Guardrail panel renders this list verbatim so an
    underwriter can see exactly what never reached the scorer."""

    field: str
    reason: str


class SanitizationReport(BaseModel):
    removed: list[RemovedField]
    allowed: list[str]


class ScoreFactor(BaseModel):
    name: str
    value: float | None
    bin_label: str
    points: int
    max_up: int
    max_down: int
    direction: str  # higher_is_better | lower_is_better
    reason_code: str  # the code this factor would contribute if it were penalized


class ScoreBreakdown(BaseModel):
    version: str
    base: int
    total: int  # clamp(base + sum(factor.points), 0, 100)
    factors: list[ScoreFactor]
    data_completeness: float  # fraction of the 7 factors that were non-null


class PrecedentSignal(BaseModel):
    """Phase 6's pgvector k-NN match result, summarised for the two-signal
    policy rule. Optional/None until Phase 6 exists; Phase 5's `decide()`
    already accepts and acts on it so Phase 6 only has to construct one."""

    peer_default_rate: float
    ci_lower: float
    ci_upper: float
    sample_size: int


class RecourseAction(BaseModel):
    feature: str
    current: float | None
    target: float
    points_gain: int
    resulting_score: int
    horizon_days: int | None  # None = achievable immediately (e.g. upload a document)
    text: str
    actionable: bool = True


class Decision(BaseModel):
    outcome: str  # APPROVE | REFER | DECLINE
    tier: str  # human label, e.g. "Standard approval" / "Tiered limit" / "Declined"
    eligible_line_inr: float
    reason_codes: list[str]
    rules_fired: list[str]  # explicit audit trace, one entry per rule evaluated
    score: int
    fraud_severity: str
    data_completeness: float
    scorecard_outcome: str | None = None
    precedent_outcome: str | None = None
    final_outcome: str | None = None
    precedent_peer_count: int | None = None
    precedent_default_rate: float | None = None
    precedent_wilson_ci: tuple[float, float] | None = None


class AdverseActionNotice(BaseModel):
    decision: str
    generated_at: str  # ISO-8601
    applicant_reference: str  # masked
    principal_reasons: list[dict] = Field(default_factory=list)  # [{code, text}]
    what_you_can_do: list[str] = Field(default_factory=list)
    basis_statement: str
    appeal_contact_placeholder: str
    non_discrimination_statement: str
