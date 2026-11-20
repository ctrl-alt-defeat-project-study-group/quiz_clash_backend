"""
Startup bootstrap helpers (e.g., seeding the initial admin account).
"""
from datetime import datetime, timezone
import logging

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.security import hash_password
from app.db.models import User
from app.db.session import SessionLocal

logger = logging.getLogger("quizclash.bootstrap")


def seed_initial_admin() -> None:
    """Seed the initial admin user from ADMIN_EMAIL / ADMIN_PASSWORD if configured."""
    if not settings.ADMIN_EMAIL or not settings.ADMIN_PASSWORD:
        return

    email = settings.ADMIN_EMAIL.strip().lower()
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            return

        admin = User(
            email=email,
            password_hash=hash_password(settings.ADMIN_PASSWORD),
            display_name=settings.ADMIN_DISPLAY_NAME or "Admin",
            role="admin",
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(admin)
        db.commit()
        logger.info("Seeded initial admin user: %s", email)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.warning("Skipping admin seed (database not ready): %s", exc)
    finally:
        db.close()
