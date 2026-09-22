"""Output contract for the fraud / document-integrity layer (Phase 4).

`run_fraud_checks()` in app/services/fraud/service.py returns a FraudReport.
Every number here must be explainable in plain English to an underwriter
(CLAUDE.md rule: no black-box decisioning) -- each Finding carries a
human-readable `message` plus machine-readable `evidence`.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class Finding(BaseModel):
    check_name: str
    severity: str  # NONE | LOW | MEDIUM | HIGH
    penalty_points: int
    message: str
    evidence: dict = Field(default_factory=dict)
    document_id: uuid.UUID | None = None


class DocumentRadar(BaseModel):
    """Per-document tamper-radar summary (Phase 7's UI overlay reads this)."""

    document_id: uuid.UUID | None = None
    doc_type: str
    radar_score: float  # 0-1
    applicable_checks: list[str]
    flagged_regions: list[list[int]] = Field(default_factory=list)  # [x0,y0,x1,y1] boxes
    heatmap_storage_key: str | None = None


class GraphEdge(BaseModel):
    """One corroborated-or-not document-reuse edge, for Phase 7's syndicate graph."""

    applicant_a: uuid.UUID
    applicant_b: uuid.UUID
    doc_type: str
    hamming_distance: int
    sha256_match: bool
    corroborated: bool


class FraudReport(BaseModel):
    findings: list[Finding]
    per_document_radar: list[DocumentRadar]
    trust_score: int  # 0-100
    authenticity_score: float  # trust_score / 100
    severity: str  # NONE | LOW | MEDIUM | HIGH
    graph_edges: list[GraphEdge] = Field(default_factory=list)
