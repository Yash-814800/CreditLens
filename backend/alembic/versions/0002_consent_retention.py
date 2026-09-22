"""Consent enforcement and retention purge migration.

Adds consent_text_sha256 and consent_withdrawn_at to applicants table.
Updates audit_log check constraint to include CONSENT_WITHDRAWN and RETENTION_PURGE.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_AUDIT_EVENT_TYPES = (
    "'APPLICATION_SUBMITTED','DOCUMENT_EXTRACTED','FRAUD_CHECKED','GUARDRAIL_APPLIED',"
    "'SCORED','PRECEDENTS_MATCHED','DECISION_MADE','SUMMARY_GENERATED',"
    "'NOTICE_GENERATED','DECISION_OVERRIDDEN','LOGIN'"
)

NEW_AUDIT_EVENT_TYPES = (
    "'APPLICATION_SUBMITTED','DOCUMENT_EXTRACTED','FRAUD_CHECKED','GUARDRAIL_APPLIED',"
    "'SCORED','PRECEDENTS_MATCHED','DECISION_MADE','SUMMARY_GENERATED',"
    "'NOTICE_GENERATED','DECISION_OVERRIDDEN','LOGIN','CONSENT_WITHDRAWN','RETENTION_PURGE'"
)


def upgrade() -> None:
    op.add_column("applicants", sa.Column("consent_text_sha256", sa.String(64), nullable=True))
    op.add_column("applicants", sa.Column("consent_withdrawn_at", sa.DateTime(timezone=True), nullable=True))

    op.drop_constraint("ck_audit_log_event_type", "audit_log", type_="check")
    op.create_check_constraint(
        "ck_audit_log_event_type",
        "audit_log",
        f"event_type IN ({NEW_AUDIT_EVENT_TYPES})",
    )


def downgrade() -> None:
    op.drop_constraint("ck_audit_log_event_type", "audit_log", type_="check")
    op.create_check_constraint(
        "ck_audit_log_event_type",
        "audit_log",
        f"event_type IN ({OLD_AUDIT_EVENT_TYPES})",
    )

    op.drop_column("applicants", "consent_withdrawn_at")
    op.drop_column("applicants", "consent_text_sha256")
