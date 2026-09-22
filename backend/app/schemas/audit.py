from datetime import datetime

from pydantic import BaseModel


class VerifyChainResponse(BaseModel):
    valid: bool
    first_broken_id: int | None
    checked: int


class AuditLogEntry(BaseModel):
    id: int
    ts: datetime
    event_type: str
    application_id: str | None
    applicant_id: str | None
    actor: str
    payload: dict


class AuditLogListResponse(BaseModel):
    items: list[AuditLogEntry]
    total: int
    page: int
    page_size: int
