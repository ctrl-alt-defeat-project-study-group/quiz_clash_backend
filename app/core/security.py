"""
Password hashing (Argon2), JWT token creation/verification, email token helpers, and cookie utils.
"""
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import secrets
from typing import Any, Dict, Optional, Tuple

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from fastapi import HTTPException, Response
import jwt

from app.core.config import settings
from app.core.errors import api_error

_password_hasher = PasswordHasher()


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


def verify_password(plain_password: str, password_hash: Optional[str]) -> bool:
    """Verify a plaintext password against an Argon2 hash."""
    if not password_hash:
        return False
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
    delete_kwargs: Dict[str, Any] = {
        "path": "/",
        "httponly": True,
        "secure": settings.COOKIE_SECURE,
        "samesite": settings.COOKIE_SAMESITE,
    }
    if settings.COOKIE_DOMAIN:
        delete_kwargs["domain"] = settings.COOKIE_DOMAIN

    response.delete_cookie(key=settings.ACCESS_COOKIE_NAME, **delete_kwargs)
    response.delete_cookie(key=settings.REFRESH_COOKIE_NAME, **delete_kwargs)


def create_pending_registration_token(
    email: str,
    display_name: str,
    password_hash: str,
    otp_hash: str,
    expires_minutes: Optional[int] = None,
) -> str:
    """Create a short-lived signed JWT holding a pending (unverified) registration."""
    now = datetime.now(timezone.utc)
    ttl_minutes = (
        expires_minutes
        if expires_minutes is not None
        else settings.PENDING_REG_EXPIRE_MINUTES
    )
    payload = {
        "type": "pending_registration",
        "email": email,
        "display_name": display_name,
        "password_hash": password_hash,
        "otp_hash": otp_hash,
        "iat": now,
        "exp": now + timedelta(minutes=ttl_minutes),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_pending_registration_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and validate a pending registration JWT; returns None on any error."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.PyJWTError:
        return None
    if payload.get("type") != "pending_registration":
        return None
    required_keys = ("email", "display_name", "password_hash", "otp_hash")
    if not all(isinstance(payload.get(k), str) and payload.get(k) for k in required_keys):
        return None
    return payload


def set_pending_registration_cookie(response: Response, token: str) -> None:
    """Attach httpOnly pending registration cookie to a response."""
    cookie_kwargs: Dict[str, Any] = {
        "httponly": True,
        "secure": settings.COOKIE_SECURE,
        "samesite": settings.COOKIE_SAMESITE,
        "path": "/",
    }
    if settings.COOKIE_DOMAIN:
        cookie_kwargs["domain"] = settings.COOKIE_DOMAIN

    response.set_cookie(
        key=settings.PENDING_REG_COOKIE_NAME,
        value=token,
        max_age=settings.PENDING_REG_EXPIRE_MINUTES * 60,
        **cookie_kwargs,
    )


def clear_pending_registration_cookie(response: Response) -> None:
    """Clear the pending registration cookie from the client."""
    delete_kwargs: Dict[str, Any] = {
        "path": "/",
        "httponly": True,
        "secure": settings.COOKIE_SECURE,
        "samesite": settings.COOKIE_SAMESITE,
    }
    if settings.COOKIE_DOMAIN:
        delete_kwargs["domain"] = settings.COOKIE_DOMAIN

    response.delete_cookie(key=settings.PENDING_REG_COOKIE_NAME, **delete_kwargs)


def generate_email_token() -> Tuple[str, str]:
    """Return (raw_token, sha256_hash) for one-time email verification or password reset."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_email_token(raw)


def generate_email_otp() -> Tuple[str, str]:
    """Return (6-digit numeric OTP, sha256_hash) for one-time email verification."""
    raw = f"{secrets.randbelow(1_000_000):06d}"
    return raw, hash_email_token(raw)


def hash_email_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_pkce_pair() -> Tuple[str, str]:
    """Generate a PKCE (code_verifier, code_challenge) pair using S256."""
    code_verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def create_oauth_state_token(
    provider: str,
    state: str,
    code_verifier: str,
    next_path: str,
    mode: str = "login",
) -> str:
    """Create a short-lived signed JWT storing OAuth CSRF state, PKCE verifier, and mode."""
    now = datetime.now(timezone.utc)
    normalized_mode = "register" if mode == "register" else "login"
    payload = {
        "type": "oauth_state",
        "provider": provider,
        "state": state,
        "code_verifier": code_verifier,
        "next": next_path,
        "mode": normalized_mode,
        "iat": now,
        "exp": now + timedelta(seconds=settings.OAUTH_STATE_EXPIRE_SECONDS),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_oauth_state_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and validate an OAuth state JWT; returns None on any error."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.PyJWTError:
        return None
    if payload.get("type") != "oauth_state":
        return None
    return payload
