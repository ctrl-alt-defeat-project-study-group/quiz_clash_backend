"""
Pydantic schemas for attempt-related data validation
"""
from pydantic import BaseModel, Field
from typing import List
from datetime import datetime


# Answer submission schemas
class AnswerSubmission(BaseModel):
    question_id: str
    choice_id: str


class AttemptCreate(BaseModel):
    answers: List[AnswerSubmission]


# Result schemas
class QuestionResult(BaseModel):
    question_id: str
    question_prompt: str
    selected_choice_id: str
    selected_choice_text: str
    correct_choice_id: str
    correct_choice_text: str
    is_correct: bool


class AttemptResponse(BaseModel):
    id: str  # Will be like "attempt_456"
    quiz_id: str
    score: int
    total_questions: int
    percentage: float
    completed_at: datetime
    questions: List[QuestionResult]
    
    class Config:
        from_attributes = True