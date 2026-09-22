from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# The app always connects through DATABASE_URL, which points at the least-privilege
# APP_DB_USER role (see migration 0001) -- never the admin/migration role.
#
# Note on pgvector + asyncpg: `historical_borrowers.signal_vector` is declared
# with `pgvector.sqlalchemy.Vector` (see db/models.py), which is a SQLAlchemy
# UserDefinedType that serialises a Python list to a Postgres `vector` literal
# STRING itself (Vector._to_db) and lets Postgres implicitly cast it -- this
# already works correctly over asyncpg with no further wiring. Do NOT also
# register `pgvector.asyncpg.register_vector` on the connection: that installs
# a native asyncpg codec for the `vector` OID which expects a raw list/ndarray
# parameter, not the string `Vector._to_db` already produced -- the two
# integration paths are mutually exclusive. Combining them was tried during
# Phase 6 and broke every bulk insert into this column with
# `asyncpg.exceptions.DataError: invalid input ... expected list or ndarray`;
# removing the codec registration (this comment's history) fixed it.
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
