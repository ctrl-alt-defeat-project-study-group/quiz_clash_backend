"""
Tests for Google OAuth 2.0 (Authorization Code + PKCE) login, auto-registration,
verified-email auto-linking, security checks, and account unlinking.
"""
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.core.security import hash_password
from app.db.models import Base, OAuthAccount, User
from app.db.session import SessionLocal, engine
from app.main import app
from app.services.oauth import GoogleUserInfo, OAuthProviderError


@pytest.fixture(autouse=True)
def reset_db_and_oauth(monkeypatch):
    rate_limiter.reset()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "test-google-client-id")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "test-google-client-secret")
    monkeypatch.setattr(settings, "APP_BASE_URL", "http://localhost:5173")
    monkeypatch.setattr(settings, "OAUTH_REDIRECT_BASE_URL", "http://localhost:8000")
    monkeypatch.setattr(settings, "OAUTH_FRONTEND_SUCCESS_PATH", "/")
    monkeypatch.setattr(settings, "OAUTH_FRONTEND_ERROR_PATH", "/login")
    yield
    Base.metadata.drop_all(bind=engine)


def _start_google_login(
    client: TestClient,
    next_path: str | None = None,
    mode: str | None = None,
):
    url = "/api/v1/auth/oauth/google/login"
    query_parts = []
    if next_path is not None:
        query_parts.append(f"next={next_path}")
    if mode is not None:
        query_parts.append(f"mode={mode}")
    if query_parts:
        url = f"{url}?{'&'.join(query_parts)}"
    resp = client.get(url, follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["location"]
    parsed = urlparse(location)
    params = parse_qs(parsed.query)
    return resp, parsed, params


def test_list_oauth_providers_reflects_configuration(monkeypatch):
    with TestClient(app) as client:
        r = client.get("/api/v1/auth/oauth/providers")
        assert r.status_code == 200
        assert r.json() == {"providers": ["google"]}

        monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", None)
        r2 = client.get("/api/v1/auth/oauth/providers")
        assert r2.status_code == 200
        assert r2.json() == {"providers": []}


def test_google_login_returns_503_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", None)
    with TestClient(app) as client:
        r = client.get("/api/v1/auth/oauth/google/login", follow_redirects=False)
        assert r.status_code == 503
        assert r.json()["detail"]["code"] == "OAUTH_PROVIDER_DISABLED"


def test_google_login_redirect_sets_pkce_and_state_cookie():
    with TestClient(app) as client:
        resp, parsed, params = _start_google_login(client, next_path="/dashboard")

        assert parsed.scheme == "https"
        assert parsed.netloc == "accounts.google.com"
        assert params["client_id"] == ["test-google-client-id"]
        assert params["redirect_uri"] == ["http://localhost:8000/api/v1/auth/oauth/google/callback"]
        assert params["response_type"] == ["code"]
        assert params["code_challenge_method"] == ["S256"]
        assert len(params["code_challenge"][0]) >= 40
        assert len(params["state"][0]) >= 30
        assert settings.OAUTH_STATE_COOKIE_NAME in resp.cookies


def test_google_callback_auto_registers_new_user_and_sets_cookies():
    fake_user = GoogleUserInfo(
        provider_user_id="google-sub-1001",
        email="alice@gmail.com",
        email_verified=True,
        display_name="Alice Google",
        avatar_url="https://lh3.googleusercontent.com/alice.png",
    )

    with TestClient(app) as client:
        _, _, params = _start_google_login(client, next_path="/quizzes")
        state = params["state"][0]

        with patch(
            "app.api.routes.auth.exchange_google_code_for_userinfo",
            return_value=fake_user,
        ) as mock_exchange:
            cb = client.get(
                f"/api/v1/auth/oauth/google/callback?code=auth-code-1&state={state}",
                follow_redirects=False,
            )

        assert mock_exchange.called
        assert cb.status_code == 302
        assert cb.headers["location"] == "http://localhost:5173/quizzes"
        assert settings.ACCESS_COOKIE_NAME in cb.cookies
        assert settings.REFRESH_COOKIE_NAME in cb.cookies

        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200
        body = me.json()
        assert body["email"] == "alice@gmail.com"
        assert body["display_name"] == "Alice Google"
        assert body["avatar_url"] == "https://lh3.googleusercontent.com/alice.png"
        assert body["email_verified_at"] is not None
        assert body["has_password"] is False
        assert body["oauth_providers"] == ["google"]

        # Password login for Google-only user must return 401 OAUTH_ACCOUNT_USE_GOOGLE (never 500)
        pw_login = client.post(
            "/api/v1/auth/login",
            json={"email": "alice@gmail.com", "password": "SomePassword123"},
        )
        assert pw_login.status_code == 401
        assert pw_login.json()["detail"]["code"] == "OAUTH_ACCOUNT_USE_GOOGLE"


def test_google_callback_returning_user_does_not_duplicate():
    fake_user = GoogleUserInfo(
        provider_user_id="google-sub-2002",
        email="bob@gmail.com",
        email_verified=True,
        display_name="Bob",
        avatar_url=None,
    )

    with TestClient(app) as client:
        # First login (registers)
        _, _, params1 = _start_google_login(client)
        with patch("app.api.routes.auth.exchange_google_code_for_userinfo", return_value=fake_user):
            cb1 = client.get(
                f"/api/v1/auth/oauth/google/callback?code=c1&state={params1['state'][0]}",
                follow_redirects=False,
            )
        assert cb1.status_code == 302

        # Second login (reuses existing User + OAuthAccount)
        _, _, params2 = _start_google_login(client)
        with patch("app.api.routes.auth.exchange_google_code_for_userinfo", return_value=fake_user):
            cb2 = client.get(
                f"/api/v1/auth/oauth/google/callback?code=c2&state={params2['state'][0]}",
                follow_redirects=False,
            )
        assert cb2.status_code == 302

    db = SessionLocal()
    try:
        assert db.query(User).filter(User.email == "bob@gmail.com").count() == 1
        assert db.query(OAuthAccount).filter(OAuthAccount.provider == "google").count() == 1
    finally:
        db.close()


def test_google_callback_auto_links_existing_email_password_user():
    db = SessionLocal()
    try:
        existing = User(
            email="carol@example.com",
            password_hash=hash_password("Password123"),
            display_name="Carol Local",
            role="user",
            is_active=True,
            email_verified_at=None,  # Previously unverified
        )
        db.add(existing)
        db.commit()
        existing_id = existing.id
    finally:
        db.close()

    fake_user = GoogleUserInfo(
        provider_user_id="google-sub-3003",
        email="carol@example.com",
        email_verified=True,
        display_name="Carol Google",
        avatar_url="https://lh3.googleusercontent.com/carol.png",
    )

    with TestClient(app) as client:
        _, _, params = _start_google_login(client)
        with patch("app.api.routes.auth.exchange_google_code_for_userinfo", return_value=fake_user):
            cb = client.get(
                f"/api/v1/auth/oauth/google/callback?code=c3&state={params['state'][0]}",
                follow_redirects=False,
            )
        assert cb.status_code == 302
        assert cb.headers["location"] == "http://localhost:5173/"

        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200
        data = me.json()
        assert data["id"] == existing_id
        assert data["display_name"] == "Carol Local"
        assert data["avatar_url"] == "https://lh3.googleusercontent.com/carol.png"
        assert data["email_verified_at"] is not None
        assert data["has_password"] is True
        assert data["oauth_providers"] == ["google"]


def test_google_callback_sanitizes_open_redirect_next_param():
    fake_user = GoogleUserInfo(
        provider_user_id="google-sub-4004",
        email="dave@gmail.com",
        email_verified=True,
        display_name="Dave",
    )

    with TestClient(app) as client:
        _, _, params = _start_google_login(client, next_path="//evil.example.com/phish")
        with patch("app.api.routes.auth.exchange_google_code_for_userinfo", return_value=fake_user):
            cb = client.get(
                f"/api/v1/auth/oauth/google/callback?code=c4&state={params['state'][0]}",
                follow_redirects=False,
            )
        assert cb.status_code == 302
        assert cb.headers["location"] == "http://localhost:5173/"


def test_google_callback_error_cases():
    with TestClient(app) as client:
        # 1. User cancelled consent
        cb_cancel = client.get(
            "/api/v1/auth/oauth/google/callback?error=access_denied",
            follow_redirects=False,
        )
        assert cb_cancel.status_code == 302
        assert cb_cancel.headers["location"] == "http://localhost:5173/login?oauth_error=OAUTH_CANCELLED"

        # 2. Missing state cookie
        cb_missing = client.get(
            "/api/v1/auth/oauth/google/callback?code=abc&state=xyz",
            follow_redirects=False,
        )
        assert cb_missing.status_code == 302
        assert cb_missing.headers["location"] == "http://localhost:5173/login?oauth_error=OAUTH_INVALID_STATE"

        # 3. Mismatched state
        _start_google_login(client)
        cb_mismatch = client.get(
            "/api/v1/auth/oauth/google/callback?code=abc&state=wrong-state",
            follow_redirects=False,
        )
        assert cb_mismatch.status_code == 302
        assert cb_mismatch.headers["location"] == "http://localhost:5173/login?oauth_error=OAUTH_INVALID_STATE"

        # 4. Unverified email from provider
        _, _, params = _start_google_login(client)
        unverified = GoogleUserInfo(
            provider_user_id="google-sub-unverified",
            email="unverified@gmail.com",
            email_verified=False,
            display_name="NoVerify",
        )
        with patch("app.api.routes.auth.exchange_google_code_for_userinfo", return_value=unverified):
            cb_unv = client.get(
                f"/api/v1/auth/oauth/google/callback?code=c5&state={params['state'][0]}",
                follow_redirects=False,
            )
        assert cb_unv.status_code == 302
        assert cb_unv.headers["location"] == "http://localhost:5173/login?oauth_error=OAUTH_EMAIL_NOT_VERIFIED"

        # 5. Token exchange error
        _, _, params2 = _start_google_login(client)
        with patch(
            "app.api.routes.auth.exchange_google_code_for_userinfo",
            side_effect=OAuthProviderError("OAUTH_TOKEN_EXCHANGE_FAILED", "bad code"),
        ):
            cb_err = client.get(
                f"/api/v1/auth/oauth/google/callback?code=bad&state={params2['state'][0]}",
                follow_redirects=False,
            )
        assert cb_err.status_code == 302
        assert cb_err.headers["location"] == "http://localhost:5173/login?oauth_error=OAUTH_TOKEN_EXCHANGE_FAILED"


def test_google_callback_blocks_disabled_account():
    db = SessionLocal()
    try:
        user = User(
            email="disabled@example.com",
            password_hash=None,
            display_name="Disabled",
            role="user",
            is_active=False,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
    finally:
        db.close()

    fake_user = GoogleUserInfo(
        provider_user_id="google-sub-disabled",
        email="disabled@example.com",
        email_verified=True,
        display_name="Disabled",
    )

    with TestClient(app) as client:
        _, _, params = _start_google_login(client)
        with patch("app.api.routes.auth.exchange_google_code_for_userinfo", return_value=fake_user):
            cb = client.get(
                f"/api/v1/auth/oauth/google/callback?code=c6&state={params['state'][0]}",
                follow_redirects=False,
            )
        assert cb.status_code == 302
        assert cb.headers["location"] == "http://localhost:5173/login?oauth_error=ACCOUNT_DISABLED"


def test_unlink_google_oauth_guard_and_success():
    fake_user = GoogleUserInfo(
        provider_user_id="google-sub-5005",
        email="eve@gmail.com",
        email_verified=True,
        display_name="Eve",
    )

    with TestClient(app) as client:
        _, _, params = _start_google_login(client)
        with patch("app.api.routes.auth.exchange_google_code_for_userinfo", return_value=fake_user):
            cb = client.get(
                f"/api/v1/auth/oauth/google/callback?code=c7&state={params['state'][0]}",
                follow_redirects=False,
            )
        assert cb.status_code == 302

        # Cannot unlink when user has no password set
        r_block = client.delete("/api/v1/auth/oauth/google")
        assert r_block.status_code == 400
        assert r_block.json()["detail"]["code"] == "CANNOT_UNLINK_LAST_AUTH_METHOD"

        # Once user sets a password, unlinking succeeds
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.email == "eve@gmail.com").first()
            u.password_hash = hash_password("NewPassword123")
            db.commit()
        finally:
            db.close()

        r_ok = client.delete("/api/v1/auth/oauth/google")
        assert r_ok.status_code == 200
        me = client.get("/api/v1/auth/me")
        assert me.json()["oauth_providers"] == []
        assert me.json()["has_password"] is True


def test_google_register_blocks_existing_oauth_account():
    fake_user = GoogleUserInfo(
        provider_user_id="google-sub-6006",
        email="frank@gmail.com",
        email_verified=True,
        display_name="Frank",
    )

    with TestClient(app) as client:
        # Initial registration via Google succeeds
        _, _, params1 = _start_google_login(client, next_path="/dashboard", mode="register")
        with patch("app.api.routes.auth.exchange_google_code_for_userinfo", return_value=fake_user):
            cb1 = client.get(
                f"/api/v1/auth/oauth/google/callback?code=c-reg-1&state={params1['state'][0]}",
                follow_redirects=False,
            )
        assert cb1.status_code == 302
        assert cb1.headers["location"] == "http://localhost:5173/dashboard"
        assert settings.ACCESS_COOKIE_NAME in cb1.cookies

    # A fresh client trying to sign up again with the same Gmail must be rejected
    with TestClient(app) as client2:
        _, _, params2 = _start_google_login(client2, next_path="/dashboard", mode="register")
        with patch("app.api.routes.auth.exchange_google_code_for_userinfo", return_value=fake_user):
            cb2 = client2.get(
                f"/api/v1/auth/oauth/google/callback?code=c-reg-2&state={params2['state'][0]}",
                follow_redirects=False,
            )
        assert cb2.status_code == 302
        assert (
            cb2.headers["location"]
            == "http://localhost:5173/register?oauth_error=OAUTH_ACCOUNT_ALREADY_EXISTS"
        )
        assert settings.ACCESS_COOKIE_NAME not in cb2.cookies
        assert settings.REFRESH_COOKIE_NAME not in cb2.cookies
        assert client2.get("/api/v1/auth/me").status_code == 401


def test_google_register_blocks_existing_email_password_account():
    db = SessionLocal()
    try:
        existing = User(
            email="grace@gmail.com",
            password_hash=hash_password("Password123"),
            display_name="Grace Local",
            role="user",
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(existing)
        db.commit()
    finally:
        db.close()

    fake_user = GoogleUserInfo(
        provider_user_id="google-sub-7007",
        email="grace@gmail.com",
        email_verified=True,
        display_name="Grace Google",
    )

    with TestClient(app) as client:
        _, _, params = _start_google_login(client, next_path="/dashboard", mode="register")
        with patch("app.api.routes.auth.exchange_google_code_for_userinfo", return_value=fake_user):
            cb = client.get(
                f"/api/v1/auth/oauth/google/callback?code=c-reg-3&state={params['state'][0]}",
                follow_redirects=False,
            )
        assert cb.status_code == 302
        assert (
            cb.headers["location"]
            == "http://localhost:5173/register?oauth_error=OAUTH_ACCOUNT_ALREADY_EXISTS"
        )
        assert settings.ACCESS_COOKIE_NAME not in cb.cookies
        assert settings.REFRESH_COOKIE_NAME not in cb.cookies
        assert client.get("/api/v1/auth/me").status_code == 401

    # Ensure Google OAuthAccount was not auto-linked during rejected signup
    db = SessionLocal()
    try:
        assert db.query(OAuthAccount).filter(OAuthAccount.provider_email == "grace@gmail.com").count() == 0
    finally:
        db.close()
