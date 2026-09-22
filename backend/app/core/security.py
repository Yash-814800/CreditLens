import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()

JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        # Malformed/legacy hash -- treat as a failed verification, never raise past auth.
        return False


def create_access_token(
    *, subject: str, email: str, role: str, expires_minutes: int, secret: str
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "email": email,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, secret: str) -> dict[str, Any]:
    return jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])


def hmac_sha256_hex(value: str, pepper: str) -> str:
    """CLAUDE.md rule 9: Aadhaar is never stored, only this HMAC. Also used for
    phone/PAN hashing so identity fields can be compared/deduped without storing them.
    """
    return hmac.new(pepper.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def mask_pan(pan: str) -> str:
    """ABCDE1234F -> ABCDE****F (never log/display the full PAN)."""
    if len(pan) <= 4:
        return "*" * len(pan)
    return pan[:5] + "*" * (len(pan) - 6) + pan[-1]


def phone_last4(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    return digits[-4:] if len(digits) >= 4 else digits
