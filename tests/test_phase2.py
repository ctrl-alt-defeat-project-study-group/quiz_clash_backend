"""
Tests verifying Phase 2 correctness fixes.
"""
from datetime import datetime, timezone
import inspect
import io
import os
import tempfile
from unittest.mock import patch

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient

from app.api.routes import attempts as attempts_route
from app.api.routes import exports as exports_route
from app.api.routes import quizzes as quizzes_route
from app.core.config import settings
from app.core.ids import parse_prefixed_id
from app.core.rate_limit import rate_limiter
from app.core.security import create_access_token, hash_password
from app.db.models import Attempt, Base, User
from app.db.session import SessionLocal, engine
from app.main import app
from app.services.parser import FileParser
from app.services.pdf_generator import PDFGenerator
from app.services.quiz_generator import QuizGenerator


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
            email="tester@example.com",
            password_hash=hash_password("Password123"),
            display_name="Tester",
            role="user",
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        access_token = create_access_token(user_id=user.id, role=user.role)
    finally:
        db.close()

    with TestClient(app) as c:
        c.cookies.set(settings.ACCESS_COOKIE_NAME, access_token)
        yield c


def _make_csv_bytes(rows):
    lines = [f'"{t}","{d}"' for t, d in rows]
    return "\n".join(lines).encode("utf-8")


SAMPLE_PAIRS_1 = [
    (f"TermA{i}", f"Definition A{i}") for i in range(1, 11)
]
SAMPLE_PAIRS_2 = [
    (f"TermB{i} <x&y>", f"Definition B{i} <a&b>") for i in range(1, 11)
]


def test_parse_prefixed_id():
    assert parse_prefixed_id("quiz_12", "quiz") == 12
    assert parse_prefixed_id("12", "quiz") == 12
    assert parse_prefixed_id("att_7", ("attempt", "att")) == 7
    assert parse_prefixed_id("attempt_7", ("attempt", "att")) == 7

    for bad in ("", "quiz_", "quiz_0", "quiz_-1", "quiz_abc", "other_5", "quiz_1_2"):
        with pytest.raises(HTTPException) as exc:
            parse_prefixed_id(bad, "quiz", status_code=404, detail="Not found")
        assert exc.value.status_code == 404


def test_sync_handlers():
    for fn in (
        quizzes_route.create_quiz_from_file,
        quizzes_route.get_quiz,
        quizzes_route.get_quiz_preview,
        quizzes_route.update_quiz,
        attempts_route.submit_attempt,
        attempts_route.get_attempt,
        exports_route.export_quiz_pdf,
    ):
        assert not inspect.iscoroutinefunction(fn), f"{fn.__name__} should be sync def"


def test_grading_ids_second_quiz_and_preview_patch(client):
    # Create quiz 1 (questions DB IDs 1..5)
    r1 = client.post(
        "/api/v1/quizzes",
        files={"file": ("set1.csv", _make_csv_bytes(SAMPLE_PAIRS_1), "text/csv")},
        data={"title": "First Quiz", "question_count": "5"},
    )
    assert r1.status_code == 201
    q1 = r1.json()
    assert len(q1["questions"]) == 5

    # Create quiz 2 (questions DB IDs 6..10, NOT 1..5)
    r2 = client.post(
        "/api/v1/quizzes",
        files={"file": ("set2.csv", _make_csv_bytes(SAMPLE_PAIRS_2), "text/csv")},
        data={"title": "Second Quiz", "question_count": "5"},
    )
    assert r2.status_code == 201
    q2 = r2.json()
    q2_ids = [q["id"] for q in q2["questions"]]
    assert q2_ids != ["q_1", "q_2", "q_3", "q_4", "q_5"]

    # Playable endpoint hides is_correct; preview includes it
    play_resp = client.get(f"/api/v1/quizzes/{q2['id']}")
    assert play_resp.status_code == 200
    assert "is_correct" not in play_resp.json()["questions"][0]["choices"][0]

    preview_resp = client.get(f"/api/v1/quizzes/{q2['id']}/preview")
    assert preview_resp.status_code == 200
    preview = preview_resp.json()
    assert "is_correct" in preview["questions"][0]["choices"][0]

    # PATCH accepts partial title-only payload
    patch_resp = client.patch(
        f"/api/v1/quizzes/{q2['id']}",
        json={"title": "Second Quiz Renamed"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["title"] == "Second Quiz Renamed"

    # Submit all correct answers for quiz 2
    answers = []
    for question in preview["questions"]:
        correct = next(c for c in question["choices"] if c["is_correct"])
        answers.append({"question_id": question["id"], "choice_id": correct["id"]})

    att_resp = client.post(
        f"/api/v1/quizzes/{q2['id']}/attempts",
        json={"answers": answers},
    )
    assert att_resp.status_code == 201
    att = att_resp.json()
    assert att["id"].startswith("att_")
    assert att["score"] == 5
    assert att["total_questions"] == 5
    assert att["percentage"] == 100.0

    # GET attempt works with both att_N and legacy attempt_N
    get_att = client.get(f"/api/v1/attempts/{att['id']}")
    assert get_att.status_code == 200
    assert get_att.json()["score"] == 5

    legacy_id = att["id"].replace("att_", "attempt_")
    get_att_legacy = client.get(f"/api/v1/attempts/{legacy_id}")
    assert get_att_legacy.status_code == 200
    assert get_att_legacy.json()["score"] == 5


def test_attempt_validation_rejects_bad_answers_before_insert(client):
    r = client.post(
        "/api/v1/quizzes",
        files={"file": ("set1.csv", _make_csv_bytes(SAMPLE_PAIRS_1), "text/csv")},
        data={"title": "Validation Quiz", "question_count": "5"},
    )
    assert r.status_code == 201
    quiz = r.json()
    first_qid = quiz["questions"][0]["id"]

    # Unknown question ID
    bad1 = client.post(
        f"/api/v1/quizzes/{quiz['id']}/attempts",
        json={"answers": [{"question_id": "q_9999", "choice_id": "a"}]},
    )
    assert bad1.status_code == 400

    # Invalid question ID format
    bad2 = client.post(
        f"/api/v1/quizzes/{quiz['id']}/attempts",
        json={"answers": [{"question_id": "not_an_id", "choice_id": "a"}]},
    )
    assert bad2.status_code == 400

    # Duplicate question ID
    bad3 = client.post(
        f"/api/v1/quizzes/{quiz['id']}/attempts",
        json={
            "answers": [
                {"question_id": first_qid, "choice_id": "a"},
                {"question_id": first_qid, "choice_id": "b"},
            ]
        },
    )
    assert bad3.status_code == 400

    # Invalid choice ID
    bad4 = client.post(
        f"/api/v1/quizzes/{quiz['id']}/attempts",
        json={"answers": [{"question_id": first_qid, "choice_id": "z"}]},
    )
    assert bad4.status_code == 400

    # Verify zero Attempt rows were created
    db = SessionLocal()
    try:
        assert db.query(Attempt).count() == 0
    finally:
        db.close()


def test_exports_stream_pdf_sanitize_filename_and_escape_xml(client):
    r = client.post(
        "/api/v1/quizzes",
        files={"file": ("special.csv", _make_csv_bytes(SAMPLE_PAIRS_2), "text/csv")},
        data={"title": 'Bio <101> / "Cell" & DNA\r\n;Test', "question_count": "5"},
    )
    assert r.status_code == 201
    quiz_id = r.json()["id"]

    for kind in ("questions", "answers"):
        resp = client.get(f"/api/v1/quizzes/{quiz_id}/exports", params={"kind": kind})
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.content.startswith(b"%PDF")
        cd = resp.headers["content-disposition"]
        assert "\r" not in cd and "\n" not in cd and "/" not in cd
        assert f'filename="quiz_{kind}_' in cd


def test_parser_reraises_http_exception_size_limit_and_line_by_line_txt():
    # Empty CSV raises exact HTTPException (not wrapped)
    empty_csv = UploadFile(filename="empty.csv", file=io.BytesIO(b"   \n  "))
    with pytest.raises(HTTPException) as exc:
        FileParser.parse_csv(empty_csv)
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "EMPTY_FILE"
    assert not exc.value.detail["message"].startswith("Error parsing CSV file:")

    # Enforces settings.MAX_UPLOAD_SIZE_MB
    big_file = UploadFile(filename="big.txt", file=io.BytesIO(b"a" * (2 * 1024 * 1024)))
    with patch.object(settings, "MAX_UPLOAD_SIZE_MB", 1):
        with pytest.raises(HTTPException) as exc:
            FileParser.validate_file(big_file)
        assert exc.value.status_code == 413
        assert exc.value.detail["code"] == "FILE_TOO_LARGE"
        assert "1MB" in exc.value.detail["message"]

    # Line-by-line mixed-separator TXT parsing
    txt_content = (
        "Photosynthesis: Process by which plants make food\n"
        "Cell - Basic unit of life\n"
        "H2O -> Water molecule\n"
        "DNA = Deoxyribonucleic acid\n"
        "Well-known: Famous or widely recognized\n"
    ).encode("utf-8")
    txt_file = UploadFile(filename="mixed.txt", file=io.BytesIO(txt_content))
    parsed = FileParser.parse_txt(txt_file)
    assert parsed == [
        ("Photosynthesis", "Process by which plants make food"),
        ("Cell", "Basic unit of life"),
        ("H2O", "Water molecule"),
        ("DNA", "Deoxyribonucleic acid"),
        ("Well-known", "Famous or widely recognized"),
    ]


def test_generator_dedupes_pairs_unique_distractors_and_contiguous_positions():
    # Include duplicate terms and duplicate definitions
    pairs = [
        ("Term1", "Def1"),
        ("term1", "Def1_duplicate_term"),
        ("Term2", "Def2"),
        ("Term3", "Def2"),  # duplicate definition
        ("Term4", "Def3"),
        ("Term5", "Def3"),  # duplicate definition
        ("Term6", "Def4"),
        ("Term7", "Def5"),
        ("Term8", "Def6"),
        ("Term9", "Def7"),
    ]
    questions = QuizGenerator.generate_from_structured(pairs, question_count=8)
    QuizGenerator.validate_questions(questions)
    assert [q["position"] for q in questions] == list(range(len(questions)))
    for q in questions:
        texts = [c["text"] for c in q["choices"]]
        assert len(set(texts)) == 4


def test_quiz_post_duplicate_detection_before_generation_and_honors_params(client):
    csv_bytes = _make_csv_bytes(SAMPLE_PAIRS_1)

    r1 = client.post(
        "/api/v1/quizzes",
        files={"file": ("bio.csv", csv_bytes, "text/csv")},
        data={"title": "Bio Quiz", "question_count": "5"},
    )
    assert r1.status_code == 201
    id1 = r1.json()["id"]
    assert len(r1.json()["questions"]) == 5

    # Exact duplicate returns existing quiz WITHOUT calling QuizGenerator
    with patch.object(
        QuizGenerator, "generate_from_structured", side_effect=AssertionError("Should not generate")
    ):
        r_dup = client.post(
            "/api/v1/quizzes",
            files={"file": ("bio.csv", csv_bytes, "text/csv")},
            data={"title": "Bio Quiz", "question_count": "5"},
        )
        assert r_dup.status_code == 201
        assert r_dup.json()["id"] == id1

    # New title creates a new quiz
    r_new_title = client.post(
        "/api/v1/quizzes",
        files={"file": ("bio.csv", csv_bytes, "text/csv")},
        data={"title": "Bio Quiz v2", "question_count": "5"},
    )
    assert r_new_title.status_code == 201
    assert r_new_title.json()["id"] != id1
    assert r_new_title.json()["title"] == "Bio Quiz v2"

    # New question_count creates a new quiz with requested count
    r_new_count = client.post(
        "/api/v1/quizzes",
        files={"file": ("bio.csv", csv_bytes, "text/csv")},
        data={"title": "Bio Quiz", "question_count": "10"},
    )
    assert r_new_count.status_code == 201
    assert r_new_count.json()["id"] != id1
    assert len(r_new_count.json()["questions"]) == 10
