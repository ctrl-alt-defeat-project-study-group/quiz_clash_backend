"""
Startup bootstrap helpers (e.g., seeding the initial admin and demo user accounts).
"""
from datetime import datetime, timezone
import logging
from typing import Optional

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

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
    *,
    promote_existing: bool = False,
) -> None:
    """Idempotently seed (or promote, for admins) a verified, active user account."""
    if not email:
        return

    normalized_email = email.strip().lower()
    if not normalized_email:
        return

    if not promote_existing and not password:
        return

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == normalized_email).first()
        if existing:
            if promote_existing:
                changed = False
                if existing.role != role:
                    existing.role = role
                    changed = True
                if not existing.is_active:
                    existing.is_active = True
                    changed = True
                if existing.email_verified_at is None:
                    existing.email_verified_at = datetime.now(timezone.utc)
                    changed = True
                if changed:
                    db.commit()
                    logger.info("Promoted existing user to %s: %s", role, normalized_email)
            return

        if not password:
            logger.warning(
                "ADMIN_EMAIL (%s) does not match an existing user and ADMIN_PASSWORD is not set; "
                "skipping %s creation.",
                normalized_email,
                role,
            )
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
    except IntegrityError:
        db.rollback()
        logger.info(
            "Initial %s user already exists (concurrent startup): %s",
            role,
            normalized_email,
        )
    except SQLAlchemyError as exc:
        db.rollback()
        logger.warning("Skipping %s seed (database not ready): %s", role, exc)
    finally:
        db.close()


def seed_initial_admin() -> None:
    """Seed or promote the initial admin user from ADMIN_EMAIL / ADMIN_PASSWORD if configured."""
    _seed_user(
        email=settings.ADMIN_EMAIL,
        password=settings.ADMIN_PASSWORD,
        display_name=settings.ADMIN_DISPLAY_NAME or "Admin",
        role="admin",
        promote_existing=True,
    )


def seed_initial_user() -> None:
    """Seed the initial regular user from DEMO_USER_EMAIL / DEMO_USER_PASSWORD if configured."""
    _seed_user(
        email=settings.DEMO_USER_EMAIL,
        password=settings.DEMO_USER_PASSWORD,
        display_name=settings.DEMO_USER_DISPLAY_NAME or "Demo User",
        role="user",
        promote_existing=False,
    )
