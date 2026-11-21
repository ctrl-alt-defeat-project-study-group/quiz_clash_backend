"""
Tests for Phase 10 AI quiz generation (Gemini 2.5 Flash + Google Search grounding).
All Gemini HTTP calls are mocked so tests run offline and deterministically.
"""
from datetime import datetime, timezone
import io
import json
from typing import Any, Dict, List
from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.rate_limit import rate_limiter
from app.core.security import create_access_token, hash_password
from app.db.models import Base, User, UserSettings
from app.db.session import SessionLocal, engine
from app.main import app
from app.services.parser import FileParser


@pytest.fixture(autouse=True)
def reset_db_and_limits():
    rate_limiter.reset()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    rate_limiter.reset()


def _create_user(email: str = "ai_user@example.com") -> User:
    db = SessionLocal()
    try:
        user = User(
            email=email,
            password_hash=hash_password("Password123"),
            display_name="AI Tester",
            role="user",
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
    client = TestClient(app)
    token = create_access_token(user_id=user.id, role=user.role)
    client.cookies.set(settings.ACCESS_COOKIE_NAME, token)
    return client


def _gemini_response(text: str, status_code: int = 200) -> httpx.Response:
    body = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    return httpx.Response(status_code=status_code, json=body)


def _mock_gemini_client(post_handler):
    """Return a context manager patching httpx.Client inside llm_quiz_generator only."""

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json=None, headers=None, **kwargs):
            return post_handler(url, json=json, headers=headers, **kwargs)

    return patch("app.services.llm_quiz_generator.httpx.Client", _FakeClient)


def _valid_questions_json(count: int = 5, prefix: str = "Q") -> str:
    questions = []
    for i in range(1, count + 1):
        questions.append(
            {
                "prompt": f"{prefix} {i}: What is concept {i}?",
                "explanation": f"Concept {i} is explained by the study notes.",
                "choices": [
                    {"text": f"Correct answer {i}", "is_correct": True},
                    {"text": f"Distractor A {i}", "is_correct": False},
                    {"text": f"Distractor B {i}", "is_correct": False},
                    {"text": f"Distractor C {i}", "is_correct": False},
                ],
            }
        )
    return json.dumps({"questions": questions})


def _analysis_json() -> str:
    return json.dumps(
        {
            "summary": "Photosynthesis converts light energy into chemical energy in chloroplasts.",
            "keywords": ["Photosynthesis", "Chloroplast", "ATP", "Calvin Cycle", "Chlorophyll"],
        }
    )


def _sample_notes_bytes() -> bytes:
    return (
        "Photosynthesis is the biological process used by plants to convert sunlight into "
        "chemical energy. It occurs inside chloroplasts using chlorophyll pigments, producing "
        "glucose and oxygen through light-dependent reactions and the Calvin cycle."
    ).encode("utf-8")


def _sample_csv_bytes() -> bytes:
    rows = [f'"Term{i}","Definition {i}"' for i in range(1, 10)]
    return "\n".join(rows).encode("utf-8")


def test_extract_raw_text_across_formats_and_empty():
    # Unstructured TXT (no ':' separators)
    txt_file = UploadFile(filename="lecture.txt", file=io.BytesIO(_sample_notes_bytes()))
    extracted_txt = FileParser.extract_raw_text(txt_file)
    assert "Photosynthesis" in extracted_txt

    # CSV
    csv_file = UploadFile(filename="notes.csv", file=io.BytesIO(_sample_csv_bytes()))
    extracted_csv = FileParser.extract_raw_text(csv_file)
    assert "Term1" in extracted_csv

    # PDF (generated in-memory with reportlab)
    from reportlab.pdfgen import canvas

    pdf_buf = io.BytesIO()
    c = canvas.Canvas(pdf_buf)
    c.drawString(72, 720, "Mitochondria generate ATP via oxidative phosphorylation.")
    c.save()
    pdf_buf.seek(0)
    pdf_file = UploadFile(filename="bio.pdf", file=pdf_buf)
    extracted_pdf = FileParser.extract_raw_text(pdf_file)
    assert "Mitochondria" in extracted_pdf

    # DOCX (generated in-memory with python-docx)
    from docx import Document

    doc = Document()
    doc.add_paragraph("DNA replication is semi-conservative.")
    table = doc.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Enzyme"
    table.rows[0].cells[1].text = "DNA Polymerase"
    docx_buf = io.BytesIO()
    doc.save(docx_buf)
    docx_buf.seek(0)
    docx_file = UploadFile(filename="genetics.docx", file=docx_buf)
    extracted_docx = FileParser.extract_raw_text(docx_file)
    assert "semi-conservative" in extracted_docx
    assert "DNA Polymerase" in extracted_docx

    # Empty file raises 400 EMPTY_FILE
    empty_file = UploadFile(filename="empty.txt", file=io.BytesIO(b"   \n  "))
    with pytest.raises(HTTPException) as exc_info:
        FileParser.extract_raw_text(empty_file)
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "EMPTY_FILE"


def test_ai_generation_full_pipeline_with_web_search():
    user = _create_user()
    recorded_payloads: List[Dict[str, Any]] = []

    def fake_post(url, json=None, headers=None, **kwargs):
        recorded_payloads.append(json)
        idx = len(recorded_payloads)
        if idx == 1:
            return _gemini_response(_analysis_json())
        if idx == 2:
            return _gemini_response("- Chloroplasts contain thylakoids.\n- ATP powers the Calvin cycle.")
        return _gemini_response(_valid_questions_json(5))

    with (
        patch.object(settings, "LLM_API_KEY", "test-gemini-key"),
        _mock_gemini_client(fake_post),
        _client_for(user) as client,
    ):
        resp = client.post(
            "/api/v1/quizzes",
            files={"file": ("biology_notes.txt", _sample_notes_bytes(), "text/plain")},
            data={"title": "Photosynthesis AI", "use_llm": "true", "question_count": "5"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["source_type"] == "llm"
        assert body["title"] == "Photosynthesis AI"
        assert len(body["questions"]) == 5
        for q in body["questions"]:
            assert len(q["choices"]) == 4
            assert all("is_correct" not in ch for ch in q["choices"])

        # Verify all 3 stages ran and Stage 2 used Google Search grounding
        assert len(recorded_payloads) == 3
        assert recorded_payloads[1].get("tools") == [{"google_search": {}}]

        # Preview endpoint includes correct answers and explanations
        preview = client.get(f"/api/v1/quizzes/{body['id']}/preview")
        assert preview.status_code == 200
        preview_body = preview.json()
        for q in preview_body["questions"]:
            assert q["explanation"]
            assert sum(1 for ch in q["choices"] if ch["is_correct"]) == 1


def test_ai_generation_without_web_search_and_myanmar_language():
    user = _create_user()
    recorded_payloads: List[Dict[str, Any]] = []

    def fake_post(url, json=None, headers=None, **kwargs):
        recorded_payloads.append(json)
        if len(recorded_payloads) == 1:
            return _gemini_response(_analysis_json())
        return _gemini_response(_valid_questions_json(5, prefix="မေးခွန်း"))

    with (
        patch.object(settings, "LLM_API_KEY", "test-gemini-key"),
        _mock_gemini_client(fake_post),
        _client_for(user) as client,
    ):
        resp = client.post(
            "/api/v1/quizzes",
            files={"file": ("notes.txt", _sample_notes_bytes(), "text/plain")},
            data={
                "use_llm": "true",
                "use_web_search": "false",
                "question_count": "5",
                "language": "mm",
            },
        )
        assert resp.status_code == 201
        # Stage 2 skipped -> only 2 Gemini calls
        assert len(recorded_payloads) == 2
        assert "tools" not in recorded_payloads[0]
        assert "tools" not in recorded_payloads[1]
        # Myanmar language instruction propagated
        stage3_text = recorded_payloads[1]["contents"][0]["parts"][0]["text"]
        assert "Myanmar (Burmese)" in stage3_text
        assert resp.json()["questions"][0]["prompt"].startswith("မေးခွန်း")


def test_ai_generation_web_search_timeout_falls_back_gracefully():
    user = _create_user()
    call_count = 0

    def fake_post(url, json=None, headers=None, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _gemini_response(_analysis_json())
        if call_count == 2:
            raise httpx.TimeoutException("search timed out")
        return _gemini_response(_valid_questions_json(5))

    with (
        patch.object(settings, "LLM_API_KEY", "test-gemini-key"),
        _mock_gemini_client(fake_post),
        _client_for(user) as client,
    ):
        resp = client.post(
            "/api/v1/quizzes",
            files={"file": ("notes.txt", _sample_notes_bytes(), "text/plain")},
            data={"use_llm": "true", "use_web_search": "true", "question_count": "5"},
        )
        assert resp.status_code == 201
        assert len(resp.json()["questions"]) == 5
        assert call_count == 3


def test_ai_generation_missing_api_key_returns_503():
    user = _create_user()
    with (
        patch.object(settings, "LLM_API_KEY", None),
        _client_for(user) as client,
    ):
        resp = client.post(
            "/api/v1/quizzes",
            files={"file": ("notes.txt", _sample_notes_bytes(), "text/plain")},
            data={"use_llm": "true", "question_count": "5"},
        )
        assert resp.status_code == 503
        assert resp.json()["detail"]["code"] == "GENERATION_FAILED"


def test_ai_generation_retries_once_on_invalid_output():
    user = _create_user()
    invalid_questions = json.dumps(
        {
            "questions": [
                {
                    "prompt": "Broken question",
                    "explanation": "Only 2 choices",
                    "choices": [
                        {"text": "A", "is_correct": True},
                        {"text": "B", "is_correct": False},
                    ],
                }
            ]
        }
    )

    # Case 1: first Stage 3 attempt invalid, retry succeeds
    calls_pass = 0

    def fake_post_pass(url, json=None, headers=None, **kwargs):
        nonlocal calls_pass
        calls_pass += 1
        if calls_pass == 1:
            return _gemini_response(_analysis_json())
        if calls_pass == 2:
            return _gemini_response(invalid_questions)
        return _gemini_response(_valid_questions_json(5))

    with (
        patch.object(settings, "LLM_API_KEY", "test-gemini-key"),
        _mock_gemini_client(fake_post_pass),
        _client_for(user) as client,
    ):
        resp = client.post(
            "/api/v1/quizzes",
            files={"file": ("retry_ok.txt", _sample_notes_bytes(), "text/plain")},
            data={"use_llm": "true", "use_web_search": "false", "question_count": "5"},
        )
        assert resp.status_code == 201
        assert calls_pass == 3

    # Case 2: both Stage 3 attempts invalid -> 500 GENERATION_FAILED
    calls_fail = 0

    def fake_post_fail(url, json=None, headers=None, **kwargs):
        nonlocal calls_fail
        calls_fail += 1
        if calls_fail == 1:
            return _gemini_response(_analysis_json())
        return _gemini_response(invalid_questions)

    with (
        patch.object(settings, "LLM_API_KEY", "test-gemini-key"),
        _mock_gemini_client(fake_post_fail),
        _client_for(user) as client,
    ):
        resp = client.post(
            "/api/v1/quizzes",
            files={"file": ("retry_fail.txt", b"Different notes about gravity.", "text/plain")},
            data={"use_llm": "true", "use_web_search": "false", "question_count": "5"},
        )
        assert resp.status_code == 500
        assert resp.json()["detail"]["code"] == "GENERATION_FAILED"
        assert calls_fail == 3


def test_ai_generation_duplicate_cache_and_rate_limit():
    user = _create_user()
    call_count = 0

    def fake_post(url, json=None, headers=None, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count % 2 == 1:
            return _gemini_response(_analysis_json())
        return _gemini_response(_valid_questions_json(5))

    with (
        patch.object(settings, "LLM_API_KEY", "test-gemini-key"),
        patch.object(settings, "RATE_LIMIT_LLM_MAX_REQUESTS", 1),
        _mock_gemini_client(fake_post),
        _client_for(user) as client,
    ):
        # First upload calls Gemini (2 calls: analyze + generate)
        r1 = client.post(
            "/api/v1/quizzes",
            files={"file": ("same.txt", _sample_notes_bytes(), "text/plain")},
            data={"use_llm": "true", "use_web_search": "false", "question_count": "5"},
        )
        assert r1.status_code == 201
        assert call_count == 2

        # Duplicate upload hits cache without triggering LLM or rate limit
        r2 = client.post(
            "/api/v1/quizzes",
            files={"file": ("same.txt", _sample_notes_bytes(), "text/plain")},
            data={"use_llm": "true", "use_web_search": "false", "question_count": "5"},
        )
        assert r2.status_code == 201
        assert r2.json()["id"] == r1.json()["id"]
        assert call_count == 2

        # New distinct AI upload hits per-user LLM rate limit -> 429 RATE_LIMITED
        r3 = client.post(
            "/api/v1/quizzes",
            files={"file": ("other.txt", b"Completely new study material on physics.", "text/plain")},
            data={"use_llm": "true", "use_web_search": "false", "question_count": "5"},
        )
        assert r3.status_code == 429
        assert r3.json()["detail"]["code"] == "RATE_LIMITED"

        # Rule-based upload (use_llm=false) is NOT blocked by LLM rate limit
        r4 = client.post(
            "/api/v1/quizzes",
            files={"file": ("flashcards.csv", _sample_csv_bytes(), "text/csv")},
            data={"use_llm": "false", "question_count": "5"},
        )
        assert r4.status_code == 201
