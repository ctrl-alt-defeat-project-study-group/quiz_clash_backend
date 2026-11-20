"""
Pydantic schemas for user settings & account management (Phase 8).
"""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator

from app.core.language import normalize_language

ThemeType = Literal["light", "dark", "system"]
DifficultyType = Literal["Mixed", "Foundational", "Advanced"]
ALLOWED_DEFAULT_QUESTIONS = (5, 10, 15, 20)


class UserSettingsResponse(BaseModel):
    display_name: str
    email: str
    theme: str
    ui_language: str
    default_questions: int
    difficulty: str
    quiz_language: str
    shuffle_questions: bool
    show_explanations: bool
    study_reminders: bool
    weekly_summary: bool


class UserSettingsUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    theme: Optional[ThemeType] = None
    ui_language: Optional[str] = None
    default_questions: Optional[int] = None
    difficulty: Optional[DifficultyType] = None
    quiz_language: Optional[str] = Field(default=None, min_length=1, max_length=30)
    shuffle_questions: Optional[bool] = None
    show_explanations: Optional[bool] = None
    study_reminders: Optional[bool] = None
    weekly_summary: Optional[bool] = None

    @field_validator("ui_language")
    @classmethod
    def validate_ui_language(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        raw = v.strip().lower()
        if raw not in ("en", "mm", "my"):
            raise ValueError("ui_language must be 'en' or 'mm'.")
        return normalize_language(raw)

    @field_validator("default_questions")
    @classmethod
    def validate_default_questions(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return None
        if v not in ALLOWED_DEFAULT_QUESTIONS:
            raise ValueError("default_questions must be one of 5, 10, 15, or 20.")
        return v


class AccountExportResponse(BaseModel):
    exported_at: datetime
    account: Dict[str, Any]
    settings: UserSettingsResponse
    quizzes: List[Dict[str, Any]]
    attempts: List[Dict[str, Any]]


class AccountResetResponse(BaseModel):
    message: str
    deleted_quizzes: int
    deleted_attempts: int
    deleted_rooms: int
