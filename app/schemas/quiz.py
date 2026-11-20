"""
Pydantic schemas for quiz-related data validation
"""
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


# Choice schemas
class ChoiceBase(BaseModel):
    text: str
    position: int = Field(default=0, ge=0, le=3)


class ChoiceCreate(ChoiceBase):
    is_correct: bool = False


class ChoiceResponse(ChoiceBase):
    id: str  # "a", "b", "c", "d"

    model_config = ConfigDict(from_attributes=True)


class ChoicePreviewResponse(ChoiceResponse):
    is_correct: bool


# Question schemas
class QuestionBase(BaseModel):
    prompt: str
    position: int = Field(default=0, ge=0)


class QuestionCreate(QuestionBase):
    explanation: Optional[str] = None
    choices: List[ChoiceCreate] = Field(..., min_length=4, max_length=4)

    @field_validator("prompt")
    @classmethod
    def prompt_not_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Question prompt must not be empty.")
        return value.strip()

    @field_validator("choices")
    @classmethod
    def validate_choices(cls, choices: List[ChoiceCreate]) -> List[ChoiceCreate]:
        if len(choices) != 4:
            raise ValueError("Each question must have exactly 4 choices.")
        for choice in choices:
            if not choice.text or not choice.text.strip():
                raise ValueError("Choice text must not be empty.")
        correct_count = sum(1 for c in choices if c.is_correct)
        if correct_count != 1:
            raise ValueError("Each question must have exactly 1 correct choice.")
        return choices


class QuestionResponse(QuestionBase):
    id: str  # "q_1", "q_2", etc.
    choices: List[ChoiceResponse]

    model_config = ConfigDict(from_attributes=True)


class QuestionPreviewResponse(QuestionBase):
    id: str
    explanation: Optional[str] = None
    choices: List[ChoicePreviewResponse]

    model_config = ConfigDict(from_attributes=True)


# Quiz schemas
class QuizBase(BaseModel):
    title: str = Field(default="Untitled Quiz", max_length=255)


class QuizCreate(QuizBase):
    category: Optional[str] = Field(default=None, max_length=100)
    source_type: str = Field(..., pattern="^(csv|txt|pdf|docx|structured|llm)$")
    questions: List[QuestionCreate]


class QuizUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    category: Optional[str] = Field(default=None, max_length=100)
    source_type: Optional[str] = Field(default=None, pattern="^(csv|txt|pdf|docx|structured|llm)$")
    questions: Optional[List[QuestionCreate]] = Field(default=None, min_length=1)


class QuizResponse(QuizBase):
    id: str  # "quiz_123"
    category: Optional[str] = None
    source_type: str
    source_filename: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime
    questions: List[QuestionResponse]

    model_config = ConfigDict(from_attributes=True)


class QuizPreviewResponse(QuizResponse):
    """Response for quiz preview/editing - includes correct answers and explanations"""
    questions: List[QuestionPreviewResponse]


class QuizSummaryResponse(BaseModel):
    """Summary item for GET /api/v1/quizzes"""
    id: str
    title: str
    category: Optional[str] = None
    source_filename: Optional[str] = None
    question_count: int
    last_score: Optional[float] = None
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# File upload schemas
class FileUpload(BaseModel):
    """Schema for file upload requests"""
    title: Optional[str] = Field(default=None, max_length=255)


# Generation request schemas
class GenerateQuizRequest(BaseModel):
    """Request to generate quiz from uploaded content"""
    title: Optional[str] = Field(default=None, max_length=255)
    category: Optional[str] = Field(default=None, max_length=100)
    use_llm: bool = Field(default=False)
    question_count: Optional[int] = Field(default=None, ge=1, le=50)
