import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.services.audit.service import append_event, verify_chain

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_append_event_and_verify_chain(db_session):
    before = await verify_chain(db_session)
    assert before["valid"] is True

    entry = await append_event(
        db_session, event_type="LOGIN", actor="chain-test-a@x.com", payload={"success": True}
    )
    await db_session.commit()

    after = await verify_chain(db_session)
    assert after["valid"] is True
    assert after["checked"] == before["checked"] + 1
    assert entry.row_hash
    assert entry.prev_hash


@pytest.mark.asyncio
async def test_chained_events_link_via_prev_hash(db_session):
    first = await append_event(
        db_session, event_type="LOGIN", actor="chain-test-b@x.com", payload={}
    )
    await db_session.commit()
    second = await append_event(
        db_session, event_type="LOGIN", actor="chain-test-c@x.com", payload={}
    )
    await db_session.commit()

    assert second.prev_hash == first.row_hash
    assert second.row_hash != first.row_hash


# The tamper-detection test lives in test_audit_tamper_isolated.py, against a
# throwaway database: proving it requires disabling the anti-tamper trigger, which
# would otherwise permanently poison this shared dev database's real hash chain.


@pytest.mark.asyncio
async def test_app_role_cannot_update_audit_log(db_session):
    entry = await append_event(
        db_session, event_type="LOGIN", actor="chain-test-d@x.com", payload={}
    )
    await db_session.commit()

    with pytest.raises(DBAPIError):
        await db_session.execute(
            text("UPDATE audit_log SET actor = 'tampered' WHERE id = :id"), {"id": entry.id}
        )
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_app_role_cannot_delete_audit_log(db_session):
    entry = await append_event(
        db_session, event_type="LOGIN", actor="chain-test-e@x.com", payload={}
    )
    await db_session.commit()

    with pytest.raises(DBAPIError):
        await db_session.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": entry.id})
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_app_role_cannot_truncate_audit_log(db_session):
    with pytest.raises(DBAPIError):
        await db_session.execute(text("TRUNCATE audit_log"))
        await db_session.commit()
    await db_session.rollback()
