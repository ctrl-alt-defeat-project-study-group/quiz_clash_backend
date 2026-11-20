"""
Tests verifying Phase 9: production safety checks and Docker/Compose hardening.
"""
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.production import collect_production_issues, validate_production_settings

ROOT_DIR = Path(__file__).resolve().parent.parent


def test_production_safety_checks_fail_fast_on_insecure_config():
    # Default dev settings do not raise when ENVIRONMENT=development
    dev_cfg = Settings(
        ENVIRONMENT="development",
        SECRET_KEY="dev-insecure-secret-key-change-in-production",
        COOKIE_SECURE=False,
    )
    validate_production_settings(dev_cfg)

    # Same settings fail fast when ENVIRONMENT=production
    bad_prod = Settings(
        ENVIRONMENT="production",
        SECRET_KEY="dev-insecure-secret-key-change-in-production",
        COOKIE_SECURE=False,
        FRONTEND_ORIGINS=["*"],
        RATE_LIMIT_AUTH_MAX_REQUESTS=0,
    )
    issues = collect_production_issues(bad_prod)
    assert len(issues) == 4
    with pytest.raises(RuntimeError, match="Unsafe production configuration"):
        validate_production_settings(bad_prod)

    # Short secret fails in production
    short_secret_prod = Settings(
        ENVIRONMENT="production",
        SECRET_KEY="short-secret",
        COOKIE_SECURE=True,
        FRONTEND_ORIGINS=["https://quizclash.example.com"],
    )
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        validate_production_settings(short_secret_prod)

    # Hardened production settings pass cleanly
    good_prod = Settings(
        ENVIRONMENT="production",
        SECRET_KEY="a" * 48,
        COOKIE_SECURE=True,
        FRONTEND_ORIGINS=["https://quizclash.example.com"],
        RATE_LIMIT_AUTH_MAX_REQUESTS=10,
        RATE_LIMIT_AUTH_WINDOW_SECONDS=60,
    )
    assert collect_production_issues(good_prod) == []
    validate_production_settings(good_prod)


def test_dockerfiles_and_compose_configuration():
    dockerfile = (ROOT_DIR / "Dockerfile").read_text(encoding="utf-8")
    dockerfile_dev = (ROOT_DIR / "Dockerfile.dev").read_text(encoding="utf-8")
    compose = (ROOT_DIR / "docker-compose.yml").read_text(encoding="utf-8")

    assert "FROM python:3.12-slim" in dockerfile
    assert "libpango-1.0-0" in dockerfile
    assert "FROM python:3.12-slim" in dockerfile_dev
    assert "libpango-1.0-0" in dockerfile_dev

    assert "postgres:16-alpine" in compose
    assert "alembic upgrade head" in compose
    assert "api:" in compose and "db:" in compose
