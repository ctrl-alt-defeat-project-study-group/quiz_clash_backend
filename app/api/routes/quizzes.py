"""
API routes for quiz management
"""
import hashlib
from typing import List
from fastapi import APIRouter, Depends, File, UploadFile, Form, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import Quiz, Question, Choice
from app.schemas.quiz import (
    QuizResponse, QuizCreate, QuizPreviewResponse,
    FileUpload, GenerateQuizRequest
)
from app.services.parser import FileParser
from app.services.quiz_generator import QuizGenerator

router = APIRouter()


def generate_quiz_id() -> str:
    """Generate a unique quiz ID"""
    import uuid
    import time
    timestamp = int(time.time() * 1000)
    unique_id = str(uuid.uuid4())[:8]
    return f"quiz_{timestamp}_{unique_id}"


@router.post("/quizzes", response_model=QuizResponse)
async def create_quiz_from_file(
    file: UploadFile = File(...),
    title: str = Form(None),
    use_llm: bool = Form(False),
    question_count: int = Form(None),
    db: Session = Depends(get_db)
):
    """
    Upload a file and generate a quiz from it
    
    - **file**: CSV or TXT file with terms and definitions
    - **title**: Optional title for the quiz (defaults to filename)
    - **use_llm**: Whether to use AI for question generation (not implemented yet)
    - **question_count**: Number of questions to generate
    """
    # Validate file
    FileParser.validate_file(file)
    
    # Parse file content
    terms_definitions = FileParser.parse_file(file)
    
    # Generate questions
    if use_llm:
        # LLM-based generation (to be implemented)
        raise HTTPException(
            status_code=501,
            detail="LLM-based generation is not yet implemented"
        )
    else:
        questions_data = QuizGenerator.generate_from_structured(
            terms_definitions, question_count
        )
    
    # Validate generated questions
    QuizGenerator.validate_questions(questions_data)
    
    # Calculate source hash for duplicate detection
    source_content = "\n".join([f"{t}:{d}" for t, d in terms_definitions])
    source_hash = hashlib.sha256(source_content.encode()).hexdigest()
    
    # Check for duplicate quiz
    existing_quiz = db.query(Quiz).filter(Quiz.source_hash == source_hash).first()
    if existing_quiz:
        # Return existing quiz instead of creating new one
        return format_quiz_response(existing_quiz, include_correct=False)
    
    # Create quiz in database
    quiz_title = title or file.filename.rsplit('.', 1)[0]  # Use filename without extension
    
    db_quiz = Quiz(
        title=quiz_title,
        source_type="csv" if file.filename.endswith('.csv') else "txt",
        source_hash=source_hash,
        status="draft"
    )
    db.add(db_quiz)
    db.flush()  # Get quiz ID for relationships
    
    # Create questions and choices
    for q_idx, question_data in enumerate(questions_data):
        db_question = Question(
            quiz_id=db_quiz.id,
            prompt=question_data["prompt"],
            position=question_data.get("position", q_idx)
        )
        db.add(db_question)
        db.flush()
        
        # Create choices
        for choice_data in question_data["choices"]:
            db_choice = Choice(
                question_id=db_question.id,
                text=choice_data["text"],
                is_correct=choice_data["is_correct"],
                position=choice_data.get("position", 0)
            )
            db.add(db_choice)
    
    db.commit()
    db.refresh(db_quiz)
    
    return format_quiz_response(db_quiz, include_correct=False)


@router.get("/quizzes/{quiz_id}", response_model=QuizResponse)
async def get_quiz(
    quiz_id: str,
    db: Session = Depends(get_db)
):
    """
    Get a playable quiz by ID
    
    Returns quiz without correct answers for taking the quiz
    """
    # Parse numeric ID from string format
    try:
        numeric_id = int(quiz_id.split('_')[-1]) if '_' in quiz_id else int(quiz_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Quiz not found")
    
    db_quiz = db.query(Quiz).filter(Quiz.id == numeric_id).first()
    if not db_quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    
    return format_quiz_response(db_quiz, include_correct=False)


@router.get("/quizzes/{quiz_id}/preview", response_model=QuizPreviewResponse)
async def get_quiz_preview(
    quiz_id: str,
    db: Session = Depends(get_db)
):
    """
    Get quiz preview with correct answers
    
    For editing/viewing quiz before publishing
    """
    # Parse numeric ID from string format
    try:
        numeric_id = int(quiz_id.split('_')[-1]) if '_' in quiz_id else int(quiz_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Quiz not found")
    
    db_quiz = db.query(Quiz).filter(Quiz.id == numeric_id).first()
    if not db_quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    
    return format_quiz_response(db_quiz, include_correct=True)


@router.patch("/quizzes/{quiz_id}")
async def update_quiz(
    quiz_id: str,
    quiz_data: QuizCreate,
    db: Session = Depends(get_db)
):
    """
    Update quiz (edit questions, choices, etc.)
    
    For Phase 1: Basic implementation
    For Phase 2: Add authentication and ownership checks
    """
    # Parse numeric ID from string format
    try:
        numeric_id = int(quiz_id.split('_')[-1]) if '_' in quiz_id else int(quiz_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Quiz not found")
    
    db_quiz = db.query(Quiz).filter(Quiz.id == numeric_id).first()
    if not db_quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    
    # TODO: Add ownership/authorization check in Phase 2
    
    # Update quiz title
    if quiz_data.title:
        db_quiz.title = quiz_data.title
    
    # TODO: Implement full question/choice editing
    # For now, just mark as published
    db_quiz.status = "published"
    
    db.commit()
    db.refresh(db_quiz)
    
    return format_quiz_response(db_quiz, include_correct=True)


def format_quiz_response(db_quiz: Quiz, include_correct: bool = False) -> dict:
    """Format database quiz for API response"""
    # Sort questions by position
    sorted_questions = sorted(db_quiz.questions, key=lambda q: q.position)
    
    formatted_questions = []
    
    for q_idx, db_question in enumerate(sorted_questions):
        # Sort choices by position
        sorted_choices = sorted(db_question.choices, key=lambda c: c.position)
        
        formatted_choices = []
        for c_idx, db_choice in enumerate(sorted_choices):
            choice_id = chr(97 + c_idx)  # 'a', 'b', 'c', 'd'
            choice_data = {
                "id": choice_id,
                "text": db_choice.text,
                "position": c_idx
            }
            
            if include_correct:
                choice_data["is_correct"] = db_choice.is_correct
            
            formatted_choices.append(choice_data)
        
        formatted_questions.append({
            "id": f"q_{q_idx + 1}",
            "prompt": db_question.prompt,
            "position": db_question.position,
            "choices": formatted_choices
        })
    
    return {
        "id": f"quiz_{db_quiz.id}",
        "title": db_quiz.title,
        "source_type": db_quiz.source_type,
        "status": db_quiz.status,
        "created_at": db_quiz.created_at,
        "questions": formatted_questions
    }