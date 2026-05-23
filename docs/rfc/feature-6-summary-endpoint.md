# RFC — Interview Summary & Session Status Endpoints

**Author:** Daniel  
**Date:** 2026-05-23  
**Status:** Draft  
**Tickets:** 6.1, 6.3, 7.1  

---

## Problem

When an interview ends the recruiter has transcripts but needs a structured summary — observations, highlights, and red flags — to make decisions and share findings with a hiring manager. The recruiter also needs to know the live state of a session while it is happening — live transcripts, awaiting summary, summary ready. Structured summaries give the recruiter what they need to make a hiring decision, and live session state gives the UI the information it needs to render the correct experience at each phase.

---

## What I'm Building

- `GET /api/v1/interviews/{id}/summary` — fetches the summary of the interview and returns structured JSON
- `POST /api/v1/interviews/{id}/summary/retry` — retries a failed summary generation
- `GET /api/v1/interviews/{id}/session` — a lightweight endpoint for the FE to poll to keep the Transcript and Summary headers live

---

## Design Decisions

### Assessment Storage

To maintain model structure and avoid migrations that might affect existing values, `ai_assessment` is kept as `Text`. Structured output from the LLM is stored as a JSON string and parsed with the `json` module on read. JSONB was considered but rejected because changing the column type would require a migration and could break any existing text values already stored in the column.

### Dropped Endpoint

`POST /summary/generate` is not being built because `complete_interview` already triggers assessment generation as a background task when the interview is marked complete. Adding a separate generate endpoint would duplicate that logic and create a surface for double-triggering generation on the same interview.

### LLM Output Contract

The LLM is prompted to return structured JSON in the following shape:

```json
{
  "observation": "The candidate demonstrated strong...",
  "highlights": ["Structured problem solving", "Clear communication"],
  "red_flags": ["Struggled with ambiguity"]
}
```

JSON was chosen over plain text because the FE expects three distinct fields. Parsing a text blob into those fields reliably would require fragile string manipulation. JSON eliminates that problem and is straightforward to work with on both sides.

### Session Status

`GET /session` reads `interviews.status` and `interviews.scheduled_start` directly from the DB. `elapsed` is computed in Python as the difference between `scheduled_start` and the current time — only when status is `in_progress`, otherwise it returns null. `session_phase` is derived from `interviews.status` using a fixed mapping rather than stored separately. The endpoint is intentionally lightweight because it will be polled frequently by the FE to keep the session header live — heavy joins would make it too slow for that use case.

---

## Tradeoffs

- Storing structured LLM output as a JSON string in a Text column means parsing on every read. The alternative — JSONB — would be cleaner at the DB level but introduces a migration risk on a column that may already have existing text values.
- Dropping `POST /summary/generate` means the FE has no way to manually trigger generation outside of completing an interview. This is acceptable because generation should always be a consequence of completion, not a standalone action.
- The retry endpoint resets `summary.status` to `"generating"` and kicks off the background task again. A decorator was added to the AI client call to retry transient errors like 500s automatically, but permanent errors in the 4xx range are not retried — those surface as failed and require a manual retry from the recruiter.

---

## Open Questions

The retry endpoint exists because the current background task has no internal retry mechanism — any exception marks the summary as failed. A cleaner long-term solution would be a scheduled asyncio worker that queries the DB for completed interviews with failed summaries and retries generation in batch every 30 seconds or so. This would eliminate the need for the retry endpoint entirely. Proposed as a separate ticket pending mentor review.