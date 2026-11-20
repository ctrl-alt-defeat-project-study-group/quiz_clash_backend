"""
Pydantic schemas for admin management endpoints.
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class AdminUserUpdate(BaseModel):
    role: Optional[Literal["user", "admin"]] = None
    is_active: Optional[bool] = None


class AdminQuizSummary(BaseModel):
    id: str
    title: str
    owner_id: Optional[int] = None
    owner_email: Optional[str] = None
    source_type: str
    status: str
    question_count: int
    created_at: datetime


class AdminStatsResponse(BaseModel):
    total_users: int
    active_users: int
    verified_users: int
    admin_users: int
    total_quizzes: int
    total_attempts: int
