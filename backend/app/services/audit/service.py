"""Hash-chained, append-only audit log.

Why a hash chain on top of the DB grants: the migration (0001) already revokes
UPDATE/DELETE/TRUNCATE on audit_log from the app role and blocks it for every role
via a trigger. That stops in-band tampering through SQL. The hash chain additionally
lets an auditor *detect* tampering that bypasses the app entirely (e.g. a row edited
directly by someone with elevated DB access, or a restored/edited backup): each row's
row_hash commits to the previous row's hash, so altering or removing any row breaks
the chain from that point forward, and verify_chain() finds exactly where.
"""

import hashlib
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog

_ADVISORY_LOCK_KEY = 727310  # arbitrary constant scoping the lock to audit-log appends
_GENESIS_HASH = "0" * 64


def _canonical_json(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def _row_payload(
    *,
    event_type: str,
    actor: str,
    application_id: str | None,
    applicant_id: str | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "actor": actor,
        "application_id": application_id,
        "applicant_id": applicant_id,
        "payload": payload,
    }


async def append_event(
    session: AsyncSession,
    *,
    event_type: str,
    actor: str,
    application_id: str | None = None,
    applicant_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditLog:
    """Append one event to the chain.

    Caller is responsible for committing the session. The advisory lock serialises
    concurrent appends within this transaction so two writers can never read the same
    "last row" and produce two rows chained to the same prev_hash.
    """
    await session.execute(select(func.pg_advisory_xact_lock(_ADVISORY_LOCK_KEY)))

    prev_hash = await session.scalar(
        select(AuditLog.row_hash).order_by(AuditLog.id.desc()).limit(1)
    )
    prev_hash = prev_hash or _GENESIS_HASH

    payload = payload or {}
    row = _row_payload(
        event_type=event_type,
        actor=actor,
        application_id=application_id,
        applicant_id=applicant_id,
        payload=payload,
    )
    row_hash = hashlib.sha256((_canonical_json(row) + prev_hash).encode("utf-8")).hexdigest()

    entry = AuditLog(
        event_type=event_type,
        actor=actor,
        application_id=application_id,
        applicant_id=applicant_id,
        payload=payload,
        prev_hash=prev_hash,
        row_hash=row_hash,
    )
    session.add(entry)
    await session.flush()
    return entry


async def verify_chain(session: AsyncSession) -> dict[str, Any]:
    """Walk the whole chain in id order. Returns {valid, first_broken_id, checked}."""
    result = await session.execute(select(AuditLog).order_by(AuditLog.id.asc()))
    rows = result.scalars().all()

    prev_hash = _GENESIS_HASH
    for row in rows:
        expected_row = _row_payload(
            event_type=row.event_type,
            actor=row.actor,
            application_id=str(row.application_id) if row.application_id else None,
            applicant_id=str(row.applicant_id) if row.applicant_id else None,
            payload=row.payload or {},
        )
        expected_hash = hashlib.sha256(
            (_canonical_json(expected_row) + prev_hash).encode("utf-8")
        ).hexdigest()
        if row.prev_hash != prev_hash or row.row_hash != expected_hash:
            return {"valid": False, "first_broken_id": row.id, "checked": len(rows)}
        prev_hash = row.row_hash

    return {"valid": True, "first_broken_id": None, "checked": len(rows)}
