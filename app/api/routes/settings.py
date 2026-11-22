"""
API routes for user settings and account data export / reset (Phase 8).
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, selectinload

from app.core.deps import get_current_user
from app.db.models import Attempt, AttemptAnswer, LiveRoom, Question, Quiz, User, UserSettings
from app.db.session import get_db
from app.schemas.settings import (
    AccountExportResponse,
    AccountResetResponse,
    UserSettingsResponse,
    UserSettingsUpdate,
)
from app.services.live_manager import live_room_manager

router = APIRouter()


def _get_or_create_settings(user: User, db: Session) -> UserSettings:
    user_settings = (
        db.query(UserSettings)
        .filter(UserSettings.user_id == user.id)
        .first()
    )
    if user_settings is None:
        user_settings = UserSettings(user_id=user.id)
        db.add(user_settings)
        db.commit()
        db.refresh(user_settings)
    return user_settings


def _format_settings(user: User, s: UserSettings) -> dict:
    return {
        "display_name": user.display_name,
        "email": user.email,
        "avatar_url": user.avatar_url,
        "theme": s.theme,
        "ui_language": s.ui_language,
        "default_questions": s.default_questions,
        "difficulty": s.difficulty,
        "quiz_language": s.quiz_language,
        "shuffle_questions": s.shuffle_questions,
        "show_explanations": s.show_explanations,
        "study_reminders": s.study_reminders,
        "weekly_summary": s.weekly_summary,
    }


@router.get("/settings", response_model=UserSettingsResponse)
def get_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the authenticated user's profile & workspace settings."""
    user_settings = _get_or_create_settings(current_user, db)
    return _format_settings(current_user, user_settings)


@router.patch("/settings", response_model=UserSettingsResponse)
def update_settings(
    payload: UserSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update the authenticated user's settings and/or display name."""
    user_settings = _get_or_create_settings(current_user, db)

    if payload.display_name is not None:
        cleaned = payload.display_name.strip()
        if cleaned:
            current_user.display_name = cleaned

    if "avatar_url" in payload.model_fields_set:
        current_user.avatar_url = payload.avatar_url

    for field_name in (
        "theme",
        "ui_language",
        "default_questions",
        "difficulty",
        "quiz_language",
        "shuffle_questions",
        "show_explanations",
        "study_reminders",
        "weekly_summary",
    ):
        value = getattr(payload, field_name)
        if value is not None:
            setattr(user_settings, field_name, value)

    user_settings.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(current_user)
    db.refresh(user_settings)
    return _format_settings(current_user, user_settings)


@router.get("/account/export", response_model=AccountExportResponse)
def export_account_data(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export a complete JSON dump of the user's quizzes, attempts, and settings."""
    user_settings = _get_or_create_settings(current_user, db)

    quizzes = (
        db.query(Quiz)
        .options(selectinload(Quiz.questions).selectinload(Question.choices))
        .filter(Quiz.owner_id == current_user.id)
        .order_by(Quiz.id.asc())
        .all()
    )
    attempts = (
        db.query(Attempt)
        .options(
            selectinload(Attempt.quiz),
            selectinload(Attempt.answers).selectinload(AttemptAnswer.choice),
        )
        .filter(Attempt.user_id == current_user.id)
        .order_by(Attempt.id.asc())
        .all()
    )

    exported_quizzes = []
    for q in quizzes:
        sorted_questions = sorted(q.questions, key=lambda item: item.position)
        exported_quizzes.append(
            {
                "id": f"quiz_{q.id}",
                "title": q.title,
                "category": q.category,
                "source_type": q.source_type,
                "source_filename": q.source_filename,
                "status": q.status,
                "created_at": q.created_at.isoformat() if q.created_at else None,
                "updated_at": (q.updated_at or q.created_at).isoformat()
                if (q.updated_at or q.created_at)
                else None,
                "questions": [
                    {
                        "id": f"q_{question.id}",
                        "prompt": question.prompt,
                        "position": question.position,
                        "explanation": question.explanation,
                        "choices": [
                            {
                                "id": chr(97 + idx),
                                "text": choice.text,
                                "position": idx,
                                "is_correct": choice.is_correct,
                            }
                            for idx, choice in enumerate(
                                sorted(question.choices, key=lambda c: c.position)
                            )
                        ],
                    }
                    for question in sorted_questions
                ],
            }
        )

    exported_attempts = []
    for att in attempts:
        pct = (
            round((att.score / att.total_questions) * 100, 2)
            if att.total_questions > 0
            else 0.0
        )
        exported_attempts.append(
            {
                "id": f"att_{att.id}",
                "quiz_id": f"quiz_{att.quiz_id}",
                "quiz_title": att.quiz.title if att.quiz else None,
                "score": att.score,
                "total_questions": att.total_questions,
                "percentage": pct,
                "duration_seconds": att.duration_seconds,
                "completed_at": att.completed_at.isoformat() if att.completed_at else None,
                "answers": [
                    {
                        "question_id": f"q_{ans.question_id}",
                        "choice_text": ans.choice.text if ans.choice else None,
                        "is_correct": ans.is_correct,
                    }
                    for ans in att.answers
                ],
            }
        )

    return {
        "exported_at": datetime.now(timezone.utc),
        "account": {
            "id": current_user.id,
            "email": current_user.email,
            "display_name": current_user.display_name,
            "role": current_user.role,
            "created_at": current_user.created_at.isoformat()
            if current_user.created_at
            else None,
        },
        "settings": _format_settings(current_user, user_settings),
        "quizzes": exported_quizzes,
        "attempts": exported_attempts,
    }


@router.delete("/account", response_model=AccountResetResponse)
def delete_account_workspace(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Delete/reset the authenticated user's workspace data:
    removes all quizzes, attempts, and hosted live rooms, and resets settings to defaults.
    """
    deleted_rooms = (
        db.query(LiveRoom)
        .filter(LiveRoom.host_id == current_user.id)
        .delete(synchronize_session=False)
    )
    deleted_attempts = (
        db.query(Attempt)
        .filter(Attempt.user_id == current_user.id)
        .delete(synchronize_session=False)
    )

    user_quizzes = db.query(Quiz).filter(Quiz.owner_id == current_user.id).all()
    deleted_quizzes = len(user_quizzes)
    for quiz in user_quizzes:
        db.delete(quiz)

    # Reset settings to defaults
    existing_settings = (
        db.query(UserSettings)
        .filter(UserSettings.user_id == current_user.id)
        .first()
    )
    if existing_settings is not None:
        db.delete(existing_settings)
        db.flush()

    db.add(UserSettings(user_id=current_user.id))
    db.commit()

    live_room_manager.remove_rooms_for_host(current_user.id)

    return {
        "message": "Workspace data has been deleted and settings reset.",
        "deleted_quizzes": deleted_quizzes,
        "deleted_attempts": deleted_attempts,
        "deleted_rooms": deleted_rooms,
    }
