"""
Pydantic schemas for attempt-related data validation
"""
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


# Answer submission schemas
class AnswerSubmission(BaseModel):
    question_id: str
    choice_id: str


class AttemptCreate(BaseModel):
    duration_seconds: Optional[int] = Field(default=None, ge=0)
    answers: List[AnswerSubmission]


# Result schemas
class QuestionResult(BaseModel):
    question_id: str
    question_prompt: str
    selected_choice_id: str
    selected_choice_text: str
    correct_choice_id: str
    correct_choice_text: str
    explanation: Optional[str] = None
    is_correct: bool


class AttemptResponse(BaseModel):
    id: str  # "att_101"
    quiz_id: str
    quiz_title: str
    score: int
    total_questions: int
    percentage: float
    duration_seconds: Optional[int] = None
    completed_at: datetime
    questions: List[QuestionResult]

    model_config = ConfigDict(from_attributes=True)


class AttemptSummaryResponse(BaseModel):
    """Summary item for GET /api/v1/attempts"""
    id: str
    quiz_id: str
    quiz_title: str
    score: int
    total_questions: int
    percentage: float
    duration_seconds: Optional[int] = None
    completed_at: datetime

    model_config = ConfigDict(from_attributes=True)
