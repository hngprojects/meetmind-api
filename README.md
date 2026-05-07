# MeetMind Backend

AI-powered meeting intelligence platform. The backend manages users, workspaces, meetings, interviews, integrations, and an "Ask Mind" conversational Q&A layer over meeting transcripts.

---

## Stack

| Layer | Choice |
|---|---|
| Web framework | FastAPI (`fastapi[standard]`) |
| Server | Uvicorn (via `fastapi dev` / `fastapi run`) |
| ORM | SQLAlchemy 2.0 (async) |
| DB driver | `asyncpg` (Postgres) |
| Migrations | Alembic (async-aware) |
| Auth | JWT via `python-jose` + bcrypt password hashing |
| Config | `pydantic-settings` (reads `.env`) |
| Package manager | `uv` |
| Tests | `pytest` + `pytest-asyncio` + `httpx.AsyncClient` |
| Python | 3.13+ |

---

## Project structure

```
meetmind-be/
├── app/
│   ├── main.py                        # FastAPI app, global exception handlers
│   ├── core/
│   │   ├── config.py                  # Settings loaded from .env
│   │   ├── exceptions.py              # Domain exception hierarchy
│   │   └── responses.py               # Standardized response envelope (success / error)
│   ├── api/
│   │   ├── deps.py                    # Shared dependencies: DBSession, CurrentUser
│   │   └── v1/
│   │       ├── router.py              # Aggregates all v1 domain routers
│   │       └── routes/
│   │           ├── health.py          # GET /health
│   │           ├── auth.py            # POST /auth/signup, /verify-email, /resend-verification
│   │           ├── users.py           # (stub) /users/*
│   │           ├── workspaces.py      # (stub) /workspaces/*
│   │           ├── meetings.py        # (stub) /meetings/*
│   │           ├── interviews.py      # (stub) /interviews/*
│   │           ├── integrations.py    # (stub) /integrations/*
│   │           └── ask_mind.py        # (stub) /ask-mind/*
│   ├── db/
│   │   └── session.py                 # Async engine + session factory + get_session()
│   ├── models/
│   │   ├── base.py                    # DeclarativeBase, UUIDPrimaryKey (v7), TimestampMixin
│   │   ├── user.py                    # User, RefreshToken, SSOProvider, ActiveSession, preferences...
│   │   ├── workspace.py               # Workspace, WorkspaceMember, WorkspaceInvite
│   │   ├── meeting.py                 # Meeting, MeetingParticipant, MeetingComment
│   │   ├── transcript.py              # Transcript, TranscriptSegment, MeetingSummary, ActionItem...
│   │   ├── interview.py               # Candidate, Interview, InterviewTranscript, InterviewSummary...
│   │   ├── scorecard.py               # ScorecardCategory, InterviewScorecard, ScorecardScore...
│   │   ├── integration.py             # UserPlatformIntegration, Integration, IntegrationChannel...
│   │   ├── email_verification.py      # EmailVerificationToken
│   │   └── ask_mind.py                # AskMindSession, AskMindMessage, AskMindSuggestedPrompt
│   ├── schemas/
│   │   ├── auth.py                    # SignupRequest
│   │   └── verification.py            # VerifyEmailRequest, ResendVerificationRequest
│   └── services/
│       ├── auth.py                    # AuthService: hashing, user creation, JWT issuance
│       └── verification_service.py    # VerificationService: token lifecycle
├── alembic/
│   ├── env.py                         # Wired to app.models.Base.metadata + settings
│   └── versions/                      # Migration files
├── tests/
│   ├── conftest.py                    # In-memory SQLite test DB, AsyncClient fixture
│   ├── test_auth.py
│   ├── test_health.py
│   ├── test_models.py
│   ├── test_verification.py
│   └── test_verification_api.py
├── docs/
│   └── architecture/
│       └── system-overview.md         # Mermaid architecture diagram
├── .env.example
├── alembic.ini
├── pyproject.toml
└── uv.lock
```

### Why this layout

- **`core/responses.py`** — single envelope for every response in the codebase. Clients always get `{success, message, data}` or `{success, message, error}`. No surprises.
- **`api/deps.py`** — all shared FastAPI dependencies live here. Routes import `DBSession` and `CurrentUser` from one place.
- **`models` / `schemas` / `services` split** — DB shape, API shape, and business logic stay decoupled. They diverge sooner than you'd think.
- **`db/session.py` separate from `models/`** — engine setup is infrastructure; models are domain.
- **UUID v7 primary keys** — time-ordered, so rows sort by insertion order naturally and index locality is preserved.

---

## Getting started

### 1. Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- A running Postgres instance (local, Docker, or Supabase)

### 2. Install

```bash
uv sync
```

### 3. Configure

```bash
cp .env.example .env
```

Fill in `.env`:

```env
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/dbname

JWT_SECRET=<generate: python3 -c "import secrets; print(secrets.token_hex(32))">
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_MINUTES=10080
```

`pydantic-settings` will fail loudly at startup if any required key is missing.

### 4. Run migrations

```bash
uv run alembic upgrade head
```

### 5. Start the dev server

```bash
uv run fastapi dev app/main.py
```

- Root → `http://127.0.0.1:8000`
- Health → `http://127.0.0.1:8000/api/v1/health`
- Swagger UI → `http://127.0.0.1:8000/docs`
- ReDoc → `http://127.0.0.1:8000/redoc`

---

## API overview

All responses use a standardized envelope defined in `app/core/responses.py`.

**Success**
```json
{ "success": true, "message": "...", "data": {}, "meta": null }
```

**Error**
```json
{ "success": false, "message": "...", "error": { "code": "snake_case_code", "details": null } }
```

### Live endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/` | No | Root liveness check |
| `GET` | `/api/v1/health` | No | DB connectivity probe |
| `POST` | `/api/v1/auth/signup` | No | Register user, issue JWT + refresh token |
| `POST` | `/api/v1/auth/verify-email` | No | Redeem single-use email verification token |
| `POST` | `/api/v1/auth/resend-verification` | No | Issue a fresh verification token |

### Stub routers (registered, no endpoints yet)

`/api/v1/users`, `/api/v1/workspaces`, `/api/v1/meetings`, `/api/v1/interviews`, `/api/v1/integrations`, `/api/v1/ask-mind`

---

## Authentication

### How tokens are issued

`POST /api/v1/auth/signup` returns both tokens in the response body and sets them as `httponly; secure; samesite=lax` cookies:

```json
{
  "success": true,
  "data": {
    "id": "...",
    "email": "user@example.com",
    "access_token": "<jwt>",
    "refresh_token": "<opaque>"
  }
}
```

The access token is a signed JWT (HS256). The refresh token is an opaque random string — only its SHA-256 hash is stored in the database.

### How to protect a route

Import `CurrentUser` from `app.api.deps` and add it to the route signature. FastAPI resolves it automatically — no decorator, no middleware.

```python
from app.api.deps import CurrentUser
from app.core.responses import success

@router.get("/me")
async def get_me(user: CurrentUser):
    return success({"id": str(user.id), "email": user.email})
```

`CurrentUser` is defined as:

```python
CurrentUser = Annotated[User, Depends(get_current_user)]
```

`get_current_user` accepts the token from either:
- The `access_token` httponly cookie (sent automatically by the browser after login)
- An `Authorization: Bearer <token>` header (for API clients / Postman)

Cookie takes priority. If neither is present or the token is invalid/expired, it raises a `401` error envelope automatically.

### Public vs protected at a glance

```python
# Public — no auth dependency
@router.get("/health")
async def health(db: DBSession): ...

# Protected — 401 if token missing or invalid
@router.get("/me")
async def get_me(user: CurrentUser): ...

# Protected + DB access
@router.get("/profile")
async def get_profile(user: CurrentUser, db: DBSession): ...
```

### Adding extra guards

Layer additional dependencies if needed:

```python
async def require_verified(user: CurrentUser) -> User:
    if not user.is_verified:
        raise APIError("Email not verified", status_code=403, code="unverified")
    return user

VerifiedUser = Annotated[User, Depends(require_verified)]
```

---

## Running tests

Tests use an in-memory SQLite database — no external DB needed.

```bash
uv run pytest
```

`pytest-asyncio` is set to `auto` mode so async tests need no decorator. The `conftest.py` wires up an `AsyncClient` via `ASGITransport` and overrides the `get_session` dependency with a test-scoped SQLite session.

---

## Migrations workflow

### Current migration chain

```
cacd5554ba5a  create all tables (base)
├── d44e91e81013  add refresh token table
│   └── 8d114ef61fcc  make refresh token datetimes timezone-aware
├── a8cbb47717b3  add refresh_token_hash to active_sessions
│   └── 864df66fbeb7  add unique constraint on refresh_token_hash
└── 64a8c4b4d071  add email verification tokens table
5b25f8695307  merge all heads
7ba4c8acd02e  sync schema with models (is_verified + missing timestamps)
2cdac93874a4  make email_verification_token datetimes timezone-aware  ← HEAD
```

### Typical cycle

```bash
# 1. Edit a model in app/models/
# 2. Generate a migration
uv run alembic revision --autogenerate -m "describe the change"
# 3. Review the generated file carefully before applying
# 4. Apply
uv run alembic upgrade head
```

### Important: add new models to `app/models/__init__.py`

Alembic discovers models by importing them. If a model file is not imported in `__init__.py`, Alembic won't see it and will either miss the table entirely or, worse, detect it as a table to drop.

```python
# app/models/__init__.py — every model must be listed here
from app.models.my_new_model import MyNewModel
```

### Gotchas encountered in this project

**Multiple heads** — branched migrations leave Alembic with multiple `HEAD` revisions. Before running `upgrade head`, merge them first:
```bash
uv run alembic merge heads -m "merge all heads"
uv run alembic upgrade head
```

**Duplicate columns in branched migrations** — if two branches both autogenerated against the same base, they'll each try to add the same columns. Remove the duplicates from the later branch manually before applying.

**`NOT NULL` column on existing rows** — autogenerate emits `nullable=False` without a server default, which fails if the table has data. Add `server_default` to the migration:
```python
# Before applying, change this:
op.add_column('users', sa.Column('is_verified', sa.Boolean(), nullable=False))
# To this:
op.add_column('users', sa.Column('is_verified', sa.Boolean(), server_default=sa.text('false'), nullable=False))
```

**Timezone mismatch** — `DateTime` columns (naive) reject timezone-aware datetimes from Python. Use `DateTime(timezone=True)` on any column that stores a UTC timestamp, and regenerate the migration.

### Useful commands

| Command | What it does |
|---|---|
| `alembic upgrade head` | Apply all pending migrations |
| `alembic downgrade -1` | Roll back one migration |
| `alembic current` | Show applied revision |
| `alembic history` | Full migration chain |
| `alembic merge heads -m "msg"` | Merge diverged heads into one |
| `alembic downgrade base` | Wipe everything (dev only) |

### Rules

- Always **review** the autogenerated file before applying — Alembic misses enum changes, some index renames, and server-side defaults.
- **Never edit** a migration that has been applied to a shared environment. Write a new one.
- Run `alembic upgrade head` **during deploy**, not at app startup.

---

## Adding new code

### New endpoint

1. Add route handlers to the relevant file in `app/api/v1/routes/`
2. Import and register in `app/api/v1/router.py` if it's a new domain (already done for existing stubs)

### New model

1. Create or extend a file in `app/models/`
2. Subclass `Base` (+ `UUIDPrimaryKey`, `TimestampMixin` as needed)
3. Import the model in `app/models/__init__.py` so Alembic discovers it
4. Generate and apply a migration

### New schema

Add Pydantic request/response models to `app/schemas/`. Keep them separate from ORM models — the API shape and DB shape diverge quickly.

### New business logic

Add it to `app/services/`. Routes should stay thin: validate input → call service → return envelope.

### New setting

Add the field to `Settings` in `app/core/config.py` and to `.env.example`. The app fails loudly at startup if the value is missing.

---

## Conventions

- **Absolute imports only** (`from app.core.config import settings`), never relative.
- **Type hints everywhere** — FastAPI uses them for validation and OpenAPI generation.
- **Routes return `success()` / `paginated()`**, never raw dicts or ORM objects.
- **Raise `APIError`** for all domain errors — the global handler converts them to the error envelope.
- **`async def` for anything that touches I/O** (DB, HTTP, files). Sync `def` is fine for pure CPU work.

---

## Production checklist

- Replace `fastapi dev` with `fastapi run` (or `uvicorn app.main:app --workers N`)
- Run `alembic upgrade head` as a deploy step before new instances boot
- Configure DB pool size to match your worker count
- Add CORS and request logging middleware in `app/main.py`
- Store secrets in your platform's secret manager, not in `.env` files
