"""
Pydantic schemas for quiz-related data validation
"""
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


# Choice schemas
class ChoiceBase(BaseModel):
    text: str
    position: int = Field(default=0, ge=0, le=3)


class ChoiceCreate(ChoiceBase):
    is_correct: bool = False


class ChoiceResponse(ChoiceBase):
    id: str  # Will be like "a", "b", "c", "d"
    
    class Config:
        from_attributes = True


# Question schemas
class QuestionBase(BaseModel):
    prompt: str
    position: int = Field(default=0, ge=0)


class QuestionCreate(QuestionBase):
    choices: List[ChoiceCreate] = Field(..., min_items=4, max_items=4)


class QuestionResponse(QuestionBase):
    id: str  # Will be like "q_1", "q_2", etc.
    choices: List[ChoiceResponse]
    
    class Config:
        from_attributes = True


# Quiz schemas
class QuizBase(BaseModel):
    title: str = Field(default="Untitled Quiz", max_length=255)


class QuizCreate(QuizBase):
    source_type: str = Field(..., regex="^(csv|txt|structured|llm)$")
    questions: List[QuestionCreate]


class QuizResponse(QuizBase):
    id: str  # Will be like "quiz_123"
    source_type: str
    status: str
    created_at: datetime
    questions: List[QuestionResponse]
    
    class Config:
        from_attributes = True


class QuizPreviewResponse(QuizResponse):
    """Response for quiz preview/editing - includes correct answers"""
    pass  # Same as QuizResponse, but will include correct answers in choices


# File upload schemas
class FileUpload(BaseModel):
    """Schema for file upload requests"""
    title: Optional[str] = Field(default=None, max_length=255)


# Generation request schemas
class GenerateQuizRequest(BaseModel):
    """Request to generate quiz from uploaded content"""
    title: Optional[str] = Field(default=None, max_length=255)
    use_llm: bool = Field(default=False)
    question_count: Optional[int] = Field(default=None, ge=1, le=50)