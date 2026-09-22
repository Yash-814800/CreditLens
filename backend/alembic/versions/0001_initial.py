"""Initial schema: core tables, least-privilege app role, audit-log immutability trigger.

Revision ID: 0001
Revises:
Create Date: 2026-09-20

"""

import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLES = "'underwriter','auditor','admin'"
DOC_TYPES = "'GIG_PAYOUT','UTILITY_BILL','BANK_STATEMENT'"
OUTCOMES = "'APPROVE','REFER','DECLINE'"
FRAUD_SEVERITIES = "'NONE','LOW','MEDIUM','HIGH'"
STAGES = (
    "'UPLOADED','EXTRACTING','FRAUD_CHECK','SANITIZING','SCORING',"
    "'PRECEDENT_MATCH','DECIDING','SUMMARIZING','COMPLETE','FAILED'"
)
AUDIT_EVENT_TYPES = (
    "'APPLICATION_SUBMITTED','DOCUMENT_EXTRACTED','FRAUD_CHECKED','GUARDRAIL_APPLIED',"
    "'SCORED','PRECEDENTS_MATCHED','DECISION_MADE','SUMMARY_GENERATED',"
    "'NOTICE_GENERATED','DECISION_OVERRIDDEN','LOGIN'"
)


def _sql_literal(value: str) -> str:
    """Escape a value read from a trusted local/deploy-time env var for use in a DDL
    literal. CREATE ROLE has no bind-parameter form, and these values are never
    end-user input (they come from .env / SSM, set by the person deploying this
    stack), so doubling quotes is sufficient -- this is not an untrusted-input path.
    """
    return value.replace("'", "''")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"role IN ({ROLES})", name="ck_users_role"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "applicants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("phone_hash", sa.String(64)),
        sa.Column("phone_last4", sa.String(4)),
        sa.Column("pan_hash", sa.String(64)),
        sa.Column("pan_masked", sa.String(20)),
        sa.Column("aadhaar_hash", sa.String(64)),
        sa.Column("declared_address", sa.Text),
        sa.Column("stated_vocation", sa.String(100)),
        sa.Column("consent_at", sa.DateTime(timezone=True)),
        sa.Column("consent_text_version", sa.String(20)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_applicants_phone_hash", "applicants", ["phone_hash"])
    op.create_index("ix_applicants_pan_hash", "applicants", ["pan_hash"])
    op.create_index("ix_applicants_aadhaar_hash", "applicants", ["aadhaar_hash"])

    op.create_table(
        "applications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "applicant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("applicants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("requested_line_inr", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("stage", sa.String(20), nullable=False, server_default="UPLOADED"),
        sa.Column("error_code", sa.String(50)),
        sa.Column("outcome", sa.String(10)),
        sa.Column("final_outcome", sa.String(10)),
        sa.Column("score", sa.Integer),
        sa.Column("fraud_severity", sa.String(10)),
        sa.Column("eligible_line_inr", sa.Numeric(12, 2)),
        sa.Column("data_completeness", sa.Numeric(3, 2)),
        sa.Column("scorecard_version", sa.String(20)),
        sa.Column("policy_version", sa.String(20)),
        sa.Column(
            "overridden_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("override_reason", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(f"stage IN ({STAGES})", name="ck_applications_stage"),
        sa.CheckConstraint(f"outcome IS NULL OR outcome IN ({OUTCOMES})", name="ck_applications_outcome"),
        sa.CheckConstraint(
            f"final_outcome IS NULL OR final_outcome IN ({OUTCOMES})", name="ck_applications_final_outcome"
        ),
        sa.CheckConstraint(
            f"fraud_severity IS NULL OR fraud_severity IN ({FRAUD_SEVERITIES})",
            name="ck_applications_fraud_severity",
        ),
        sa.CheckConstraint("score IS NULL OR score BETWEEN 0 AND 100", name="ck_applications_score_range"),
        sa.CheckConstraint(
            "data_completeness IS NULL OR data_completeness BETWEEN 0 AND 1",
            name="ck_applications_completeness_range",
        ),
    )
    op.create_index("ix_applications_applicant_id", "applications", ["applicant_id"])

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("doc_type", sa.String(20), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("mime", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("phash", postgresql.BIT(256)),
        sa.Column("extracted", postgresql.JSONB),
        sa.Column("extraction_confidence", sa.Numeric(3, 2)),
        sa.Column("extraction_model", sa.String(100)),
        sa.Column("forensic", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"doc_type IN ({DOC_TYPES})", name="ck_documents_doc_type"),
    )
    op.create_index("ix_documents_application_id", "documents", ["application_id"])
    op.create_index("ix_documents_sha256", "documents", ["sha256"])
    op.create_index("ix_documents_phash", "documents", ["phash"])

    op.create_table(
        "fraud_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE")
        ),
        sa.Column("check_name", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("penalty", sa.Integer, nullable=False, server_default="0"),
        sa.Column("evidence", postgresql.JSONB),
        sa.Column("message", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"severity IN ({FRAUD_SEVERITIES})", name="ck_fraud_findings_severity"),
    )
    op.create_index("ix_fraud_findings_application_id", "fraud_findings", ["application_id"])

    op.create_table(
        "scorecard_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("features", postgresql.JSONB, nullable=False),
        sa.Column("factors", postgresql.JSONB, nullable=False),
        sa.Column("base", sa.Integer, nullable=False),
        sa.Column("total", sa.Integer, nullable=False),
        sa.Column("version", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_scorecard_results_application_id", "scorecard_results", ["application_id"])

    op.create_table(
        "historical_borrowers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("features", postgresql.JSONB, nullable=False),
        sa.Column("signal_vector", Vector(10)),
        sa.Column("defaulted", sa.Boolean, nullable=False),
        sa.Column("synthetic", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("cohort", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.execute(
        "CREATE INDEX ix_historical_borrowers_signal_vector_hnsw ON historical_borrowers "
        "USING hnsw (signal_vector vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )

    op.create_table(
        "precedent_matches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "historical_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("historical_borrowers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("similarity", sa.Numeric(6, 5), nullable=False),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_precedent_matches_application_id", "precedent_matches", ["application_id"])

    op.create_table(
        "decision_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("content", postgresql.JSONB, nullable=False),
        sa.Column("model", sa.String(100)),
        sa.Column("prompt_version", sa.String(20)),
        sa.Column("source", sa.String(20)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_decision_artifacts_application_id", "decision_artifacts", ["application_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True)),
        sa.Column("applicant_id", postgresql.UUID(as_uuid=True)),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("row_hash", sa.String(64), nullable=False, unique=True),
        sa.CheckConstraint(f"event_type IN ({AUDIT_EVENT_TYPES})", name="ck_audit_log_event_type"),
    )
    op.create_index("ix_audit_log_event_type", "audit_log", ["event_type"])
    op.create_index("ix_audit_log_application_id", "audit_log", ["application_id"])
    op.create_index("ix_audit_log_applicant_id", "audit_log", ["applicant_id"])
    op.create_index("ix_audit_log_ts", "audit_log", ["ts"])

    # --- Least-privilege app role + audit-log immutability (CLAUDE.md rules 2, 9; Phase 1 §3-4) ---
    app_role = os.environ["APP_DB_USER"]
    app_password = _sql_literal(os.environ["APP_DB_PASSWORD"])
    db_name = os.environ["POSTGRES_DB"]
    role_ident = sa.sql.quoted_name(app_role, quote=True)

    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_sql_literal(app_role)}') THEN
                CREATE ROLE {role_ident} LOGIN PASSWORD '{app_password}';
            ELSE
                ALTER ROLE {role_ident} LOGIN PASSWORD '{app_password}';
            END IF;
        END
        $$;
        """
    )
    op.execute(f'GRANT CONNECT ON DATABASE "{db_name}" TO {role_ident}')
    op.execute(f"GRANT USAGE ON SCHEMA public TO {role_ident}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role_ident}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role_ident}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role_ident}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {role_ident}")
    # audit_log is the one table the app role may only append to, never mutate/delete.
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM {role_ident}")
    op.execute(f"GRANT SELECT, INSERT ON audit_log TO {role_ident}")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_log_deny_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only: % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    # These fire for every role, including the migration/admin (superuser) role -- see
    # docs/threat_model.md (added Phase 8) for the residual risk that a superuser could
    # still disable triggers or set session_replication_role='replica'.
    op.execute(
        "CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log "
        "FOR EACH ROW EXECUTE FUNCTION audit_log_deny_mutation()"
    )
    op.execute(
        "CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log "
        "FOR EACH ROW EXECUTE FUNCTION audit_log_deny_mutation()"
    )
    op.execute(
        "CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_log_deny_mutation()"
    )


def downgrade() -> None:
    # Deliberately does NOT DROP ROLE: APP_DB_USER is a cluster-wide Postgres role,
    # not scoped to this database, so a downgrade run against one database (e.g. an
    # isolated migration test database) must never delete a role another database
    # (the real app) is actively connecting as. Only this database's grants/objects
    # are undone; the role definition itself is left alone.
    app_role = os.environ["APP_DB_USER"]
    role_ident = sa.sql.quoted_name(app_role, quote=True)
    db_name = os.environ["POSTGRES_DB"]

    op.execute("DROP TRIGGER IF EXISTS audit_log_no_truncate ON audit_log")
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_delete ON audit_log")
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_update ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS audit_log_deny_mutation()")

    op.drop_table("audit_log")
    op.drop_table("decision_artifacts")
    op.drop_table("precedent_matches")
    op.execute("DROP INDEX IF EXISTS ix_historical_borrowers_signal_vector_hnsw")
    op.drop_table("historical_borrowers")
    op.drop_table("scorecard_results")
    op.drop_table("fraud_findings")
    op.drop_table("documents")
    op.drop_table("applications")
    op.drop_table("applicants")
    op.drop_table("users")

    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {role_ident}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE USAGE, SELECT ON SEQUENCES FROM {role_ident}")
    op.execute(f"REVOKE ALL PRIVILEGES ON SCHEMA public FROM {role_ident}")
    op.execute(f"REVOKE CONNECT ON DATABASE {sa.sql.quoted_name(db_name, quote=True)} FROM {role_ident}")
