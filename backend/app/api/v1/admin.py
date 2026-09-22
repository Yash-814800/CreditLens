"""Admin endpoints for data retention, purging, and privacy compliance."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import CurrentUser, require_roles
from app.core.config import settings
from app.db.models import Applicant, Application, Document
from app.db.session import get_session
from app.schemas.applications import PurgeResponse
from app.services.audit.service import append_event
from app.services.ingestion.storage import build_storage_backend

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
_admin_role = require_roles("admin")


def _redact_extracted_data(extracted: dict[str, Any] | None) -> dict[str, Any] | None:
    if not extracted:
        return extracted
    redacted = dict(extracted)
    pii_fields = {
        "account_holder",
        "consumer_name",
        "partner_name",
        "service_address",
        "billing_address",
        "account_number_masked",
        "phone",
        "email",
    }
    for k in pii_fields:
        if k in redacted and redacted[k] is not None:
            redacted[k] = "[REDACTED]"
    return redacted


@router.post("/retention/purge", response_model=PurgeResponse)
async def purge_retained_data(
    dry_run: bool = Query(True),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(_admin_role),
) -> PurgeResponse:
    cutoff = datetime.now(UTC) - timedelta(days=settings.retention_days)

    # Eligible applications: consent withdrawn OR older than retention_days, not already redacted
    stmt = (
        select(Application, Applicant)
        .join(Applicant, Applicant.id == Application.applicant_id)
        .where(
            or_(
                Applicant.consent_withdrawn_at.is_not(None),
                Application.created_at < cutoff,
            ),
            Applicant.name != "[REDACTED]",
        )
    )
    rows = (await session.execute(stmt)).all()

    eligible_app_ids = [str(app.id) for app, _ in rows]
    storage = build_storage_backend(settings)
    files_to_delete = 0

    # Gather documents for eligible applications
    for app, _ in rows:
        docs = (
            (await session.execute(select(Document).where(Document.application_id == app.id)))
            .scalars()
            .all()
        )
        for doc in docs:
            if doc.storage_key:
                files_to_delete += 1
            if doc.forensic and doc.forensic.get("heatmap_storage_key"):
                files_to_delete += 1

    if dry_run:
        return PurgeResponse(
            dry_run=True,
            eligible_applications=len(rows),
            applications_purged=0,
            files_deleted=0,
            application_ids=eligible_app_ids,
        )

    # Perform actual purge
    deleted_files = 0
    for app, applicant in rows:
        docs = (
            (await session.execute(select(Document).where(Document.application_id == app.id)))
            .scalars()
            .all()
        )
        for doc in docs:
            if doc.storage_key:
                await storage.delete(doc.storage_key)
                deleted_files += 1
            if doc.forensic and doc.forensic.get("heatmap_storage_key"):
                await storage.delete(doc.forensic["heatmap_storage_key"])
                doc.forensic["heatmap_storage_key"] = None
                deleted_files += 1
            if doc.extracted:
                doc.extracted = _redact_extracted_data(doc.extracted)

        # Redact Applicant PII
        applicant.name = "[REDACTED]"
        applicant.declared_address = None
        applicant.stated_vocation = None
        applicant.phone_hash = None
        applicant.phone_last4 = None
        applicant.pan_hash = None
        applicant.pan_masked = "[REDACTED]"
        applicant.aadhaar_hash = None

        app.status = "PURGED"

    await session.flush()
    await append_event(
        session,
        event_type="RETENTION_PURGE",
        actor=user.email,
        payload={
            "dry_run": False,
            "purged_count": len(rows),
            "files_deleted": deleted_files,
            "application_ids": eligible_app_ids,
        },
    )
    await session.commit()

    return PurgeResponse(
        dry_run=False,
        eligible_applications=len(rows),
        applications_purged=len(rows),
        files_deleted=deleted_files,
        application_ids=eligible_app_ids,
    )
