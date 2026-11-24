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
    assert "alembic upgrade head" in dockerfile
    assert "${PORT:-8000}" in dockerfile


def test_database_url_normalization():
    s1 = Settings(DATABASE_URL="postgres://user:pass@host:5432/db")
    assert s1.DATABASE_URL == "postgresql+psycopg2://user:pass@host:5432/db"

    s2 = Settings(DATABASE_URL="postgresql://user:pass@host:5432/db")
    assert s2.DATABASE_URL == "postgresql+psycopg2://user:pass@host:5432/db"

    s3 = Settings(DATABASE_URL="sqlite:///./dev.db")
    assert s3.DATABASE_URL == "sqlite:///./dev.db"


def test_render_blueprint_configuration():
    render_yaml = (ROOT_DIR / "render.yaml").read_text(encoding="utf-8")
    assert "runtime: docker" in render_yaml
    assert "dockerfilePath: ./Dockerfile" in render_yaml
    assert "healthCheckPath: /api/v1/health" in render_yaml
    assert "plan: free" in render_yaml
    assert "ENVIRONMENT" in render_yaml and "production" in render_yaml
    assert "COOKIE_SECURE" in render_yaml
    assert "COOKIE_SAMESITE" in render_yaml and "none" in render_yaml
    assert "fromDatabase:" in render_yaml
    assert "BREVO_API_KEY" in render_yaml
    assert "LLM_API_KEY" in render_yaml
    assert not (ROOT_DIR / "docker-compose.prod.yml").exists()
    assert not (ROOT_DIR / "Caddyfile").exists()


def test_cross_site_cookie_clearing_preserves_security_attributes(monkeypatch):
    from fastapi import Response
    from app.core import security

    monkeypatch.setattr(security.settings, "COOKIE_SECURE", True)
    monkeypatch.setattr(security.settings, "COOKIE_SAMESITE", "none")

    resp = Response()
    security.clear_auth_cookies(resp)
    security.clear_pending_registration_cookie(resp)

    set_cookies = [v.decode("latin-1").lower() for k, v in resp.raw_headers if k.lower() == b"set-cookie"]
    assert len(set_cookies) == 3
    for header in set_cookies:
        assert "secure" in header
        assert "samesite=none" in header
        assert "httponly" in header
