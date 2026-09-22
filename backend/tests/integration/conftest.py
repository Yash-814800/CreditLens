import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory
from app.main import app


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
def unique_email() -> str:
    # NOT .test/.example/.invalid/.localhost: pydantic's EmailStr (via email-validator)
    # rejects those IANA-reserved special-use domains as "not a valid email address".
    return f"test-{uuid.uuid4().hex[:12]}@creditlens.demo"


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Every test shares one ASGITransport client (same process, same fake remote
    address), so without this the login-rate-limit tests would starve later tests
    of their own login attempts."""
    from app.core.rate_limit import limiter

    limiter.reset()
    yield


@pytest_asyncio.fixture(autouse=True, scope="session")
async def _ensure_history_seeded():
    """Ensure HistoricalBorrower is populated from history.parquet for integration tests
    that test precedent matching (e.g. P10 and P11 two-signal rules)."""
    import pandas as pd
    from scripts.seed_history import HISTORY_PATH, seed
    from sqlalchemy import func, select

    from app.db.models import HistoricalBorrower

    if HISTORY_PATH.exists():
        async with async_session_factory() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(HistoricalBorrower)
                .where(HistoricalBorrower.synthetic.is_(True))
            )
            if (count or 0) < 50:
                df = pd.read_parquet(HISTORY_PATH)
                await seed(df, session=session)
    yield
