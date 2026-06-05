## Description

Add confidence level, strengths/weaknesses split, justification, sub-rubrics with evidence, and aggregate fields (`total_score`, `overall_confidence`) to the scorecard endpoint. The scorecard is generated as a background task when `POST /{id}/complete` is called, and a notification is sent when ready.

The response shape now includes sub-rubrics (nested criteria) and evidence objects linking back to specific transcript turns by UUID, enabling the frontend to display granular scores with supporting evidence traces.

## Type of Change

- [x] `feat` — New feature

## Related Issue

Closes MS4-BE-001

## Changes Made

### Models (`app/models/scorecard.py`)
- Added `ScorecardSubRubric` table: `score_id` (FK), `name`, `score_pct`, `confidence`, `justification`, `strengths` (JSON), `weaknesses` (JSON), `sort_order`
- Added `ScorecardEvidence` table: `score_id` (FK, nullable), `sub_rubric_id` (FK, nullable), `question_turn_id`, `response_turn_id`, `reason`
- Added `confidence` (Integer, default=0) and `justification` (Text) columns to `ScorecardScore`
- Changed `ScorecardSignal.label` from `String(80)` to `Text`

### Migrations (1 new)
- `6dfc72e0da4a` — label→Text, confidence + justification, scorecard_sub_rubrics (with strengths/weaknesses JSON), scorecard_evidence

### Schemas (`app/schemas/assessment.py`)
- Added `AssessmentEvidence` with `question_turn_id`, `response_turn_id`, `reason`
- Added `AssessmentSubRubric` with `id`, `title`, `score`, `confidence`, `justification`, `strengths`, `weaknesses`, `evidence`
- Renamed `AssessmentCriterionScore` fields: `name` → `id`+`title`, `signals` → `signals_detected`, `questions` → `questions_asked`
- Added `sub_rubrics` list to `AssessmentCriterionScore`

### Schemas (`app/schemas/interview.py`)
- Added `ScorecardEvidence`, `ScorecardSubRubric` schemas with `id`/`title`, evidence, strengths/weaknesses
- Updated `ScorecardSection`: added `id`, `signals_detected`, `strengths`, `weaknesses`, `evidence`, `sub_rubrics`, `expanded`
- Added `total_score`, `overall_confidence` to `InterviewScorecardResponse`

### Service (`app/services/interview.py`)
- `_persist_scorecard_report`:
  - Saves `confidence`/`justification` on scores
  - Prepends `[strength]`/`[weakness]` prefix tags on signals for parsing
  - **FK-safe delete order**: deletes evidence first (by sub_rubric_id subquery + score_id), then sub-rubrics, avoiding FK violations
  - Persists sub-rubrics with `strengths`/`weaknesses` from LLM output
  - Strips `[]` brackets from `question_turn_id`/`response_turn_id` via `.strip("[]")`
  - Persists section-level evidence (`sub_rubric_id IS NULL`)
- `get_scorecard`:
  - Parses `[strength]`/`[weakness]` prefix tags into separate `strengths`/`weaknesses`/`signals_detected` lists
  - Loads sub-rubrics with strengths/weaknesses from DB (not hardcoded `[]`)
  - Loads section-level and sub-rubric-level evidence separately
  - Computes `total_score` and `overall_confidence` as averages
  - Supports `view="summary"` param (clears questions/signals)

### AI Service (`app/services/ai_generation_service.py`)
- **Transcript format**: DB turns output as `[uuid] Speaker: text`; fallback JSON format as `[idx] Speaker: text` — LLM sees real UUIDs for evidence reference
- **Prompt rewrite**: Consolidated UUID instruction, explicit "no markdown/no code fences", JSON schema at end of prompt, confidence semantics explanation, mandatory sub-rubrics (1–3 per criterion), sub-rubric uniqueness guardrail
- **Report builder**: Maps LLM field names (`title`→`name`, `signals_detected`→`signals`, `questions_asked`→`questions`) for persist compatibility
- Calls `_persist_scorecard_report` after assessment generation
- Wrapped `_retrieve_resume_context` in try/except to prevent embedding API failures from crashing generation

### Agent (`app/agent/report.py`)
- Updated LiveKit agent prompt to request `confidence`, `strengths`, `weaknesses`, `justification` in each criterion

### Routes (`app/api/v1/routes/interviews.py`)
- Added `?view=summary|detailed` query param to `GET /{id}/scorecard`

### LLM Providers
- Fixed `_client()` → `_client` in Gemini, Groq, OpenRouter providers (lazy init → module-level singleton)

### Context Service (`app/services/interview_context_service.py`)
- Fixed `DocumentService._client()` → direct `_gemini_client` import

### Docs
- `docs/api/scorecard-response.md` (full API contract)
- `docs/rfc/ms4-be-001-scorecard-response.md` (design RFC)

### Post-review fixes
- Made `justification`, `questions`, `criteria` optional with defaults
- Moved `view=summary` logic from route to service layer

## Proof of Work

<details>
<summary>API Response — GET /scorecard?view=detailed (current)</summary>

```json
GET /api/v1/interviews/{id}/scorecard
Status: 200 OK

{
  "success": true,
  "message": "Scorecard retrieved successfully",
  "data": {
    "interview_id": "019e976e-c9ae-7d18-b146-dffef3e211f5",
    "total_score": 50,
    "overall_confidence": 70,
    "sections": [
      {
        "id": "technical_depth",
        "title": "Technical Depth",
        "score": 60,
        "confidence": 80,
        "score_bar_percent": 60,
        "questions_asked": [
          "Can you tell me a little bit about your background as a backend developer?",
          "Can you walk me through how you designed and implemented the retry engine?"
        ],
        "signals_detected": [
          "built a retry engine",
          "used SQLite3 and background workers",
          "lacked concrete examples"
        ],
        "strengths": [
          "built a retry engine",
          "used SQLite3 and background workers"
        ],
        "weaknesses": [
          "lacked concrete examples"
        ],
        "justification": "The candidate demonstrated some knowledge of software engineering concepts...",
        "evidence": [
          {
            "question_turn_id": "019e976f-4baf-76c1-9440-352220ddd789",
            "response_turn_id": "019e9770-428f-70e3-b90e-c76fefdc7574",
            "reason": "Candidate mentioned building a retry engine, but didn't provide details."
          }
        ],
        "expanded": true,
        "sub_rubrics": [
          {
            "id": "programming_languages_and_frameworks",
            "title": "Programming Languages and Frameworks",
            "score": 70,
            "confidence": 90,
            "score_bar_percent": 70,
            "strengths": ["knowledge of SQLite3"],
            "weaknesses": ["lacked depth"],
            "justification": "...",
            "evidence": [...],
            "expanded": false
          }
        ]
      },
      {
        "id": "communication",
        "title": "Communication",
        "score": 40,
        "confidence": 80,
        "score_bar_percent": 40,
        "questions_asked": [...],
        "signals_detected": [
          "enthusiastic and willing to learn",
          "struggled to provide clear explanations"
        ],
        "strengths": ["enthusiastic and willing to learn"],
        "weaknesses": ["struggled to provide clear explanations"],
        "justification": "...",
        "evidence": [...],
        "expanded": false,
        "sub_rubrics": [
          {
            "id": "clarity",
            "title": "Clarity",
            "score": 30,
            "confidence": 60,
            "score_bar_percent": 30,
            "strengths": [...],
            "weaknesses": [...],
            "justification": "...",
            "evidence": [...],
            "expanded": false
          }
        ]
      }
    ]
  }
}
```
</details>

## Test Cases

- [x] `test_transcript_fallback_format_turns_text` — fallback format includes `[idx]` prefix
- [x] All 315 tests pass

<details>
<summary>Test output</summary>

```bash
$ uv run pytest tests/ -v --tb=short
====================== 315 passed, 2 warnings in 24.36s =======================
```
</details>

## Checklist

- [x] My branch follows the naming convention (`<type>/<short-description>`)
- [x] My commits follow [Conventional Commits](https://www.conventionalcommits.org/)
- [x] All new and existing tests pass locally (`uv run pytest`)
- [x] I have included proof of work (JSON responses or screenshots)
- [x] I have updated documentation if needed
- [x] My code follows the project's style guidelines (`ruff check` + `ruff format` pass)
