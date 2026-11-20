"""
API routes for quiz exports (PDF generation)
"""
import os
import re
import tempfile
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, selectinload
from starlette.background import BackgroundTask

from app.core.deps import ensure_owner_or_admin, get_current_user
from app.core.ids import parse_prefixed_id
from app.db.session import get_db
from app.db.models import Quiz, Question, User
from app.services.pdf_generator import PDFGenerator

router = APIRouter()


def _sanitize_filename(title: str) -> str:
    """Sanitize a quiz title into a safe ASCII filename stem."""
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", title).strip("_")
    return (cleaned[:100] if cleaned else "quiz")


def _cleanup_file(path: str) -> None:
    """Remove a temporary file after the response finishes streaming."""
    try:
        os.unlink(path)
    except OSError:
        pass


@router.get("/quizzes/{quiz_id}/exports")
def export_quiz_pdf(
    quiz_id: str,
    kind: str = "questions",  # "questions" or "answers"
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Export quiz as PDF.

    - **kind**: "questions" for questions-only PDF, "answers" for answer key PDF
    """
    if kind not in ("questions", "answers"):
        raise HTTPException(
            status_code=400,
            detail="Invalid kind parameter. Use 'questions' or 'answers'",
        )

    quiz_numeric_id = parse_prefixed_id(
        quiz_id, "quiz", status_code=400, detail="Invalid quiz ID format"
    )

    db_quiz = db.query(Quiz).filter(Quiz.id == quiz_numeric_id).first()
    if not db_quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    ensure_owner_or_admin(db_quiz.owner_id, current_user)

    db_questions = (
        db.query(Question)
        .options(selectinload(Question.choices))
        .filter(Question.quiz_id == quiz_numeric_id)
        .order_by(Question.position)
        .all()
    )

    if not db_questions:
        raise HTTPException(status_code=400, detail="Quiz has no questions")

    questions_data = []

    for q_idx, db_question in enumerate(db_questions):
        sorted_choices = sorted(db_question.choices, key=lambda c: c.position)

        question_data = {
            "number": q_idx + 1,
            "prompt": db_question.prompt,
            "choices": [],
        }

        correct_choice_letter = None
        for c_idx, db_choice in enumerate(sorted_choices):
            choice_letter = chr(97 + c_idx)  # 'a', 'b', 'c', 'd'
            question_data["choices"].append(
                {
                    "letter": choice_letter,
                    "text": db_choice.text,
                }
            )
            if db_choice.is_correct:
                correct_choice_letter = choice_letter

        if kind == "answers":
            question_data["correct_answer"] = correct_choice_letter

        questions_data.append(question_data)

    pdf_generator = PDFGenerator()
    safe_title = _sanitize_filename(db_quiz.title)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
        pdf_path = tmp_file.name

    try:
        if kind == "questions":
            pdf_generator.generate_questions_pdf(
                quiz_title=db_quiz.title,
                questions=questions_data,
                output_path=pdf_path,
            )
            filename = f"quiz_questions_{safe_title}.pdf"
        else:
            pdf_generator.generate_answers_pdf(
                quiz_title=db_quiz.title,
                questions=questions_data,
                output_path=pdf_path,
            )
            filename = f"quiz_answers_{safe_title}.pdf"
    except Exception:
        _cleanup_file(pdf_path)
        raise

    return FileResponse(
        path=pdf_path,
        filename=filename,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        background=BackgroundTask(_cleanup_file, pdf_path),
    )
