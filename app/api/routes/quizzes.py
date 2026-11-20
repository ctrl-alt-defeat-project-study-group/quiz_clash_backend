"""
API routes for quiz management
"""
import hashlib
from typing import Optional
from fastapi import APIRouter, Depends, File, UploadFile, Form, HTTPException
from sqlalchemy.orm import Session, selectinload

from app.core.deps import ensure_owner_or_admin, get_current_user
from app.core.ids import parse_prefixed_id
from app.db.session import get_db
from app.db.models import Quiz, Question, Choice, User
from app.schemas.quiz import QuizResponse, QuizUpdate, QuizPreviewResponse
from app.services.parser import FileParser
from app.services.quiz_generator import QuizGenerator

router = APIRouter()


@router.post("/quizzes", response_model=QuizResponse)
def create_quiz_from_file(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    use_llm: bool = Form(False),
    question_count: Optional[int] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Upload a file and generate a quiz from it.

    - **file**: CSV or TXT file with terms and definitions
    - **title**: Optional title for the quiz (defaults to filename)
    - **use_llm**: Whether to use AI for question generation (not implemented yet)
    - **question_count**: Number of questions to generate
    """
    FileParser.validate_file(file)
    terms_definitions = FileParser.parse_file(file)

    if use_llm:
        raise HTTPException(
            status_code=501,
            detail="LLM-based generation is not yet implemented",
        )

    filename = file.filename or "Untitled Quiz"
    quiz_title = (title.strip() if title and title.strip() else filename.rsplit(".", 1)[0])

    # Run duplicate detection before generation while honoring new title and question_count
    source_content = "\n".join(f"{t}:{d}" for t, d in terms_definitions)
    source_hash = hashlib.sha256(source_content.encode("utf-8")).hexdigest()

    existing_quizzes = (
        db.query(Quiz)
        .options(selectinload(Quiz.questions).selectinload(Question.choices))
        .filter(
            Quiz.owner_id == current_user.id,
            Quiz.source_hash == source_hash,
            Quiz.title == quiz_title,
        )
        .all()
    )
    for existing_quiz in existing_quizzes:
        if question_count is None or len(existing_quiz.questions) == question_count:
            return format_quiz_response(existing_quiz, include_correct=False)

    questions_data = QuizGenerator.generate_from_structured(
        terms_definitions, question_count
    )
    QuizGenerator.validate_questions(questions_data)

    db_quiz = Quiz(
        owner_id=current_user.id,
        title=quiz_title,
        source_type="csv" if filename.lower().endswith(".csv") else "txt",
        source_hash=source_hash,
        status="draft",
    )
    db.add(db_quiz)
    db.flush()

    for q_idx, question_data in enumerate(questions_data):
        db_question = Question(
            quiz_id=db_quiz.id,
            prompt=question_data["prompt"],
            position=question_data.get("position", q_idx),
        )
        db.add(db_question)
        db.flush()

        for choice_data in question_data["choices"]:
            db_choice = Choice(
                question_id=db_question.id,
                text=choice_data["text"],
                is_correct=choice_data["is_correct"],
                position=choice_data.get("position", 0),
            )
            db.add(db_choice)

    db.commit()

    db_quiz = (
        db.query(Quiz)
        .options(selectinload(Quiz.questions).selectinload(Question.choices))
        .filter(Quiz.id == db_quiz.id)
        .first()
    )
    return format_quiz_response(db_quiz, include_correct=False)


@router.get("/quizzes/{quiz_id}", response_model=QuizResponse)
def get_quiz(
    quiz_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get a playable quiz by ID.

    Returns quiz without correct answers for taking the quiz.
    """
    numeric_id = parse_prefixed_id(
        quiz_id, "quiz", status_code=404, detail="Quiz not found"
    )

    db_quiz = (
        db.query(Quiz)
        .options(selectinload(Quiz.questions).selectinload(Question.choices))
        .filter(Quiz.id == numeric_id)
        .first()
    )
    if not db_quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    ensure_owner_or_admin(db_quiz.owner_id, current_user)
    return format_quiz_response(db_quiz, include_correct=False)


@router.get("/quizzes/{quiz_id}/preview", response_model=QuizPreviewResponse)
def get_quiz_preview(
    quiz_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get quiz preview with correct answers.

    For editing/viewing quiz before publishing.
    """
    numeric_id = parse_prefixed_id(
        quiz_id, "quiz", status_code=404, detail="Quiz not found"
    )

    db_quiz = (
        db.query(Quiz)
        .options(selectinload(Quiz.questions).selectinload(Question.choices))
        .filter(Quiz.id == numeric_id)
        .first()
    )
    if not db_quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    ensure_owner_or_admin(db_quiz.owner_id, current_user)
    return format_quiz_response(db_quiz, include_correct=True)


@router.patch("/quizzes/{quiz_id}", response_model=QuizPreviewResponse)
def update_quiz(
    quiz_id: str,
    quiz_data: QuizUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update quiz (title, status; full question/choice editing in Phase 5).
    """
    numeric_id = parse_prefixed_id(
        quiz_id, "quiz", status_code=404, detail="Quiz not found"
    )

    db_quiz = (
        db.query(Quiz)
        .options(selectinload(Quiz.questions).selectinload(Question.choices))
        .filter(Quiz.id == numeric_id)
        .first()
    )
    if not db_quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    ensure_owner_or_admin(db_quiz.owner_id, current_user)

    if quiz_data.title is not None:
        db_quiz.title = quiz_data.title

    db_quiz.status = "published"

    db.commit()
    db.refresh(db_quiz)

    return format_quiz_response(db_quiz, include_correct=True)


def format_quiz_response(db_quiz: Quiz, include_correct: bool = False) -> dict:
    """Format database quiz for API response"""
    sorted_questions = sorted(db_quiz.questions, key=lambda q: q.position)

    formatted_questions = []

    for db_question in sorted_questions:
        sorted_choices = sorted(db_question.choices, key=lambda c: c.position)

        formatted_choices = []
        for c_idx, db_choice in enumerate(sorted_choices):
            choice_id = chr(97 + c_idx)  # 'a', 'b', 'c', 'd'
            choice_data = {
                "id": choice_id,
                "text": db_choice.text,
                "position": c_idx,
            }

            if include_correct:
                choice_data["is_correct"] = db_choice.is_correct

            formatted_choices.append(choice_data)

        formatted_questions.append(
            {
                "id": f"q_{db_question.id}",
                "prompt": db_question.prompt,
                "position": db_question.position,
                "choices": formatted_choices,
            }
        )

    return {
        "id": f"quiz_{db_quiz.id}",
        "title": db_quiz.title,
        "source_type": db_quiz.source_type,
        "status": db_quiz.status,
        "created_at": db_quiz.created_at,
        "questions": formatted_questions,
    }
