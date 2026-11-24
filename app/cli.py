"""
Command-line management utilities for QuizClash Backend.

Usage:
    python -m app.cli create-admin --email admin@example.com [--password ...] [--display-name Admin] [--promote-existing]
    python -m app.cli promote-admin --email user@example.com
    python -m app.cli list-admins
"""
import argparse
from datetime import datetime, timezone
import getpass
import sys
from typing import List, Optional, Sequence, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.security import hash_password, validate_password_strength
from app.db.models import User
from app.db.session import SessionLocal


def _normalize_email(email: str) -> str:
    normalized = (email or "").strip().lower()
    if not normalized or "@" not in normalized:
        raise ValueError(f"Invalid email address: {email!r}")
    return normalized


def _validate_password_or_raise(password: str) -> None:
    try:
        validate_password_strength(password)
    except HTTPException as exc:
        detail = exc.detail
        if isinstance(detail, dict) and detail.get("message"):
            raise ValueError(detail["message"]) from exc
        raise ValueError(str(detail)) from exc


def create_admin_user(
    db: Session,
    email: str,
    password: Optional[str] = None,
    display_name: str = "Admin",
    *,
    promote_existing: bool = False,
) -> Tuple[User, str]:
    """Create a new verified, active admin user (or promote an existing user if requested)."""
    normalized_email = _normalize_email(email)
    existing = db.query(User).filter(User.email == normalized_email).first()

    if existing:
        if not promote_existing:
            raise ValueError(
                f"User '{normalized_email}' already exists. "
                "Use 'promote-admin' or pass --promote-existing."
            )
        return promote_user_to_admin(db, normalized_email)

    if not password:
        raise ValueError("Password is required when creating a new admin account.")

    _validate_password_or_raise(password)

    user = User(
        email=normalized_email,
        password_hash=hash_password(password),
        display_name=(display_name or "Admin").strip() or "Admin",
        role="admin",
        is_active=True,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, "created"


def promote_user_to_admin(db: Session, email: str) -> Tuple[User, str]:
    """Promote an existing user (including OAuth-only users) to an active, verified admin."""
    normalized_email = _normalize_email(email)
    user = db.query(User).filter(User.email == normalized_email).first()
    if not user:
        raise ValueError(f"User '{normalized_email}' not found.")

    changed = False
    if user.role != "admin":
        user.role = "admin"
        changed = True
    if not user.is_active:
        user.is_active = True
        changed = True
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(timezone.utc)
        changed = True

    if changed:
        db.commit()
        db.refresh(user)
        return user, "promoted"

    return user, "unchanged"


def list_admin_users(db: Session) -> List[User]:
    """Return all users with role == 'admin' ordered by ID."""
    return (
        db.query(User)
        .filter(User.role == "admin")
        .order_by(User.id.asc())
        .all()
    )


def _prompt_password() -> str:
    password = getpass.getpass("Admin password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        raise ValueError("Passwords do not match.")
    return password


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="QuizClash administrative CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser(
        "create-admin",
        help="Create a new verified admin account (or promote an existing one).",
    )
    create_parser.add_argument("--email", required=True, help="Admin email address")
    create_parser.add_argument(
        "--password",
        default=None,
        help="Admin password (if omitted, you will be prompted securely)",
    )
    create_parser.add_argument(
        "--display-name",
        default="Admin",
        help="Display name for the admin account (default: Admin)",
    )
    create_parser.add_argument(
        "--promote-existing",
        action="store_true",
        help="If the email already exists, promote it to admin instead of failing",
    )

    promote_parser = subparsers.add_parser(
        "promote-admin",
        help="Promote an existing user (including Google OAuth accounts) to admin.",
    )
    promote_parser.add_argument("--email", required=True, help="Existing user's email address")

    subparsers.add_parser(
        "list-admins",
        help="List all current admin accounts.",
    )

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        if args.command == "create-admin":
            normalized_email = _normalize_email(args.email)
            existing = db.query(User).filter(User.email == normalized_email).first()
            password = args.password
            if not existing and password is None:
                password = _prompt_password()

            user, action = create_admin_user(
                db=db,
                email=normalized_email,
                password=password,
                display_name=args.display_name,
                promote_existing=args.promote_existing,
            )
            if action == "created":
                print(f"Created admin account: id={user.id} email={user.email}")
            elif action == "promoted":
                print(f"Promoted existing user to admin: id={user.id} email={user.email}")
            else:
                print(f"User is already an active admin: id={user.id} email={user.email}")
            return 0

        if args.command == "promote-admin":
            user, action = promote_user_to_admin(db=db, email=args.email)
            if action == "promoted":
                print(f"Promoted user to admin: id={user.id} email={user.email}")
            else:
                print(f"User is already an active admin: id={user.id} email={user.email}")
            return 0

        if args.command == "list-admins":
            admins = list_admin_users(db)
            if not admins:
                print("No admin accounts found.")
                return 0
            print(f"{'ID':<6} {'EMAIL':<32} {'NAME':<20} {'ACTIVE':<8} {'VERIFIED':<10} {'PASSWORD'}")
            for admin in admins:
                print(
                    f"{admin.id:<6} {admin.email:<32} {admin.display_name:<20} "
                    f"{str(admin.is_active):<8} {str(admin.email_verified_at is not None):<10} "
                    f"{str(admin.has_password)}"
                )
            return 0

        parser.print_help()
        return 1
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
