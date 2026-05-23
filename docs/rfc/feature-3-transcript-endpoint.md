# RFC: Feature 3 — Dedicated Interview Transcript API

## Status
Draft

## Authors
- Daniel

## Summary
This RFC defines the backend design for Feature 3: a dedicated transcript API for interview sessions. The feature adds three endpoints to separate transcript data from chat history and support transcript download and stop-transcribing behavior.

## Motivation
The frontend currently reuses `GET /api/v1/interviews/{id}/chat/history` for both the Chat and Transcript tabs. This violates separation of concerns because chat history and transcript turns have different shapes, semantics, and UI requirements.

A dedicated transcript endpoint allows:
- a clear contract for the Transcript tab
- proper speaker normalization for UI labels
- export/download support in a simple text format
- a controlled stop action for transcript capture

## Scope
This RFC covers:
- `GET /api/v1/interviews/{id}/transcript`
- `GET /api/v1/interviews/{id}/transcript/export`
- `POST /api/v1/interviews/{id}/transcript/stop`

It does not change the existing chat history contract beyond keeping transcript and chat separate.

## Design
### Service structure
Reuse `ChatHistoryService` for shared transcript lookup and interview ownership validation. Extend it with transcript-specific methods rather than introducing a new service.

### Interview ownership
All endpoints must verify that the interview belongs to the authenticated user. The same guard used by `InterviewService.get_interview` is reused in `ChatHistoryService`.

### Transcript model
Transcript turns are stored in `interview_transcript_turns` and are fetched by `transcript_id`, ordered by `sequence_no`.

### Speaker normalization
The response must map DB speaker values to normalized response values:
- `ai` -> `meet_mind`, `Meet Mind`
- `candidate` -> `candidate`, `Candidate`
- `interviewer` -> `interviewer`, `Interviewer`

Unknown DB speaker values are normalized to `unknown` / `Unknown` to avoid leaking raw DB values.

### Timestamp formatting
Timestamps are returned as elapsed time from the first turn's `timestamp_sec`, formatted as `MM:SS`.

If no transcript exists, the endpoint returns 200 with empty `turns: []`.

## API contract
### 1. GET /api/v1/interviews/{id}/transcript
Returns transcript turns in the shape expected by the Transcript tab.

Response:
```json
{
  "success": true,
  "message": "Transcript retrieved",
  "data": {
    "interview_id": "uuid",
    "total_turns": 12,
    "turns": [
      {
        "id": "uuid",
        "speaker": "meet_mind",
        "speaker_label": "Meet Mind",
        "timestamp": "05:46",
        "content": "Tell me about a time you led a team under pressure.",
        "is_typing": false,
        "is_active": false,
        "sequence_no": 1
      }
    ]
  }
}
```

Acceptance criteria:
- Returns 200 with empty `turns: []` when no transcript exists.
- Returns 404 if interview not found or not owned by user.
- `speaker` and `speaker_label` always use normalized values.
- `timestamp` always formatted as `MM:SS`.
- Requires auth.

### 2. GET /api/v1/interviews/{id}/transcript/export
Returns a `.txt` download of the full transcript.

Behavior:
- Fetch all transcript turns ordered by `sequence_no`.
- Format each turn as `[MM:SS] Speaker: Content`.
- Return `text/plain` with `Content-Disposition: attachment; filename=transcript_{interview_id}.txt`.

Acceptance criteria:
- File is downloadable as `.txt`.
- File contains turns in order with normalized speaker labels.
- Returns 404 if interview not found or not owned by user.
- If no transcript exists, returns a minimal empty file header line.
- Requires auth.

### 3. POST /api/v1/interviews/{id}/transcript/stop
Transitions the interview from `in_progress` to `completed`.

Request body: none.

Response:
```json
{
  "success": true,
  "message": "Interview transcript stopped successfully",
  "data": {
    "interview_id": "uuid",
    "status": "completed"
  }
}
```

Acceptance criteria:
- Only transitions `in_progress` -> `completed`.
- Returns 409 if already `completed` or `cancelled`.
- Returns 404 if interview not found or not owned by user.
- Requires auth.

## Implementation details
### Route layer
Add routes in `app/api/v1/routes/interviews.py`:
- `GET /{interview_id}/transcript`
- `GET /{interview_id}/transcript/export`
- `POST /{interview_id}/transcript/stop`

### Service layer
Extend `app/services/chat_history.py` with:
- `get_transcript(...)`
- `get_transcript_export(...)`
- shared interview ownership guard

Add `InterviewService.stop_transcript(...)` in `app/services/interview.py`.

### Schemas
Add `app/schemas/transcript.py` with:
- `TranscriptTurnResponse`
- `TranscriptResponse`

### Export behavior
Use `fastapi.responses.StreamingResponse` to stream a list of transcript lines as a text file.

## Testing
Add endpoint coverage in `tests/test_transcript_endpoints.py` for:
- empty transcript retrieval
- transcript turn normalization and timestamp formatting
- transcript export file download
- empty transcript export
- stop transcript success
- stop transcript 409 on completed/cancelled
- 404 for non-owner
- 401 without token

## FE migration note
After deployment, the frontend must update `getTranscript()` in `src/lib/services/interviews.service.ts` to call `/api/v1/interviews/{id}/transcript` instead of `/interviews/{id}/chat/history`.

## Implementation alignment
The current implementation matches this RFC, with the following decisions:
- transcript endpoints are implemented in `app/api/v1/routes/interviews.py`
- transcript retrieval and export are handled by `ChatHistoryService`
- stop-transcript state transition is handled in `InterviewService`
- speaker values are normalized and unknown values are mapped safely
- empty transcript export returns a single header line
