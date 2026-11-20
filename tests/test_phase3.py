"""
Tests verifying Phase 3 migrations, package structure, FKs, cascades, and indexes.
"""
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from app.db.models import Attempt, AttemptAnswer, Base, Choice, Question, Quiz
from app.db.session import SessionLocal, engine
from app.main import app


def test_package_init_files_exist():
    project_root = Path(__file__).resolve().parent.parent
    expected_packages = [
        "app",
        "app/api",
        "app/api/routes",
        "app/core",
        "app/db",
        "app/schemas",
        "app/services",
    ]
    for pkg in expected_packages:
        assert (project_root / pkg / "__init__.py").is_file(), f"Missing {pkg}/__init__.py"


def test_startup_does_not_call_create_all():
    with patch.object(Base.metadata, "create_all") as mock_create_all:
        with TestClient(app) as client:
            resp = client.get("/api/v1/health")
            assert resp.status_code == 200
        mock_create_all.assert_not_called()


def test_alembic_initial_migration_schema_fks_and_indexes(tmp_path):
    db_path = tmp_path / "alembic_test.db"
    db_url = f"sqlite:///{db_path}"

    project_root = Path(__file__).resolve().parent.parent
    alembic_cfg = Config(str(project_root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(project_root / "alembic"))

    with patch("app.core.config.settings.DATABASE_URL", db_url):
        command.upgrade(alembic_cfg, "head")

    test_engine = create_engine(db_url)
    try:
        insp = inspect(test_engine)
        tables = set(insp.get_table_names())
        assert {"quizzes", "questions", "choices", "attempts", "attempt_answers", "users"}.issubset(tables)

        # Verify indexes on source_hash and quiz_id
        quiz_indexes = {tuple(ix["column_names"]) for ix in insp.get_indexes("quizzes")}
        assert ("source_hash",) in quiz_indexes

        question_indexes = {tuple(ix["column_names"]) for ix in insp.get_indexes("questions")}
        assert ("quiz_id",) in question_indexes

        attempt_indexes = {tuple(ix["column_names"]) for ix in insp.get_indexes("attempts")}
        assert ("quiz_id",) in attempt_indexes

        # Verify AttemptAnswer has FK to questions.id with CASCADE, plus attempts.id & choices.id
        aa_fks = {
            (tuple(fk["constrained_columns"]), fk["referred_table"], fk.get("options", {}).get("ondelete"))
            for fk in insp.get_foreign_keys("attempt_answers")
        }
        assert (("question_id",), "questions", "CASCADE") in aa_fks
        assert (("attempt_id",), "attempts", "CASCADE") in aa_fks
        assert (("choice_id",), "choices", "CASCADE") in aa_fks
    finally:
        test_engine.dispose()


def test_cascade_delete_on_quiz():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        quiz = Quiz(title="Cascade Test", source_type="csv", source_hash="abc123")
        db.add(quiz)
        db.flush()

        q = Question(quiz_id=quiz.id, prompt="What is H2O?", position=0)
        db.add(q)
        db.flush()

        c = Choice(question_id=q.id, text="Water", is_correct=True, position=0)
        db.add(c)
        db.flush()

        att = Attempt(quiz_id=quiz.id, score=1, total_questions=1)
        db.add(att)
        db.flush()

        ans = AttemptAnswer(attempt_id=att.id, question_id=q.id, choice_id=c.id, is_correct=True)
        db.add(ans)
        db.commit()

        # Perform DB-level delete directly to verify ON DELETE CASCADE
        db.execute(text("DELETE FROM quizzes WHERE id = :qid"), {"qid": quiz.id})
        db.commit()

        assert db.query(Question).count() == 0
        assert db.query(Choice).count() == 0
        assert db.query(Attempt).count() == 0
        assert db.query(AttemptAnswer).count() == 0
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
