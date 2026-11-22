"""
Google OAuth 2.0 (Authorization Code + PKCE) service helpers.
"""
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode

import httpx

from app.core.config import settings

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_SCOPES = "openid email profile"


class OAuthProviderError(Exception):
    """Structured error raised when Google OAuth token exchange or profile lookup fails."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class GoogleUserInfo:
    provider_user_id: str
    email: Optional[str]
    email_verified: bool
    display_name: str
    avatar_url: Optional[str] = None


def is_google_oauth_enabled() -> bool:
    """Return True when both Google OAuth client ID and client secret are configured."""
    return bool(
        (settings.GOOGLE_CLIENT_ID or "").strip()
        and (settings.GOOGLE_CLIENT_SECRET or "").strip()
    )


def sanitize_next_path(next_path: Optional[str]) -> str:
    """
    Allow only safe relative redirect paths starting with a single '/'.
    Prevents open-redirect attacks via protocol-relative URLs (//evil.com) or schemes.
    """
    default_path = settings.OAUTH_FRONTEND_SUCCESS_PATH or "/"
    if not default_path.startswith("/") or default_path.startswith("//"):
        default_path = "/"

    if not next_path:
        return default_path

    candidate = next_path.strip()
    if (
        not candidate.startswith("/")
        or candidate.startswith("//")
        or "\\" in candidate
        or any(ord(ch) < 32 for ch in candidate)
    ):
        return default_path
    return candidate


def build_google_authorization_url(
    redirect_uri: str,
    state: str,
    code_challenge: str,
) -> str:
    """Build the Google OAuth 2.0 authorization URL with PKCE S256."""
    params = {
        "client_id": (settings.GOOGLE_CLIENT_ID or "").strip(),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def exchange_google_code_for_userinfo(
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> GoogleUserInfo:
    """Exchange a Google authorization code + PKCE verifier for normalized user profile data."""
    timeout = httpx.Timeout(settings.OAUTH_HTTP_TIMEOUT_SECONDS)
    try:
        with httpx.Client(timeout=timeout) as client:
            token_resp = client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": (settings.GOOGLE_CLIENT_ID or "").strip(),
                    "client_secret": (settings.GOOGLE_CLIENT_SECRET or "").strip(),
                    "code": code,
                    "code_verifier": code_verifier,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                },
                headers={"Accept": "application/json"},
            )
            if token_resp.status_code != 200:
                raise OAuthProviderError(
                    "OAUTH_TOKEN_EXCHANGE_FAILED",
                    "Failed to exchange authorization code with Google.",
                )

            token_data = token_resp.json()
            access_token = token_data.get("access_token")
            if not access_token:
                raise OAuthProviderError(
                    "OAUTH_TOKEN_EXCHANGE_FAILED",
                    "Google token response did not include an access token.",
                )

            userinfo_resp = client.get(
                GOOGLE_USERINFO_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
            )
            if userinfo_resp.status_code != 200:
                raise OAuthProviderError(
                    "OAUTH_USERINFO_FAILED",
                    "Failed to retrieve user profile from Google.",
                )

            profile = userinfo_resp.json()
    except OAuthProviderError:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise OAuthProviderError(
            "OAUTH_PROVIDER_ERROR",
            f"Error communicating with Google OAuth: {exc}",
        ) from exc

    sub = str(profile.get("sub") or "").strip()
    if not sub:
        raise OAuthProviderError(
            "OAUTH_USERINFO_FAILED",
            "Google userinfo response is missing subject identifier.",
        )

    raw_email = profile.get("email")
    email = str(raw_email).strip().lower() if raw_email else None
    email_verified = bool(profile.get("email_verified") is True)

    raw_name = (
        profile.get("name")
        or profile.get("given_name")
        or (email.split("@")[0] if email else "User")
    )
    display_name = str(raw_name).strip()[:100] or "User"

    raw_picture = profile.get("picture")
    avatar_url = str(raw_picture).strip()[:500] if raw_picture else None

    return GoogleUserInfo(
        provider_user_id=sub,
        email=email,
        email_verified=email_verified,
        display_name=display_name,
        avatar_url=avatar_url,
    )
