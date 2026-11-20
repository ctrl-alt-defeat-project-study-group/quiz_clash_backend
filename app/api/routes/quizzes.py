"""
API routes for quiz management
"""
from datetime import datetime, timezone
import hashlib
from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, File, Form, Header, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.core.deps import ensure_owner_or_admin, get_current_user
from app.core.errors import api_error
from app.core.ids import parse_prefixed_id
from app.core.language import resolve_request_language
from app.db.models import Attempt, Choice, Question, Quiz, User
from app.db.session import get_db
from app.schemas.quiz import (
    QuizPreviewResponse,
    QuizResponse,
    QuizSummaryResponse,
    QuizUpdate,
)
from app.services.parser import FileParser
from app.services.quiz_generator import QuizGenerator

router = APIRouter()

ALLOWED_QUESTION_COUNTS = (5, 10, 15, 20)


@router.get("/quizzes", response_model=List[QuizSummaryResponse])
def list_quizzes(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List the authenticated user's saved quizzes for dashboard and sidebar library."""
    quizzes = (
        db.query(Quiz)
        .filter(Quiz.owner_id == current_user.id)
        .order_by(Quiz.updated_at.desc(), Quiz.id.desc())
        .all()
    )
    if not quizzes:
        return []

    quiz_ids = [q.id for q in quizzes]

    # Batch-load question counts in a single query
    question_count_rows = (
        db.query(Question.quiz_id, func.count(Question.id))
        .filter(Question.quiz_id.in_(quiz_ids))
        .group_by(Question.quiz_id)
        .all()
    )
    question_counts: Dict[int, int] = {
        qid: count for qid, count in question_count_rows
    }

    # Batch-load latest attempt percentage per quiz for this user
    attempt_rows = (
        db.query(Attempt)
        .filter(
            Attempt.quiz_id.in_(quiz_ids),
            Attempt.user_id == current_user.id,
        )
        .order_by(Attempt.completed_at.desc(), Attempt.id.desc())
        .all()
    )
    last_scores: Dict[int, float] = {}
    for attempt in attempt_rows:
        if attempt.quiz_id not in last_scores:
            pct = (
                round((attempt.score / attempt.total_questions) * 100, 2)
                if attempt.total_questions > 0
                else 0.0
            )
            last_scores[attempt.quiz_id] = pct

    return [
        {
            "id": f"quiz_{quiz.id}",
            "title": quiz.title,
            "category": quiz.category,
            "source_filename": quiz.source_filename,
            "question_count": question_counts.get(quiz.id, 0),
            "last_score": last_scores.get(quiz.id),
            "updated_at": quiz.updated_at or quiz.created_at,
        }
        for quiz in quizzes
    ]


def _detect_source_type(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".csv"):
        return "csv"
    if lower.endswith(".pdf"):
        return "pdf"
    if lower.endswith(".docx"):
        return "docx"
    return "txt"


@router.post("/quizzes", response_model=QuizResponse, status_code=201)
def create_quiz_from_file(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
    use_llm: bool = Form(False),
    question_count: Optional[int] = Form(None),
    language: Optional[str] = Form(None),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Upload a file and generate a quiz from it.

    - **file**: CSV, TXT, PDF, or DOCX file with terms and definitions
    - **title**: Optional title for the quiz (defaults to filename)
    - **category**: Optional subject/category label
    - **use_llm**: Whether to use AI for question generation (not implemented yet)
    - **question_count**: Number of questions to generate (5, 10, 15, or 20)
    - **language**: Optional quiz language ('en' or 'mm'; 'my' accepted as alias)
    """
    if question_count is not None and question_count not in ALLOWED_QUESTION_COUNTS:
        raise api_error(
            422,
            "VALIDATION_ERROR",
            f"question_count must be one of {', '.join(str(c) for c in ALLOWED_QUESTION_COUNTS)}.",
        )

    resolved_lang = resolve_request_language(language, accept_language)

    FileParser.validate_file(file)
    terms_definitions = FileParser.parse_file(file)

    if use_llm:
        raise api_error(
            501,
            "GENERATION_FAILED",
            "LLM-based generation is not yet implemented.",
        )

    filename = file.filename or "Untitled Quiz"
    quiz_title = (
        title.strip() if title and title.strip() else filename.rsplit(".", 1)[0]
    )
    quiz_category = category.strip() if category and category.strip() else None

    # Run duplicate detection before generation while honoring title, category, language, and question_count
    source_content = f"lang={resolved_lang}\n" + "\n".join(
        f"{t}:{d}" for t, d in terms_definitions
    )
    source_hash = hashlib.sha256(source_content.encode("utf-8")).hexdigest()

    existing_quizzes = (
        db.query(Quiz)
        .options(selectinload(Quiz.questions).selectinload(Question.choices))
        .filter(
            Quiz.owner_id == current_user.id,
            Quiz.source_hash == source_hash,
            Quiz.title == quiz_title,
            Quiz.category == quiz_category,
        )
        .all()
    )
    for existing_quiz in existing_quizzes:
        if question_count is None or len(existing_quiz.questions) == question_count:
            return format_quiz_response(existing_quiz, include_correct=False)

    questions_data = QuizGenerator.generate_from_structured(
        terms_definitions,
        question_count,
        language=resolved_lang,
    )
    QuizGenerator.validate_questions(questions_data)

    now = datetime.now(timezone.utc)
    db_quiz = Quiz(
        owner_id=current_user.id,
        title=quiz_title,
        category=quiz_category,
        source_type=_detect_source_type(filename),
        source_filename=filename,
        source_hash=source_hash,
        status="ready",
        updated_at=now,
    )
    db.add(db_quiz)
    db.flush()

    for q_idx, question_data in enumerate(questions_data):
        db_question = Question(
            quiz_id=db_quiz.id,
            prompt=question_data["prompt"],
            explanation=question_data.get("explanation"),
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
        quiz_id,
        "quiz",
        status_code=404,
        detail="Quiz not found.",
        code="QUIZ_NOT_FOUND",
    )

    db_quiz = (
        db.query(Quiz)
        .options(selectinload(Quiz.questions).selectinload(Question.choices))
        .filter(Quiz.id == numeric_id)
        .first()
    )
    if not db_quiz:
        raise api_error(404, "QUIZ_NOT_FOUND", "Quiz not found.")

    ensure_owner_or_admin(db_quiz.owner_id, current_user)
    return format_quiz_response(db_quiz, include_correct=False)


@router.get("/quizzes/{quiz_id}/preview", response_model=QuizPreviewResponse)
def get_quiz_preview(
    quiz_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get quiz preview with correct answers and explanations.

    For reviewing and editing a quiz.
    """
    numeric_id = parse_prefixed_id(
        quiz_id,
        "quiz",
        status_code=404,
        detail="Quiz not found.",
        code="QUIZ_NOT_FOUND",
    )

    db_quiz = (
        db.query(Quiz)
        .options(selectinload(Quiz.questions).selectinload(Question.choices))
        .filter(Quiz.id == numeric_id)
        .first()
    )
    if not db_quiz:
        raise api_error(404, "QUIZ_NOT_FOUND", "Quiz not found.")

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
    Update quiz metadata (title, category, source_type) and optionally replace
    questions and choices (each question must have 4 choices and 1 correct choice).
    """
    numeric_id = parse_prefixed_id(
        quiz_id,
        "quiz",
        status_code=404,
        detail="Quiz not found.",
        code="QUIZ_NOT_FOUND",
    )

    db_quiz = (
        db.query(Quiz)
        .options(selectinload(Quiz.questions).selectinload(Question.choices))
        .filter(Quiz.id == numeric_id)
        .first()
    )
    if not db_quiz:
        raise api_error(404, "QUIZ_NOT_FOUND", "Quiz not found.")

    ensure_owner_or_admin(db_quiz.owner_id, current_user)

    if quiz_data.title is not None:
        cleaned_title = quiz_data.title.strip()
        if not cleaned_title:
            raise api_error(422, "VALIDATION_ERROR", "Quiz title must not be empty.")
        db_quiz.title = cleaned_title

    if quiz_data.category is not None:
        db_quiz.category = quiz_data.category.strip() or None

    if quiz_data.source_type is not None:
        db_quiz.source_type = quiz_data.source_type

    if quiz_data.questions is not None:
        # Replace questions and choices atomically
        db_quiz.questions.clear()
        db.flush()

        for q_idx, q_in in enumerate(quiz_data.questions):
            db_question = Question(
                quiz_id=db_quiz.id,
                prompt=q_in.prompt,
                explanation=q_in.explanation,
                position=q_in.position if q_in.position is not None else q_idx,
            )
            db.add(db_question)
            db.flush()

            for c_idx, c_in in enumerate(q_in.choices):
                db_choice = Choice(
                    question_id=db_question.id,
                    text=c_in.text.strip(),
                    is_correct=c_in.is_correct,
                    position=c_in.position if c_in.position is not None else c_idx,
                )
                db.add(db_choice)

    db_quiz.status = "ready"
    db_quiz.updated_at = datetime.now(timezone.utc)

    db.commit()

    db_quiz = (
        db.query(Quiz)
        .options(selectinload(Quiz.questions).selectinload(Question.choices))
        .filter(Quiz.id == db_quiz.id)
        .first()
    )
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

        question_payload = {
            "id": f"q_{db_question.id}",
            "prompt": db_question.prompt,
            "position": db_question.position,
            "choices": formatted_choices,
        }
        if include_correct:
            question_payload["explanation"] = db_question.explanation

        formatted_questions.append(question_payload)

    return {
        "id": f"quiz_{db_quiz.id}",
        "title": db_quiz.title,
        "category": db_quiz.category,
        "source_type": db_quiz.source_type,
        "source_filename": db_quiz.source_filename,
        "status": db_quiz.status,
        "created_at": db_quiz.created_at,
        "updated_at": db_quiz.updated_at or db_quiz.created_at,
        "questions": formatted_questions,
    }
