from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

from app.core.config import settings
from app.core.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str
    role: str


async def get_current_user(token: Annotated[str | None, Depends(oauth2_scheme)]) -> CurrentUser:
    if token is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_access_token(token, settings.jwt_secret)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc
    return CurrentUser(id=payload["sub"], email=payload.get("email", ""), role=payload["role"])


def require_roles(*roles: str):
    """RBAC dependency factory. Role matrix (CLAUDE.md): underwriter can create/read
    applications and override decisions; auditor is read-only including the audit log;
    admin can do everything. Enforced per-endpoint by passing the allowed roles here.
    """

    async def _dependency(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient role for this operation")
        return user

    return _dependency
