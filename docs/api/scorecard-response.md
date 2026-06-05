# Scorecard API

## `GET /api/v1/interviews/{id}/scorecard`

Retrieves candidate evaluation results grouped by rubric criteria. Generated as a background task after `POST /{id}/complete`.

### Query Parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `view` | `"detailed" \| "summary"` | `"detailed"` | `detailed` — full response with questions & signals; `summary` — scores/confidence/strengths/weaknesses only |

**Examples:**
```
GET /api/v1/interviews/019e976e-.../scorecard
GET /api/v1/interviews/019e976e-.../scorecard?view=summary
GET /api/v1/interviews/019e976e-.../scorecard?view=detailed
```

### Flow

1. User calls `POST /api/v1/interviews/{id}/complete`
2. Backend marks the interview as completed and enqueues assessment generation as a **background task**
3. The background task generates the LLM assessment and **persists the scorecard** (`total_score`, per-criterion scores, confidence, signals, strengths/weaknesses, justification) to the database
4. User receives `"Interview Summary Ready"` notification (poll `GET .../notifications`)
5. User calls `GET .../scorecard` — returns the full evaluation from the DB

**Important:** The scorecard is only generated when `/complete` is called. Calling `/scorecard` before `/complete` or before the background task finishes will return `sections: []`.

### Response Schema

```json
{
  "success": true,
  "message": "Scorecard retrieved successfully",
  "data": {
    "interview_id": "019e976e-c9ae-7d18-b146-dffef3e211f5",
    "total_score": 50,
    "overall_confidence": 70,
    "sections": [
      {
        "title": "Technical Depth",
        "score": 40,
        "confidence": 60,
        "score_bar_percent": 40,
        "questions_asked": [
          "Can you walk me through how you designed and implemented the retry engine?"
        ],
        "signals_detected": [
          "Demonstrated ability to build a retry engine with background worker processing",
          "Struggled to provide in-depth explanations",
          "Familiarity with SQLite3"
        ],
        "strengths": [
          "Demonstrated ability to build a retry engine with background worker processing",
          "Familiarity with SQLite3"
        ],
        "weaknesses": [
          "Struggled to provide in-depth explanations"
        ],
        "justification": "The candidate explained retry logic but lacked depth on exponential backoff.",
        "expanded": true
      }
    ]
  }
}
```

### Field Descriptions

| Field | Type | Description |
|---|---|---|
| `interview_id` | UUID | Interview identifier |
| `total_score` | int (0–100) | Average of all criterion `score` values |
| `overall_confidence` | int (0–100) | Average of all criterion `confidence` values |
| **sections[]** | | |
| `title` | string | Rubric/criterion name (e.g. "Technical Depth") |
| `score` | int (0–100) | How well the candidate performed on this criterion |
| `confidence` | int (0–100) | AI's certainty in this score (lower = degraded audio, limited evidence) |
| `score_bar_percent` | int (0–100) | Same as `score`, for rendering progress bars |
| `questions_asked` | string[] | Interview questions mapped to this criterion. Empty in `view=summary` |
| `signals_detected` | string[] | All detected signals (strengths + weaknesses combined + neutral). Empty in `view=summary` |
| `strengths` | string[] | Positive indicators only |
| `weaknesses` | string[] | Areas for improvement or gaps |
| `justification` | string\|null | Transcript-grounded explanation of why this score was given |
| `expanded` | bool | Suggestion for which section to show open by default. Only the **first** section is `true`; the rest are `false` |

### Notes for Frontend

- **`expanded`**: Set `expanded: true` on only the first section so the UI doesn't appear cluttered. The frontend can still let users toggle others open/closed.
- **`view=summary`**: Use this for list/card views where space is tight. Use `view=detailed` for the full scorecard detail page.
- **Signals are deduplicated**: A signal may appear in both `signals_detected` and one of `strengths` or `weaknesses`. Render `signals_detected` as the complete list and use `strengths`/`weaknesses` for visual badges/tags.
- **Old interviews**: Interviews completed before this feature was deployed will return `sections: []` because scorecard data was never generated for them.
- **Timing**: The assessment runs as a background task and can take 10–60 seconds. Poll `GET .../notifications` for the `"Interview Summary Ready"` notification before calling this endpoint.

### Error Responses

| Status | Code | Description |
|---|---|---|
| 404 | `interview_not_found` | Interview doesn't exist or not owned by user |
| 401 | — | Missing or invalid auth token |
