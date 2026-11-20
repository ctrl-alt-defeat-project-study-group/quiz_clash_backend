"""
Tests verifying Phase 6: Language (EN/MM), PDF/DOCX uploads, and PDF/Word exports.
"""
from datetime import datetime, timezone
import io

from docx import Document
from fastapi import UploadFile
from fastapi.testclient import TestClient
import pytest
from reportlab.pdfgen import canvas

from app.core.config import settings
from app.core.language import normalize_language, resolve_request_language
from app.core.rate_limit import rate_limiter
from app.core.security import create_access_token, hash_password
from app.db.models import Base, User
from app.db.session import SessionLocal, engine
from app.main import app
from app.services.parser import FileParser
from app.services.pdf_generator import MYANMAR_BOLD_FONT, MYANMAR_REGULAR_FONT


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
            email="phase6@example.com",
            password_hash=hash_password("Password123"),
            display_name="Phase6 User",
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


def _make_pdf_bytes(lines):
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    y = 750
    for line in lines:
        c.drawString(50, y, line)
        y -= 20
    c.save()
    return buf.getvalue()


def _make_docx_bytes(lines=None, table_rows=None):
    doc = Document()
    for line in (lines or []):
        doc.add_paragraph(line)
    if table_rows:
        table = doc.add_table(rows=0, cols=2)
        for term, definition in table_rows:
            row = table.add_row().cells
            row[0].text = term
            row[1].text = definition
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_language_normalization_and_bundled_fonts():
    assert normalize_language(None) == "en"
    assert normalize_language("") == "en"
    assert normalize_language("en") == "en"
    assert normalize_language("en-US") == "en"
    assert normalize_language("mm") == "mm"
    assert normalize_language("MM") == "mm"
    assert normalize_language("my") == "mm"
    assert normalize_language("my-MM,en;q=0.8") == "mm"
    assert normalize_language("fr") == "en"

    assert resolve_request_language("mm", "en") == "mm"
    assert resolve_request_language("my", "en") == "mm"
    assert resolve_request_language(None, "my") == "mm"
    assert resolve_request_language(None, "mm") == "mm"
    assert resolve_request_language(None, None) == "en"

    assert MYANMAR_REGULAR_FONT.exists()
    assert MYANMAR_BOLD_FONT.exists()


def test_parser_utf8_bom_and_myanmar_separators():
    # UTF-8 with BOM CSV
    bom_csv = "\ufeffTerm1,Def1\nTerm2,Def2\n".encode("utf-8")
    parsed_csv = FileParser.parse_csv(UploadFile(filename="bom.csv", file=io.BytesIO(bom_csv)))
    assert parsed_csv == [("Term1", "Def1"), ("Term2", "Def2")]

    # Myanmar TXT with BOM, ၊ and ။ separators
    mm_txt = (
        "\ufeffဆဲလ် ၊ သက်ရှိအခြေခံယူနစ်။ ဒီအန်အေ ၊ မျိုးရိုးဗီဇပစ္စည်း။\n"
        "အောက်ဆီဂျင်: အသက်ရှူရန်လိုအပ်သောဓာတ်ငွေ့\n"
    ).encode("utf-8")
    parsed_txt = FileParser.parse_txt(UploadFile(filename="mm.txt", file=io.BytesIO(mm_txt)))
    assert parsed_txt == [
        ("ဆဲလ်", "သက်ရှိအခြေခံယူနစ်"),
        ("ဒီအန်အေ", "မျိုးရိုးဗီဇပစ္စည်း"),
        ("အောက်ဆီဂျင်", "အသက်ရှူရန်လိုအပ်သောဓာတ်ငွေ့"),
    ]


def test_pdf_and_docx_uploads_and_empty_rejection(client):
    # Valid PDF upload
    pdf_lines = [f"PDFTerm{i}: PDFDefinition {i}" for i in range(1, 11)]
    r_pdf = client.post(
        "/api/v1/quizzes",
        files={"file": ("notes.pdf", _make_pdf_bytes(pdf_lines), "application/pdf")},
        data={"title": "PDF Quiz", "question_count": "5"},
    )
    assert r_pdf.status_code == 201
    assert r_pdf.json()["source_type"] == "pdf"
    assert len(r_pdf.json()["questions"]) == 5

    # Empty PDF -> 400 EMPTY_FILE
    r_empty_pdf = client.post(
        "/api/v1/quizzes",
        files={"file": ("blank.pdf", _make_pdf_bytes([]), "application/pdf")},
        data={"question_count": "5"},
    )
    assert r_empty_pdf.status_code == 400
    assert r_empty_pdf.json()["detail"]["code"] == "EMPTY_FILE"

    # Valid DOCX upload (table-based term-definition pairs)
    docx_rows = [(f"DocxTerm{i}", f"DocxDefinition {i}") for i in range(1, 11)]
    r_docx = client.post(
        "/api/v1/quizzes",
        files={
            "file": (
                "study.docx",
                _make_docx_bytes(table_rows=docx_rows),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"title": "DOCX Quiz", "question_count": "5"},
    )
    assert r_docx.status_code == 201
    assert r_docx.json()["source_type"] == "docx"
    assert len(r_docx.json()["questions"]) == 5

    # Empty DOCX -> 400 EMPTY_FILE
    r_empty_docx = client.post(
        "/api/v1/quizzes",
        files={
            "file": (
                "empty.docx",
                _make_docx_bytes(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"question_count": "5"},
    )
    assert r_empty_docx.status_code == 400
    assert r_empty_docx.json()["detail"]["code"] == "EMPTY_FILE"


def test_myanmar_quiz_generation_and_pdf_word_exports(client):
    mm_pairs = "\n".join(
        f"ဝေါဟာရ{i} ၊ အဓိပ္ပာယ်ဖွင့်ဆိုချက် {i}" for i in range(1, 11)
    ).encode("utf-8")

    # Upload with Accept-Language: my (normalized to mm)
    r_mm = client.post(
        "/api/v1/quizzes",
        files={"file": ("myanmar_notes.txt", mm_pairs, "text/plain")},
        data={"title": "Myanmar Biology", "question_count": "5"},
        headers={"Accept-Language": "my"},
    )
    assert r_mm.status_code == 201
    quiz = r_mm.json()
    assert "၏ အဓိပ္ပာယ်မှာ အဘယ်နည်း။" in quiz["questions"][0]["prompt"]
    quiz_id = quiz["id"]

    # PDF exports in EN and MM (questions & answers)
    for kind in ("questions", "answers"):
        for lang in ("en", "mm", "my"):
            resp = client.get(
                f"/api/v1/quizzes/{quiz_id}/exports",
                params={"kind": kind, "format": "pdf", "lang": lang},
            )
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "application/pdf"
            assert resp.content.startswith(b"%PDF")

    # Word (.docx) exports in EN and MM (questions & answers)
    for kind in ("questions", "answers"):
        for lang, expected_label in (("en", "Quiz" if kind == "questions" else "Answer Key"), ("mm", "မေးခွန်းလွှာ" if kind == "questions" else "အဖြေမှန်လွှာ")):
            resp = client.get(
                f"/api/v1/quizzes/{quiz_id}/exports",
                params={"kind": kind, "format": "word", "lang": lang},
            )
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            assert f'filename="quiz_{kind}_Myanmar_Biology.docx"' in resp.headers["content-disposition"]

            # Verify DOCX parses cleanly and contains localized label
            doc = Document(io.BytesIO(resp.content))
            all_text = "\n".join(p.text for p in doc.paragraphs)
            assert expected_label in all_text

    # Invalid format returns 400 VALIDATION_ERROR
    bad_fmt = client.get(
        f"/api/v1/quizzes/{quiz_id}/exports",
        params={"kind": "questions", "format": "xlsx"},
    )
    assert bad_fmt.status_code == 400
    assert bad_fmt.json()["detail"]["code"] == "VALIDATION_ERROR"
