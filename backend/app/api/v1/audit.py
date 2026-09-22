from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import require_roles
from app.db.models import AuditLog
from app.db.session import get_session
from app.schemas.audit import AuditLogEntry, AuditLogListResponse, VerifyChainResponse
from app.services.audit.service import verify_chain

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])

# Role matrix (CLAUDE.md): auditor is read-only including the audit log;
# admin can do everything; underwriter has no audit-log access at all.
_auditor_or_admin = require_roles("auditor", "admin")


@router.get("/verify", response_model=VerifyChainResponse)
async def audit_verify(
    session: AsyncSession = Depends(get_session), _user=Depends(_auditor_or_admin)
) -> VerifyChainResponse:
    result = await verify_chain(session)
    return VerifyChainResponse(**result)


@router.get("", response_model=AuditLogListResponse)
async def list_audit_log(
    event_type: str | None = None,
    application_id: str | None = None,
    applicant_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    _user=Depends(_auditor_or_admin),
) -> AuditLogListResponse:
    stmt = select(AuditLog)
    count_stmt = select(func.count()).select_from(AuditLog)
    if event_type:
        stmt = stmt.where(AuditLog.event_type == event_type)
        count_stmt = count_stmt.where(AuditLog.event_type == event_type)
    if application_id:
        stmt = stmt.where(AuditLog.application_id == application_id)
        count_stmt = count_stmt.where(AuditLog.application_id == application_id)
    if applicant_id:
        stmt = stmt.where(AuditLog.applicant_id == applicant_id)
        count_stmt = count_stmt.where(AuditLog.applicant_id == applicant_id)

    total = await session.scalar(count_stmt)
    rows = (
        (
            await session.execute(
                stmt.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    items = [
        AuditLogEntry(
            id=r.id,
            ts=r.ts,
            event_type=r.event_type,
            application_id=str(r.application_id) if r.application_id else None,
            applicant_id=str(r.applicant_id) if r.applicant_id else None,
            actor=r.actor,
            payload=r.payload,
        )
        for r in rows
    ]
    return AuditLogListResponse(items=items, total=total or 0, page=page, page_size=page_size)
