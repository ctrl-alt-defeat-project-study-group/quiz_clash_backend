"""
Tests for POST /api/v1/auth/change-password (password update and OAuth initial password setup).
"""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import rate_limiter
from app.core.security import hash_password, set_auth_cookies
from app.db.models import Base, OAuthAccount, User
from app.db.session import SessionLocal, engine
from app.main import app


@pytest.fixture(autouse=True)
def reset_db():
    rate_limiter.reset()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def _create_verified_user(email: str, password: str | None) -> int:
    db = SessionLocal()
    try:
        user = User(
            email=email,
            password_hash=hash_password(password) if password else None,
            display_name="Test User",
            role="user",
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id
    finally:
        db.close()


def test_change_password_success_and_validation():
    _create_verified_user("alice@example.com", "OldPass123")

    with TestClient(app) as client:
        login_res = client.post(
            "/api/v1/auth/login",
            json={"email": "alice@example.com", "password": "OldPass123"},
        )
        assert login_res.status_code == 200

        # Wrong current password
        bad_cur = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "WrongPass1", "new_password": "NewPass123"},
        )
        assert bad_cur.status_code == 400
        assert bad_cur.json()["detail"]["code"] == "INVALID_CURRENT_PASSWORD"

        # Same password
        same_pw = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "OldPass123", "new_password": "OldPass123"},
        )
        assert same_pw.status_code == 400
        assert same_pw.json()["detail"]["code"] == "PASSWORD_UNCHANGED"

        # Weak new password
        weak_pw = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "OldPass123", "new_password": "short"},
        )
        assert weak_pw.status_code == 422
        assert weak_pw.json()["detail"]["code"] == "VALIDATION_ERROR"

        # Valid password change
        ok = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "OldPass123", "new_password": "NewPass456"},
        )
        assert ok.status_code == 200

        # Old password no longer works; new password works
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"email": "alice@example.com", "password": "OldPass123"},
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"email": "alice@example.com", "password": "NewPass456"},
            ).status_code
            == 200
        )


def test_change_password_disabled_for_oauth_only_user():
    user_id = _create_verified_user("oauth@gmail.com", None)
    db = SessionLocal()
    try:
        db.add(
            OAuthAccount(
                user_id=user_id,
                provider="google",
                provider_user_id="google-sub-pw-1",
                provider_email="oauth@gmail.com",
            )
        )
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        from fastapi import Response

        dummy = Response()
        set_auth_cookies(dummy, user_id=user_id, role="user")
        for header_val in dummy.headers.getlist("set-cookie"):
            pair = header_val.split(";", 1)[0]
            k, v = pair.split("=", 1)
            client.cookies.set(k, v)

        me_before = client.get("/api/v1/auth/me")
        assert me_before.status_code == 200
        assert me_before.json()["has_password"] is False

        res = client.post(
            "/api/v1/auth/change-password",
            json={"new_password": "FirstPass123"},
        )
        assert res.status_code == 400
        assert res.json()["detail"]["code"] == "OAUTH_PASSWORD_MANAGED_EXTERNALLY"

        me_after = client.get("/api/v1/auth/me")
        assert me_after.status_code == 200
        assert me_after.json()["has_password"] is False


def test_register_sends_6_digit_otp_and_verifies_with_email():
    from unittest.mock import patch
    from app.services.mailer import MailerService

    captured: list[str] = []

    def fake_send(to_email: str, display_name: str, token: str) -> str:
        captured.append(token)
        return f"http://localhost:5173/verify-email?email={to_email}&token={token}"

    with patch.object(MailerService, "send_verification_email", side_effect=fake_send):
        with TestClient(app) as client:
            reg = client.post(
                "/api/v1/auth/register",
                json={
                    "email": "otpuser@example.com",
                    "password": "Password123",
                    "display_name": "OTP User",
                },
            )
            assert reg.status_code == 202
            assert len(captured) == 1
            otp = captured[0]
            assert len(otp) == 6 and otp.isdigit()

            # User row must NOT exist in DB before OTP verification
            db = SessionLocal()
            try:
                assert db.query(User).filter(User.email == "otpuser@example.com").first() is None
            finally:
                db.close()

            # Wrong email with valid OTP must fail and not create User
            wrong_email = client.post(
                "/api/v1/auth/verify-email",
                json={"email": "someoneelse@example.com", "token": otp},
            )
            assert wrong_email.status_code == 400

            # Correct email + 6-digit OTP succeeds and creates verified User
            ok = client.post(
                "/api/v1/auth/verify-email",
                json={"email": "otpuser@example.com", "token": otp},
            )
            assert ok.status_code == 200

            db = SessionLocal()
            try:
                created = db.query(User).filter(User.email == "otpuser@example.com").first()
                assert created is not None
                assert created.email_verified_at is not None
            finally:
                db.close()

            # Now login works
            login_res = client.post(
                "/api/v1/auth/login",
                json={"email": "otpuser@example.com", "password": "Password123"},
            )
            assert login_res.status_code == 200
