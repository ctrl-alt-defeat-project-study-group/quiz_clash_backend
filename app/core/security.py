"""
Password hashing (Argon2), JWT token creation/verification, email token helpers, and cookie utils.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from typing import Any, Dict, Tuple

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from fastapi import HTTPException, Response
import jwt

from app.core.config import settings

_password_hasher = PasswordHasher()


def api_error(status_code: int, code: str, message: str) -> HTTPException:
    """Build a structured HTTPException matching the API contract."""
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def validate_password_strength(password: str) -> None:
    """Enforce baseline password strength rules."""
    if len(password) < 8:
        raise api_error(
            422,
            "VALIDATION_ERROR",
            "Password must be at least 8 characters long.",
        )
    if not any(ch.isalpha() for ch in password) or not any(ch.isdigit() for ch in password):
        raise api_error(
            422,
            "VALIDATION_ERROR",
            "Password must contain at least one letter and one number.",
        )


def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2id."""
    return _password_hasher.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a plaintext password against an Argon2 hash."""
    try:
        return _password_hasher.verify(password_hash, plain_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_access_token(user_id: int, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "iat": now,
        "exp": now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str, expected_type: str) -> Dict[str, Any]:
    """Decode and validate a JWT of the expected type ('access' or 'refresh')."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.PyJWTError:
        raise api_error(401, "UNAUTHORIZED", "Invalid or expired authentication token.")

    if payload.get("type") != expected_type or not payload.get("sub"):
        raise api_error(401, "UNAUTHORIZED", "Invalid authentication token type.")

    return payload


def set_auth_cookies(response: Response, user_id: int, role: str) -> None:
    """Attach httpOnly access and refresh cookies to a response."""
    access_token = create_access_token(user_id=user_id, role=role)
    refresh_token = create_refresh_token(user_id=user_id)

    cookie_kwargs: Dict[str, Any] = {
        "httponly": True,
        "secure": settings.COOKIE_SECURE,
        "samesite": settings.COOKIE_SAMESITE,
        "path": "/",
    }
    if settings.COOKIE_DOMAIN:
        cookie_kwargs["domain"] = settings.COOKIE_DOMAIN

    response.set_cookie(
        key=settings.ACCESS_COOKIE_NAME,
        value=access_token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        **cookie_kwargs,
    )
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        **cookie_kwargs,
    )


def clear_auth_cookies(response: Response) -> None:
    """Clear auth cookies from the client."""
    delete_kwargs: Dict[str, Any] = {"path": "/"}
    if settings.COOKIE_DOMAIN:
        delete_kwargs["domain"] = settings.COOKIE_DOMAIN

    response.delete_cookie(key=settings.ACCESS_COOKIE_NAME, **delete_kwargs)
    response.delete_cookie(key=settings.REFRESH_COOKIE_NAME, **delete_kwargs)


def generate_email_token() -> Tuple[str, str]:
    """Return (raw_token, sha256_hash) for one-time email verification or password reset."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_email_token(raw)


def hash_email_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
