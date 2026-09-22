"""Seeds one demo user per role from DEMO_*_PASSWORD env vars. Idempotent: re-running
skips users that already exist. Refuses nothing itself in production -- app config
already refuses to even start in production if these are left at their placeholder
value (see app.core.config.Settings.production_guard_errors), so if this script runs
at all in production the passwords are real ones the deployer chose.
"""

import asyncio

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.models import User
from app.db.session import async_session_factory

_DEMO_USERS = (
    ("underwriter@creditlens.demo", "underwriter", settings.demo_underwriter_password),
    ("auditor@creditlens.demo", "auditor", settings.demo_auditor_password),
    ("admin@creditlens.demo", "admin", settings.demo_admin_password),
)


async def seed() -> None:
    async with async_session_factory() as session:
        for email, role, password in _DEMO_USERS:
            if not password:
                print(f"skip {email}: no {role} password configured")
                continue
            existing = await session.scalar(select(User).where(User.email == email))
            if existing is not None:
                print(f"exists: {email} ({role})")
                continue
            session.add(
                User(email=email, password_hash=hash_password(password), role=role, is_active=True)
            )
            print(f"created: {email} ({role})")
        await session.commit()


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
