"""
Production safety checks executed during application startup.
"""
import logging
from typing import List

from app.core.config import Settings

logger = logging.getLogger(__name__)

INSECURE_SECRET_KEYS = {
    "dev-insecure-secret-key-change-in-production",
    "change-me-to-a-long-random-secret",
    "secret",
    "changeme",
}
MIN_PRODUCTION_SECRET_LENGTH = 32


def collect_production_issues(cfg: Settings) -> List[str]:
    """Return a list of security misconfigurations for production deployments."""
    issues: List[str] = []

    secret = (cfg.SECRET_KEY or "").strip()
    if secret in INSECURE_SECRET_KEYS or len(secret) < MIN_PRODUCTION_SECRET_LENGTH:
        issues.append(
            f"SECRET_KEY must be a non-default random value of at least "
            f"{MIN_PRODUCTION_SECRET_LENGTH} characters."
        )

    if not cfg.COOKIE_SECURE:
        issues.append("COOKIE_SECURE must be True in production.")

    if any(origin.strip() == "*" for origin in cfg.FRONTEND_ORIGINS):
        issues.append("FRONTEND_ORIGINS must not contain wildcard '*' in production.")

    if cfg.RATE_LIMIT_AUTH_MAX_REQUESTS <= 0 or cfg.RATE_LIMIT_AUTH_WINDOW_SECONDS <= 0:
        issues.append("Auth rate limiting must be enabled with positive limits in production.")

    return issues


def validate_production_settings(cfg: Settings) -> None:
    """Fail fast in production if critical security settings are insecure."""
    env = (cfg.ENVIRONMENT or "development").strip().lower()
    issues = collect_production_issues(cfg)
    if not issues:
        return

    if env == "production":
        joined = "; ".join(issues)
        raise RuntimeError(f"Unsafe production configuration: {joined}")

    logger.warning(
        "Running in %s mode with non-production security settings: %s",
        env,
        "; ".join(issues),
    )
