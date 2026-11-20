# QuizClash Backend – Roadmap

Legend: `[x]` done, `[ ]` not done.  
Backend is edited in this repo. Frontend is tracked under **Frontend handoff** (not edited here).

Details of Phase 1 are in [phase1_boot_fix.md](phase1_boot_fix.md). Frontend reference notes are in [frontend_notes.md](frontend_notes.md). API contract is in [Backend_API_Data_Contract.md](Backend_API_Data_Contract.md).

## Phase 1 – Make it boot (DONE)
- [x] `quiz_generator.py`: import `Optional`
- [x] `attempts.py`: remove the bad `AnswerSubmission` import
- [x] `schemas/quiz.py`: `regex` -> `pattern`, `min_items`/`max_items` -> `min_length`/`max_length`
- [x] `config.py`: accept comma-separated `FRONTEND_ORIGINS`
- [x] `config.py`: switch `class Config` to `SettingsConfigDict`
- [x] Database driver set to `postgresql+psycopg2://` in `config.py`, `.env.example`, `README.md`
- [x] `models.py`: add `ForeignKey("choices.id")` on `AttemptAnswer.choice_id`
- [x] Verify: import, mapper config, settings parsing, health tests (2 passed)

## Phase 2 – Correctness fixes (DONE)
- [x] **Grading IDs:** make `format_quiz_response` use `q_{db_id}` so quiz output and grading agree
- [x] **Attempts:** validate all answers before inserting; reject unknown/invalid/duplicate IDs (`400`/`422`); remove N+1 queries (eager loading)
- [x] **Exports:** clean up temp PDF with `BackgroundTask` (stop deleting before streaming); sanitize download filename
- [x] **PDF:** escape user text in `Paragraph`; load `.ttc` fonts with `subfontIndex`; apply Unicode font to table cells
- [x] **Parser:** re-raise `HTTPException` instead of wrapping it; enforce `settings.MAX_UPLOAD_SIZE_MB`; parse TXT line by line
- [x] **Generator:** dedupe pairs, pick unique distractors, renumber question positions after skipped items
- [x] **Quiz POST:** run duplicate detection before generation; honor new `title` and `question_count`
- [x] **Shared helper:** single `parse_prefixed_id()` in `app/core/ids.py` instead of 3 copies
- [x] **Sync handlers:** switch blocking DB handlers from `async def` to `def`

## Phase 3 – Migrations & project base (DONE)
- [x] Add `__init__.py` files and `tests/conftest.py` (fixes `find_packages()` and running `pytest` without `PYTHONPATH=.`)
- [x] Initialize Alembic with an initial migration; remove `Base.metadata.create_all()` from startup
- [x] Add `ForeignKey("questions.id")` on `AttemptAnswer.question_id`, `ondelete="CASCADE"` on FKs, and indexes on `quiz_id` and `source_hash`

## Phase 4 – Auth, roles, email verification & admin (DONE)
- [x] Dependencies: add `argon2-cffi`, `PyJWT`, `email-validator`
- [x] Settings: `SECRET_KEY`, cookie flags (`COOKIE_SECURE`, `COOKIE_SAMESITE`), token lifetimes, `ADMIN_EMAIL`/`ADMIN_PASSWORD`, `SMTP_*` (optional), `APP_BASE_URL`
- [x] Models + migration: `User` (`display_name`, `role` `user|admin`, `is_active`, `email_verified_at`), `EmailToken` (`user_id`, `purpose` `verify|reset`, `token_hash`, `expires_at`, `used_at`), `Quiz.owner_id`, `Attempt.user_id`
- [x] Password hashing with Argon2 and password strength rules
- [x] Mailer service: console backend in dev (prints clickable link when SMTP is not configured) + SMTP backend for production
- [x] `POST /api/v1/auth/register` (open sign-up, always creates `user`, sends verification email)
- [x] `POST /api/v1/auth/verify-email` and `POST /api/v1/auth/resend-verification`
- [x] `POST /api/v1/auth/login` (sets httpOnly access + refresh cookies; blocks unverified users with `403 EMAIL_NOT_VERIFIED`; `401 INVALID_CREDENTIALS`; `403 ACCOUNT_DISABLED`)
- [x] `POST /api/v1/auth/logout`, `POST /api/v1/auth/refresh`, `GET /api/v1/auth/me`
- [x] `POST /api/v1/auth/forgot-password` and `POST /api/v1/auth/reset-password` (one-time expiring token)
- [x] Auth dependencies: `get_current_user` (`401`), `require_admin` (`403`), `get_optional_user` (for guest-capable live routes)
- [x] CSRF guard: verify `Origin` header against `FRONTEND_ORIGINS` on `POST`/`PATCH`/`DELETE`; cookies `HttpOnly`, `SameSite=Lax`, `Secure` in prod
- [x] Rate limiting on login, register, and forgot-password (`429 RATE_LIMITED`)
- [x] Seed first admin user on startup from `ADMIN_EMAIL`/`ADMIN_PASSWORD`
- [x] Ownership enforcement: users only read/edit/delete their own quizzes and attempts; admins can access all; guests cannot play solo or create quizzes
- [x] Admin API: `GET /api/v1/admin/users` (with search), `PATCH /api/v1/admin/users/{id}` (`role`, `is_active`), `DELETE /api/v1/admin/users/{id}`, `GET /api/v1/admin/quizzes`, `DELETE /api/v1/admin/quizzes/{id}`, `GET /api/v1/admin/stats`
- [x] Safety guard: prevent deleting or demoting the last active admin
- [x] Auth error codes: `INVALID_CREDENTIALS`, `EMAIL_ALREADY_EXISTS`, `EMAIL_NOT_VERIFIED`, `TOKEN_INVALID_OR_EXPIRED`, `ACCOUNT_DISABLED`

## Phase 5 – API contract core
- [ ] `GET /api/v1/health` -> `{"status": "ok", "service": "quiz-clash-api"}`; update `tests/test_health.py`
- [ ] `app/core/errors.py`: structured `{"detail": {"code": ..., "message": ...}}` helper + global handlers for `VALIDATION_ERROR` (`422`) and `SERVER_ERROR` (`500`)
- [ ] Return contract error codes everywhere (`QUIZ_NOT_FOUND`, `ATTEMPT_NOT_FOUND`, `UNSUPPORTED_FILE_TYPE`, `FILE_TOO_LARGE` `413`, `EMPTY_FILE`, `GENERATION_FAILED`, `EXPORT_FAILED`)
- [ ] Models + migration: `Quiz` (`category`, `source_filename`, `updated_at`, `status` default `"ready"`), `Question.explanation`, `Attempt.duration_seconds`
- [ ] Standardize ID formats: `quiz_N`, `q_N`, `a`–`d`, `att_N` (accept legacy `attempt_N` on input if needed)
- [ ] `POST /api/v1/quizzes`: return `201`, accept `category`, `question_count` in `{5, 10, 15, 20}`, save `source_filename`, generate `explanation` (`"{term}: {definition}"`)
- [ ] `GET /api/v1/quizzes`: list user's quizzes (`id`, `title`, `category`, `source_filename`, `question_count`, `last_score`, `updated_at`)
- [ ] `GET /api/v1/quizzes/{id}` hides `is_correct`; `GET /api/v1/quizzes/{id}/preview` includes `is_correct` and `explanation`
- [ ] `PATCH /api/v1/quizzes/{id}`: full edit of `title`, `questions`, and `choices` (4 choices, 1 correct), update `updated_at`
- [ ] `POST /api/v1/quizzes/{id}/attempts`: accept `duration_seconds`, return `201` with `id: att_N`, `quiz_title`, `explanation`
- [ ] `GET /api/v1/attempts` (list) and `GET /api/v1/attempts/{id}` (detail with `explanation`)
- [ ] Align `ApiQuizResponse` and `ApiAttemptResponse` schemas field-for-field with the contract

## Phase 6 – Language (EN/MM), uploads & exports
- [ ] Language helper: canonical code `mm` everywhere (`Accept-Language`, form `language`, query `lang`); silently accept `my` as an alias and normalize to `mm` (default `en`)
- [ ] Parser: decode with `utf-8-sig` (BOM-safe); handle Myanmar separators (`။`, `၊`)
- [ ] Upload support for `.pdf` (`pypdf`) and `.docx` (`python-docx`); update `ALLOWED_FILE_TYPES`; empty extracted text -> `400 EMPTY_FILE`
- [ ] Quiz prompt template per language (`en` / `mm`)
- [ ] Exports: support `lang` (`en|mm`) and `format` (`pdf|word`) query params
- [ ] Word (`.docx`) export for both `questions` and `answers`
- [ ] Bundle `Noto Sans Myanmar` Unicode font for PDF/DOCX; decide and implement Myanmar PDF shaping (WeasyPrint vs ReportLab)
- [ ] Translate static export labels/headings by `lang`

## Phase 7 – Live rooms
- [ ] Models + migration: `LiveRoom` (`quiz_id`, `host_id`, `pin`, `timer_seconds`, `status`)
- [ ] `POST /api/v1/live/rooms` (authenticated host only)
- [ ] `POST /api/v1/live/rooms/{pin}/join` (guests allowed with `display_name`; `INVALID_ROOM_PIN` `400`, `ROOM_NOT_FOUND` `404`)
- [ ] `POST /api/v1/live/rooms/{pin}/next` (host only)
- [ ] `WS /api/v1/live/rooms/{pin}/ws` (server-timed rounds, answer submission, latency scoring, live leaderboard broadcast)
- [ ] Room state payload matches `LiveGameState` in contract

## Phase 8 – Settings & account
- [ ] `UserSettings` model + migration (theme, `ui_language`, `default_questions`, `difficulty`, `quiz_language`, `shuffle_questions`, `show_explanations`, `study_reminders`, `weekly_summary`)
- [ ] `GET /api/v1/settings` and `PATCH /api/v1/settings`
- [ ] `GET /api/v1/account/export` (JSON dump of user's quizzes, attempts, settings)
- [ ] `DELETE /api/v1/account` (delete/reset user workspace data)

## Phase 9 – Hardening & tests
- [ ] Automated test suite: auth flow, email verification/reset, CSRF, ownership, admin guards, contract response shapes, CSV/TXT/PDF/DOCX parsers, PDF/Word exports, live rooms
- [ ] Bump Dockerfiles from Python 3.9 to 3.11+ and add `docker-compose.yml` (api + postgres)
- [ ] Production safety checks (non-default `SECRET_KEY`, `COOKIE_SECURE=true`, rate limits)

## Deferred
- AI quiz generation (`use_llm=true`): to be discussed later; return a clear error code until implemented.

## Frontend handoff (not edited in this repo)
- [ ] Send `credentials: "include"` on all `fetch` calls; handle `401` (redirect to login) and `403`
- [ ] Add pages & route guards: register, verify-email, login, forgot/reset password, admin (users, quizzes, stats)
- [ ] Add new auth error codes to `src/i18n/errors.ts` (`INVALID_CREDENTIALS`, `EMAIL_ALREADY_EXISTS`, `EMAIL_NOT_VERIFIED`, `TOKEN_INVALID_OR_EXPIRED`, `ACCOUNT_DISABLED`)
- [ ] Use `mm` consistently everywhere (including `Accept-Language: mm`)
- [ ] Update `api.ts` & `types/quiz.ts`: `listQuizzes`, `listAttempts`, `duration_seconds`, `format=word`, `.pdf`/`.docx` upload, `explanation`/`category`/`source_filename`/`updated_at`
- [ ] Wire Live Lobby & Leaderboard to REST + WebSocket (guests join with display name)
- [ ] Wire Settings & Account screens to real API; remove/gate offline seed fallback
- [ ] Translate all UI copy (EN/MM) and load Myanmar web font (`Noto Sans Myanmar`)
