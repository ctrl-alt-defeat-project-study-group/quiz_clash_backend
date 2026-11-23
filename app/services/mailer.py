"""
Email delivery service: Brevo HTTPS API (preferred on Render), SMTP, or console backend in dev.
"""
from email.message import EmailMessage
import logging
import smtplib
from urllib.parse import quote

import httpx

from app.core.config import settings

logger = logging.getLogger("quizclash.mailer")

BREVO_EMAIL_API_URL = "https://api.brevo.com/v3/smtp/email"


class MailerService:
    """Send transactional emails (verification and password reset)."""

    @staticmethod
    def _send_via_brevo(to_email: str, subject: str, body: str) -> None:
        api_key = (settings.BREVO_API_KEY or "").strip()
        payload = {
            "sender": {
                "name": settings.BREVO_FROM_NAME or "QuizClash",
                "email": settings.SMTP_FROM_EMAIL,
            },
            "to": [{"email": to_email}],
            "subject": subject,
            "textContent": body,
        }
        response = httpx.post(
            BREVO_EMAIL_API_URL,
            json=payload,
            headers={
                "accept": "application/json",
                "api-key": api_key,
                "content-type": "application/json",
            },
            timeout=10.0,
        )
        if not response.is_success:
            logger.error(
                "Brevo email API failed (%s): %s",
                response.status_code,
                response.text[:300],
            )
            raise RuntimeError(f"Brevo email API error ({response.status_code})")

    @staticmethod
    def _send(to_email: str, subject: str, body: str) -> None:
        if (settings.BREVO_API_KEY or "").strip():
            MailerService._send_via_brevo(to_email, subject, body)
            return

        if not settings.SMTP_HOST:
            logger.info("[DEV MAILER] To: %s | Subject: %s\n%s", to_email, subject, body)
            print(f"[DEV MAILER] To: {to_email} | Subject: {subject}\n{body}")
            return

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = settings.SMTP_FROM_EMAIL
        msg["To"] = to_email
        msg.set_content(body)

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
            if settings.SMTP_USE_TLS:
                server.starttls()
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)

    @classmethod
    def send_verification_email(cls, to_email: str, display_name: str, token: str) -> str:
        base = settings.APP_BASE_URL.rstrip("/")
        link = f"{base}/verify-email?email={quote(to_email)}&token={quote(token)}"
        body = (
            f"Hi {display_name},\n\n"
            f"Your QuizClash verification code (OTP) is:\n\n"
            f"    {token}\n\n"
            f"Enter this 6-digit code on the verification page, or open this link:\n{link}\n\n"
            f"This code expires in 15 minutes.\n"
        )
        cls._send(to_email, f"Your QuizClash verification code: {token}", body)
        return link

    @classmethod
    def send_password_reset_email(cls, to_email: str, display_name: str, token: str) -> str:
        base = settings.APP_BASE_URL.rstrip("/")
        link = f"{base}/reset-password?token={quote(token)}"
        body = (
            f"Hi {display_name},\n\n"
            f"Reset your QuizClash password by opening this link:\n{link}\n\n"
            f"This link expires in {settings.PASSWORD_RESET_EXPIRE_HOURS} hour(s).\n"
        )
        cls._send(to_email, "Reset your QuizClash password", body)
        return link
