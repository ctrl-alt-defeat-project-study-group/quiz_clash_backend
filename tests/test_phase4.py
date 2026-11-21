"""
Tests verifying Phase 4 auth, email verification, password reset, CSRF, rate limiting,
ownership enforcement, admin seeding, and admin endpoints.
"""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.core.security import create_access_token, hash_password
from app.db.models import Base, User
from app.db.session import SessionLocal, engine
from app.main import app
from app.services.bootstrap import seed_initial_admin
from app.services.mailer import MailerService


@pytest.fixture(autouse=True)
def reset_db_and_limits():
    rate_limiter.reset()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    rate_limiter.reset()


def _create_verified_user(email: str, role: str = "user", is_active: bool = True) -> User:
    db = SessionLocal()
    try:
        user = User(
            email=email,
            password_hash=hash_password("Password123"),
            display_name=email.split("@")[0].title(),
            role=role,
            is_active=is_active,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _sample_csv_bytes() -> bytes:
    rows = [f'"Term{i}","Definition {i}"' for i in range(1, 11)]
    return "\n".join(rows).encode("utf-8")


def test_register_verify_login_refresh_logout_flow():
    captured_tokens = []

    def fake_send_verify(to_email, display_name, token):
        captured_tokens.append(token)
        return f"http://localhost:5173/verify-email?token={token}"

    with patch.object(MailerService, "send_verification_email", side_effect=fake_send_verify):
        with TestClient(app) as client:
            # Weak password rejected
            weak = client.post(
                "/api/v1/auth/register",
                json={"email": "alice@example.com", "password": "short", "display_name": "Alice"},
            )
            assert weak.status_code == 422
            assert weak.json()["detail"]["code"] == "VALIDATION_ERROR"

            # Register creates unverified 'user'
            reg = client.post(
                "/api/v1/auth/register",
                json={"email": "alice@example.com", "password": "Password123", "display_name": "Alice"},
            )
            assert reg.status_code == 201
            body = reg.json()
            assert body["role"] == "user"
            assert body["email_verified_at"] is None
            assert len(captured_tokens) == 1

            # Duplicate email returns 409 EMAIL_ALREADY_EXISTS
            dup = client.post(
                "/api/v1/auth/register",
                json={"email": "ALICE@example.com", "password": "Password123", "display_name": "Alice2"},
            )
            assert dup.status_code == 409
            assert dup.json()["detail"]["code"] == "EMAIL_ALREADY_EXISTS"

            # Login blocked before verification
            unverified_login = client.post(
                "/api/v1/auth/login",
                json={"email": "alice@example.com", "password": "Password123"},
            )
            assert unverified_login.status_code == 403
            assert unverified_login.json()["detail"]["code"] == "EMAIL_NOT_VERIFIED"

            # Resend verification invalidates first token and issues a second
            resend = client.post(
                "/api/v1/auth/resend-verification",
                json={"email": "alice@example.com"},
            )
            assert resend.status_code == 200
            assert len(captured_tokens) == 2

            # First token is now invalid
            old_verify = client.post("/api/v1/auth/verify-email", json={"token": captured_tokens[0]})
            assert old_verify.status_code == 400
            assert old_verify.json()["detail"]["code"] == "TOKEN_INVALID_OR_EXPIRED"

            # Second token verifies email
            verify = client.post("/api/v1/auth/verify-email", json={"token": captured_tokens[1]})
            assert verify.status_code == 200

            # Reusing verified token fails
            reuse = client.post("/api/v1/auth/verify-email", json={"token": captured_tokens[1]})
            assert reuse.status_code == 400
            assert reuse.json()["detail"]["code"] == "TOKEN_INVALID_OR_EXPIRED"

            # Wrong password -> 401 INVALID_CREDENTIALS
            bad_pw = client.post(
                "/api/v1/auth/login",
                json={"email": "alice@example.com", "password": "WrongPassword1"},
            )
            assert bad_pw.status_code == 401
            assert bad_pw.json()["detail"]["code"] == "INVALID_CREDENTIALS"

            # Successful login sets httpOnly cookies
            login_resp = client.post(
                "/api/v1/auth/login",
                json={"email": "alice@example.com", "password": "Password123"},
            )
            assert login_resp.status_code == 200
            assert settings.ACCESS_COOKIE_NAME in login_resp.cookies
            assert settings.REFRESH_COOKIE_NAME in login_resp.cookies
            set_cookie_headers = login_resp.headers.get_list("set-cookie")
            assert any("httponly" in h.lower() for h in set_cookie_headers)

            # /auth/me works with cookie
            me = client.get("/api/v1/auth/me")
            assert me.status_code == 200
            assert me.json()["email"] == "alice@example.com"

            # /auth/refresh rotates cookies
            ref = client.post("/api/v1/auth/refresh")
            assert ref.status_code == 200
            assert settings.ACCESS_COOKIE_NAME in ref.cookies

            # /auth/logout clears cookies
            out = client.post("/api/v1/auth/logout")
            assert out.status_code == 200
            assert client.get("/api/v1/auth/me").status_code == 401


def test_forgot_and_reset_password_flow():
    _create_verified_user("bob@example.com")
    reset_tokens = []

    def fake_send_reset(to_email, display_name, token):
        reset_tokens.append(token)
        return f"http://localhost:5173/reset-password?token={token}"

    with patch.object(MailerService, "send_password_reset_email", side_effect=fake_send_reset):
        with TestClient(app) as client:
            resp = client.post("/api/v1/auth/forgot-password", json={"email": "bob@example.com"})
            assert resp.status_code == 200
            assert len(reset_tokens) == 1

            reset_resp = client.post(
                "/api/v1/auth/reset-password",
                json={"token": reset_tokens[0], "new_password": "NewPassword456"},
            )
            assert reset_resp.status_code == 200

            # Reusing token fails
            reuse = client.post(
                "/api/v1/auth/reset-password",
                json={"token": reset_tokens[0], "new_password": "AnotherPassword789"},
            )
            assert reuse.status_code == 400
            assert reuse.json()["detail"]["code"] == "TOKEN_INVALID_OR_EXPIRED"

            # Old password rejected, new password works
            old_login = client.post(
                "/api/v1/auth/login",
                json={"email": "bob@example.com", "password": "Password123"},
            )
            assert old_login.status_code == 401

            new_login = client.post(
                "/api/v1/auth/login",
                json={"email": "bob@example.com", "password": "NewPassword456"},
            )
            assert new_login.status_code == 200


def test_csrf_origin_guard_and_rate_limiting():
    _create_verified_user("csrf@example.com")

    with TestClient(app) as client:
        # Untrusted Origin on POST blocked with 403
        blocked = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "https://evil.example.com"},
            json={"email": "csrf@example.com", "password": "Password123"},
        )
        assert blocked.status_code == 403
        assert blocked.json()["detail"]["code"] == "FORBIDDEN"

        # Trusted Origin allowed
        allowed = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://localhost:5173"},
            json={"email": "csrf@example.com", "password": "Password123"},
        )
        assert allowed.status_code == 200

        # Same-origin request (e.g. Swagger UI /docs) allowed
        same_origin = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://testserver"},
            json={"email": "csrf@example.com", "password": "Password123"},
        )
        assert same_origin.status_code == 200

        # Rate limit triggers 429 RATE_LIMITED
        rate_limiter.reset()
        with patch.object(settings, "RATE_LIMIT_AUTH_MAX_REQUESTS", 2):
            for _ in range(2):
                r = client.post(
                    "/api/v1/auth/login",
                    json={"email": "csrf@example.com", "password": "WrongPassword1"},
                )
                assert r.status_code == 401
            limited = client.post(
                "/api/v1/auth/login",
                json={"email": "csrf@example.com", "password": "WrongPassword1"},
            )
            assert limited.status_code == 429
            assert limited.json()["detail"]["code"] == "RATE_LIMITED"


def test_ownership_enforcement_and_admin_access():
    user_a = _create_verified_user("owner@example.com", role="user")
    user_b = _create_verified_user("other@example.com", role="user")
    admin = _create_verified_user("boss@example.com", role="admin")

    # Guest cannot create quiz
    with TestClient(app) as guest:
        g_resp = guest.post(
            "/api/v1/quizzes",
            files={"file": ("bio.csv", _sample_csv_bytes(), "text/csv")},
            data={"title": "Guest Quiz", "question_count": "5"},
        )
        assert g_resp.status_code == 401
        assert g_resp.json()["detail"]["code"] == "UNAUTHORIZED"

    # User A creates quiz and submits attempt
    with TestClient(app) as client_a:
        client_a.cookies.set(settings.ACCESS_COOKIE_NAME, create_access_token(user_a.id, user_a.role))
        q_resp = client_a.post(
            "/api/v1/quizzes",
            files={"file": ("bio.csv", _sample_csv_bytes(), "text/csv")},
            data={"title": "User A Quiz", "question_count": "5"},
        )
        assert q_resp.status_code == 201
        quiz_id = q_resp.json()["id"]
        first_qid = q_resp.json()["questions"][0]["id"]

        att_resp = client_a.post(
            f"/api/v1/quizzes/{quiz_id}/attempts",
            json={"answers": [{"question_id": first_qid, "choice_id": "a"}]},
        )
        assert att_resp.status_code == 201
        attempt_id = att_resp.json()["id"]

    # User B gets 403 FORBIDDEN on User A's quiz, export, and attempt
    with TestClient(app) as client_b:
        client_b.cookies.set(settings.ACCESS_COOKIE_NAME, create_access_token(user_b.id, user_b.role))
        assert client_b.get(f"/api/v1/quizzes/{quiz_id}").status_code == 403
        assert client_b.get(f"/api/v1/quizzes/{quiz_id}/preview").status_code == 403
        assert client_b.patch(f"/api/v1/quizzes/{quiz_id}", json={"title": "Hack"}).status_code == 403
        assert client_b.get(f"/api/v1/quizzes/{quiz_id}/exports").status_code == 403
        assert client_b.get(f"/api/v1/attempts/{attempt_id}").status_code == 403

    # Admin can access User A's quiz and attempt
    with TestClient(app) as client_admin:
        client_admin.cookies.set(settings.ACCESS_COOKIE_NAME, create_access_token(admin.id, admin.role))
        assert client_admin.get(f"/api/v1/quizzes/{quiz_id}").status_code == 200
        assert client_admin.get(f"/api/v1/attempts/{attempt_id}").status_code == 200


def test_admin_seeding_endpoints_and_last_admin_guard():
    with patch.object(settings, "ADMIN_EMAIL", "rootadmin@example.com"), patch.object(
        settings, "ADMIN_PASSWORD", "AdminPass123"
    ):
        seed_initial_admin()

        user = _create_verified_user("member@example.com", role="user")

        # Non-admin blocked from /admin/*
        with TestClient(app) as client_user:
            client_user.cookies.set(settings.ACCESS_COOKIE_NAME, create_access_token(user.id, user.role))
            assert client_user.get("/api/v1/admin/users").status_code == 403
            assert client_user.get("/api/v1/admin/stats").status_code == 403

        with TestClient(app) as client_admin:
            login_resp = client_admin.post(
                "/api/v1/auth/login",
                json={"email": "rootadmin@example.com", "password": "AdminPass123"},
            )
            assert login_resp.status_code == 200
            admin_id = login_resp.json()["id"]

            # Search users
            users_resp = client_admin.get("/api/v1/admin/users", params={"q": "member"})
            assert users_resp.status_code == 200
            assert len(users_resp.json()) == 1
            assert users_resp.json()[0]["email"] == "member@example.com"

            # Cannot demote, deactivate, or delete last active admin
            assert client_admin.patch(f"/api/v1/admin/users/{admin_id}", json={"role": "user"}).status_code == 400
            assert client_admin.patch(f"/api/v1/admin/users/{admin_id}", json={"is_active": False}).status_code == 400
            assert client_admin.delete(f"/api/v1/admin/users/{admin_id}").status_code == 400

            # Deactivate regular user -> blocked from login with 403 ACCOUNT_DISABLED
            deact = client_admin.patch(f"/api/v1/admin/users/{user.id}", json={"is_active": False})
            assert deact.status_code == 200
            assert deact.json()["is_active"] is False

            with TestClient(app) as disabled_client:
                r = disabled_client.post(
                    "/api/v1/auth/login",
                    json={"email": "member@example.com", "password": "Password123"},
                )
                assert r.status_code == 403
                assert r.json()["detail"]["code"] == "ACCOUNT_DISABLED"

            # Promote user (and re-activate) -> now we have 2 admins so admin_id can be demoted
            promo = client_admin.patch(
                f"/api/v1/admin/users/{user.id}",
                json={"role": "admin", "is_active": True},
            )
            assert promo.status_code == 200
            assert promo.json()["role"] == "admin"

            # Admin stats & quizzes
            stats = client_admin.get("/api/v1/admin/stats")
            assert stats.status_code == 200
            assert stats.json()["total_users"] == 2
            assert stats.json()["admin_users"] == 2

            quizzes_list = client_admin.get("/api/v1/admin/quizzes")
            assert quizzes_list.status_code == 200

            # Delete second user succeeds
            del_u = client_admin.delete(f"/api/v1/admin/users/{user.id}")
            assert del_u.status_code == 200


def test_demo_user_seeding_and_login():
    from app.services.bootstrap import seed_initial_user

    with (
        patch.object(settings, "DEMO_USER_EMAIL", "demo@example.com"),
        patch.object(settings, "DEMO_USER_PASSWORD", "UserPassword123"),
        patch.object(settings, "DEMO_USER_DISPLAY_NAME", "Demo User"),
    ):
        seed_initial_user()
        seed_initial_user()  # idempotent

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/auth/login",
                json={"email": "demo@example.com", "password": "UserPassword123"},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["email"] == "demo@example.com"
            assert body["role"] == "user"
            assert body["email_verified_at"] is not None
