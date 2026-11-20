"""
Admin management API routes (requires role == 'admin').
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.core.deps import require_admin
from app.core.ids import parse_prefixed_id
from app.core.security import api_error
from app.db.models import Attempt, Quiz, User
from app.db.session import get_db
from app.schemas.admin import AdminQuizSummary, AdminStatsResponse, AdminUserUpdate
from app.schemas.auth import MessageResponse, UserProfileResponse

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


def _count_other_active_admins(db: Session, exclude_user_id: int) -> int:
    return (
        db.query(User)
        .filter(
            User.role == "admin",
            User.is_active.is_(True),
            User.id != exclude_user_id,
        )
        .count()
    )


@router.get("/users", response_model=List[UserProfileResponse])
def list_users(
    q: Optional[str] = Query(default=None, description="Search by email or display name"),
    db: Session = Depends(get_db),
):
    """List all users, optionally filtered by search query."""
    query = db.query(User)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        query = query.filter(
            or_(
                User.email.ilike(pattern),
                User.display_name.ilike(pattern),
            )
        )
    return query.order_by(User.id.asc()).all()


@router.patch("/users/{user_id}", response_model=UserProfileResponse)
def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    db: Session = Depends(get_db),
):
    """Update a user's role and/or active status. Cannot demote/disable the last active admin."""
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise api_error(404, "NOT_FOUND", "User not found.")

    new_role = payload.role if payload.role is not None else target.role
    new_active = payload.is_active if payload.is_active is not None else target.is_active

    was_active_admin = target.role == "admin" and target.is_active
    will_be_active_admin = new_role == "admin" and new_active

    if was_active_admin and not will_be_active_admin:
        if _count_other_active_admins(db, exclude_user_id=target.id) == 0:
            raise api_error(
                400,
                "FORBIDDEN",
                "Cannot demote or deactivate the last active admin.",
            )

    target.role = new_role
    target.is_active = new_active
    db.commit()
    db.refresh(target)
    return target


@router.delete("/users/{user_id}", response_model=MessageResponse)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
):
    """Delete a user. Cannot delete the last active admin."""
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise api_error(404, "NOT_FOUND", "User not found.")

    if target.role == "admin" and target.is_active:
        if _count_other_active_admins(db, exclude_user_id=target.id) == 0:
            raise api_error(
                400,
                "FORBIDDEN",
                "Cannot delete the last active admin.",
            )

    db.delete(target)
    db.commit()
    return {"message": "User deleted."}


@router.get("/quizzes", response_model=List[AdminQuizSummary])
def list_all_quizzes(db: Session = Depends(get_db)):
    """List all quizzes across all users."""
    quizzes = (
        db.query(Quiz)
        .options(selectinload(Quiz.owner), selectinload(Quiz.questions))
        .order_by(Quiz.id.desc())
        .all()
    )
    return [
        AdminQuizSummary(
            id=f"quiz_{q.id}",
            title=q.title,
            owner_id=q.owner_id,
            owner_email=q.owner.email if q.owner else None,
            source_type=q.source_type,
            status=q.status,
            question_count=len(q.questions),
            created_at=q.created_at,
        )
        for q in quizzes
    ]


@router.delete("/quizzes/{quiz_id}", response_model=MessageResponse)
def delete_any_quiz(quiz_id: str, db: Session = Depends(get_db)):
    """Delete any quiz by ID."""
    numeric_id = parse_prefixed_id(
        quiz_id, "quiz", status_code=404, detail="Quiz not found"
    )
    db_quiz = db.query(Quiz).filter(Quiz.id == numeric_id).first()
    if not db_quiz:
        raise api_error(404, "QUIZ_NOT_FOUND", "Quiz not found.")

    db.delete(db_quiz)
    db.commit()
    return {"message": "Quiz deleted."}


@router.get("/stats", response_model=AdminStatsResponse)
def get_admin_stats(db: Session = Depends(get_db)):
    """Return site-wide summary counts."""
    return AdminStatsResponse(
        total_users=db.query(User).count(),
        active_users=db.query(User).filter(User.is_active.is_(True)).count(),
        verified_users=db.query(User).filter(User.email_verified_at.isnot(None)).count(),
        admin_users=db.query(User).filter(User.role == "admin", User.is_active.is_(True)).count(),
        total_quizzes=db.query(Quiz).count(),
        total_attempts=db.query(Attempt).count(),
    )
