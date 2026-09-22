import time

import jwt
import pytest

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    hmac_sha256_hex,
    mask_pan,
    phone_last4,
    verify_password,
)

pytestmark = pytest.mark.unit


def test_password_hash_roundtrip():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)


def test_password_hash_rejects_wrong_password():
    hashed = hash_password("correct horse battery staple")
    assert not verify_password("wrong password", hashed)


def test_password_hash_rejects_malformed_hash():
    assert not verify_password("anything", "not-a-real-argon2-hash")


def test_jwt_roundtrip():
    token = create_access_token(
        subject="user-1", email="a@b.com", role="underwriter", expires_minutes=30, secret="s" * 32
    )
    payload = decode_access_token(token, "s" * 32)
    assert payload["sub"] == "user-1"
    assert payload["email"] == "a@b.com"
    assert payload["role"] == "underwriter"


def test_jwt_rejects_tampered_signature():
    token = create_access_token(
        subject="user-1", email="a@b.com", role="underwriter", expires_minutes=30, secret="s" * 32
    )
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(tampered, "s" * 32)


def test_jwt_rejects_wrong_secret():
    token = create_access_token(
        subject="user-1", email="a@b.com", role="underwriter", expires_minutes=30, secret="s" * 32
    )
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, "different-secret-32-characters!!")


def test_jwt_expires():
    token = create_access_token(
        subject="user-1", email="a@b.com", role="underwriter", expires_minutes=-1, secret="s" * 32
    )
    time.sleep(0.01)
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token, "s" * 32)


def test_hmac_sha256_hex_is_deterministic_and_keyed():
    a = hmac_sha256_hex("123456789012", "pepper-a")
    b = hmac_sha256_hex("123456789012", "pepper-a")
    c = hmac_sha256_hex("123456789012", "pepper-b")
    assert a == b
    assert a != c
    assert len(a) == 64


def test_mask_pan():
    assert mask_pan("ABCDE1234F") == "ABCDE****F"


def test_phone_last4():
    assert phone_last4("+91 98765 43210") == "3210"
