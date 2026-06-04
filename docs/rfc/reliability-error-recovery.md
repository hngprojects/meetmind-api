# RFC — Reliability, Error Recovery, and Transcript Fallback Mechanisms

**Author:** Antigravity  
**Date:** 2026-06-04  
**Status:** Approved  
**Tickets:** MS4-BE-005  

---

## Problem

The MeetMind API depends heavily on external APIs and background operations to run core features:
- **Transactional emails** (via Resend) for verification, password resets, and session links.
- **AI-driven screening/interviewer responses** (via Gemini SDK).
- **Resume document extraction and embeddings** (via Gemini SDK).
- **Live transcript turn ingestion** (via LiveKit `/transcript/turn` calls).

External API dependencies can fail due to temporary network dropouts, API rate limits, or transient provider outages. When a transient error occurs during a background task (like resume parsing or assessment generation), the entire operation fails, leading to degraded user experience (e.g., summaries marked as `failed`, missing candidate details, or unsent invites).

Additionally, if live transcript ingestion fails halfway or loses turns due to database connection resets, recruiters could lose the screening transcript entirely.

---

## What We Built

### 1. Centralized Async Retry Helper
We implemented a generalized `retry_async` function in `app/core/utils.py` that executes any async callable with:
- **Exponential Backoff**: Configurable delays, backoff multipliers, and max retry counts (defaulting to 3 retries, starting at 2.0s delay).
- **Failure Logging**: 
  - `logger.warning` for intermediate attempt failures (including stack traces and target task information).
  - `logger.error` when all retry attempts are exhausted.

### 2. Core Task Resiliency Integration
We integrated the `retry_async` wrapper across all external integration points:
- **Email Delivery**: Wrapped `resend.Emails.send_async` to retry delivery.
- **AI Assessment & Interview Plan**: Wrapped LLM `generate_structured_output` calls.
- **Next Question & Q&A Queries**: Wrapped LLM `generate_text` calls.
- **Document Services**: Wrapped resume extraction and embedding batch creation.

### 3. Transcript Fallback Access
We established a robust fallback mechanism for reading transcripts. If the database `interview_transcript_turns` lookup yields zero items (either because the record wasn't created or live turns failed to persist):
- We query the corresponding `InterviewSession` (linked via `interview.session_id`).
- We retrieve the final `transcript_json` array (uploaded at the end of the LiveKit session).
- We parse it dynamically and convert the turns into the expected Pydantic or formatted line structure on-the-fly.

This fallback is fully integrated into:
- `ChatHistoryService.get_chat_history`
- `ChatHistoryService.get_transcript`
- `ChatHistoryService.get_transcript_export`
- `AIGenerationService._format_turns_text` (ensuring post-interview summaries can still be generated successfully).

---

## Design Decisions

### Centralized Wrapper vs Decorators
While decorators are elegant, python decorators on class methods or external SDK methods (like `resend.Emails.send_async`) can be complex or require monkey-patching. A centralized async function wrapper `retry_async` allows us to cleanly wrap any third-party SDK call directly at the execution site, with precise control over parameters (such as `task_name` for logging context).

### Dynamic Schema Mapping on Fallback
To keep the fallback entirely transparent to callers and the frontend:
- For `/chat/history`, turns parsed from `transcript_json` are mapped directly to `ChatMessageResponse`.
- For `/transcript`, turns are mapped to `TranscriptTurnResponse` (generating synthetic UUIDs for ID fields).
- For `/transcript/export`, they are formatted to the same relative timestamp lines (`[MM:SS] Speaker: Content`).

This prevents breaking changes in the API schemas.

---

## Tradeoffs

- **Increased Latency on Failure**: Retrying third-party services with backoff increases the execution time of failing background tasks. This is highly acceptable for asynchronous background tasks (like resume embedding or summary generation), as it prioritizes success over rapid failure.
- **Synthetic Identifiers**: Fallback transcripts lack permanent database primary keys for individual turns, so synthetic UUIDs are generated dynamically. This is acceptable since the UI does not write back to individual turns by ID.
