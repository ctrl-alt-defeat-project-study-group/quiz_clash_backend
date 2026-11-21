"""
Startup bootstrap helpers (e.g., seeding the initial admin and demo user accounts).
"""
from datetime import datetime, timezone
import logging
from typing import Optional

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.security import hash_password
from app.db.models import User
from app.db.session import SessionLocal

logger = logging.getLogger("quizclash.bootstrap")


def _seed_user(
    email: Optional[str],
    password: Optional[str],
    display_name: str,
    role: str,
) -> None:
    """Idempotently seed a verified, active user account if credentials are configured."""
    if not email or not password:
        return

    normalized_email = email.strip().lower()
    if not normalized_email:
        return

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == normalized_email).first()
        if existing:
            return

        user = User(
            email=normalized_email,
            password_hash=hash_password(password),
            display_name=display_name,
            role=role,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
        logger.info("Seeded initial %s user: %s", role, normalized_email)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.warning("Skipping %s seed (database not ready): %s", role, exc)
    finally:
        db.close()


def seed_initial_admin() -> None:
    """Seed the initial admin user from ADMIN_EMAIL / ADMIN_PASSWORD if configured."""
    _seed_user(
        email=settings.ADMIN_EMAIL,
        password=settings.ADMIN_PASSWORD,
        display_name=settings.ADMIN_DISPLAY_NAME or "Admin",
        role="admin",
    )


def seed_initial_user() -> None:
    """Seed the initial regular user from DEMO_USER_EMAIL / DEMO_USER_PASSWORD if configured."""
    _seed_user(
        email=settings.DEMO_USER_EMAIL,
        password=settings.DEMO_USER_PASSWORD,
        display_name=settings.DEMO_USER_DISPLAY_NAME or "Demo User",
        role="user",
    )
