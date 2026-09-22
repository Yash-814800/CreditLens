from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin import router as admin_router
from app.api.v1.applications import fraud_router, meta_router
from app.api.v1.applications import router as applications_router
from app.api.v1.audit import router as audit_router
from app.api.v1.auth import router as auth_router
from app.api.v1.demo import router as demo_router
from app.core.config import settings
from app.core.errors import problem_response, register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import (
    MaxBodySizeMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.rate_limit import limiter
from app.db.session import get_session

configure_logging(settings.log_level)

app = FastAPI(title="CreditLens API", version="0.1.0")

app.state.limiter = limiter


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Same RFC 7807 problem+json shape as every other error response (app/core/errors.py) --
    slowapi's own default handler returns a bare {"error": "..."} body, which would otherwise
    be the one endpoint in the whole API with an inconsistent error contract."""
    return problem_response(
        429, "Too Many Requests", "Too many requests. Please wait a moment and try again."
    )


app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
register_exception_handlers(app)

app.add_middleware(SlowAPIMiddleware)
app.add_middleware(MaxBodySizeMiddleware, max_bytes=settings.max_upload_bytes)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(audit_router)
app.include_router(applications_router)
app.include_router(meta_router)
app.include_router(fraud_router)
app.include_router(demo_router)
app.include_router(admin_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe. Does not touch the DB -- see /readyz for that."""
    return {"status": "ok", "env": settings.app_env}


@app.get("/readyz")
async def readyz(session: AsyncSession = Depends(get_session)):
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        return problem_response(503, "Service Unavailable", "Database is not reachable.")
    return {"status": "ready"}
