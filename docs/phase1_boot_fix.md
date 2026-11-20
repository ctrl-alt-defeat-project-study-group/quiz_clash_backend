# Phase 1: Make the Backend Boot Cleanly

## Goal
Fix every import-time and startup-time crash so the FastAPI app can be imported, configured and started.

## Changes

| File | Change | Why |
|------|--------|-----|
| `app/services/quiz_generator.py` | Added `Optional` to the `typing` import | `NameError` at import |
| `app/api/routes/attempts.py` | Removed `from app.schemas.quiz import AnswerSubmission` | `ImportError` (the class lives in `schemas/attempt.py` and was unused here) |
| `app/schemas/quiz.py` | `regex=` -> `pattern=`; `min_items`/`max_items` -> `min_length`/`max_length` | Pydantic v2 removed/deprecated these |
| `app/core/config.py` | Default driver set to `postgresql+psycopg2://`; `FRONTEND_ORIGINS` accepts comma-separated strings via a `field_validator`; `class Config` replaced by `SettingsConfigDict` | Driver mismatch with `psycopg2-binary`; env value from `.env.example` was not valid JSON |
| `.env.example`, `README.md` | `DATABASE_URL` uses `postgresql+psycopg2://` | Keep docs consistent with the driver |
| `app/db/models.py` | Added `ForeignKey("choices.id")` on `AttemptAnswer.choice_id` | The `AttemptAnswer.choice` relationship raised `NoForeignKeysError` during mapper configuration |

## Verification (Python 3.12, local `.venv`)
```bash
.venv/bin/python -c "import app.main; from sqlalchemy.orm import configure_mappers; configure_mappers()"
FRONTEND_ORIGINS="http://localhost:5173,http://localhost:3000" .venv/bin/python -c "from app.core.config import Settings; print(Settings().FRONTEND_ORIGINS)"
PYTHONPATH=. DATABASE_URL="sqlite:///./test_boot.db" .venv/bin/pytest -q tests/test_health.py
```
Results: import and mapper configuration OK, origins parsed as a list, 2 tests passed.

## Notes
- Not tested against a real PostgreSQL server.
- `pytest` needs `PYTHONPATH=.` until a `conftest.py` or `__init__.py` files are added.

## Next (Phase 2, not started)
Question ID mismatch between quiz and grading, PDF export cleanup and escaping, parser error handling, attempt validation, `PATCH` schema, generator duplicates.
