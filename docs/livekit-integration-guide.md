# LiveKit AI Interviewer — Integration Guide

> **Audience:** Frontend & backend devs integrating the AI voice interviewer.
> **Last updated:** May 30, 2026

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
| **FastAPI Backend** | Python / Uvicorn | `8000` | REST API — token generation, interview configs, result persistence |
| **Next.js Frontend** | TypeScript / React | `3000` | Recruiter Dashboard (create/view interviews) + call connection UI |
| **LiveKit Agent** | Python / LiveKit SDK | _(no HTTP port)_ | Connects to LiveKit Cloud, runs the real-time STT → LLM → TTS loop |

All three must be running simultaneously for a complete interview flow.

---

## Architecture

```
┌────────────────────────────────┐
│      Browser (port 3000)       │
│  Next.js frontend              │
│                                │
│  1. Fetch /api/token           │──── proxies JWT request to FastAPI backend
│     { interviewId }            │
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
│         {interview_id}/config  │     returns interview questions, rubric
│                                │
│  4. Runs live interview via    │
│     STT → LLM → TTS pipeline  │
│                                │
│  5. POST /api/v1/livekit/      │───► FastAPI (port 8000)
│         {interview_id}/result  │     stores transcript + AI scorecard report
└────────────────────────────────┘
```

### Key Concept: Room Name = Interview ID

The LiveKit **room name** is always the backend's **interview ID** (a standard UUID). This is how the agent knows which interview configuration to load and where to post results when the session completes.

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.13+ | `winget install Python.Python.3` |
| uv | 0.4+ | `pip install uv` |
| Node.js | 20.x+ | `winget install OpenJS.Nodejs` |
| npm | 10.x+ | _(bundled with Node)_ |
| PostgreSQL | 15.x+ | Windows installer or Docker Compose |

---

## Environment Variables

### Backend (`meetmind-api/.env`)

Copy `.env.example` to `.env` and fill in **at minimum** these LiveKit-related keys:

```dotenv
# ── LiveKit (required for AI interviewer) ───────────────────────
LIVEKIT_URL=wss://meetmind-xxxx.livekit.cloud
LIVEKIT_API_KEY=APIxxxxxxx
LIVEKIT_API_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# ── Gemini (used for AI shaping and plan generation) ────────────
GEMINI_API_KEY=AIzaSy...

# ── Core (should already be set) ────────────────────────────────
DATABASE_URL=postgresql+asyncpg://meetmind_user:meetmind_password@localhost:5432/meetmind
FRONTEND_URL=http://localhost:3000
```

### Frontend (`ai-interviewer/web/.env.local`)

Create a `.env.local` file in the frontend's `web/` directory:

```dotenv
# ── LiveKit (same credentials as the backend) ──────────────────
LIVEKIT_URL=wss://meetmind-xxxx.livekit.cloud
LIVEKIT_API_KEY=APIxxxxxxx
LIVEKIT_API_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

---

## Backend Setup (FastAPI)

```powershell
cd meetmind-api

# 1. Create venv & sync dependencies using uv
uv sync

# 2. Copy and edit .env
cp .env.example .env

# 3. Run database migrations
uv run alembic upgrade head

# 4. Start the server
uv run uvicorn app.main:app --reload --port 8000
```

---

## Frontend Setup (Next.js)

```powershell
cd ai-interviewer/web

# 1. Install dependencies
npm install

# 2. Create .env.local (see Environment Variables section above)

# 3. Start the dev server
npm run dev
```

---

## Running the AI Agent

```powershell
cd meetmind-api

# Start the agent worker (separate terminal from the backend)
uv run python -m app.agent.interviewer dev
```

The agent is now connected to LiveKit Cloud and waiting. It will automatically join any room that a candidate connects to.

---

## End-to-End Flow

### Step 1 — Recruiter Creates an Interview
1. Go to `http://localhost:3000/interviews/new`.
2. Fill in: role title, candidate name, framing, questions, duration, and scoring rubric.
3. Submit → the Next.js API proxy (`/api/interviews`) maps details and sends them to the FastAPI backend. An `Interview` record is created in the database in `'scheduled'` status.

### Step 2 — Sharing the Interview Link (New Endpoint!)
Recruiters can trigger an invitation email containing the candidate's custom call link:
*   **API:** `POST /api/v1/interviews/{interview_id}/send-link`
*   Can be sent directly to the logged-in user or a candidate's email via the `email` query parameter.

### Step 3 — Candidate Joins the Interview
1. The candidate opens the link: `http://localhost:3000/interview/{interview_id}` and clicks **"Start screening call"**.
2. The frontend fetches room token details from `/api/token` (which proxies securely to `/api/v1/livekit/{interview_id}/token`).
3. The browser connects to LiveKit Cloud using the generated JWT.

### Step 4 — Agent Joins Automatically
1. LiveKit Cloud detects the participant and dispatches a job to the Python agent worker.
2. The agent:
   - Fetches interview config: `GET /api/v1/livekit/{interview_id}/config`
   - Dynamically builds the system instructions, questions list, and rubric
   - Joins the room and greets the candidate to conduct the screen
3. During the call, transcript turns are posted incrementally to `POST /api/v1/livekit/{interview_id}/transcript/turn`.

### Step 5 — Interview Completes
1. When the call is complete, the agent evaluates the interview against the custom rubric.
2. The agent posts the transcript and scorecard report to `POST /api/v1/livekit/{interview_id}/result`.
3. The backend persists the transcript and scorecard evaluations to the DB and sets the interview status to `'completed'`.

---

## API Reference

All backend endpoints are mounted at `/api/v1/livekit/` (unless stated otherwise).

### `POST /livekit/{interview_id}/token`
Generate a LiveKit access token for a participant to join an interview room.

*   **Path Parameter:** `interview_id` (string / UUID)
*   **Request body (Optional):**
    ```json
    {
      "participant_name": "Jane Doe"
    }
    ```
*   **Response (200):**
    ```json
    {
      "serverUrl": "wss://meetmind-xxxx.livekit.cloud",
      "roomName": "019e5a68-dcfb-711b-8a1a-1f9119d60159",
      "participantName": "Jane Doe",
      "participantToken": "eyJhbGciOiJIUzI1NiIs..."
    }
    ```

---

### `GET /livekit/{interview_id}/config`
Called by the agent to fetch the interview setup for a given interview.

*   **Response (200):**
    ```json
    {
      "role": "Software Engineer",
      "intro": "an automated first-round screening interview",
      "questions": [
        {
          "text": "Walk me through a backend system you've built that you're proud of.",
          "followUpHint": "Probe scale, contribution, and trade-offs.",
          "maxFollowUps": 2
        }
      ],
      "rubric": [
        {
          "name": "Technical Depth",
          "description": "Real, hands-on software engineering knowledge.",
          "weight": 3
        }
      ],
      "durationMinutes": 20,
      "closing": "Thanks for your time. A recruiter will follow up.",
      "candidateName": "Jane Doe"
    }
    ```

---

### `POST /livekit/{interview_id}/transcript/turn`
Incremental post handler used during the live call to persist transcript turns.

*   **Request body:**
    ```json
    {
      "speaker": "interviewer",
      "content": "How do you handle database migrations in production?",
      "sequence_no": 2,
      "speaker_name": "AI",
      "timestamp_sec": 45,
      "is_ai_question": true
    }
    ```

---

### `POST /livekit/{interview_id}/result`
Called by the agent when the interview ends to persist transcripts and scorecard report.

*   **Request body:**
    ```json
    {
      "transcript": [
        { "speaker": "interviewer", "text": "Tell me about your experience." },
        { "speaker": "candidate", "text": "I worked at..." }
      ],
      "report": {
        "summary": "Strong candidate with good system design skills.",
        "overall": "yes",
        "criteria": [
          { "name": "Technical Depth", "score": 4, "justification": "..." }
        ]
      }
    }
    ```

---

### `POST /interviews/{interview_id}/send-link` (New Endpoint!)
Send the interview invitation/LiveKit room link via email.

*   **Route:** `/api/v1/interviews/{interview_id}/send-link`
*   **Query Parameters (Optional):** `email` (string). If omitted, defaults to the verified recruiter's registered email address.
*   **Response (200):**
    ```json
    {
      "success": true,
      "message": "Interview link email sent successfully to candidate@example.com"
    }
    ```

---

## Data Models

The database models are fully mapped in PostgreSQL.

*   **`candidates`:** Holds candidate profile metadata (email, skills, location, experience).
*   **`interviews`:** Connects candidates, recruiters, and LiveKit rooms. Statuses: `scheduled` | `in_progress` | `completed` | `cancelled`.
*   **`interview_transcripts`:** Relational transcript database storing sequence number, speaker, content, and timestamp for each turn.
*   **`interview_scorecards`:** Evaluated scorecard report card with section scores, parsed signals, and justifications.
