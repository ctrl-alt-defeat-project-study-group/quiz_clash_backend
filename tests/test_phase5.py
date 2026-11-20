"""
Tests verifying Phase 5 API contract core.
"""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.core.security import create_access_token, hash_password
from app.db.models import Base, User
from app.db.session import SessionLocal, engine
from app.main import app
from app.services.pdf_generator import PDFGenerator


@pytest.fixture(autouse=True)
def reset_db():
    rate_limiter.reset()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def _create_user(email: str, role: str = "user") -> User:
    db = SessionLocal()
    try:
        user = User(
            email=email,
            password_hash=hash_password("Password123"),
            display_name=email.split("@")[0],
            role=role,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _client_for(user: User) -> TestClient:
    c = TestClient(app, raise_server_exceptions=False)
    c.cookies.set(settings.ACCESS_COOKIE_NAME, create_access_token(user.id, user.role))
    return c


def _sample_csv(prefix: str = "Bio", count: int = 10) -> bytes:
    return "\n".join(f'"{prefix}Term{i}","{prefix}Definition {i}"' for i in range(1, count + 1)).encode("utf-8")


def test_health_and_contract_error_codes():
    user = _create_user("err@example.com")
    with _client_for(user) as c:
        # Health contract
        h = c.get("/api/v1/health")
        assert h.status_code == 200
        assert h.json() == {"status": "ok", "service": "quiz-clash-api"}

        # QUIZ_NOT_FOUND (404)
        r_nf = c.get("/api/v1/quizzes/quiz_99999")
        assert r_nf.status_code == 404
        assert r_nf.json()["detail"]["code"] == "QUIZ_NOT_FOUND"

        # ATTEMPT_NOT_FOUND (404)
        r_att_nf = c.get("/api/v1/attempts/att_99999")
        assert r_att_nf.status_code == 404
        assert r_att_nf.json()["detail"]["code"] == "ATTEMPT_NOT_FOUND"

        # UNSUPPORTED_FILE_TYPE (400)
        r_type = c.post(
            "/api/v1/quizzes",
            files={"file": ("notes.exe", b"hello", "application/octet-stream")},
            data={"question_count": "5"},
        )
        assert r_type.status_code == 400
        assert r_type.json()["detail"]["code"] == "UNSUPPORTED_FILE_TYPE"

        # EMPTY_FILE (400)
        r_empty = c.post(
            "/api/v1/quizzes",
            files={"file": ("empty.csv", b"", "text/csv")},
            data={"question_count": "5"},
        )
        assert r_empty.status_code == 400
        assert r_empty.json()["detail"]["code"] == "EMPTY_FILE"

        # FILE_TOO_LARGE (413)
        with patch.object(settings, "MAX_UPLOAD_SIZE_MB", 1):
            r_big = c.post(
                "/api/v1/quizzes",
                files={"file": ("big.csv", b"a" * (2 * 1024 * 1024), "text/csv")},
                data={"question_count": "5"},
            )
            assert r_big.status_code == 413
            assert r_big.json()["detail"]["code"] == "FILE_TOO_LARGE"

        # Invalid question_count -> VALIDATION_ERROR (422)
        r_bad_count = c.post(
            "/api/v1/quizzes",
            files={"file": ("bio.csv", _sample_csv(), "text/csv")},
            data={"question_count": "7"},
        )
        assert r_bad_count.status_code == 422
        assert r_bad_count.json()["detail"]["code"] == "VALIDATION_ERROR"

        # Pydantic request validation error -> VALIDATION_ERROR (422)
        r_pydantic = c.post(
            "/api/v1/quizzes/quiz_1/attempts",
            json={"duration_seconds": -5, "answers": []},
        )
        assert r_pydantic.status_code == 422
        assert r_pydantic.json()["detail"]["code"] == "VALIDATION_ERROR"

        # use_llm=true -> GENERATION_FAILED (501)
        r_llm = c.post(
            "/api/v1/quizzes",
            files={"file": ("bio.csv", _sample_csv(), "text/csv")},
            data={"use_llm": "true", "question_count": "5"},
        )
        assert r_llm.status_code == 501
        assert r_llm.json()["detail"]["code"] == "GENERATION_FAILED"


def test_quiz_create_list_preview_and_full_patch():
    user_a = _create_user("owner@example.com")
    user_b = _create_user("other@example.com")

    with _client_for(user_a) as ca:
        # POST /api/v1/quizzes returns 201 with contract fields
        r = ca.post(
            "/api/v1/quizzes",
            files={"file": ("Cell_Biology_Notes.csv", _sample_csv("Cell", 10), "text/csv")},
            data={"title": "Cell structure", "category": "Biology", "question_count": "5"},
        )
        assert r.status_code == 201
        quiz = r.json()
        assert quiz["id"].startswith("quiz_")
        assert quiz["title"] == "Cell structure"
        assert quiz["category"] == "Biology"
        assert quiz["source_type"] == "csv"
        assert quiz["source_filename"] == "Cell_Biology_Notes.csv"
        assert quiz["status"] == "ready"
        assert quiz["created_at"]
        assert quiz["updated_at"]
        assert len(quiz["questions"]) == 5

        # Playable endpoint hides is_correct & explanation
        play = ca.get(f"/api/v1/quizzes/{quiz['id']}").json()
        assert "is_correct" not in play["questions"][0]["choices"][0]
        assert "explanation" not in play["questions"][0]

        # Preview endpoint includes is_correct and explanation ("{term}: {definition}")
        prev = ca.get(f"/api/v1/quizzes/{quiz['id']}/preview").json()
        assert "is_correct" in prev["questions"][0]["choices"][0]
        assert ": " in prev["questions"][0]["explanation"]

        # GET /api/v1/quizzes lists user's quizzes with summary fields
        lst = ca.get("/api/v1/quizzes")
        assert lst.status_code == 200
        items = lst.json()
        assert len(items) == 1
        assert items[0]["id"] == quiz["id"]
        assert items[0]["title"] == "Cell structure"
        assert items[0]["category"] == "Biology"
        assert items[0]["source_filename"] == "Cell_Biology_Notes.csv"
        assert items[0]["question_count"] == 5
        assert items[0]["last_score"] is None
        assert items[0]["updated_at"]

        # PATCH /api/v1/quizzes/{id} rejects invalid questions (e.g., 0 correct choices)
        bad_patch = ca.patch(
            f"/api/v1/quizzes/{quiz['id']}",
            json={
                "questions": [
                    {
                        "prompt": "Broken Q",
                        "position": 0,
                        "choices": [
                            {"text": "A", "position": 0, "is_correct": False},
                            {"text": "B", "position": 1, "is_correct": False},
                            {"text": "C", "position": 2, "is_correct": False},
                            {"text": "D", "position": 3, "is_correct": False},
                        ],
                    }
                ]
            },
        )
        assert bad_patch.status_code == 422
        assert bad_patch.json()["detail"]["code"] == "VALIDATION_ERROR"

        # Full PATCH edit of title, category, questions, and choices
        patched = ca.patch(
            f"/api/v1/quizzes/{quiz['id']}",
            json={
                "title": "Cell Structure Updated",
                "category": "AP Biology",
                "questions": [
                    {
                        "prompt": "What is the primary function of the cell membrane?",
                        "position": 0,
                        "explanation": "Regulates movement of substances in and out of the cell.",
                        "choices": [
                            {"text": "Produce energy", "position": 0, "is_correct": False},
                            {"text": "Regulate movement", "position": 1, "is_correct": True},
                            {"text": "Synthesize proteins", "position": 2, "is_correct": False},
                            {"text": "Store DNA", "position": 3, "is_correct": False},
                        ],
                    }
                ],
            },
        )
        assert patched.status_code == 200
        p_data = patched.json()
        assert p_data["title"] == "Cell Structure Updated"
        assert p_data["category"] == "AP Biology"
        assert p_data["status"] == "ready"
        assert len(p_data["questions"]) == 1
        assert p_data["questions"][0]["explanation"] == "Regulates movement of substances in and out of the cell."
        assert [c["id"] for c in p_data["questions"][0]["choices"]] == ["a", "b", "c", "d"]

    # Another user does not see user_a's quizzes in GET /api/v1/quizzes
    with _client_for(user_b) as cb:
        assert cb.get("/api/v1/quizzes").json() == []


def test_attempts_list_detail_duration_and_export_failed():
    user = _create_user("player@example.com")
    with _client_for(user) as c:
        r = c.post(
            "/api/v1/quizzes",
            files={"file": ("hist.csv", _sample_csv("Hist", 10), "text/csv")},
            data={"title": "World History", "category": "History", "question_count": "5"},
        )
        assert r.status_code == 201
        quiz_id = r.json()["id"]

        preview = c.get(f"/api/v1/quizzes/{quiz_id}/preview").json()
        answers = []
        for idx, q in enumerate(preview["questions"]):
            # Answer first 4 correctly, last one incorrectly (80%)
            if idx < 4:
                choice = next(ch for ch in q["choices"] if ch["is_correct"])
            else:
                choice = next(ch for ch in q["choices"] if not ch["is_correct"])
            answers.append({"question_id": q["id"], "choice_id": choice["id"]})

        att_resp = c.post(
            f"/api/v1/quizzes/{quiz_id}/attempts",
            json={"duration_seconds": 185, "answers": answers},
        )
        assert att_resp.status_code == 201
        att = att_resp.json()
        assert att["id"].startswith("att_")
        assert att["quiz_id"] == quiz_id
        assert att["quiz_title"] == "World History"
        assert att["score"] == 4
        assert att["total_questions"] == 5
        assert att["percentage"] == 80.0
        assert att["duration_seconds"] == 185
        assert len(att["questions"]) == 5
        assert ": " in att["questions"][0]["explanation"]

        # GET /api/v1/attempts lists attempts
        list_resp = c.get("/api/v1/attempts")
        assert list_resp.status_code == 200
        attempts_list = list_resp.json()
        assert len(attempts_list) == 1
        assert attempts_list[0]["id"] == att["id"]
        assert attempts_list[0]["quiz_title"] == "World History"
        assert attempts_list[0]["duration_seconds"] == 185
        assert attempts_list[0]["percentage"] == 80.0

        # GET /api/v1/quizzes now reports last_score == 80.0
        q_list = c.get("/api/v1/quizzes").json()
        assert q_list[0]["last_score"] == 80.0

        # GET /api/v1/attempts/{id} works with att_N and legacy attempt_N
        detail = c.get(f"/api/v1/attempts/{att['id']}").json()
        assert detail["quiz_title"] == "World History"
        assert detail["duration_seconds"] == 185
        assert ": " in detail["questions"][0]["explanation"]

        legacy = c.get(f"/api/v1/attempts/{att['id'].replace('att_', 'attempt_')}")
        assert legacy.status_code == 200
        assert legacy.json()["id"] == att["id"]

        # EXPORT_FAILED (500) when PDF generation raises
        with patch.object(PDFGenerator, "generate_questions_pdf", side_effect=RuntimeError("boom")):
            exp_err = c.get(f"/api/v1/quizzes/{quiz_id}/exports", params={"kind": "questions"})
            assert exp_err.status_code == 500
            assert exp_err.json()["detail"]["code"] == "EXPORT_FAILED"
