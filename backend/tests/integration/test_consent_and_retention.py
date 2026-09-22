"""Integration tests for consent verification, withdrawal, and retention purge.

Covers CLAUDE.md Phase 12 requirements.
"""

from __future__ import annotations

import hashlib
import uuid

import pytest
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.security import hash_password
from app.db.models import Applicant, Application, AuditLog, Document, User
from app.services.audit.service import verify_chain
from app.services.ingestion.storage import build_storage_backend

pytestmark = pytest.mark.integration


async def _create_user(db_session, email: str, role: str, password: str = "test-pass-123") -> User:
    user = User(email=email, password_hash=hash_password(password), role=role, is_active=True)
    db_session.add(user)
    await db_session.commit()
    return user


async def _login(client, email: str, password: str = "test-pass-123") -> str:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _fresh_email() -> str:
    return f"test-{uuid.uuid4().hex[:12]}@creditlens.demo"


@pytest.fixture
async def underwriter_token(client, db_session):
    email = _fresh_email()
    await _create_user(db_session, email, "underwriter")
    return await _login(client, email)


@pytest.fixture
async def admin_token(client, db_session):
    email = _fresh_email()
    await _create_user(db_session, email, "admin")
    return await _login(client, email)


@pytest.mark.asyncio
async def test_get_consent_meta(client):
    """GET /api/v1/meta/consent is public and returns valid consent text and sha256."""
    resp = await client.get("/api/v1/meta/consent")
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == "v1"
    assert "Purpose Limitation" in data["text"]
    assert "Document Hashes" in data["text"]
    expected_hash = hashlib.sha256(data["text"].encode("utf-8")).hexdigest()
    assert data["sha256"] == expected_hash


@pytest.mark.asyncio
async def test_submit_application_consent_validation(client, underwriter_token):
    """POST /api/v1/applications rejects submissions with missing or stale consent."""
    headers = {"Authorization": f"Bearer {underwriter_token}"}

    # 1. consent_accepted is False
    kyc_no_consent = {
        "full_name": "Test User",
        "phone": "9876543210",
        "pan": "ABCDE1234F",
        "aadhaar": "123412341234",
        "requested_line_inr": 25000,
        "consent_accepted": False,
        "consent_text_version": "v1",
    }
    resp = await client.post(
        "/api/v1/applications",
        data={"kyc": str(kyc_no_consent).replace("'", '"').replace("False", "false")},
        files={"utility_bill": ("bill.pdf", b"%PDF-dummy", "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 422
    assert "consent_accepted must be true" in resp.text

    # 2. consent_text_version is stale
    kyc_stale_consent = {
        "full_name": "Test User",
        "phone": "9876543210",
        "pan": "ABCDE1234F",
        "aadhaar": "123412341234",
        "requested_line_inr": 25000,
        "consent_accepted": True,
        "consent_text_version": "v0",
    }
    resp = await client.post(
        "/api/v1/applications",
        data={"kyc": str(kyc_stale_consent).replace("'", '"').replace("True", "true")},
        files={"utility_bill": ("bill.pdf", b"%PDF-dummy", "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 422
    assert "stale or invalid consent_text_version" in resp.text


@pytest.mark.asyncio
async def test_submit_demo_persona_consent_validation(client, db_session, underwriter_token):
    """POST /api/v1/demo/personas/{id}/submit enforces consent check in body."""
    headers = {"Authorization": f"Bearer {underwriter_token}"}

    # 1. Explicit consent_accepted = False in body
    resp = await client.post(
        "/api/v1/demo/personas/P01/submit",
        json={"consent_accepted": False, "consent_text_version": "v1"},
        headers=headers,
    )
    assert resp.status_code == 422
    assert "consent_accepted must be true" in resp.text

    # 2. Explicit stale consent_text_version in body
    resp = await client.post(
        "/api/v1/demo/personas/P01/submit",
        json={"consent_accepted": True, "consent_text_version": "v0"},
        headers=headers,
    )
    assert resp.status_code == 422
    assert "stale or invalid consent_text_version" in resp.text

    # 3. Valid body succeeds
    resp = await client.post(
        "/api/v1/demo/personas/P01/submit",
        json={"consent_accepted": True, "consent_text_version": "v1"},
        headers=headers,
    )
    assert resp.status_code == 202
    app_id = resp.json()["id"]

    # Cleanup
    app_row = await db_session.get(Application, uuid.UUID(app_id))
    if app_row:
        await db_session.execute(delete(Applicant).where(Applicant.id == app_row.applicant_id))
        await db_session.commit()


@pytest.mark.asyncio
async def test_audit_records_consent_without_pii(client, db_session, underwriter_token):
    """APPLICATION_SUBMITTED audit entry contains consent metadata and zero PII."""
    headers = {"Authorization": f"Bearer {underwriter_token}"}
    resp = await client.post(
        "/api/v1/demo/personas/P01/submit",
        json={"consent_accepted": True, "consent_text_version": "v1"},
        headers=headers,
    )
    assert resp.status_code == 202
    app_id = resp.json()["id"]

    try:
        stmt = (
            select(AuditLog)
            .where(
                AuditLog.event_type == "APPLICATION_SUBMITTED",
                AuditLog.application_id == uuid.UUID(app_id),
            )
            .order_by(AuditLog.id.desc())
        )
        entry = (await db_session.execute(stmt)).scalars().first()
        assert entry is not None

        payload = entry.payload
        assert payload["consent_text_version"] == "v1"
        assert len(payload["consent_text_sha256"]) == 64
        assert "consent_at" in payload

        # Verify no PII in audit payload
        forbidden_pii = ["name", "full_name", "phone", "pan", "aadhaar", "address"]
        for pii in forbidden_pii:
            assert pii not in payload, f"PII key '{pii}' leaked in audit log payload"

    finally:
        app_row = await db_session.get(Application, uuid.UUID(app_id))
        if app_row:
            await db_session.execute(delete(Applicant).where(Applicant.id == app_row.applicant_id))
            await db_session.commit()


@pytest.mark.asyncio
async def test_withdraw_consent(client, db_session, underwriter_token):
    """POST /api/v1/applications/{id}/withdraw-consent marks consent withdrawn.

    Also verifies that a CONSENT_WITHDRAWN event is written to the audit log.
    """
    headers = {"Authorization": f"Bearer {underwriter_token}"}
    resp = await client.post(
        "/api/v1/demo/personas/P01/submit",
        json={"consent_accepted": True, "consent_text_version": "v1"},
        headers=headers,
    )
    assert resp.status_code == 202
    app_id = resp.json()["id"]

    try:
        # Withdraw consent
        withdraw_resp = await client.post(
            f"/api/v1/applications/{app_id}/withdraw-consent",
            headers=headers,
        )
        assert withdraw_resp.status_code == 200
        data = withdraw_resp.json()
        assert data["consent_withdrawn"] is True
        assert data["application_id"] == app_id
        assert data["withdrawn_at"] is not None

        # Verify applicant in DB has consent_withdrawn_at set
        app_row = await db_session.get(Application, uuid.UUID(app_id))
        applicant = await db_session.get(Applicant, app_row.applicant_id)
        assert applicant.consent_withdrawn_at is not None

        # Verify audit log event
        stmt = (
            select(AuditLog)
            .where(
                AuditLog.event_type == "CONSENT_WITHDRAWN",
                AuditLog.application_id == uuid.UUID(app_id),
            )
            .order_by(AuditLog.id.desc())
        )
        audit_entry = (await db_session.execute(stmt)).scalars().first()
        assert audit_entry is not None
        assert audit_entry.application_id == uuid.UUID(app_id)
        assert "withdrawn_at" in audit_entry.payload

    finally:
        app_row = await db_session.get(Application, uuid.UUID(app_id))
        if app_row:
            await db_session.execute(delete(Applicant).where(Applicant.id == app_row.applicant_id))
            await db_session.commit()


@pytest.mark.asyncio
async def test_retention_purge_admin_only_and_lifecycle(
    client, db_session, underwriter_token, admin_token
):
    """Admin-only retention purge cleans up files and redacts PII while preserving audit chain."""
    storage = build_storage_backend(settings)

    # 1. Non-admin gets 403
    underwriter_headers = {"Authorization": f"Bearer {underwriter_token}"}
    resp = await client.post("/api/v1/admin/retention/purge", headers=underwriter_headers)
    assert resp.status_code == 403

    # 2. Submit persona P01
    resp = await client.post(
        "/api/v1/demo/personas/P01/submit",
        json={"consent_accepted": True, "consent_text_version": "v1"},
        headers=underwriter_headers,
    )
    assert resp.status_code == 202
    app_id = resp.json()["id"]

    try:
        # Withdraw consent to make it immediately eligible for purge
        await client.post(
            f"/api/v1/applications/{app_id}/withdraw-consent",
            headers=underwriter_headers,
        )

        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # 3. Dry-run purge
        dry_resp = await client.post(
            "/api/v1/admin/retention/purge?dry_run=true",
            headers=admin_headers,
        )
        assert dry_resp.status_code == 200
        dry_data = dry_resp.json()
        assert dry_data["dry_run"] is True
        assert dry_data["eligible_applications"] >= 1
        assert dry_data["applications_purged"] == 0
        assert app_id in dry_data["application_ids"]

        # Verify applicant is still not redacted
        app_row = await db_session.get(Application, uuid.UUID(app_id))
        applicant = await db_session.get(Applicant, app_row.applicant_id)
        assert applicant.name != "[REDACTED]"

        # Verify chain valid before live purge
        chain_before = await verify_chain(db_session)
        assert chain_before["valid"] is True

        # 4. Live purge
        live_resp = await client.post(
            "/api/v1/admin/retention/purge?dry_run=false",
            headers=admin_headers,
        )
        assert live_resp.status_code == 200
        live_data = live_resp.json()
        assert live_data["dry_run"] is False
        assert live_data["applications_purged"] >= 1
        assert app_id in live_data["application_ids"]

        # Verify applicant PII is redacted
        await db_session.refresh(applicant)
        assert applicant.name == "[REDACTED]"
        assert applicant.phone_hash is None
        assert applicant.phone_last4 is None
        assert applicant.pan_hash is None
        assert applicant.pan_masked == "[REDACTED]"
        assert applicant.aadhaar_hash is None
        assert applicant.declared_address is None

        # Verify documents have files deleted from storage
        docs = (
            (
                await db_session.execute(
                    select(Document).where(Document.application_id == uuid.UUID(app_id))
                )
            )
            .scalars()
            .all()
        )
        for doc in docs:
            if doc.storage_key:
                assert await storage.exists(doc.storage_key) is False

        # Verify audit log recorded RETENTION_PURGE
        stmt = (
            select(AuditLog)
            .where(AuditLog.event_type == "RETENTION_PURGE")
            .order_by(AuditLog.id.desc())
        )
        purge_audit = (await db_session.execute(stmt)).scalars().first()
        assert purge_audit is not None
        assert purge_audit.payload["dry_run"] is False
        assert purge_audit.payload["purged_count"] >= 1

        # Verify audit hash chain is STILL completely valid
        chain_after = await verify_chain(db_session)
        assert chain_after["valid"] is True
        assert chain_after["checked"] >= chain_before["checked"] + 1

    finally:
        app_row = await db_session.get(Application, uuid.UUID(app_id))
        if app_row:
            await db_session.execute(delete(Applicant).where(Applicant.id == app_row.applicant_id))
            await db_session.commit()
