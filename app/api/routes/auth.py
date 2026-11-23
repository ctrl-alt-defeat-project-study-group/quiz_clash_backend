"""
API routes for authentication, Google OAuth 2.0, email verification, and password reset.
"""
from datetime import datetime, timedelta, timezone
import secrets
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.rate_limit import rate_limit_auth
from app.core.security import (
    api_error,
    clear_auth_cookies,
    create_oauth_state_token,
    decode_oauth_state_token,
    decode_token,
    generate_email_otp,
    generate_email_token,
    generate_pkce_pair,
    hash_email_token,
    hash_password,
    set_auth_cookies,
    validate_password_strength,
    verify_password,
)
from app.db.models import EmailToken, OAuthAccount, User
from app.db.session import get_db
from app.schemas.auth import (
    ChangePasswordRequest,
    EmailRequest,
    LoginRequest,
    MessageResponse,
    OAuthProvidersResponse,
    RegisterRequest,
    ResetPasswordRequest,
    UserProfileResponse,
    VerifyEmailRequest,
)
from app.services.mailer import MailerService
from app.services.oauth import (
    OAuthProviderError,
    build_google_authorization_url,
    exchange_google_code_for_userinfo,
    is_google_oauth_enabled,
    sanitize_next_path,
)

router = APIRouter(prefix="/auth")


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _issue_email_token(
    db: Session,
    user: User,
    purpose: str,
    expire_hours: Optional[int] = None,
    expire_minutes: Optional[int] = None,
) -> str:
    """Invalidate unused prior tokens of the same purpose and issue a new one."""
    now = datetime.now(timezone.utc)
    db.query(EmailToken).filter(
        EmailToken.user_id == user.id,
        EmailToken.purpose == purpose,
        EmailToken.used_at.is_(None),
    ).update({"used_at": now}, synchronize_session=False)

    if purpose == "verify":
        raw_token, token_hash = generate_email_otp()
        ttl = timedelta(minutes=expire_minutes if expire_minutes is not None else 15)
    else:
        raw_token, token_hash = generate_email_token()
        ttl = timedelta(hours=expire_hours if expire_hours is not None else 1)

    db_token = EmailToken(
        user_id=user.id,
        purpose=purpose,
        token_hash=token_hash,
        expires_at=now + ttl,
    )
    db.add(db_token)
    return raw_token


@router.post(
    "/register",
    response_model=UserProfileResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_auth("register"))],
)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    """Open sign-up: always creates an unverified 'user' and sends a verification email."""
    email = payload.email.strip().lower()
    display_name = payload.display_name.strip()
    if not display_name:
        raise api_error(422, "VALIDATION_ERROR", "Display name cannot be empty.")

    validate_password_strength(payload.password)

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise api_error(409, "EMAIL_ALREADY_EXISTS", "An account with this email already exists.")

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        display_name=display_name,
        role="user",
        is_active=True,
        email_verified_at=None,
    )
    db.add(user)
    db.flush()

    raw_token = _issue_email_token(
        db,
        user=user,
        purpose="verify",
        expire_hours=settings.EMAIL_TOKEN_EXPIRE_HOURS,
    )
    try:
        MailerService.send_verification_email(user.email, user.display_name, raw_token)
    except Exception:
        db.rollback()
        raise api_error(
            503,
            "EMAIL_DELIVERY_FAILED",
            "Could not send verification email. Please try again later.",
        )

    db.commit()
    db.refresh(user)
    return user


@router.post(
    "/verify-email",
    response_model=MessageResponse,
    dependencies=[Depends(rate_limit_auth("verify_email"))],
)
def verify_email(payload: VerifyEmailRequest, db: Session = Depends(get_db)):
    """Verify a user's email address using a one-time 6-digit OTP code."""
    token_hash = hash_email_token(payload.token.strip())
    query = db.query(EmailToken).filter(
        EmailToken.token_hash == token_hash,
        EmailToken.purpose == "verify",
    )
    if payload.email:
        target_user = (
            db.query(User).filter(User.email == payload.email.strip().lower()).first()
        )
        if not target_user:
            raise api_error(
                400,
                "TOKEN_INVALID_OR_EXPIRED",
                "Verification code is invalid or has expired.",
            )
        query = query.filter(EmailToken.user_id == target_user.id)

    db_token = query.first()

    now = datetime.now(timezone.utc)
    if (
        not db_token
        or db_token.used_at is not None
        or _as_utc(db_token.expires_at) < now
    ):
        raise api_error(
            400,
            "TOKEN_INVALID_OR_EXPIRED",
            "Verification code is invalid or has expired.",
        )

    user = db.query(User).filter(User.id == db_token.user_id).first()
    if not user:
        raise api_error(
            400,
            "TOKEN_INVALID_OR_EXPIRED",
            "Verification code is invalid or has expired.",
        )

    db_token.used_at = now
    if user.email_verified_at is None:
        user.email_verified_at = now
    db.commit()

    return {"message": "Email verified successfully."}


@router.post(
    "/resend-verification",
    response_model=MessageResponse,
    dependencies=[Depends(rate_limit_auth("resend_verification"))],
)
def resend_verification(payload: EmailRequest, db: Session = Depends(get_db)):
    """Resend verification email if the account exists and is not yet verified."""
    email = payload.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()

    if user and user.is_active and user.email_verified_at is None:
        raw_token = _issue_email_token(
            db,
            user=user,
            purpose="verify",
            expire_hours=settings.EMAIL_TOKEN_EXPIRE_HOURS,
        )
        try:
            MailerService.send_verification_email(user.email, user.display_name, raw_token)
        except Exception:
            db.rollback()
            raise api_error(
                503,
                "EMAIL_DELIVERY_FAILED",
                "Could not send verification email. Please try again later.",
            )
        db.commit()

    return {"message": "If the account exists and is unverified, a verification email has been sent."}


@router.post(
    "/login",
    response_model=UserProfileResponse,
    dependencies=[Depends(rate_limit_auth("login"))],
)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    """Authenticate with email/password and set httpOnly access + refresh cookies."""
    email = payload.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()

    if not user or not user.password_hash or not verify_password(payload.password, user.password_hash):
        raise api_error(401, "INVALID_CREDENTIALS", "Invalid email or password.")

    if not user.is_active:
        raise api_error(403, "ACCOUNT_DISABLED", "This account has been deactivated.")

    if user.email_verified_at is None:
        raise api_error(403, "EMAIL_NOT_VERIFIED", "Please verify your email address before logging in.")

    set_auth_cookies(response, user_id=user.id, role=user.role)
    return user


@router.post("/refresh", response_model=UserProfileResponse)
def refresh_session(request: Request, response: Response, db: Session = Depends(get_db)):
    """Rotate httpOnly access and refresh cookies using the refresh cookie."""
    refresh_token = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if not refresh_token:
        raise api_error(401, "UNAUTHORIZED", "Missing refresh token.")

    payload = decode_token(refresh_token, expected_type="refresh")
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        raise api_error(401, "UNAUTHORIZED", "Invalid refresh token.")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise api_error(401, "UNAUTHORIZED", "User account no longer exists.")
    if not user.is_active:
        clear_auth_cookies(response)
        raise api_error(403, "ACCOUNT_DISABLED", "This account has been deactivated.")
    if user.email_verified_at is None:
        clear_auth_cookies(response)
        raise api_error(403, "EMAIL_NOT_VERIFIED", "Please verify your email address first.")

    set_auth_cookies(response, user_id=user.id, role=user.role)
    return user


@router.post("/logout", response_model=MessageResponse)
def logout(response: Response):
    """Clear authentication cookies."""
    clear_auth_cookies(response)
    return {"message": "Logged out successfully."}


@router.get("/me", response_model=UserProfileResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """Return the currently authenticated user's profile."""
    return current_user


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    dependencies=[Depends(rate_limit_auth("forgot_password"))],
)
def forgot_password(payload: EmailRequest, db: Session = Depends(get_db)):
    """Send a one-time password reset link if the account exists and is active."""
    email = payload.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()

    if user and user.is_active:
        raw_token = _issue_email_token(
            db,
            user=user,
            purpose="reset",
            expire_hours=settings.PASSWORD_RESET_EXPIRE_HOURS,
        )
        try:
            MailerService.send_password_reset_email(user.email, user.display_name, raw_token)
        except Exception:
            db.rollback()
            raise api_error(
                503,
                "EMAIL_DELIVERY_FAILED",
                "Could not send password reset email. Please try again later.",
            )
        db.commit()

    return {"message": "If an account with that email exists, a password reset link has been sent."}


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(
    payload: ResetPasswordRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """Reset password using a valid one-time reset token."""
    validate_password_strength(payload.new_password)

    token_hash = hash_email_token(payload.token.strip())
    db_token = (
        db.query(EmailToken)
        .filter(
            EmailToken.token_hash == token_hash,
            EmailToken.purpose == "reset",
        )
        .first()
    )

    now = datetime.now(timezone.utc)
    if (
        not db_token
        or db_token.used_at is not None
        or _as_utc(db_token.expires_at) < now
    ):
        raise api_error(
            400,
            "TOKEN_INVALID_OR_EXPIRED",
            "Password reset token is invalid or has expired.",
        )

    user = db.query(User).filter(User.id == db_token.user_id).first()
    if not user or not user.is_active:
        raise api_error(
            400,
            "TOKEN_INVALID_OR_EXPIRED",
            "Password reset token is invalid or has expired.",
        )

    user.password_hash = hash_password(payload.new_password)
    db_token.used_at = now
    db.commit()
    clear_auth_cookies(response)

    return {"message": "Password reset successfully."}


@router.post("/change-password", response_model=MessageResponse)
def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change the current user's password (disabled for Google OAuth-only accounts)."""
    if not current_user.password_hash:
        raise api_error(
            400,
            "OAUTH_PASSWORD_MANAGED_EXTERNALLY",
            "Password changes are disabled for Google sign-in accounts.",
        )

    if not payload.current_password or not verify_password(
        payload.current_password, current_user.password_hash
    ):
        raise api_error(
            400,
            "INVALID_CURRENT_PASSWORD",
            "Current password is incorrect.",
        )
    if payload.current_password == payload.new_password:
        raise api_error(
            400,
            "PASSWORD_UNCHANGED",
            "New password must be different from your current password.",
        )

    validate_password_strength(payload.new_password)
    current_user.password_hash = hash_password(payload.new_password)
    db.commit()

    return {"message": "Password updated successfully."}


# ---------------------------------------------------------------------------
# Google OAuth 2.0 (Authorization Code + PKCE)
# ---------------------------------------------------------------------------


def _google_redirect_uri(request: Request) -> str:
    base = (settings.OAUTH_REDIRECT_BASE_URL or "").strip().rstrip("/")
    if not base:
        base = str(request.base_url).rstrip("/")
    return f"{base}/api/v1/auth/oauth/google/callback"


def _frontend_redirect_url(path: str, query: Optional[dict] = None) -> str:
    base = (settings.APP_BASE_URL or "http://localhost:5173").rstrip("/")
    clean_path = path if path.startswith("/") else f"/{path}"
    if query:
        return f"{base}{clean_path}?{urlencode(query)}"
    return f"{base}{clean_path}"


def _oauth_state_cookie_samesite() -> str:
    # SameSite=Strict drops cookies on top-level cross-site OAuth redirects
    configured = (settings.COOKIE_SAMESITE or "lax").strip().lower()
    return "none" if configured == "none" else "lax"


def _clear_oauth_state_cookie(response: Response) -> None:
    delete_kwargs = {"path": "/api/v1/auth/oauth"}
    if settings.COOKIE_DOMAIN:
        delete_kwargs["domain"] = settings.COOKIE_DOMAIN
    response.delete_cookie(key=settings.OAUTH_STATE_COOKIE_NAME, **delete_kwargs)


def _oauth_error_redirect(error_code: str, mode: str = "login") -> RedirectResponse:
    error_path = (
        "/register"
        if mode == "register"
        else (settings.OAUTH_FRONTEND_ERROR_PATH or "/login")
    )
    resp = RedirectResponse(
        url=_frontend_redirect_url(error_path, {"oauth_error": error_code}),
        status_code=status.HTTP_302_FOUND,
    )
    _clear_oauth_state_cookie(resp)
    return resp


@router.get("/oauth/providers", response_model=OAuthProvidersResponse)
def list_oauth_providers():
    """Return the list of currently enabled OAuth providers."""
    providers = ["google"] if is_google_oauth_enabled() else []
    return {"providers": providers}


@router.get(
    "/oauth/google/login",
    dependencies=[Depends(rate_limit_auth("oauth_login"))],
)
def google_oauth_login(
    request: Request,
    next: Optional[str] = Query(default=None, description="Optional safe relative path to redirect to after login"),
    mode: Optional[str] = Query(default="login", description="OAuth intent: 'login' or 'register'"),
):
    """Start Google OAuth 2.0 login/registration using Authorization Code + PKCE."""
    if not is_google_oauth_enabled():
        raise api_error(
            503,
            "OAUTH_PROVIDER_DISABLED",
            "Google OAuth is not configured on this server.",
        )

    safe_next = sanitize_next_path(next)
    normalized_mode = "register" if (mode or "").strip().lower() == "register" else "login"
    state = secrets.token_urlsafe(32)
    code_verifier, code_challenge = generate_pkce_pair()
    state_jwt = create_oauth_state_token(
        provider="google",
        state=state,
        code_verifier=code_verifier,
        next_path=safe_next,
        mode=normalized_mode,
    )

    redirect_uri = _google_redirect_uri(request)
    auth_url = build_google_authorization_url(
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=code_challenge,
    )

    response = RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)
    cookie_kwargs = {
        "httponly": True,
        "secure": settings.COOKIE_SECURE,
        "samesite": _oauth_state_cookie_samesite(),
        "max_age": settings.OAUTH_STATE_EXPIRE_SECONDS,
        "path": "/api/v1/auth/oauth",
    }
    if settings.COOKIE_DOMAIN:
        cookie_kwargs["domain"] = settings.COOKIE_DOMAIN
    response.set_cookie(key=settings.OAUTH_STATE_COOKIE_NAME, value=state_jwt, **cookie_kwargs)
    return response


@router.get(
    "/oauth/google/callback",
    dependencies=[Depends(rate_limit_auth("oauth_callback"))],
)
def google_oauth_callback(
    request: Request,
    code: Optional[str] = Query(default=None),
    state: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Handle Google OAuth callback, auto-link or auto-register user, and set auth cookies."""
    state_cookie = request.cookies.get(settings.OAUTH_STATE_COOKIE_NAME)
    state_payload = decode_oauth_state_token(state_cookie) if state_cookie else None
    oauth_mode = (
        "register"
        if state_payload and state_payload.get("mode") == "register"
        else "login"
    )

    if not is_google_oauth_enabled():
        return _oauth_error_redirect("OAUTH_PROVIDER_DISABLED", mode=oauth_mode)

    if error:
        if error == "access_denied":
            return _oauth_error_redirect("OAUTH_CANCELLED", mode=oauth_mode)
        return _oauth_error_redirect("OAUTH_PROVIDER_ERROR", mode=oauth_mode)

    if not state_cookie or not state or not code:
        return _oauth_error_redirect("OAUTH_INVALID_STATE", mode=oauth_mode)

    if (
        not state_payload
        or state_payload.get("provider") != "google"
        or not isinstance(state_payload.get("state"), str)
        or not secrets.compare_digest(state_payload["state"], state)
        or not isinstance(state_payload.get("code_verifier"), str)
    ):
        return _oauth_error_redirect("OAUTH_INVALID_STATE", mode=oauth_mode)

    redirect_uri = _google_redirect_uri(request)
    try:
        info = exchange_google_code_for_userinfo(
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=state_payload["code_verifier"],
        )
    except OAuthProviderError as exc:
        return _oauth_error_redirect(exc.code, mode=oauth_mode)

    now = datetime.now(timezone.utc)
    oauth_acct = (
        db.query(OAuthAccount)
        .filter(
            OAuthAccount.provider == "google",
            OAuthAccount.provider_user_id == info.provider_user_id,
        )
        .first()
    )

    if oauth_acct is not None:
        if oauth_mode == "register":
            return _oauth_error_redirect("OAUTH_ACCOUNT_ALREADY_EXISTS", mode="register")
        user = db.query(User).filter(User.id == oauth_acct.user_id).first()
        if not user:
            return _oauth_error_redirect("OAUTH_ACCOUNT_ERROR", mode=oauth_mode)
        if not user.is_active:
            return _oauth_error_redirect("ACCOUNT_DISABLED", mode=oauth_mode)
        if info.email and oauth_acct.provider_email != info.email:
            oauth_acct.provider_email = info.email
        if info.avatar_url and not user.avatar_url:
            user.avatar_url = info.avatar_url
        if user.email_verified_at is None and info.email_verified:
            user.email_verified_at = now
        db.commit()
        db.refresh(user)
    else:
        if not info.email or not info.email_verified:
            return _oauth_error_redirect("OAUTH_EMAIL_NOT_VERIFIED", mode=oauth_mode)

        user = db.query(User).filter(User.email == info.email).first()
        if user is not None:
            if oauth_mode == "register":
                return _oauth_error_redirect("OAUTH_ACCOUNT_ALREADY_EXISTS", mode="register")
            if not user.is_active:
                return _oauth_error_redirect("ACCOUNT_DISABLED", mode=oauth_mode)
            if user.email_verified_at is None:
                user.email_verified_at = now
            if info.avatar_url and not user.avatar_url:
                user.avatar_url = info.avatar_url
        else:
            user = User(
                email=info.email,
                password_hash=None,
                display_name=info.display_name,
                avatar_url=info.avatar_url,
                role="user",
                is_active=True,
                email_verified_at=now,
            )
            db.add(user)
            db.flush()

        db.add(
            OAuthAccount(
                user_id=user.id,
                provider="google",
                provider_user_id=info.provider_user_id,
                provider_email=info.email,
            )
        )
        db.commit()
        db.refresh(user)

    next_path = sanitize_next_path(state_payload.get("next"))
    response = RedirectResponse(
        url=_frontend_redirect_url(next_path),
        status_code=status.HTTP_302_FOUND,
    )
    _clear_oauth_state_cookie(response)
    set_auth_cookies(response, user_id=user.id, role=user.role)
    return response


@router.delete("/oauth/google", response_model=MessageResponse)
def unlink_google_oauth(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Unlink Google OAuth from the current user's account (requires a password to remain)."""
    oauth_acct = (
        db.query(OAuthAccount)
        .filter(
            OAuthAccount.user_id == current_user.id,
            OAuthAccount.provider == "google",
        )
        .first()
    )
    if not oauth_acct:
        raise api_error(404, "OAUTH_NOT_LINKED", "Google account is not linked.")

    other_providers = (
        db.query(OAuthAccount)
        .filter(
            OAuthAccount.user_id == current_user.id,
            OAuthAccount.provider != "google",
        )
        .count()
    )
    if not current_user.password_hash and other_providers == 0:
        raise api_error(
            400,
            "CANNOT_UNLINK_LAST_AUTH_METHOD",
            "Set a password before unlinking your Google account.",
        )

    db.delete(oauth_acct)
    db.commit()
    return {"message": "Google account unlinked successfully."}
