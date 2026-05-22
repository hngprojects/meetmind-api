# LiveKit AI Interviewer — Integration Guide

> **Audience:** Frontend & backend engineers integrating the AI voice interviewer.
> **Last updated:** 2026-05-22

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [Environment Variables](#environment-variables)
5. [Backend Setup (FastAPI)](#backend-setup-fastapi)
6. [Frontend Setup (Next.js)](#frontend-setup-nextjs)
7. [Running the AI Agent](#running-the-ai-agent)
8. [End-to-End Flow](#end-to-end-flow)
9. [API Reference](#api-reference)
10. [Data Models](#data-models)
11. [Troubleshooting](#troubleshooting)

---

## Overview

MeetMind's AI Interviewer conducts first-round screening interviews via live voice calls. The system has three independently running components:

| Component | Tech | Port | Purpose |
|-----------|------|------|---------|
| **FastAPI Backend** | Python / Uvicorn | `8000` | REST API — token generation, interview config, result storage |
| **Next.js Frontend** | TypeScript / React | `3000` | Dashboard (create/view sessions) + interview call UI |
| **LiveKit Agent** | Python / LiveKit SDK | _(no HTTP port)_ | Connects to LiveKit Cloud, runs the real-time STT → LLM → TTS loop |

All three must be running simultaneously for a complete interview flow.

---

## Architecture

```
┌────────────────────────────────┐
│        Browser (port 3000)     │
│  Next.js frontend              │
│                                │
│  1. POST /api/token            │──── creates JWT via livekit-server-sdk
│     { sessionId, candidateName }│
│  2. Joins LiveKit room         │
└────────────┬───────────────────┘
             │ WebSocket (audio/video)
             ▼
┌────────────────────────────────┐
│     LiveKit Cloud              │
│  wss://meetmind-xxxx.          │
│       livekit.cloud            │
│                                │
│  Dispatches "job" to agent     │
│  when a participant joins      │
└────────────┬───────────────────┘
             │ WebSocket
             ▼
┌────────────────────────────────┐
│     Python Agent Worker        │
│  app.agent.interviewer         │
│                                │
│  3. GET  /api/v1/livekit/      │───► FastAPI (port 8000)
│         {session_id}/config    │     returns interview questions, rubric
│                                │
│  4. Runs live interview via    │
│     STT → LLM → TTS pipeline  │
│                                │
│  5. POST /api/v1/livekit/      │───► FastAPI (port 8000)
│         {session_id}/result    │     stores transcript + AI report
└────────────────────────────────┘
```

### Key Concept: Room Name = Session ID

The LiveKit **room name** is always the interview **session ID** (a cuid, e.g. `cmpgp042d0000sligmwl1zlm9`). This is how the agent knows which interview config to load and where to post results.

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.11+ | `winget install Python.Python.3` |
| uv | 0.2+ | `pip install uv` |
| Node.js | 20.x+ | `winget install OpenJS.Nodejs` |
| npm | 10.x+ | _(bundled with Node)_ |
| PostgreSQL | 15.x+ | Windows installer or `choco install postgresql` |
| Docker _(optional)_ | 24.x+ | Docker Desktop |

---

## Environment Variables

### Backend (`meetmind-api/.env`)

Copy `.env.example` to `.env` and fill in **at minimum** these LiveKit-related keys:

```dotenv
# ── LiveKit (required for AI interviewer) ───────────────────────
LIVEKIT_URL=wss://meetmind-xxxx.livekit.cloud
LIVEKIT_API_KEY=APIxxxxxxx
LIVEKIT_API_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# ── Gemini (optional — only needed for document embedding) ──────
GEMINI_API_KEY=

# ── Core (should already be set) ────────────────────────────────
DATABASE_URL=postgresql+asyncpg://meetmind_user:meetmind_password@localhost:5432/meetmind
FRONTEND_URL=http://localhost:3000
```

> **Important:** The backend uses `postgresql+asyncpg://` as the driver prefix (SQLAlchemy async). The frontend uses plain `postgresql://` (Prisma).

### Frontend (`ai-interviewer/web/.env.local`)

Create a `.env.local` file in the frontend's `web/` directory:

```dotenv
# ── LiveKit (same credentials as the backend) ──────────────────
LIVEKIT_URL=wss://meetmind-xxxx.livekit.cloud
LIVEKIT_API_KEY=APIxxxxxxx
LIVEKIT_API_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# ── Database (Prisma — plain postgres, no asyncpg prefix) ──────
DATABASE_URL=postgresql://meetmind_user:meetmind_password@localhost:5432/meetmind
```

> **Why does the frontend need LiveKit credentials?**
> The frontend's `/api/token` Next.js route handler generates JWT tokens server-side using `livekit-server-sdk`. These credentials never reach the browser.

### Agent Worker Environment

The agent reads its LiveKit credentials from the **same `.env`** as the backend (it loads `meetmind-api/.env` via `python-dotenv`). No extra config file is needed.

The agent also reads these optional env vars to customize the AI models:

| Variable | Default | Purpose |
|----------|---------|---------|
| `INTERVIEWER_STT` | `deepgram/nova-3` | Speech-to-text model (LiveKit Inference) |
| `INTERVIEWER_LLM` | `openai/gpt-5.2-chat-latest` | Language model for the interviewer |
| `INTERVIEWER_TTS` | `cartesia/sonic-3` | Text-to-speech model |
| `INTERVIEWER_TTS_VOICE` | `9626c31c-...` | TTS voice ID |
| `WEB_BASE_URL` | `http://localhost:8000` | Where the agent fetches config / posts results |

---

## Backend Setup (FastAPI)

```powershell
cd meetmind-api

# 1. Create venv & install dependencies
uv venv
uv sync

# 2. Copy and edit .env
cp .env.example .env
# Fill in LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET

# 3. Run database migrations
uv run alembic upgrade head

# 4. Start the server
uv run uvicorn app.main:app --reload --port 8000
```

You should see:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete.
```

### Verifying the backend

```powershell
# Health check — should return the default interview config
curl http://localhost:8000/api/v1/livekit/test-room/config

# Token generation — should return a JWT
curl -X POST http://localhost:8000/api/v1/livekit/test-room/token `
  -H "Content-Type: application/json" `
  -d '{"participant_name": "Test User"}'
```

---

## Frontend Setup (Next.js)

```powershell
cd ai-interviewer/web

# 1. Install dependencies
npm install

# 2. Create .env.local (see "Environment Variables" section above)

# 3. Push the Prisma schema to your local database (first time only)
#    Prisma CLI doesn't read .env.local, so pass the var inline:
$env:DATABASE_URL="postgresql://meetmind_user:meetmind_password@localhost:5432/meetmind"
npx prisma db push

# 4. Start the dev server
npm run dev
```

You should see:
```
▲ Next.js 15.x (Turbopack)
- Local: http://localhost:3000
✓ Ready
```

### Important Notes for Frontend Devs

- **Prisma and Alembic share the same database.** The backend uses Alembic for its tables; the frontend uses Prisma for the `Session` table. They coexist in the `public` schema without conflict.
- **`npx prisma db push`** is only needed once (or whenever `prisma/schema.prisma` changes). It creates/updates the `Session` table.
- **Do NOT use `pnpm`** on this project — use `npm` only. If you see a `pnpm-lock.yaml`, ignore it.

---

## Running the AI Agent

```powershell
cd meetmind-api

# Start the agent worker (separate terminal from the backend)
uv run python -m app.agent.interviewer dev
```

You should see:
```
INFO  livekit.agents  process initialized
INFO  livekit.agents  registered worker
```

The agent is now connected to LiveKit Cloud and waiting. It will automatically join any room that a candidate connects to.

---

## End-to-End Flow

Here's what happens when a recruiter creates and runs an interview:

### Step 1 — Recruiter Creates a Session

1. Go to `http://localhost:3000`
2. Click **"New interview"**
3. Fill in: role, candidate name, questions, rubric, duration
4. Submit → a `Session` row is created in the database with status `created`

### Step 2 — Candidate Joins the Interview

1. The recruiter sends the candidate a link: `http://localhost:3000/interview/{session_id}`
2. The candidate opens the link and clicks **"Start call"**
3. The frontend's `/api/token` route:
   - Validates the `sessionId` exists and isn't `completed`
   - Generates a signed LiveKit JWT scoped to that room
   - Returns `{ serverUrl, roomName, participantToken }`
4. The browser connects to LiveKit Cloud using the token

### Step 3 — Agent Joins Automatically

1. LiveKit Cloud sees a participant in the room
2. It dispatches a "job" to the registered Python agent worker
3. The agent:
   - Fetches interview config: `GET /api/v1/livekit/{session_id}/config`
   - Builds a system prompt from the questions and rubric
   - Joins the room and greets the candidate
4. Real-time interview loop: **Candidate speaks → STT → LLM → TTS → Agent speaks**

### Step 4 — Interview Ends

When the interview timer runs out (or the candidate disconnects):

1. The agent extracts the transcript from the chat history
2. Generates an AI evaluation report (scores each rubric criterion 1-5)
3. Posts both to: `POST /api/v1/livekit/{session_id}/result`
4. A local JSON backup is saved to `app/agent/transcripts/`

### Step 5 — Recruiter Reviews

The recruiter views the session detail page (`/sessions/{id}`) to see the transcript and AI-generated scorecard.

---

## API Reference

All endpoints are mounted at `/api/v1/livekit/`.

### `POST /{session_id}/token`

Generate a LiveKit access token for a participant to join an interview room.

**Request body:**
```json
{
  "participant_name": "Jane Doe"
}
```

**Response (200):**
```json
{
  "token": "eyJhbGciOiJIUzI1NiIs..."
}
```

**Errors:**
- `500` — LiveKit credentials not configured in `.env`

---

### `GET /{session_id}/config`

Called by the agent to fetch the interview setup for a given session.

**Response (200):**
```json
{
  "role": "Software Engineer",
  "intro": "an automated first-round screening interview",
  "questions": [
    {
      "text": "Tell me about a system you built.",
      "followUpHint": "Probe scale and trade-offs.",
      "maxFollowUps": 2
    }
  ],
  "rubric": [
    {
      "name": "Technical Depth",
      "description": "Hands-on backend knowledge.",
      "weight": 3
    }
  ],
  "durationMinutes": 20,
  "closing": "Thanks for your time. A recruiter will follow up.",
  "candidateName": "Jane Doe"
}
```

> **Note:** Currently returns a hardcoded default. Wire this to your database to return per-session configs.

---

### `POST /{session_id}/result`

Called by the agent when the interview ends.

**Request body:**
```json
{
  "transcript": [
    { "speaker": "interviewer", "text": "Tell me about your experience." },
    { "speaker": "candidate", "text": "I worked at..." }
  ],
  "report": {
    "criteria": [
      { "name": "Technical Depth", "score": 4, "justification": "..." }
    ],
    "overall": "yes",
    "summary": "Strong candidate with good system design skills."
  }
}
```

**Response (200):**
```json
{
  "status": "success",
  "message": "Result saved successfully"
}
```

> **Note:** Currently the result is acknowledged but not persisted to the database. Wire this to update the `Session` row with transcript and report JSON.

---

## Data Models

### Backend — `Interview` dataclass (`app/agent/interview.py`)

```python
@dataclass
class Interview:
    role: str                        # e.g. "Software Engineer"
    intro: str                       # e.g. "a first-round screening"
    questions: list[Question]        # ordered list of questions
    rubric: list[RubricCriterion]    # scoring criteria
    duration_minutes: int = 20       # interview time limit
    closing: str = "Thanks..."       # sign-off message
    candidate_name: str | None = None

@dataclass
class Question:
    text: str                        # the question to ask
    follow_up_hint: str = ""         # guidance for follow-ups
    max_follow_ups: int = 2          # cap on follow-up questions

@dataclass
class RubricCriterion:
    name: str                        # e.g. "Technical Depth"
    description: str                 # what to evaluate
    weight: int = 1                  # relative importance
```

### Frontend — Prisma `Session` model (`prisma/schema.prisma`)

```prisma
model Session {
  id              String    @id @default(cuid())
  role            String
  candidateName   String?
  intro           String
  questionsJson   String    // JSON-encoded Question[]
  rubricJson      String    // JSON-encoded RubricCriterion[]
  durationMinutes Int       @default(20)
  closing         String    @default("Thanks for your time...")
  status          String    @default("created")  // created | in_progress | completed
  transcriptJson  String?   // JSON-encoded transcript (set by agent)
  reportJson      String?   // JSON-encoded report (set by agent)
  createdAt       DateTime  @default(now())
  startedAt       DateTime?
  completedAt     DateTime?
}
```

### How They Map Together

| Frontend Session field | Agent config JSON key | Notes |
|------------------------|-----------------------|-------|
| `role` | `role` | Direct mapping |
| `candidateName` | `candidateName` | Nullable |
| `intro` | `intro` | Used in the system prompt |
| `questionsJson` | `questions` | Parse with `JSON.parse()` on frontend; agent receives as array |
| `rubricJson` | `rubric` | Same as above |
| `durationMinutes` | `durationMinutes` | Integer |
| `closing` | `closing` | Agent reads for sign-off |
| `transcriptJson` | _(posted in result)_ | Agent posts; frontend stores |
| `reportJson` | _(posted in result)_ | Agent posts; frontend stores |

---

## Troubleshooting

### Backend won't start — `ValueError: No API key was provided`

The `DocumentService` initializes a Google Gemini client at import time. If `GEMINI_API_KEY` is empty/missing, the app crashes.

**Fix:** Set `GEMINI_API_KEY` in your `.env` (even an empty string works — the client is lazy-loaded).

---

### Frontend — `error: Environment variable not found: DATABASE_URL`

Prisma can't find the database URL.

**Fix:** Create `web/.env.local` with `DATABASE_URL=postgresql://...` (see Environment Variables section).

---

### Frontend — `The table 'public.Session' does not exist`

The Prisma schema hasn't been pushed to the database yet.

**Fix:**
```powershell
$env:DATABASE_URL="postgresql://meetmind_user:meetmind_password@localhost:5432/meetmind"
npx prisma db push
```

---

### Agent — `Could not find file "model_q8.onnx"`

The `MultilingualModel` turn detector failed to download its ONNX weights.

**Fix:** The turn detector line in `app/agent/interviewer.py` is commented out. The agent falls back to Silero VAD, which works fine.

---

### Agent connects but immediately disconnects

Check that `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET` are all set correctly in `meetmind-api/.env`. The agent must be able to reach the LiveKit Cloud WebSocket endpoint.

---

### Alembic — `Can't locate revision identified by 'xxx'`

If you ran `npx prisma db push --accept-data-loss`, Prisma may have dropped the `alembic_version` table.

**Fix:**
```powershell
uv run alembic stamp head
```

This re-creates the tracking table without re-running migrations.

---

## What's Left to Wire Up

The following items are stubbed and need real database integration:

1. **`GET /{session_id}/config`** — Currently returns a hardcoded default. Should query the `Session` table (via SQLAlchemy) and return the actual `questionsJson` / `rubricJson` for that session.

2. **`POST /{session_id}/result`** — Currently acknowledges but discards the payload. Should update the `Session` row: set `transcriptJson`, `reportJson`, `status = 'completed'`, and `completedAt = now()`.

3. **Session status transitions** — The frontend creates sessions with `status = 'created'`. The backend should set `status = 'in_progress'` when the agent joins, and `status = 'completed'` when the result is posted.
