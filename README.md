<div align="center">

# ⚡ QuizClash — Backend API

**FastAPI backend powering document parsing, rule-based & AI quiz generation, real-time multiplayer rooms, bilingual PDF/Word exports, and secure cookie-based authentication.**

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00?style=flat-square&logo=sqlalchemy&logoColor=white)](https://www.sqlalchemy.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](./LICENSE)

</div>

---

## ✨ Key Features

- **Multi-Format Document Parsing** — Ingests `.csv`, `.txt`, `.pdf` (`pypdf`), and `.docx` (`python-docx`) study files with size and content validation.
- **Rule-Based & AI Quiz Generation** — Generates multiple-choice questions deterministically from term-definition pairs, or via optional **Gemini LLM** generation (`use_llm=true`) with built-in rate limiting.
- **Quiz & Attempt Management** — Create, preview, edit, and delete quizzes; serve answer-stripped playable quizzes; grade submitted attempts server-side; and track full attempt history.
- **Bilingual PDF & Word Exports** — Export `questions` worksheets and `answers` keys as **PDF** (ReportLab + WeasyPrint with Pango/HarfBuzz shaping for Myanmar script) or **Word (`.docx`)** in English (`en`) and Myanmar (`mm`).
- **Real-Time Live Multiplayer** — WebSocket-driven live rooms (`/api/v1/live/rooms/{pin}/ws`) with 6-digit PINs, player lobbies, ready states, round progression, live scoring, and match history.
- **Authentication & Security** — Argon2 password hashing, HTTP-only JWT access/refresh cookies, CSRF origin validation middleware, per-route rate limiting, email OTP verification & password reset (SMTP or dev console mailer), and **Google OAuth 2.0 (PKCE)**.
- **User Settings & Admin API** — Per-user preferences, full JSON account data export, account reset, and admin-only moderation and platform statistics endpoints.

---

## 🛠️ Tech Stack

| Layer | Technologies |
| :--- | :--- |
| **Web Framework** | FastAPI, Uvicorn |
| **Database & Migrations** | PostgreSQL 16, SQLAlchemy 2.0, Alembic |
| **Validation & Config** | Pydantic v2, Pydantic Settings |
| **Auth & Security** | Argon2 (`argon2-cffi`), PyJWT, CSRF Origin Middleware, Google OAuth 2.0 |
| **Parsing & Exports** | `pypdf`, `python-docx`, `reportlab`, `weasyprint` |
| **Testing** | Pytest, Pytest-Asyncio, HTTPX |
| **Containerization** | Multi-stage Docker (`python:3.12-slim`), Docker Compose |

---

## 🚀 Quick Start

### Option A: Docker Compose (Recommended)

Spins up PostgreSQL 16 and the FastAPI server with automatic Alembic migrations and live reload:

```bash
# 1. Create environment configuration
cp .env.example .env

# 2. Start database and API
docker compose up --build
```

The API will be available at `http://localhost:8000`.

### Option B: Local Python Setup

#### Prerequisites

- **Python 3.10+** (3.12 recommended)
- **PostgreSQL 14+**

```bash
# 1. Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment variables
cp .env.example .env
# Update DATABASE_URL and SECRET_KEY in .env

# 4. Create the database and run migrations
createdb quizclash
alembic upgrade head

# 5. Start the development server
uvicorn app.main:app --reload --port 8000
```

### Interactive API Docs

Once running, explore the OpenAPI documentation at:

- **Swagger UI:** [`http://localhost:8000/docs`](http://localhost:8000/docs)
- **ReDoc:** [`http://localhost:8000/redoc`](http://localhost:8000/redoc)

---

## ⚙️ Environment Variables

Copy [`.env.example`](./.env.example) to `.env` and configure as needed:

| Category | Key Variables | Notes |
| :--- | :--- | :--- |
| **Core & DB** | `ENVIRONMENT`, `DATABASE_URL`, `FRONTEND_ORIGINS`, `APP_BASE_URL` | `ENVIRONMENT` accepts `development`, `staging`, or `production` |
| **Auth & Cookies** | `SECRET_KEY`, `COOKIE_SECURE`, `COOKIE_SAMESITE`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS` | Use a strong random `SECRET_KEY` and `COOKIE_SECURE=true` in production |
| **Google OAuth** | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `OAUTH_REDIRECT_BASE_URL` | Optional; enables *Continue with Google* when both client vars are set |
| **Seed Accounts** | `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `DEMO_USER_EMAIL`, `DEMO_USER_PASSWORD` | Optional; auto-seeded on startup if configured |
| **SMTP Mailer** | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, `SMTP_USE_TLS` | Optional; falls back to printing verification/reset links to console in dev |
| **Uploads & Quizzes** | `MAX_UPLOAD_SIZE_MB`, `DEFAULT_QUESTIONS_PER_QUIZ`, `MIN_DEFINITIONS_FOR_GENERATION` | Defaults: `10` MB, `10` questions, `8` minimum pairs |
| **AI / LLM** | `LLM_API_KEY`, `LLM_MODEL`, `LLM_MAX_TOKENS`, `RATE_LIMIT_LLM_MAX_REQUESTS` | Optional Gemini API settings for `use_llm=true` |

---

## 📡 API Endpoints

All endpoints are prefixed with `/api/v1` unless noted otherwise.

<details open>
<summary><strong>Health & Meta</strong></summary>

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/` | Root API metadata and doc links |
| `GET` | `/api/v1/health` | Service health check |

</details>

<details open>
<summary><strong>Authentication & OAuth (<code>/api/v1/auth</code>)</strong></summary>

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/auth/register` | Register a new account and send verification OTP |
| `POST` | `/auth/login` | Authenticate and set HTTP-only JWT cookies |
| `POST` | `/auth/verify-email` | Verify email address with OTP |
| `POST` | `/auth/resend-verification` | Resend verification email |
| `POST` | `/auth/refresh` | Refresh access token cookie |
| `POST` | `/auth/logout` | Clear auth cookies |
| `GET` | `/auth/me` | Get current authenticated user profile |
| `POST` | `/auth/forgot-password` | Request password reset email |
| `POST` | `/auth/reset-password` | Complete password reset with token |
| `POST` | `/auth/change-password` | Change password for authenticated user |
| `GET` | `/auth/oauth/providers` | List enabled OAuth providers |
| `GET` | `/auth/oauth/google/start` | Start Google OAuth 2.0 PKCE flow |
| `GET` | `/auth/oauth/google/callback` | Handle Google OAuth callback |
| `DELETE` | `/auth/oauth/google` | Unlink Google account |

</details>

<details open>
<summary><strong>Quizzes, Attempts & Exports</strong></summary>

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/quizzes` | List user's saved quizzes |
| `POST` | `/quizzes` | Upload study file (`.csv`, `.txt`, `.pdf`, `.docx`) and generate quiz |
| `GET` | `/quizzes/{quiz_id}` | Get playable quiz (correct answers hidden) |
| `GET` | `/quizzes/{quiz_id}/preview` | Get full quiz with answers for review & editing |
| `PATCH` | `/quizzes/{quiz_id}` | Update quiz title, questions, or choices |
| `DELETE` | `/quizzes/{quiz_id}` | Delete a quiz |
| `GET` | `/quizzes/{quiz_id}/exports` | Export quiz (`?kind=questions\|answers&format=pdf\|word&lang=en\|mm`) |
| `GET` | `/attempts` | List user's attempt history |
| `POST` | `/quizzes/{quiz_id}/attempts` | Submit answers and receive graded results |
| `GET` | `/attempts/{attempt_id}` | Get detailed attempt results |
| `DELETE` | `/attempts/{attempt_id}` | Delete a single attempt (`DELETE /attempts` clears all) |

</details>

<details>
<summary><strong>Live Multiplayer (<code>/api/v1/live</code>)</strong></summary>

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/live/rooms` | Host a new live game room |
| `GET` | `/live/rooms/{pin}` | Fetch current room state |
| `POST` | `/live/rooms/{pin}/join` | Join a room by PIN |
| `POST` | `/live/rooms/{pin}/players/{player_id}/ready` | Toggle player ready status |
| `DELETE` | `/live/rooms/{pin}/players/{player_id}` | Leave or remove player from room |
| `POST` | `/live/rooms/{pin}/next` | Advance room to the next question/phase |
| `DELETE` | `/live/rooms/{pin}` | Close an active room |
| `WS` | `/live/rooms/{pin}/ws` | Real-time WebSocket stream for gameplay & leaderboard |
| `GET` | `/live/history` | List completed live game sessions |
| `DELETE` | `/live/history/{room_id}` | Delete a live game history record |

</details>

<details>
<summary><strong>Settings, Account & Admin</strong></summary>

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` / `PATCH` | `/settings` | Retrieve or update user preferences |
| `GET` | `/account/export` | Export all user data as JSON |
| `DELETE` | `/account` | Reset or delete user account data |
| `GET` / `PATCH` / `DELETE` | `/admin/users`, `/admin/users/{user_id}` | Admin user management |
| `GET` / `DELETE` | `/admin/quizzes`, `/admin/quizzes/{quiz_id}` | Admin quiz moderation |
| `GET` | `/admin/stats` | Platform-wide usage statistics |

</details>

---

## 📄 Supported Study File Formats

| Format | Expected Structure |
| :--- | :--- |
| **CSV (`.csv`)** | UTF-8 `term,definition` columns (optional header row) |
| **Text (`.txt`)** | `term: definition`, `term - definition`, `term = definition`, or one term per line |
| **PDF (`.pdf`)** | Text-based PDF documents extracted via `pypdf` |
| **Word (`.docx`)** | Paragraphs and tables extracted via `python-docx` |

---

## 📁 Project Structure

```text
quiz_clash_backend/
├── alembic/                       # Database migration environment & versions
├── app/
│   ├── api/routes/                # Route handlers (auth, admin, quizzes, attempts, exports, live, settings)
│   ├── assets/fonts/              # Bundled fonts for English & Myanmar PDF rendering
│   ├── core/                      # Config, security, CSRF, rate limiting, language & error helpers
│   ├── db/                        # SQLAlchemy models & session management
│   ├── schemas/                   # Pydantic request/response schemas
│   ├── services/                  # Parsers, quiz/LLM generators, PDF/DOCX exporters, mailer, OAuth, live manager
│   └── main.py                    # FastAPI app factory, middleware & lifespan hooks
├── docs/                          # API data contracts, DBML schema & roadmap
├── tests/                         # Pytest integration & feature test suite
├── Dockerfile                     # Multi-stage production container (with WeasyPrint/Pango libs)
├── Dockerfile.dev                 # Development container
├── docker-compose.yml             # PostgreSQL 16 + API local stack
├── alembic.ini
├── requirements.txt
└── .env.example
```

---

## 🧪 Testing & Database Migrations

```bash
# Run the full test suite
pytest

# Create a new Alembic migration after model changes
alembic revision --autogenerate -m "describe_change"

# Apply all pending migrations
alembic upgrade head
```

---

## 🐳 Production Deployment

The included [`Dockerfile`](./Dockerfile) uses a multi-stage `python:3.12-slim` build, installs the native Pango/Cairo/HarfBuzz libraries required by WeasyPrint for Myanmar script shaping, runs as a non-root user (`appuser`), and automatically runs `alembic upgrade head` before starting Uvicorn with `--proxy-headers`.

```bash
docker build -t quizclash-api .
docker run -p 8000:8000 --env-file .env quizclash-api
```

> **Production Safety Check:** On startup, `validate_production_settings()` fails fast if `ENVIRONMENT=production` is paired with insecure defaults (such as a weak `SECRET_KEY` or `COOKIE_SECURE=false`).

### Creating an Admin Account in Production (Render / AWS / Docker)

There are three ways to provision an admin account in a deployed environment:

1. **Environment Variables on Startup (works on Render Free/Paid, AWS, Docker):**
   - **New admin account:** Set `ADMIN_EMAIL`, `ADMIN_PASSWORD`, and optionally `ADMIN_DISPLAY_NAME` in your host's environment variables, then deploy/restart.
   - **Promote an existing user (including Google OAuth accounts):** Set `ADMIN_EMAIL` (no `ADMIN_PASSWORD` needed) and redeploy/restart. The existing account is promoted to `admin`, activated, and verified without changing its password.
   - **Security tip:** After verifying you can log in and access `/api/v1/admin/stats`, remove `ADMIN_PASSWORD` (and optionally `ADMIN_EMAIL`) from your environment variables.

2. **Admin CLI Tool (works on AWS EC2/Docker, Render Paid Shell, or locally — no password in env vars):**
   ```bash
   # Create a new admin (prompts securely for password if --password is omitted)
   python -m app.cli create-admin --email admin@example.com --display-name "Admin"

   # Promote an existing user (e.g. Google OAuth or registered user) to admin
   python -m app.cli promote-admin --email user@example.com

   # List all current admin accounts
   python -m app.cli list-admins
   ```
   On Docker / AWS EC2 with Docker Compose:
   ```bash
   docker compose exec api python -m app.cli create-admin --email admin@example.com
   ```

3. **Promote Additional Admins via API:**
   Once logged in as an admin, promote any other user with `PATCH /api/v1/admin/users/{user_id}` and body `{"role": "admin"}`.

---

## 📄 License

MIT
