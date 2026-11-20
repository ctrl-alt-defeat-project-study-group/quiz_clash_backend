"""
API routes for authentication, email verification, and password reset.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.rate_limit import rate_limit_auth
from app.core.security import (
    api_error,
    clear_auth_cookies,
    decode_token,
    generate_email_token,
    hash_email_token,
    hash_password,
    set_auth_cookies,
    validate_password_strength,
    verify_password,
)
from app.db.models import EmailToken, User
from app.db.session import get_db
from app.schemas.auth import (
    EmailRequest,
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    ResetPasswordRequest,
    UserProfileResponse,
    VerifyEmailRequest,
)
from app.services.mailer import MailerService

router = APIRouter(prefix="/auth")


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _issue_email_token(
    db: Session,
    user: User,
    purpose: str,
    expire_hours: int,
) -> str:
    """Invalidate unused prior tokens of the same purpose and issue a new one."""
    now = datetime.now(timezone.utc)
    db.query(EmailToken).filter(
        EmailToken.user_id == user.id,
        EmailToken.purpose == purpose,
        EmailToken.used_at.is_(None),
    ).update({"used_at": now}, synchronize_session=False)

    raw_token, token_hash = generate_email_token()
    db_token = EmailToken(
        user_id=user.id,
        purpose=purpose,
        token_hash=token_hash,
        expires_at=now + timedelta(hours=expire_hours),
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
    db.commit()
    db.refresh(user)

    MailerService.send_verification_email(user.email, user.display_name, raw_token)
    return user


@router.post("/verify-email", response_model=MessageResponse)
def verify_email(payload: VerifyEmailRequest, db: Session = Depends(get_db)):
    """Verify a user's email address using a one-time token."""
    token_hash = hash_email_token(payload.token.strip())
    db_token = (
        db.query(EmailToken)
        .filter(
            EmailToken.token_hash == token_hash,
            EmailToken.purpose == "verify",
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
            "Verification token is invalid or has expired.",
        )

    user = db.query(User).filter(User.id == db_token.user_id).first()
    if not user:
        raise api_error(
            400,
            "TOKEN_INVALID_OR_EXPIRED",
            "Verification token is invalid or has expired.",
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
        db.commit()
        MailerService.send_verification_email(user.email, user.display_name, raw_token)

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

    if not user or not verify_password(payload.password, user.password_hash):
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
        db.commit()
        MailerService.send_password_reset_email(user.email, user.display_name, raw_token)

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
