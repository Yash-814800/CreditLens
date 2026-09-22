from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import CurrentUser, get_current_user
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token, verify_password
from app.db.models import User
from app.db.session import get_session
from app.schemas.auth import LoginRequest, LoginResponse, MeResponse
from app.services.audit.service import append_event

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
@limiter.limit(settings.rate_limit_login)
async def login(
    request: Request, body: LoginRequest, session: AsyncSession = Depends(get_session)
) -> LoginResponse:
    user = await session.scalar(select(User).where(User.email == body.email))
    success = (
        user is not None and user.is_active and verify_password(body.password, user.password_hash)
    )

    # Audited regardless of outcome (CLAUDE.md audit event LOGIN) -- never logs the password.
    await append_event(session, event_type="LOGIN", actor=body.email, payload={"success": success})
    await session.commit()

    if not success or user is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(
        subject=str(user.id),
        email=user.email,
        role=user.role,
        expires_minutes=settings.jwt_expire_minutes,
        secret=settings.jwt_secret,
    )
    return LoginResponse(access_token=token, role=user.role)


@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUser = Depends(get_current_user)) -> MeResponse:
    return MeResponse(id=user.id, email=user.email, role=user.role)
