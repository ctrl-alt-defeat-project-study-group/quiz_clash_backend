"""
Tests verifying Phase 8: User settings, account export, and workspace reset.
"""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.core.security import create_access_token, hash_password
from app.db.models import Base, User
from app.db.session import SessionLocal, engine
from app.main import app


@pytest.fixture(autouse=True)
def reset_db():
    rate_limiter.reset()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    db = SessionLocal()
    try:
        user = User(
            email="alex.m@example.com",
            password_hash=hash_password("Password123"),
            display_name="Alex M.",
            role="user",
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_access_token(user.id, user.role)
    finally:
        db.close()

    with TestClient(app) as c:
        c.cookies.set(settings.ACCESS_COOKIE_NAME, token)
        yield c


def _sample_csv() -> bytes:
    return "\n".join(f'"Term{i}","Definition {i}"' for i in range(1, 11)).encode("utf-8")


def test_settings_get_patch_and_validation(client):
    # GET /api/v1/settings returns defaults matching contract
    r = client.get("/api/v1/settings")
    assert r.status_code == 200
    data = r.json()
    assert data == {
        "display_name": "Alex M.",
        "email": "alex.m@example.com",
        "theme": "system",
        "ui_language": "en",
        "default_questions": 10,
        "difficulty": "Mixed",
        "quiz_language": "English",
        "shuffle_questions": True,
        "show_explanations": True,
        "study_reminders": False,
        "weekly_summary": True,
    }

    # PATCH /api/v1/settings updates fields and normalizes 'my' -> 'mm'
    p = client.patch(
        "/api/v1/settings",
        json={
            "display_name": "Alex Myanmar",
            "theme": "dark",
            "ui_language": "my",
            "default_questions": 15,
            "difficulty": "Advanced",
            "quiz_language": "Myanmar",
            "shuffle_questions": False,
            "study_reminders": True,
        },
    )
    assert p.status_code == 200
    updated = p.json()
    assert updated["display_name"] == "Alex Myanmar"
    assert updated["theme"] == "dark"
    assert updated["ui_language"] == "mm"
    assert updated["default_questions"] == 15
    assert updated["difficulty"] == "Advanced"
    assert updated["quiz_language"] == "Myanmar"
    assert updated["shuffle_questions"] is False
    assert updated["study_reminders"] is True

    # Invalid theme / default_questions rejected with 422 VALIDATION_ERROR
    bad_theme = client.patch("/api/v1/settings", json={"theme": "neon"})
    assert bad_theme.status_code == 422
    assert bad_theme.json()["detail"]["code"] == "VALIDATION_ERROR"

    bad_q = client.patch("/api/v1/settings", json={"default_questions": 12})
    assert bad_q.status_code == 422
    assert bad_q.json()["detail"]["code"] == "VALIDATION_ERROR"


def test_account_export_and_delete_workspace(client):
    # Create a quiz and submit an attempt
    q_resp = client.post(
        "/api/v1/quizzes",
        files={"file": ("bio.csv", _sample_csv(), "text/csv")},
        data={"title": "Cell Structure", "category": "Biology", "question_count": "5"},
    )
    assert q_resp.status_code == 201
    quiz = q_resp.json()

    att_resp = client.post(
        f"/api/v1/quizzes/{quiz['id']}/attempts",
        json={
            "duration_seconds": 90,
            "answers": [{"question_id": quiz["questions"][0]["id"], "choice_id": "a"}],
        },
    )
    assert att_resp.status_code == 201

    client.patch("/api/v1/settings", json={"theme": "dark", "ui_language": "mm"})

    # GET /api/v1/account/export returns full JSON dump
    exp = client.get("/api/v1/account/export")
    assert exp.status_code == 200
    dump = exp.json()
    assert dump["account"]["email"] == "alex.m@example.com"
    assert dump["settings"]["theme"] == "dark"
    assert dump["settings"]["ui_language"] == "mm"
    assert len(dump["quizzes"]) == 1
    assert dump["quizzes"][0]["title"] == "Cell Structure"
    assert len(dump["attempts"]) == 1
    assert dump["attempts"][0]["duration_seconds"] == 90

    # DELETE /api/v1/account deletes workspace data and resets settings
    del_resp = client.delete("/api/v1/account")
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted_quizzes"] == 1
    assert del_resp.json()["deleted_attempts"] == 1

    # Verify quizzes/attempts are empty and settings are reset to defaults
    assert client.get("/api/v1/quizzes").json() == []
    assert client.get("/api/v1/attempts").json() == []
    reset_settings = client.get("/api/v1/settings").json()
    assert reset_settings["theme"] == "system"
    assert reset_settings["ui_language"] == "en"
