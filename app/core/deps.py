"""
FastAPI authentication & authorization dependencies.
"""
from typing import Optional

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import api_error, decode_token
from app.db.models import User
from app.db.session import get_db


def _load_authenticated_user(request: Request, db: Session) -> Optional[User]:
    token = request.cookies.get(settings.ACCESS_COOKIE_NAME)
    if not token:
        return None

    payload = decode_token(token, expected_type="access")
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        raise api_error(401, "UNAUTHORIZED", "Invalid authentication token subject.")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise api_error(401, "UNAUTHORIZED", "User account no longer exists.")

    if not user.is_active:
        raise api_error(403, "ACCOUNT_DISABLED", "This account has been deactivated.")

    if user.email_verified_at is None:
        raise api_error(403, "EMAIL_NOT_VERIFIED", "Please verify your email address first.")

    return user


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """Require an authenticated, active, verified user."""
    user = _load_authenticated_user(request, db)
    if user is None:
        raise api_error(401, "UNAUTHORIZED", "Authentication required.")
    return user


def get_optional_user(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Return the authenticated user if present and valid; otherwise None (for guest routes)."""
    token = request.cookies.get(settings.ACCESS_COOKIE_NAME)
    if not token:
        return None
    try:
        return _load_authenticated_user(request, db)
    except Exception:
        return None


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Require an authenticated admin user."""
    if current_user.role != "admin":
        raise api_error(403, "FORBIDDEN", "Administrator privileges required.")
    return current_user


def ensure_owner_or_admin(owner_id: Optional[int], current_user: User) -> None:
    """Enforce resource ownership unless the current user is an admin."""
    if current_user.role == "admin":
        return
    if owner_id != current_user.id:
        raise api_error(403, "FORBIDDEN", "You do not have permission to access this resource.")
