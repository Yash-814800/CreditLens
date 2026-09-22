import uuid
from datetime import datetime

import asyncpg
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import BIT, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import (
    AUDIT_EVENT_TYPES,
    DOC_TYPES,
    FRAUD_SEVERITIES,
    OUTCOMES,
    ROLES,
    STAGES,
    sql_in_list,
)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (CheckConstraint(f"role IN ({sql_in_list(ROLES)})", name="ck_users_role"),)


class Applicant(Base):
    __tablename__ = "applicants"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    phone_last4: Mapped[str | None] = mapped_column(String(4))
    pan_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    pan_masked: Mapped[str | None] = mapped_column(String(20))
    aadhaar_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    declared_address: Mapped[str | None] = mapped_column(Text)
    stated_vocation: Mapped[str | None] = mapped_column(String(100))
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consent_text_version: Mapped[str | None] = mapped_column(String(20))
    consent_text_sha256: Mapped[str | None] = mapped_column(String(64))
    consent_withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[uuid.UUID] = _uuid_pk()
    applicant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("applicants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requested_line_inr: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    stage: Mapped[str] = mapped_column(String(20), nullable=False, default="UPLOADED")
    error_code: Mapped[str | None] = mapped_column(String(50))
    outcome: Mapped[str | None] = mapped_column(String(10))
    final_outcome: Mapped[str | None] = mapped_column(String(10))
    score: Mapped[int | None] = mapped_column(Integer)
    fraud_severity: Mapped[str | None] = mapped_column(String(10))
    eligible_line_inr: Mapped[float | None] = mapped_column(Numeric(12, 2))
    data_completeness: Mapped[float | None] = mapped_column(Numeric(3, 2))
    scorecard_version: Mapped[str | None] = mapped_column(String(20))
    policy_version: Mapped[str | None] = mapped_column(String(20))
    overridden_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    override_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(f"stage IN ({sql_in_list(STAGES)})", name="ck_applications_stage"),
        CheckConstraint(
            f"outcome IS NULL OR outcome IN ({sql_in_list(OUTCOMES)})",
            name="ck_applications_outcome",
        ),
        CheckConstraint(
            f"final_outcome IS NULL OR final_outcome IN ({sql_in_list(OUTCOMES)})",
            name="ck_applications_final_outcome",
        ),
        CheckConstraint(
            f"fraud_severity IS NULL OR fraud_severity IN ({sql_in_list(FRAUD_SEVERITIES)})",
            name="ck_applications_fraud_severity",
        ),
        CheckConstraint(
            "score IS NULL OR score BETWEEN 0 AND 100", name="ck_applications_score_range"
        ),
        CheckConstraint(
            "data_completeness IS NULL OR data_completeness BETWEEN 0 AND 1",
            name="ck_applications_completeness_range",
        ),
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    doc_type: Mapped[str] = mapped_column(String(20), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mime: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # NOTE: the asyncpg driver's BIT codec round-trips this column as
    # `asyncpg.BitString`, not `str` -- see app/services/fraud/phash.py's
    # module docstring for why. Use bits_to_bitstring()/bitstring_to_bits()
    # to convert to/from the plain '0'/'1' string form.
    phash: Mapped[asyncpg.BitString | None] = mapped_column(BIT(256), index=True)
    extracted: Mapped[dict | None] = mapped_column(JSONB)
    extraction_confidence: Mapped[float | None] = mapped_column(Numeric(3, 2))
    extraction_model: Mapped[str | None] = mapped_column(String(100))
    forensic: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        CheckConstraint(f"doc_type IN ({sql_in_list(DOC_TYPES)})", name="ck_documents_doc_type"),
    )


class FraudFinding(Base):
    __tablename__ = "fraud_findings"

    id: Mapped[uuid.UUID] = _uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE")
    )
    check_name: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    penalty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evidence: Mapped[dict | None] = mapped_column(JSONB)
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        CheckConstraint(
            f"severity IN ({sql_in_list(FRAUD_SEVERITIES)})", name="ck_fraud_findings_severity"
        ),
    )


class ScorecardResult(Base):
    __tablename__ = "scorecard_results"

    id: Mapped[uuid.UUID] = _uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    features: Mapped[dict] = mapped_column(JSONB, nullable=False)
    factors: Mapped[dict] = mapped_column(JSONB, nullable=False)
    base: Mapped[int] = mapped_column(Integer, nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = _created_at()


class HistoricalBorrower(Base):
    __tablename__ = "historical_borrowers"

    id: Mapped[uuid.UUID] = _uuid_pk()
    features: Mapped[dict] = mapped_column(JSONB, nullable=False)
    signal_vector: Mapped[list[float] | None] = mapped_column(Vector(10))
    defaulted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cohort: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        Index(
            "ix_historical_borrowers_signal_vector_hnsw",
            "signal_vector",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"signal_vector": "vector_cosine_ops"},
        ),
    )


class PrecedentMatch(Base):
    __tablename__ = "precedent_matches"

    id: Mapped[uuid.UUID] = _uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    historical_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("historical_borrowers.id", ondelete="CASCADE"),
        nullable=False,
    )
    similarity: Mapped[float] = mapped_column(Numeric(6, 5), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class DecisionArtifact(Base):
    __tablename__ = "decision_artifacts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(20))
    source: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = _created_at()


class AuditLog(Base):
    """Append-only hash chain. Immutability is enforced twice: DB grants (the app
    role has no UPDATE/DELETE on this table) and a trigger (see migration 0001) that
    rejects UPDATE/DELETE/TRUNCATE for every role, including the migration/admin role.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    application_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)
    applicant_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    __table_args__ = (
        CheckConstraint(
            f"event_type IN ({sql_in_list(AUDIT_EVENT_TYPES)})", name="ck_audit_log_event_type"
        ),
    )
