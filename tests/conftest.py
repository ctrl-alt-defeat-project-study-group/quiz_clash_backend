"""
Shared pytest configuration so tests run without PYTHONPATH=. or manual DATABASE_URL.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure project root is importable when running `pytest` directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Provide an isolated SQLite database by default during test runs
_temp_db_dir = None
if "DATABASE_URL" not in os.environ:
    _temp_db_dir = tempfile.TemporaryDirectory(prefix="quizclash_test_")
    _db_path = Path(_temp_db_dir.name) / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"

# Keep local .env demo-user seed out of automated test runs unless explicitly patched
os.environ.setdefault("DEMO_USER_EMAIL", "")
os.environ.setdefault("DEMO_USER_PASSWORD", "")


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_db():
    yield
    if _temp_db_dir is not None:
        from app.db.session import engine

        engine.dispose()
        _temp_db_dir.cleanup()
