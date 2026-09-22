"""Runs the full migration chain against a throwaway database, never the shared
dev database other integration tests use -- see the comment on the migration's
downgrade() for why: APP_DB_USER is a cluster-wide role and a downgrade must not
touch its existence, only this database's grants.

Deliberately synchronous (no @pytest.mark.asyncio): alembic's `command.upgrade`/
`command.downgrade` each call `asyncio.run(...)` internally (see alembic/env.py), and
`asyncio.run` cannot be invoked from inside an already-running event loop.
"""

import asyncio
import os
import uuid
from urllib.parse import urlsplit

import asyncpg
import pytest
from alembic.config import Config

from alembic import command
from app.core.config import settings

pytestmark = pytest.mark.integration


def _admin_dsn(database: str) -> str:
    parsed = urlsplit(settings.database_url)
    host = parsed.hostname or "db"
    port = parsed.port or 5432
    return (
        f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
        f"@{host}:{port}/{database}"
    )


def test_migration_upgrade_then_downgrade_then_upgrade_again():
    test_db = f"migration_test_{uuid.uuid4().hex[:10]}"

    async def _create_db() -> None:
        conn = await asyncpg.connect(_admin_dsn(os.environ["POSTGRES_DB"]))
        try:
            await conn.execute(f'CREATE DATABASE "{test_db}"')
        finally:
            await conn.close()

    async def _drop_db() -> None:
        conn = await asyncpg.connect(_admin_dsn(os.environ["POSTGRES_DB"]))
        try:
            await conn.execute(f'DROP DATABASE IF EXISTS "{test_db}" WITH (FORCE)')
        finally:
            await conn.close()

    asyncio.run(_create_db())
    original_db = os.environ["POSTGRES_DB"]
    os.environ["POSTGRES_DB"] = test_db
    try:
        cfg = Config("alembic.ini")
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
    finally:
        os.environ["POSTGRES_DB"] = original_db
        asyncio.run(_drop_db())
    # If migrations had connected as the least-privilege APP_DB_USER instead of the
    # admin role, CREATE ROLE / CREATE TRIGGER / CREATE EXTENSION above would have
    # failed with a permission-denied error and this test would already have raised.
