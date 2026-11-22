"""
Application configuration settings
"""
from typing import List, Optional, Union
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    # Runtime environment ("development" | "staging" | "production")
    ENVIRONMENT: str = "development"

    # Database
    DATABASE_URL: str = "postgresql+psycopg2://quizclash:quizclash@localhost:5432/quizclash"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def normalize_database_url(cls, v):
        if isinstance(v, str):
            url = v.strip()
            if url.startswith("postgres://"):
                return "postgresql+psycopg2://" + url[len("postgres://"):]
            if url.startswith("postgresql://"):
                return "postgresql+psycopg2://" + url[len("postgresql://"):]
        return v

    # CORS
    FRONTEND_ORIGINS: Union[List[str], str] = [
        "http://localhost:5173",  # Vite default
        "http://127.0.0.1:5173",  # Vite loopback IP
        "http://localhost:3000",  # Create React App default
        "http://127.0.0.1:3000",  # CRA loopback IP
    ]

    @field_validator("FRONTEND_ORIGINS", mode="before")
    @classmethod
    def parse_frontend_origins(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    # App URL for email links
    APP_BASE_URL: str = "http://localhost:5173"

    # Auth & JWT settings
    SECRET_KEY: str = "dev-insecure-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    EMAIL_TOKEN_EXPIRE_HOURS: int = 24
    PASSWORD_RESET_EXPIRE_HOURS: int = 1

    # Cookie settings
    ACCESS_COOKIE_NAME: str = "qc_access_token"
    REFRESH_COOKIE_NAME: str = "qc_refresh_token"
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"
    COOKIE_DOMAIN: Optional[str] = None

    # Google OAuth settings
    OAUTH_REDIRECT_BASE_URL: Optional[str] = None
    OAUTH_FRONTEND_SUCCESS_PATH: str = "/"
    OAUTH_FRONTEND_ERROR_PATH: str = "/login"
    OAUTH_STATE_COOKIE_NAME: str = "qc_oauth_state"
    OAUTH_STATE_EXPIRE_SECONDS: int = 600
    OAUTH_HTTP_TIMEOUT_SECONDS: int = 10
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None

    # Initial admin seed
    ADMIN_EMAIL: Optional[str] = None
    ADMIN_PASSWORD: Optional[str] = None
    ADMIN_DISPLAY_NAME: str = "Admin"

    # Initial regular user seed (optional)
    DEMO_USER_EMAIL: Optional[str] = None
    DEMO_USER_PASSWORD: Optional[str] = None
    DEMO_USER_DISPLAY_NAME: str = "Demo User"

    # Optional SMTP settings (console mailer used when SMTP_HOST is unset)
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM_EMAIL: str = "no-reply@quizclash.local"
    SMTP_USE_TLS: bool = True

    # Rate limiting for auth routes
    RATE_LIMIT_AUTH_MAX_REQUESTS: int = 10
    RATE_LIMIT_AUTH_WINDOW_SECONDS: int = 60

    # Rate limiting for LLM quiz generation (per user)
    RATE_LIMIT_LLM_MAX_REQUESTS: int = 5
    RATE_LIMIT_LLM_WINDOW_SECONDS: int = 60

    # File upload settings
    MAX_UPLOAD_SIZE_MB: int = 10
    ALLOWED_FILE_TYPES: List[str] = [".csv", ".txt", ".pdf", ".docx"]

    # Quiz generation settings
    DEFAULT_QUESTIONS_PER_QUIZ: int = 10
    MIN_DEFINITIONS_FOR_GENERATION: int = 8

    # LLM Settings (Gemini API)
    LLM_API_KEY: Optional[str] = None
    LLM_MODEL: str = "gemini-3.5-flash-lite"
    LLM_API_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta"
    LLM_MAX_TOKENS: int = 4096
    LLM_TIMEOUT_SECONDS: int = 30
    LLM_WEB_SEARCH_TIMEOUT_SECONDS: int = 15
    LLM_MAX_INPUT_CHARS: int = 20000
    LLM_MAX_KEYWORDS: int = 6

    # PDF Generation
    PDF_FONT_NAME: str = "Helvetica"


settings = Settings()
