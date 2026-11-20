"""
API routes for quiz exports (PDF & Word generation, EN / MM)
"""
import logging
import os
import re
import tempfile
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, selectinload
from starlette.background import BackgroundTask

from app.core.deps import ensure_owner_or_admin, get_current_user
from app.core.errors import api_error
from app.core.ids import parse_prefixed_id
from app.core.language import resolve_request_language
from app.db.models import Question, Quiz, User
from app.db.session import get_db
from app.services.docx_generator import DocxGenerator
from app.services.pdf_generator import PDFGenerator

logger = logging.getLogger(__name__)
router = APIRouter()

DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _sanitize_filename(title: str) -> str:
    """Sanitize a quiz title into a safe ASCII filename stem."""
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", title).strip("_")
    return cleaned[:100] if cleaned else "quiz"


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
    format: str = "pdf",  # "pdf" or "word"
    lang: Optional[str] = None,  # "en" or "mm" ("my" alias accepted)
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Export quiz as PDF or Word (.docx) in English or Myanmar.

    - **kind**: "questions" for blank study sheet, "answers" for answer key
    - **format**: "pdf" (default) or "word"
    - **lang**: "en" (default) or "mm" ("my" accepted as alias)
    """
    if kind not in ("questions", "answers"):
        raise api_error(
            400,
            "VALIDATION_ERROR",
            "Invalid kind parameter. Use 'questions' or 'answers'.",
        )

    export_format = format.strip().lower()
    if export_format not in ("pdf", "word"):
        raise api_error(
            400,
            "VALIDATION_ERROR",
            "Invalid format parameter. Use 'pdf' or 'word'.",
        )

    resolved_lang = resolve_request_language(lang, accept_language)

    quiz_numeric_id = parse_prefixed_id(
        quiz_id,
        "quiz",
        status_code=404,
        detail="Quiz not found.",
        code="QUIZ_NOT_FOUND",
    )

    db_quiz = db.query(Quiz).filter(Quiz.id == quiz_numeric_id).first()
    if not db_quiz:
        raise api_error(404, "QUIZ_NOT_FOUND", "Quiz not found.")

    ensure_owner_or_admin(db_quiz.owner_id, current_user)

    db_questions = (
        db.query(Question)
        .options(selectinload(Question.choices))
        .filter(Question.quiz_id == quiz_numeric_id)
        .order_by(Question.position)
        .all()
    )

    if not db_questions:
        raise api_error(400, "VALIDATION_ERROR", "Quiz has no questions.")

    questions_data = []

    for q_idx, db_question in enumerate(db_questions):
        sorted_choices = sorted(db_question.choices, key=lambda c: c.position)

        question_data = {
            "number": q_idx + 1,
            "prompt": db_question.prompt,
            "explanation": db_question.explanation,
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

    safe_title = _sanitize_filename(db_quiz.title)
    suffix = ".pdf" if export_format == "pdf" else ".docx"
    media_type = "application/pdf" if export_format == "pdf" else DOCX_MIME_TYPE
    filename = f"quiz_{kind}_{safe_title}{suffix}"

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
        out_path = tmp_file.name

    try:
        if export_format == "pdf":
            pdf_generator = PDFGenerator()
            if kind == "questions":
                pdf_generator.generate_questions_pdf(
                    quiz_title=db_quiz.title,
                    questions=questions_data,
                    output_path=out_path,
                    lang=resolved_lang,
                )
            else:
                pdf_generator.generate_answers_pdf(
                    quiz_title=db_quiz.title,
                    questions=questions_data,
                    output_path=out_path,
                    lang=resolved_lang,
                )
        else:
            docx_generator = DocxGenerator()
            if kind == "questions":
                docx_generator.generate_questions_docx(
                    quiz_title=db_quiz.title,
                    questions=questions_data,
                    output_path=out_path,
                    lang=resolved_lang,
                )
            else:
                docx_generator.generate_answers_docx(
                    quiz_title=db_quiz.title,
                    questions=questions_data,
                    output_path=out_path,
                    lang=resolved_lang,
                )
    except HTTPException:
        _cleanup_file(out_path)
        raise
    except Exception:
        _cleanup_file(out_path)
        logger.exception(
            "Failed to generate %s (%s) export for quiz %s", kind, export_format, quiz_id
        )
        raise api_error(500, "EXPORT_FAILED", "Failed to generate quiz export.")

    return FileResponse(
        path=out_path,
        filename=filename,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        background=BackgroundTask(_cleanup_file, out_path),
    )
