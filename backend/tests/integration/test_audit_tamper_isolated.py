"""Proves verify_chain() detects out-of-band tampering (e.g. a hand-edited backup
restore, or an attacker with elevated DB access): update a row's payload directly at
the SQL level, bypassing append_event, and confirm verify_chain flags exactly that row.

Runs against a throwaway database created/migrated/dropped here, never the shared dev
database: demonstrating this requires disabling the anti-tamper trigger (see migration
0001), which would otherwise permanently break that database's real hash chain for the
rest of the dev/demo session.

Deliberately synchronous for the same reason as test_migrations.py: alembic's
`command.upgrade` calls `asyncio.run(...)` internally.
"""

import asyncio
import os
import uuid
from urllib.parse import urlsplit

import asyncpg
import pytest
from alembic.config import Config
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from app.core.config import settings
from app.services.audit.service import append_event, verify_chain

pytestmark = pytest.mark.integration


def _db_host_port() -> tuple[str, int]:
    parsed = urlsplit(settings.database_url)
    return parsed.hostname or "db", parsed.port or 5432


def _admin_dsn(database: str) -> str:
    host, port = _db_host_port()
    return f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}@{host}:{port}/{database}"


def _app_async_dsn(database: str) -> str:
    host, port = _db_host_port()
    return f"postgresql+asyncpg://{os.environ['APP_DB_USER']}:{os.environ['APP_DB_PASSWORD']}@{host}:{port}/{database}"


async def _create_db(test_db: str) -> None:
    conn = await asyncpg.connect(_admin_dsn(os.environ["POSTGRES_DB"]))
    try:
        await conn.execute(f'CREATE DATABASE "{test_db}"')
    finally:
        await conn.close()


async def _drop_db(test_db: str) -> None:
    conn = await asyncpg.connect(_admin_dsn(os.environ["POSTGRES_DB"]))
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{test_db}" WITH (FORCE)')
    finally:
        await conn.close()


async def _exercise_tamper(test_db: str) -> tuple[dict, int]:
    engine = create_async_engine(_app_async_dsn(test_db))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            entry = await append_event(
                session, event_type="LOGIN", actor="tamper@x.test", payload={}
            )
            await session.commit()
            entry_id = entry.id

        admin_conn = await asyncpg.connect(_admin_dsn(test_db))
        try:
            await admin_conn.execute("ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_update")
            await admin_conn.execute(
                "UPDATE audit_log SET payload = $1 WHERE id = $2", '{"success": true}', entry_id
            )
            await admin_conn.execute("ALTER TABLE audit_log ENABLE TRIGGER audit_log_no_update")
        finally:
            await admin_conn.close()

        async with session_factory() as session:
            result = await verify_chain(session)
        return result, entry_id
    finally:
        await engine.dispose()


def test_verify_chain_detects_a_tampered_row_in_an_isolated_database():
    test_db = f"audit_tamper_test_{uuid.uuid4().hex[:10]}"
    asyncio.run(_create_db(test_db))
    original_db = os.environ["POSTGRES_DB"]
    os.environ["POSTGRES_DB"] = test_db
    try:
        command.upgrade(Config("alembic.ini"), "head")
        result, entry_id = asyncio.run(_exercise_tamper(test_db))
    finally:
        os.environ["POSTGRES_DB"] = original_db
        asyncio.run(_drop_db(test_db))

    assert result["valid"] is False
    assert result["first_broken_id"] == entry_id
