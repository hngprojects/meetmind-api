# RFC: MS4-BE-001 — Rubric-Based Scorecard Response

**Author:**Abdulrahmon
**Date:** 2026-06-05
**Status:** Draft
**Tickets:** MS4-BE-001

---

## Problem

The scorecard endpoint (`GET /interviews/{id}/scorecard`) returns percentage-based rubric scores with transcript evidence, but it does not return a confidence level for each score, nor does it separate strengths from weaknesses per rubric criterion. Also, the response lacks a rolled-up total score and overall confidence indicator.

Recruiters need to know how reliable each score is. They also need strengths and weaknesses  separated so the scorecard is immediately scannable without manual interpretation.

---

## What I'm Building

1. **Confidence level** — a 0–100 integer per criterion indicating how certain the AI is about that score, based on transcript quality, answer clarity, and evidence sufficiency.
2. **Strengths/weaknesses split** — per-criterion lists separating positive signals from areas of improvement, generated directly by the AI during report generation.
3. **Aggregate fields** — `total_score` and `overall_confidence` at the `InterviewScorecardResponse` root level so the frontend has a single number for the scorecard header.

---

## Design Decisions

### Confidence stored as Integer (0–100)

Matches `score_pct` which is already 0–100. Using the same scale avoids frontend confusion — both fields represent a percentage. Per-criterion rather than per-scorecard because confidence can legitimately vary across criteria (e.g., one topic had a garbled audio segment, another was clear).

### Strengths/weaknesses stored via `[strength]` / `[weakness]` prefix tags

Rather than adding a new DB table or a boolean `is_strength` column on `ScorecardSignal`, strengths and weaknesses are stored in the existing `scorecard_signals` table with a prefix tag. The read layer parses the prefix back out. This avoids a migration to add a column or a new table.

Disadvantage: the prefix consumes 10 characters of the 80-char `String(80)` label limit. Acceptable because 70 characters is sufficient for a signal label.

### Overall confidence computed as mean of per-criterion confidences

Simple average. Weighted average was considered (weighted by criterion weight from the rubric) but rejected because the rubric weight is a importance-to-role score, not a confidence-relevance score. A straight average is more transparent.

### AI prompt modified to emit new fields

The  `generate_report()` function in `app/agent/report.py` is the source of all scorecard data. Adding instructions and output fields in the prompt template is the cleanest way to introduce the new data.

---

## Acceptance Criteria

### GET /api/v1/interviews/{id}/scorecard

- Returns 200 with `total_score` (0–100), `overall_confidence` (0–100) at the root of `InterviewScorecardResponse`.
- Each rubric criterion includes `confidence` (0–100 integer), `strengths` (list of strings), and `weaknesses` (list of strings).
- Returns 404 if interview not found or not owned by user.
- Existing fields (`score_pct`, `signals`, etc.) remain unchanged and at the same positions.
- Requires auth.

### Confidence field behavior

- `confidence` is 0–100 integer; values outside this range are rejected by the schema validator.
- When confidence cannot be determined (e.g., empty transcript), AI defaults to 0.

### Strengths/weaknesses parsing

- `[strength]` and `[weakness]` prefix tags are parsed out of the signal label on read.
- A signal with neither prefix is treated as a neutral signal (appears in neither list).
- Unknown or malformed prefixes result in the raw label being included as a neutral signal — no 500 error.

---

## Tradeoffs

- **Prefix tags over schema change**: Encoding strengths/weaknesses as `[strength]`/`[weakness]` prefixes in the existing `String(80)` label avoids a DB migration but consumes 10 characters of the label limit. If signals routinely need more than 70 meaningful characters, a `signal_type` column or separate table would be cleaner.
