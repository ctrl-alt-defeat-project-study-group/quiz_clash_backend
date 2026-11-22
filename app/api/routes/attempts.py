"""
API routes for quiz attempts
"""
from typing import Dict, List, Tuple
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, selectinload

from app.core.deps import ensure_owner_or_admin, get_current_user
from app.core.errors import api_error
from app.core.ids import parse_prefixed_id
from app.db.models import Attempt, AttemptAnswer, Choice, Question, Quiz, User
from app.db.session import get_db
from app.schemas.attempt import (
    AttemptCreate,
    AttemptResponse,
    AttemptSummaryResponse,
)

router = APIRouter()


def get_choice_mapping(questions: List[Question]) -> Dict[str, Dict[str, Choice]]:
    """
    Create mapping from API choice IDs (a, b, c, d) to Choice ORM instances.

    Returns: {f"q_{question.id}": {choice_letter: Choice}}
    """
    choice_mapping: Dict[str, Dict[str, Choice]] = {}

    for question in questions:
        sorted_choices = sorted(question.choices, key=lambda c: c.position)
        question_mapping: Dict[str, Choice] = {}

        for idx, choice in enumerate(sorted_choices):
            choice_letter = chr(97 + idx)  # 'a', 'b', 'c', 'd'
            question_mapping[choice_letter] = choice

        choice_mapping[f"q_{question.id}"] = question_mapping

    return choice_mapping


@router.get("/attempts", response_model=List[AttemptSummaryResponse])
def list_attempts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List the authenticated user's quiz attempts ordered by most recent first."""
    attempts = (
        db.query(Attempt)
        .options(selectinload(Attempt.quiz))
        .filter(Attempt.user_id == current_user.id)
        .order_by(Attempt.completed_at.desc(), Attempt.id.desc())
        .all()
    )

    results = []
    for db_attempt in attempts:
        percentage = (
            (db_attempt.score / db_attempt.total_questions * 100)
            if db_attempt.total_questions > 0
            else 0.0
        )
        results.append(
            {
                "id": f"att_{db_attempt.id}",
                "quiz_id": f"quiz_{db_attempt.quiz_id}",
                "quiz_title": db_attempt.quiz.title if db_attempt.quiz else "Untitled Quiz",
                "score": db_attempt.score,
                "total_questions": db_attempt.total_questions,
                "percentage": round(percentage, 2),
                "duration_seconds": db_attempt.duration_seconds,
                "completed_at": db_attempt.completed_at,
            }
        )
    return results


@router.post("/quizzes/{quiz_id}/attempts", response_model=AttemptResponse, status_code=201)
def submit_attempt(
    quiz_id: str,
    attempt_data: AttemptCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Submit answers for a quiz and get graded results.

    - Validates all answers before writing to the database
    - Calculates score on server
    - Stores attempt in database
    - Returns detailed results
    """
    quiz_numeric_id = parse_prefixed_id(
        quiz_id,
        "quiz",
        status_code=404,
        detail="Quiz not found.",
        code="QUIZ_NOT_FOUND",
    )

    db_quiz = (
        db.query(Quiz)
        .options(selectinload(Quiz.questions).selectinload(Question.choices))
        .filter(Quiz.id == quiz_numeric_id)
        .first()
    )
    if not db_quiz:
        raise api_error(404, "QUIZ_NOT_FOUND", "Quiz not found.")

    ensure_owner_or_admin(db_quiz.owner_id, current_user)

    db_questions = sorted(db_quiz.questions, key=lambda q: q.position)
    if not db_questions:
        raise api_error(400, "VALIDATION_ERROR", "Quiz has no questions.")

    choice_mapping = get_choice_mapping(db_questions)
    question_map = {f"q_{q.id}": q for q in db_questions}

    # Validate every submitted answer before inserting anything
    validated_entries: List[Tuple[Question, Choice, Choice, str]] = []
    seen_question_ids = set()

    for answer in attempt_data.answers:
        q_numeric_id = parse_prefixed_id(
            answer.question_id,
            "q",
            status_code=400,
            detail=f"Invalid question ID format: {answer.question_id}",
            code="VALIDATION_ERROR",
        )
        normalized_qid = f"q_{q_numeric_id}"

        if normalized_qid in seen_question_ids:
            raise api_error(
                400,
                "VALIDATION_ERROR",
                f"Duplicate answer for question: {normalized_qid}",
            )
        seen_question_ids.add(normalized_qid)

        db_question = question_map.get(normalized_qid)
        if not db_question:
            raise api_error(
                400,
                "VALIDATION_ERROR",
                f"Unknown question ID for this quiz: {answer.question_id}",
            )

        correct_choice = next((c for c in db_question.choices if c.is_correct), None)
        if not correct_choice:
            raise api_error(
                500,
                "SERVER_ERROR",
                f"Question {normalized_qid} has no correct choice configured.",
            )

        selected_choice_letter = answer.choice_id.strip().lower()
        selected_choice = choice_mapping.get(normalized_qid, {}).get(
            selected_choice_letter
        )
        if not selected_choice:
            raise api_error(
                400,
                "VALIDATION_ERROR",
                f"Invalid choice ID '{answer.choice_id}' for question '{normalized_qid}'",
            )

        validated_entries.append(
            (db_question, selected_choice, correct_choice, selected_choice_letter)
        )

    # All answers validated; now persist Attempt and AttemptAnswer rows
    db_attempt = Attempt(
        quiz_id=quiz_numeric_id,
        user_id=current_user.id,
        score=0,
        total_questions=len(db_questions),
        duration_seconds=attempt_data.duration_seconds,
    )
    db.add(db_attempt)
    db.flush()

    correct_count = 0
    question_results = []

    for db_question, selected_choice, correct_choice, selected_letter in validated_entries:
        is_correct = selected_choice.id == correct_choice.id
        if is_correct:
            correct_count += 1

        db_attempt_answer = AttemptAnswer(
            attempt_id=db_attempt.id,
            question_id=db_question.id,
            choice_id=selected_choice.id,
            is_correct=is_correct,
        )
        db.add(db_attempt_answer)

        question_results.append(
            {
                "question_id": f"q_{db_question.id}",
                "question_prompt": db_question.prompt,
                "selected_choice_id": selected_letter,
                "selected_choice_text": selected_choice.text,
                "correct_choice_id": get_choice_letter(
                    db_question.choices, correct_choice.id
                ),
                "correct_choice_text": correct_choice.text,
                "explanation": db_question.explanation,
                "is_correct": is_correct,
            }
        )

    db_attempt.score = correct_count
    percentage = (correct_count / len(db_questions) * 100) if db_questions else 0.0

    db.commit()
    db.refresh(db_attempt)

    return {
        "id": f"att_{db_attempt.id}",
        "quiz_id": f"quiz_{quiz_numeric_id}",
        "quiz_title": db_quiz.title,
        "score": correct_count,
        "total_questions": len(db_questions),
        "percentage": round(percentage, 2),
        "duration_seconds": db_attempt.duration_seconds,
        "completed_at": db_attempt.completed_at,
        "questions": question_results,
    }


@router.get("/attempts/{attempt_id}", response_model=AttemptResponse)
def get_attempt(
    attempt_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get attempt results by ID. Accepts both 'att_N' and legacy 'attempt_N'.
    """
    attempt_numeric_id = parse_prefixed_id(
        attempt_id,
        ("att", "attempt"),
        status_code=404,
        detail="Attempt not found.",
        code="ATTEMPT_NOT_FOUND",
    )

    db_attempt = (
        db.query(Attempt)
        .options(selectinload(Attempt.answers).selectinload(AttemptAnswer.choice))
        .filter(Attempt.id == attempt_numeric_id)
        .first()
    )
    if not db_attempt:
        raise api_error(404, "ATTEMPT_NOT_FOUND", "Attempt not found.")

    ensure_owner_or_admin(db_attempt.user_id, current_user)

    db_quiz = db.query(Quiz).filter(Quiz.id == db_attempt.quiz_id).first()
    if not db_quiz:
        raise api_error(404, "QUIZ_NOT_FOUND", "Quiz not found.")

    # Eager-load all questions and their choices in one query (no N+1)
    question_ids = [ans.question_id for ans in db_attempt.answers]
    questions_by_id: Dict[int, Question] = {}
    if question_ids:
        db_questions = (
            db.query(Question)
            .options(selectinload(Question.choices))
            .filter(Question.id.in_(question_ids))
            .all()
        )
        questions_by_id = {q.id: q for q in db_questions}

    question_results = []
    for db_answer in db_attempt.answers:
        db_question = questions_by_id.get(db_answer.question_id)
        if not db_question:
            continue

        selected_choice = db_answer.choice
        if not selected_choice:
            continue

        correct_choice = next((c for c in db_question.choices if c.is_correct), None)
        if not correct_choice:
            continue

        question_results.append(
            {
                "question_id": f"q_{db_question.id}",
                "question_prompt": db_question.prompt,
                "selected_choice_id": get_choice_letter(
                    db_question.choices, selected_choice.id
                ),
                "selected_choice_text": selected_choice.text,
                "correct_choice_id": get_choice_letter(
                    db_question.choices, correct_choice.id
                ),
                "correct_choice_text": correct_choice.text,
                "explanation": db_question.explanation,
                "is_correct": db_answer.is_correct,
            }
        )

    percentage = (
        (db_attempt.score / db_attempt.total_questions * 100)
        if db_attempt.total_questions > 0
        else 0.0
    )

    return {
        "id": f"att_{db_attempt.id}",
        "quiz_id": f"quiz_{db_attempt.quiz_id}",
        "quiz_title": db_quiz.title,
        "score": db_attempt.score,
        "total_questions": db_attempt.total_questions,
        "percentage": round(percentage, 2),
        "duration_seconds": db_attempt.duration_seconds,
        "completed_at": db_attempt.completed_at,
        "questions": question_results,
    }


@router.delete("/attempts/{attempt_id}")
def delete_attempt(
    attempt_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a single quiz attempt owned by the authenticated user (or admin)."""
    attempt_numeric_id = parse_prefixed_id(
        attempt_id,
        ("att", "attempt"),
        status_code=404,
        detail="Attempt not found.",
        code="ATTEMPT_NOT_FOUND",
    )

    db_attempt = db.query(Attempt).filter(Attempt.id == attempt_numeric_id).first()
    if not db_attempt:
        raise api_error(404, "ATTEMPT_NOT_FOUND", "Attempt not found.")

    ensure_owner_or_admin(db_attempt.user_id, current_user)
    db.delete(db_attempt)
    db.commit()
    return {"message": "Attempt deleted."}


@router.delete("/attempts")
def clear_attempts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete all quiz attempts belonging to the authenticated user."""
    attempts = db.query(Attempt).filter(Attempt.user_id == current_user.id).all()
    for att in attempts:
        db.delete(att)
    db.commit()
    return {"message": "Attempt history cleared."}


def get_choice_letter(choices: List[Choice], target_choice_id: int) -> str:
    """Get choice letter (a, b, c, d) from database choice ID"""
    sorted_choices = sorted(choices, key=lambda c: c.position)

    for idx, choice in enumerate(sorted_choices):
        if choice.id == target_choice_id:
            return chr(97 + idx)  # 'a', 'b', 'c', 'd'

    return "?"
