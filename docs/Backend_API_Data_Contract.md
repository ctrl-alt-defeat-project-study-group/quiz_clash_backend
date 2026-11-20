# QuizClash Backend — API & Frontend Data Contract

This document defines every API endpoint, request payload, response schema, and error format required by the QuizClash React frontend (`src/services/api.ts`, `src/types/quiz.ts`, `src/context/AppContext.tsx`).

---

## 1. Base URL & Request Headers

- **Base URL:** `http://localhost:8000/api/v1` (configured via `VITE_API_BASE_URL` in `.env`)
- **Language Header:** Every API request may include:
  - `Accept-Language: en` (English) or `Accept-Language: my` (Myanmar)
  - For file uploads (`POST /quizzes`), `language` (`"en"` | `"mm"`) is also sent in `FormData`.
  - For exports (`GET /quizzes/{id}/exports`), `lang` (`"en"` | `"mm"`) is also sent as a query parameter.
- **Myanmar Unicode Note:** Any generated PDF or Word document containing Myanmar text should embed a Unicode Myanmar font (e.g., *Noto Sans Myanmar*).

---

## 2. Standard Error Response Contract (Hybrid `code` + HTTP Status)

The frontend translates UI and error messages locally (`src/i18n/errors.ts`) based on the active UK/MM toggle (`uiLanguage`).

### Recommended FastAPI Error Format
Return the appropriate HTTP status code (`400`, `401`, `403`, `404`, `413`, `422`, `429`, `500`, `503`) with a structured `detail` object containing a machine-readable `code` and an English `message` (for logs/debugging):

```json
{
  "detail": {
    "code": "UNSUPPORTED_FILE_TYPE",
    "message": "Only CSV, TXT, PDF, and DOCX files are supported."
  }
}
```

```python
from fastapi import HTTPException

raise HTTPException(
    status_code=400,
    detail={
        "code": "UNSUPPORTED_FILE_TYPE",
        "message": "Only CSV, TXT, PDF, and DOCX files are supported."
    }
)
```

### Frontend Fallback Order (`src/services/api.ts` → `src/i18n/errors.ts`)
1. `detail.code` (matches frontend EN/MM dictionary — **preferred**)
2. `detail.message_en` / `detail.message_mm` (optional backend-supplied bilingual messages)
3. HTTP status code (`400`, `401`, `403`, `404`, `408`, `413`, `422`, `429`, `500`, `503`)
4. Generic localized fallback (`UNKNOWN_ERROR`)

### Supported Error Codes

| Error Code | Typical HTTP Status | When to Return |
| :--- | :--- | :--- |
| `INVALID_ROOM_PIN` | `400` | Room PIN format is invalid |
| `ROOM_NOT_FOUND` | `404` | No active live game room matches the PIN |
| `QUIZ_NOT_FOUND` | `404` | Quiz ID does not exist |
| `ATTEMPT_NOT_FOUND` | `404` | Attempt ID does not exist |
| `UNSUPPORTED_FILE_TYPE` | `400` | Uploaded file is not `.csv`, `.txt`, `.pdf`, or `.docx` |
| `FILE_TOO_LARGE` | `413` | Uploaded file exceeds max size limit |
| `EMPTY_FILE` | `400` | Uploaded file has no readable study text |
| `GENERATION_FAILED` | `500` | Quiz/LLM generation failed |
| `EXPORT_FAILED` | `500` | PDF/Word export generation failed |
| `VALIDATION_ERROR` | `422` | FastAPI/Pydantic request validation error |
| `UNAUTHORIZED` | `401` | Missing or expired auth credentials |
| `FORBIDDEN` | `403` | User does not have permission |
| `RATE_LIMITED` | `429` | Too many requests |
| `SERVER_ERROR` | `500` | Unhandled server exception |

---

## 3. Core Data Models Needed by Frontend

### 3.1 Health Check
- **Endpoint:** `GET /api/v1/health`
- **Response (`200 OK`):**
```json
{
  "status": "ok",
  "service": "quiz-clash-api"
}
```

---

### 3.2 Quizzes (Screens 01, 02, 03)

#### Create Quiz from Uploaded Study File
- **Endpoint:** `POST /api/v1/quizzes`
- **Content-Type:** `multipart/form-data`
- **Form Fields:**
  - `file` *(required)*: `.csv`, `.txt`, `.pdf`, or `.docx`
  - `title` *(optional, string)*: Quiz title (e.g. `"Cell structure"`)
  - `question_count` *(optional, integer)*: `5` | `10` | `15` | `20`
  - `use_llm` *(optional, boolean string)*: `"true"` | `"false"`
  - `language` *(optional, string)*: `"en"` | `"mm"`
- **Response (`201 Created` / `200 OK`) — `ApiQuizResponse`:**
```json
{
  "id": "quiz_1",
  "title": "Cell structure",
  "category": "Biology",
  "source_type": "csv",
  "source_filename": "Cell_Biology_Notes.csv",
  "status": "ready",
  "created_at": "2026-11-20T10:00:00Z",
  "updated_at": "2026-11-20T10:00:00Z",
  "questions": [
    {
      "id": "q_1",
      "prompt": "What is the primary function of the cell membrane?",
      "position": 0,
      "explanation": "The cell membrane is selectively permeable and regulates what enters and leaves the cell.",
      "choices": [
        { "id": "a", "text": "Produce energy for the cell", "position": 0, "is_correct": false },
        { "id": "b", "text": "Regulate movement of substances", "position": 1, "is_correct": true },
        { "id": "c", "text": "Synthesize proteins", "position": 2, "is_correct": false },
        { "id": "d", "text": "Store genetic information", "position": 3, "is_correct": false }
      ]
    }
  ]
}
```

#### List Saved Quizzes (Dashboard & Sidebar Library)
- **Endpoint:** `GET /api/v1/quizzes`
- **Response (`200 OK`):** Array of quiz summary/detail objects including `id`, `title`, `category`, `source_filename`, `question_count`, `last_score`, `updated_at`.

#### Get Quiz / Preview Quiz
- **Endpoints:**
  - `GET /api/v1/quizzes/{quiz_id}` (for solo play; `is_correct` may be omitted)
  - `GET /api/v1/quizzes/{quiz_id}/preview` (for review & editing; **must include** `is_correct` and `explanation`)
- **Response (`200 OK`):** `ApiQuizResponse`

#### Update Quiz Questions
- **Endpoint:** `PATCH /api/v1/quizzes/{quiz_id}`
- **Content-Type:** `application/json`
- **Request Body:**
```json
{
  "title": "Cell structure",
  "source_type": "csv",
  "questions": [
    {
      "prompt": "What is the primary function of the cell membrane?",
      "position": 0,
      "explanation": "Optional updated explanation",
      "choices": [
        { "text": "Produce energy for the cell", "position": 0, "is_correct": false },
        { "text": "Regulate movement of substances", "position": 1, "is_correct": true },
        { "text": "Synthesize proteins", "position": 2, "is_correct": false },
        { "text": "Store genetic information", "position": 3, "is_correct": false }
      ]
    }
  ]
}
```
- **Response (`200 OK`):** Updated `ApiQuizResponse`

---

### 3.3 Study Sheet Exports (Screen 03 & Screen 05)
- **Endpoint:** `GET /api/v1/quizzes/{quiz_id}/exports?kind=questions|answers&format=pdf|word&lang=en|mm`
- **Query Parameters:**
  - `kind`: `"questions"` (blank study sheet) or `"answers"` (answer key)
  - `format` *(optional, default `"pdf"`)*: `"pdf"` | `"word"`
  - `lang` *(optional, default `"en"`)*: `"en"` | `"mm"`
- **Response (`200 OK`):** Binary file stream (`application/pdf` or `.docx` MIME type) with `Content-Disposition: attachment; filename="quiz_questions_Cell_structure.pdf"`.

---

### 3.4 Solo Practice & Attempt History (Screens 04 & 05)

#### Submit Solo Quiz Attempt
- **Endpoint:** `POST /api/v1/quizzes/{quiz_id}/attempts`
- **Request Body:**
```json
{
  "duration_seconds": 185,
  "answers": [
    { "question_id": "q_1", "choice_id": "b" },
    { "question_id": "q_2", "choice_id": "a" }
  ]
}
```
- **Response (`201 Created` / `200 OK`) — `ApiAttemptResponse`:**
```json
{
  "id": "att_101",
  "quiz_id": "quiz_1",
  "quiz_title": "Cell structure",
  "score": 8,
  "total_questions": 10,
  "percentage": 80,
  "duration_seconds": 185,
  "completed_at": "2026-11-20T10:15:00Z",
  "questions": [
    {
      "question_id": "q_1",
      "question_prompt": "What is the primary function of the cell membrane?",
      "selected_choice_id": "b",
      "selected_choice_text": "Regulate movement of substances",
      "correct_choice_id": "b",
      "correct_choice_text": "Regulate movement of substances",
      "explanation": "The cell membrane is selectively permeable...",
      "is_correct": true
    }
  ]
}
```

#### List / Get Attempt History
- **Endpoints:**
  - `GET /api/v1/attempts` (returns attempt list for Dashboard stats & Screen 05 table)
  - `GET /api/v1/attempts/{attempt_id}` (returns detailed `ApiAttemptResponse` with missed questions)

---

### 3.5 Live Game Lobby & Leaderboard (Screens 06 & 07)
Currently simulated locally in `AppContext.tsx` (`LiveGameState`). When connecting live multiplayer to the backend (REST + WebSocket):

#### Room State Schema (`LiveGameState`)
```json
{
  "pin": "482 619",
  "quiz_id": "quiz_1",
  "timer_seconds": 20,
  "round": 3,
  "total_rounds": 10,
  "status": "lobby",
  "players": [
    {
      "id": "player_1",
      "name": "Maya",
      "status": "Ready",
      "correct": 3,
      "total": 3,
      "points": 2450
    }
  ]
}
```
- **Suggested Endpoints:**
  - `POST /api/v1/live/rooms` — Create a room for `quiz_id` and `timer_seconds`, returns `pin` & initial room state.
  - `POST /api/v1/live/rooms/{pin}/join` — Join with `{ "display_name": "Alex M." }`. Returns `404` (`ROOM_NOT_FOUND`) or `400` (`INVALID_ROOM_PIN`).
  - `POST /api/v1/live/rooms/{pin}/next` — Advance round / broadcast next question.
  - `WS /api/v1/live/rooms/{pin}/ws` — Real-time player join, answer submission, and leaderboard updates.

---

### 3.6 User Profile & Settings (Screen 08)
Currently persisted in `localStorage` (`STORAGE_KEY = 'quiz-clash-react-v2-state'`). When connecting user accounts:

#### Settings Schema
```json
{
  "display_name": "Alex M.",
  "email": "alex.m@example.com",
  "theme": "system",
  "ui_language": "en",
  "default_questions": 10,
  "difficulty": "Mixed",
  "quiz_language": "English",
  "shuffle_questions": true,
  "show_explanations": true,
  "study_reminders": false,
  "weekly_summary": true
}
```
- **Field Values:**
  - `theme`: `"light"` | `"dark"` | `"system"`
  - `ui_language`: `"en"` | `"mm"`
  - `default_questions`: `5` | `10` | `15` | `20`
  - `difficulty`: `"Mixed"` | `"Foundational"` | `"Advanced"`
- **Suggested Endpoints:**
  - `GET /api/v1/settings`
  - `PATCH /api/v1/settings`
  - `GET /api/v1/account/export` (JSON dump of quizzes, attempts, settings)
  - `DELETE /api/v1/account` (delete/reset workspace data)

---

## 4. Screen-to-Backend Data Summary

| Screen | Route | Backend Data Required |
| :--- | :--- | :--- |
| **01 Dashboard** | `/dashboard` | Quizzes list, Attempt history summary (total quizzes, completed attempts, average score) |
| **02 Generate Quiz** | `/generate` | `POST /quizzes` (file upload + title + question_count + language) |
| **03 Review & Export** | `/quizzes` | `GET /quizzes/{id}/preview`, `PATCH /quizzes/{id}`, `GET /quizzes/{id}/exports` |
| **04 Solo Quiz** | `/play` | `GET /quizzes/{id}`, `POST /quizzes/{id}/attempts` |
| **05 Results & History** | `/history` | `GET /attempts`, `GET /attempts/{id}`, `GET /quizzes/{id}/exports?kind=answers` |
| **06 Live Lobby** | `/lobby` | `POST /live/rooms`, `POST /live/rooms/{pin}/join`, `WS /live/rooms/{pin}/ws` |
| **07 Live Leaderboard** | `/leaderboard` | Live room standings & round progression (`WS` / `POST /live/rooms/{pin}/next`) |
| **08 Settings** | `/settings` | `GET/PATCH /settings`, `GET /account/export`, `DELETE /account` |


---

## 5. Auth, Roles, Email & Language Addendum

### 5.1 Language Code Convention
- **`mm` is the canonical code for Myanmar everywhere:** `Accept-Language: mm`, form field `language=mm`, and query parameter `lang=mm`.
- The backend also silently accepts `my` as an alias and normalizes it to `mm` (default `"en"`).

### 5.2 Authentication & Cookie Session
- Website authentication uses **httpOnly cookies** (short-lived access cookie + longer-lived refresh cookie, `HttpOnly`, `SameSite=Lax`, `Secure` in production).
- The frontend **must** pass `credentials: "include"` on all `fetch` requests.
- State-changing requests (`POST`, `PATCH`, `DELETE`) are CSRF-protected by validating the `Origin` header against `FRONTEND_ORIGINS`.
- **Roles:** `"user"` and `"admin"`.
  - Sign-up is open to anyone and always creates role `"user"`.
  - Only an `"admin"` can grant or revoke the `"admin"` role. The first admin is seeded from server environment variables (`ADMIN_EMAIL`, `ADMIN_PASSWORD`).
- **Guests:** Unauthenticated guests may join live rooms (`POST /api/v1/live/rooms/{pin}/join` + WebSocket) using a `display_name`. Creating quizzes, solo play, history, exports, and settings require an authenticated account.
- **Email verification:** Required before login. Unverified accounts receive `403` with `EMAIL_NOT_VERIFIED`.

### 5.3 Auth Endpoints

| Method | Endpoint | Auth | Notes |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/auth/register` | Public | `{ email, password, display_name }` → creates unverified `user`, sends verification email (`201`) |
| `POST` | `/api/v1/auth/verify-email` | Public | `{ token }` → marks email verified (`200`) |
| `POST` | `/api/v1/auth/resend-verification` | Public | `{ email }` → resends verification email (`200`) |
| `POST` | `/api/v1/auth/login` | Public | `{ email, password }` → sets httpOnly cookies, returns user profile (`200`) |
| `POST` | `/api/v1/auth/refresh` | Cookie | Rotates access/refresh cookies (`200`) |
| `POST` | `/api/v1/auth/logout` | Cookie | Clears auth cookies (`200`) |
| `GET` | `/api/v1/auth/me` | User | Returns `{ id, email, display_name, role, is_active, email_verified_at }` |
| `POST` | `/api/v1/auth/forgot-password` | Public | `{ email }` → sends one-time reset link (`200`) |
| `POST` | `/api/v1/auth/reset-password` | Public | `{ token, new_password }` → updates password (`200`) |

### 5.4 Admin Endpoints (Require `role == "admin"`)

| Method | Endpoint | Notes |
| :--- | :--- | :--- |
| `GET` | `/api/v1/admin/users` | List & search users (`?q=`) |
| `PATCH` | `/api/v1/admin/users/{id}` | Update `role` (`"user"` \| `"admin"`) and/or `is_active`; cannot demote/disable last active admin |
| `DELETE` | `/api/v1/admin/users/{id}` | Delete user; cannot delete last active admin |
| `GET` | `/api/v1/admin/quizzes` | List all quizzes across all users |
| `DELETE` | `/api/v1/admin/quizzes/{id}` | Delete any quiz |
| `GET` | `/api/v1/admin/stats` | Site summary counts (users, quizzes, attempts) |

### 5.5 Additional Auth Error Codes

| Error Code | Typical HTTP Status | When to Return |
| :--- | :--- | :--- |
| `INVALID_CREDENTIALS` | `401` | Email or password is incorrect |
| `EMAIL_ALREADY_EXISTS` | `409` | Email is already registered |
| `EMAIL_NOT_VERIFIED` | `403` | Login attempted before verifying email |
| `TOKEN_INVALID_OR_EXPIRED` | `400` | Verification or password-reset token is invalid or expired |
| `ACCOUNT_DISABLED` | `403` | User account has been deactivated by an admin |
