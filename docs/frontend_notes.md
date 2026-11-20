# Frontend Notes (so we don't need to re-scan the frontend)

Source: `../quiz_clash_frontend` (checked 2026-11-20). Update this file when the frontend changes.

## Stack
- React 19 + TypeScript 6 + Vite 8, Tailwind 4, shadcn/base-ui components, `react-router-dom` 7, `sweetalert2`, `lucide-react`/`@tabler/icons-react`.
- No state library: one `src/context/AppContext.tsx` (~21 KB) holds theme, language, quizzes, history, practice, live, settings, toast, modal.
- No test runner configured (scripts: `dev`, `build`, `lint`, `preview`).
- API base URL: `VITE_API_BASE_URL=http://localhost:8000/api/v1` (`.env`). Dev origin is the Vite default `http://localhost:5173` (already in backend CORS).

## Key files
| File | Purpose |
|---|---|
| `src/services/api.ts` | `fetch` client. `buildHeaders(language)` sends `Accept-Language`. Calls: `checkHealth`, `createQuizFromFile`, `getQuiz`, `getQuizPreview`, `updateQuiz`, `submitAttempt`, `getAttempt`, `getQuizExportUrl`, `downloadQuizPdf` |
| `src/types/quiz.ts` | API types (`ApiQuizResponse`, `ApiAttemptResponse`, ...) and workspace types (`QuizItem`, `AttemptRecord`, `LiveGameState`, `UserSettings`) |
| `src/i18n/errors.ts` | `ErrorCode` union + EN/MM message dictionary. Only errors are translated here |
| `src/components/common/LanguageSwitch.tsx` | The 🇬🇧/🇲🇲 toggle. `AppContext` holds `uiLanguage` (`'en' \| 'mm'`) |
| `src/data/seedData.ts` | Seed quizzes (Cell structure, World history, Chemistry basics) used as offline fallback |
| `src/App.tsx` | Routes (below) |
| `docs/` | `Frontend_Implementation_Tasks.md`, `Quiz_Clash_System_Design.md`, `db_&_flowcharts/database.md`, `project-flowchart.md`, `prototype/` |

## Routes / screens
| Screen | Routes |
|---|---|
| 01 Dashboard | `/dashboard` (`/`, `/s1`) |
| 02 Generate | `/generate`, `/upload` |
| 03 Review & Export | `/quizzes`, `/quizzes/:id`, `/quizzes/:id/preview`, `/quizzes/:id/export` |
| 04 Solo quiz | `/play`, `/quizzes/:id/play` |
| 05 Results & History | `/history`, `/results`, `/attempts/:id` |
| 06 Live Lobby | `/lobby`, `/rooms/:pin` |
| 07 Live Leaderboard | `/leaderboard` |
| 08 Settings | `/settings` (tabs: Profile, Quiz defaults, Notifications, Privacy & account) |
All routes sit under one `AppLayout` (sticky 64px header + fixed left sidebar). Unknown paths redirect to `/dashboard`.

## Current state vs. what we need (gaps)
- **Auth: none.** No login/register pages, no token, no `Authorization` header, no route guards, no admin screens. `UNAUTHORIZED`/`FORBIDDEN` exist only as error codes.
- **Language:** the toggle and error dictionary exist. Page text is not yet fully translated (no UI string dictionary). Myanmar font for the website is not set up.
- **API client lags the contract** (`docs/Backend_API_Data_Contract.md`): no `listQuizzes`, `listAttempts`, no live/settings/account calls, `submitAttempt` does not send `duration_seconds`, `downloadQuizPdf` hardcodes `.pdf` and does not send `format`, types lack `explanation`/`category`/`source_filename`/`updated_at`.
- **Offline fallback:** `AppContext` falls back to local seed data/generation when the backend is down. This must be removed or gated once the backend is the source of truth.
- **Upload:** UI accepts `.csv/.txt/.pdf/.docx`, but only CSV/TXT is actually sent to the backend today.
- **Live game and settings** are simulated locally (localStorage key `quiz-clash-react-v2-state`).

## Backend contract facts the frontend relies on
- IDs are strings: `quiz_N`, `q_N`, choice ids `a|b|c|d`, attempts `att_N`.
- Errors: `{"detail": {"code": "...", "message": "..."}}`. The frontend maps `code` to its own EN/MM text.
- Language: `Accept-Language: en|my` header; form field `language` and query `lang` use `en|mm`. (Header uses `my`, form/query use `mm`; handle both.)
- Export: `GET /quizzes/{id}/exports?kind=questions|answers&format=pdf|word&lang=en|mm`.
- Full endpoint list: see `Backend_API_Data_Contract.md` in this folder.

## DB design doc facts (frontend `docs/db_&_flowcharts/database.md`)
- `users(id, email unique, password_hash bcrypt/Argon2, created_at)`, `quizzes`, `questions`, `choices`, `attempts(user_id nullable in Phase 1)`, `attempt_answers`, `rooms(quiz_id, host_id, pin 6 chars, status lobby|active|finished|closed)`.
- Live rooms: in-memory `RoomSession` on the server with WebSockets, server-controlled round deadlines, scoring `Base_Points + Latency_Bonus`.
- Invariants: exactly 4 choices and 1 correct; `GET /quizzes/{id}` hides `is_correct`; grading is server-side only.


## Locked-in Auth & Language Decisions (2026-11-20)
- **Roles:** `user` and `admin`. Open sign-up creates `user`; only an `admin` can promote another user. First admin is seeded from env.
- **Session:** httpOnly cookies (access + refresh), `SameSite=Lax`, `Secure` in prod, CSRF `Origin` check. Frontend `fetch` must send `credentials: "include"`.
- **Email:** verification (login blocked until verified, `403 EMAIL_NOT_VERIFIED`) + password reset. No SMTP yet — dev uses console mailer; SMTP placeholders in `.env.example`.
- **Guests:** may join live rooms with display name only; solo play and quiz creation require login.
- **Language code:** `mm` is canonical everywhere (header, form, query); backend also accepts `my` as an alias.
- **Ownership:** backend-only edits here; frontend changes are tracked in the `Frontend handoff` section of `docs/roadmap.md`.
