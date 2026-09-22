import pytest

from app.core.security import hash_password
from app.db.models import User

pytestmark = pytest.mark.integration


async def _create_user(db_session, email, role, password):
    user = User(email=email, password_hash=hash_password(password), role=role, is_active=True)
    db_session.add(user)
    await db_session.commit()
    return user


@pytest.mark.asyncio
async def test_login_success_returns_token_with_role(client, db_session, unique_email):
    await _create_user(db_session, unique_email, "underwriter", "correct-password-123")

    resp = await client.post(
        "/api/v1/auth/login", json={"email": unique_email, "password": "correct-password-123"}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "underwriter"
    assert body["token_type"] == "bearer"
    assert body["access_token"]


@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(client, db_session, unique_email):
    await _create_user(db_session, unique_email, "underwriter", "correct-password-123")

    resp = await client.post(
        "/api/v1/auth/login", json={"email": unique_email, "password": "wrong"}
    )

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_email_returns_401(client):
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@nowhere.demo", "password": "x"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_inactive_user_returns_401(client, db_session, unique_email):
    user = await _create_user(db_session, unique_email, "underwriter", "correct-password-123")
    user.is_active = False
    await db_session.commit()

    resp = await client.post(
        "/api/v1/auth/login", json={"email": unique_email, "password": "correct-password-123"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_protected_endpoint_without_token_is_401(client):
    resp = await client.get("/api/v1/audit/verify")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_protected_endpoint_with_wrong_role_is_403(client, db_session, unique_email):
    await _create_user(db_session, unique_email, "underwriter", "correct-password-123")
    login = await client.post(
        "/api/v1/auth/login", json={"email": unique_email, "password": "correct-password-123"}
    )
    token = login.json()["access_token"]

    resp = await client.get("/api/v1/audit/verify", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_protected_endpoint_with_correct_role_is_200_for_auditor(
    client, db_session, unique_email
):
    await _create_user(db_session, unique_email, "auditor", "correct-password-123")
    login = await client.post(
        "/api/v1/auth/login", json={"email": unique_email, "password": "correct-password-123"}
    )
    token = login.json()["access_token"]

    resp = await client.get("/api/v1/audit/verify", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert "valid" in resp.json()


@pytest.mark.asyncio
async def test_protected_endpoint_with_correct_role_is_200_for_admin(
    client, db_session, unique_email
):
    await _create_user(db_session, unique_email, "admin", "correct-password-123")
    login = await client.post(
        "/api/v1/auth/login", json={"email": unique_email, "password": "correct-password-123"}
    )
    token = login.json()["access_token"]

    resp = await client.get("/api/v1/audit/verify", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_invalid_bearer_token_is_401(client):
    resp = await client.get(
        "/api/v1/audit/verify", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_endpoint_returns_identity(client, db_session, unique_email):
    await _create_user(db_session, unique_email, "admin", "correct-password-123")
    login = await client.post(
        "/api/v1/auth/login", json={"email": unique_email, "password": "correct-password-123"}
    )
    token = login.json()["access_token"]

    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == unique_email
    assert body["role"] == "admin"


@pytest.mark.asyncio
async def test_login_failure_is_audited(client, db_session, unique_email):
    from sqlalchemy import select

    from app.db.models import AuditLog

    await client.post("/api/v1/auth/login", json={"email": unique_email, "password": "whatever"})

    row = await db_session.scalar(
        select(AuditLog).where(AuditLog.actor == unique_email).order_by(AuditLog.id.desc())
    )
    assert row is not None
    assert row.event_type == "LOGIN"
    assert row.payload == {"success": False}


@pytest.mark.asyncio
async def test_login_rate_limit_returns_rfc7807_shape(client, unique_email):
    """Regression test: slowapi's own default 429 handler returns a bare
    {"error": "..."} body, which used to be the one endpoint in the whole API
    with an error contract inconsistent with app/core/errors.py's RFC 7807
    problem+json shape (found via a real Playwright run of the frontend cockpit
    hitting this limit after a handful of demo logins)."""
    payload = {"email": unique_email, "password": "whatever"}
    for _ in range(5):
        await client.post("/api/v1/auth/login", json=payload)

    resp = await client.post("/api/v1/auth/login", json=payload)

    assert resp.status_code == 429
    assert resp.headers["content-type"] == "application/problem+json"
    body = resp.json()
    assert body["status"] == 429
    assert isinstance(body["detail"], str) and body["detail"]
    assert isinstance(body["title"], str) and body["title"]
