import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.db.base import Base
from app.db.models import *  # noqa: F401,F403 -- registers every table on Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _admin_database_url() -> str:
    """Migrations (CREATE TABLE/ROLE/TRIGGER) must run as the Postgres admin/migration
    role (POSTGRES_USER), never the least-privilege runtime role in DATABASE_URL
    (APP_DB_USER) -- that role deliberately cannot create roles, tables or triggers.
    """
    app_url = make_url(os.environ["DATABASE_URL"])
    admin_url = app_url.set(
        username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        database=os.environ["POSTGRES_DB"],
    )
    # plain str(url) masks the password as "***" (safe-by-default for logging/repr) --
    # render_as_string(hide_password=False) is required to get the real credential.
    return admin_url.render_as_string(hide_password=False)


def run_migrations_offline() -> None:
    context.configure(
        url=_admin_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _admin_database_url()
    connectable = async_engine_from_config(
        configuration, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
