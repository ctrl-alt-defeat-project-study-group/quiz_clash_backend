"""
Tests for admin startup seeding (including existing-user promotion) and the admin CLI (app.cli).
"""
from unittest.mock import patch

import pytest

from app.cli import main as cli_main
from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.db.models import User
from app.db.session import Base, SessionLocal, engine
from app.services.bootstrap import seed_initial_admin


@pytest.fixture(autouse=True)
def reset_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def test_seed_initial_admin_creates_new_admin_and_is_idempotent():
    with (
        patch.object(settings, "ADMIN_EMAIL", "Founder@Example.com"),
        patch.object(settings, "ADMIN_PASSWORD", "StrongPass123"),
        patch.object(settings, "ADMIN_DISPLAY_NAME", "Site Admin"),
    ):
        seed_initial_admin()

    # Change ADMIN_PASSWORD and re-run: must NOT overwrite existing admin's password
    with (
        patch.object(settings, "ADMIN_EMAIL", "founder@example.com"),
        patch.object(settings, "ADMIN_PASSWORD", "DifferentPass456"),
        patch.object(settings, "ADMIN_DISPLAY_NAME", "Other Name"),
    ):
        seed_initial_admin()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "founder@example.com").first()
        assert user is not None
        assert user.role == "admin"
        assert user.is_active is True
        assert user.email_verified_at is not None
        assert user.display_name == "Site Admin"
        assert verify_password("StrongPass123", user.password_hash)
    finally:
        db.close()


def test_seed_initial_admin_promotes_existing_regular_user_without_overwriting_password():
    db = SessionLocal()
    try:
        existing = User(
            email="existing@example.com",
            password_hash=hash_password("UserOriginal123"),
            display_name="Existing User",
            role="user",
            is_active=False,
            email_verified_at=None,
        )
        db.add(existing)
        db.commit()
    finally:
        db.close()

    with (
        patch.object(settings, "ADMIN_EMAIL", "existing@example.com"),
        patch.object(settings, "ADMIN_PASSWORD", None),
    ):
        seed_initial_admin()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "existing@example.com").first()
        assert user is not None
        assert user.role == "admin"
        assert user.is_active is True
        assert user.email_verified_at is not None
        assert verify_password("UserOriginal123", user.password_hash)
    finally:
        db.close()


def test_seed_initial_admin_promotes_existing_oauth_only_user():
    db = SessionLocal()
    try:
        oauth_user = User(
            email="oauth-founder@example.com",
            password_hash=None,
            display_name="OAuth Founder",
            role="user",
            is_active=True,
            email_verified_at=None,
        )
        db.add(oauth_user)
        db.commit()
    finally:
        db.close()

    with (
        patch.object(settings, "ADMIN_EMAIL", "oauth-founder@example.com"),
        patch.object(settings, "ADMIN_PASSWORD", None),
    ):
        seed_initial_admin()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "oauth-founder@example.com").first()
        assert user is not None
        assert user.role == "admin"
        assert user.is_active is True
        assert user.email_verified_at is not None
        assert user.password_hash is None
    finally:
        db.close()


def test_seed_initial_admin_skips_unknown_email_when_password_missing(caplog):
    with (
        patch.object(settings, "ADMIN_EMAIL", "ghost@example.com"),
        patch.object(settings, "ADMIN_PASSWORD", None),
    ):
        with caplog.at_level("WARNING", logger="quizclash.bootstrap"):
            seed_initial_admin()

    db = SessionLocal()
    try:
        assert db.query(User).filter(User.email == "ghost@example.com").first() is None
    finally:
        db.close()
    assert "ADMIN_PASSWORD is not set" in caplog.text


def test_cli_create_admin_and_duplicate_handling(capsys):
    exit_code = cli_main(
        [
            "create-admin",
            "--email",
            "cli-admin@example.com",
            "--password",
            "AdminPass123",
            "--display-name",
            "CLI Admin",
        ]
    )
    assert exit_code == 0
    assert "Created admin account" in capsys.readouterr().out

    # Duplicate without --promote-existing fails cleanly
    dup_code = cli_main(
        [
            "create-admin",
            "--email",
            "cli-admin@example.com",
            "--password",
            "AdminPass123",
        ]
    )
    assert dup_code == 1
    assert "already exists" in capsys.readouterr().err

    # Weak password rejected
    weak_code = cli_main(
        [
            "create-admin",
            "--email",
            "weak@example.com",
            "--password",
            "short",
        ]
    )
    assert weak_code == 1
    assert "at least 8 characters" in capsys.readouterr().err


def test_cli_create_admin_with_promote_existing_and_promote_admin(capsys):
    db = SessionLocal()
    try:
        db.add(
            User(
                email="member1@example.com",
                password_hash=hash_password("MemberPass123"),
                display_name="Member One",
                role="user",
                is_active=True,
            )
        )
        db.add(
            User(
                email="member2@example.com",
                password_hash=None,
                display_name="Member Two",
                role="user",
                is_active=False,
            )
        )
        db.commit()
    finally:
        db.close()

    # Promote via create-admin --promote-existing (no password needed for existing user)
    code1 = cli_main(
        ["create-admin", "--email", "member1@example.com", "--promote-existing"]
    )
    assert code1 == 0
    assert "Promoted existing user to admin" in capsys.readouterr().out

    # Promote via promote-admin
    code2 = cli_main(["promote-admin", "--email", "member2@example.com"])
    assert code2 == 0
    assert "Promoted user to admin" in capsys.readouterr().out

    # Idempotent re-run
    code2_again = cli_main(["promote-admin", "--email", "member2@example.com"])
    assert code2_again == 0
    assert "already an active admin" in capsys.readouterr().out

    # Unknown email fails
    missing_code = cli_main(["promote-admin", "--email", "nobody@example.com"])
    assert missing_code == 1
    assert "not found" in capsys.readouterr().err

    # list-admins displays both promoted admins
    list_code = cli_main(["list-admins"])
    assert list_code == 0
    output = capsys.readouterr().out
    assert "member1@example.com" in output
    assert "member2@example.com" in output
