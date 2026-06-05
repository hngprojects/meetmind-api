# RFC: MS4-BE-006 — Privacy & Session Cleanup for Audio and Context

## Status
Draft

## Authors
- (Abumair)

## Summary
This RFC defines the backend design for automated privacy cleanup of interview session data. After a LiveKit interview session ends, all raw audio-derived data (transcript turns, local transcript files, session context fields) must be completely purged within 10 minutes. A deletion audit trail is maintained for compliance verification.

The cleanup preserves derived evaluation data (AI assessments, scores, highlights, red flags) that interviewers need for hiring decisions — only the raw session content is purged.

## Motivation
Users participating in AI-powered interviews have a reasonable expectation that their session audio and conversation text are not retained indefinitely. The current system persists:

- **Interview transcript turns** in `interview_transcript_turns` (full conversation text)
- **Transcript headers** in `interview_transcripts`
- **Local JSON transcript backups** on the agent server filesystem (`app/agent/transcripts/`)
- **Session-level context** in `interview_sessions` (`transcript_json`, `report_json`)

None of this data is currently cleaned up automatically. This RFC addresses the privacy gap by introducing time-bound automatic purging with full audit logging.

## Scope
This RFC covers:
- Automatic purging of raw interview session data within 10 minutes of session end
- Deletion audit logging (DB table + structured application logs)
- A read-only admin endpoint for audit queries
- A safety-net sweep job for sessions that escape the primary cleanup path
- Retry logic for transient failures

It does **not** cover:
- Meeting transcript/recording cleanup (separate concern — `transcripts` / `transcript_segments` tables)
- Deletion of derived evaluation data (AI assessment, highlights, red flags, scores)
- User-facing UI for privacy controls

## Design

### Data inventory — what gets deleted

| # | Data location | Type | Description |
|---|---|---|---|
| 1 | `interview_transcript_turns` rows | DB rows | Individual conversation turns (speaker + text) |
| 2 | `interview_transcripts` rows | DB rows | Transcript header linking turns to an interview |
| 3 | `app/agent/transcripts/{session_id}-*.json` | Local file | JSON backup written by `save_transcript()` |
| 4 | `interview_sessions.transcript_json` | DB field | Raw transcript JSON stored on the session row |
| 5 | `interview_sessions.report_json` | DB field | Raw report JSON stored on the session row |

### Data inventory — what is preserved

| Data | Reason |
|---|---|
| `interview_summaries` (AI assessment, scoring rubric, etc.) | Derived business record; no raw user audio/text |
| `interview_highlights` | Derived evaluation data |
| `interview_red_flags` | Derived evaluation data |
| `interview_skills_to_assess` | Configuration data, not session content |
| `interviews` row itself | Metadata record (status, dates, links) |
| `candidates` row | Profile data, not session-specific |

### Lifecycle — cleanup sequencing

The cleanup timer starts **after** the AI report has been generated and persisted, ensuring no dependency issues:

```
Session ends (room closes)
    │
    ▼
on_shutdown callback fires
    │
    ├── 1. Cancel transcript streaming task
    ├── 2. Save local transcript backup
    ├── 3. Generate AI report (reads transcript turns)
    ├── 4. POST result to web app (persists report to DB)
    └── 5. SET Redis key `cleanup:{session_id}` with 600s TTL  ← NEW
                │
                ▼ (10 minutes later)
         Redis keyspace expiration event
                │
                ▼
         Cleanup job executes
                │
                ├── Delete transcript turns (DB)
                ├── Delete transcript header (DB)
                ├── Nullify session context fields (DB)
                ├── Delete local JSON files (filesystem)
                └── Write audit log entries (DB + structured log)
```

### Scheduling mechanism — Redis keyspace notifications

**Why Redis TTL + keyspace notifications?**
- Redis is already in the stack (JWT blacklist, rate limiting)
- No new infrastructure required
- TTL-based expiration is atomic and reliable
- Keyspace notifications provide event-driven cleanup (no polling)

**How it works:**
1. On session end, the agent (or the `/result` endpoint handler) sets a Redis key:
   ```
   SET cleanup:{session_id} "{interview_id}" EX 600
   ```
2. The FastAPI process subscribes to Redis keyspace notifications for `expired` events on keys matching `cleanup:*`.
3. When the key expires after 600 seconds, the listener receives the event and dispatches the cleanup job.

**Redis configuration requirement:**
Redis must have keyspace notifications enabled for expired events:
```
CONFIG SET notify-keyspace-events Ex
```
This should be set in the Redis configuration or via `docker-compose.yml` command override.

### Cleanup service — `SessionCleanupService`

A new service at `app/services/session_cleanup.py` encapsulates all purge logic:

```python
class SessionCleanupService:
    """Purges raw session data and logs deletion audits."""

    CLEANUP_DELAY_SECONDS = 600       # 10-minute window
    MAX_RETRIES = 3                   # Retry on transient failure
    SWEEP_INTERVAL_SECONDS = 1800     # Safety-net sweep every 30 min

    async def schedule_cleanup(session_id: str, interview_id: str) -> None
    async def execute_cleanup(session_id: str, interview_id: str) -> None
    async def purge_transcript_turns(interview_id: UUID, db: AsyncSession) -> int
    async def purge_transcript_header(interview_id: UUID, db: AsyncSession) -> int
    async def purge_session_context(session_id: UUID, db: AsyncSession) -> bool
    async def purge_local_files(session_id: str) -> list[str]
    async def run_sweep() -> None
```

**Deletion order** (respects foreign keys):
1. `interview_transcript_turns` (child rows first)
2. `interview_transcripts` (parent row)
3. `interview_sessions.transcript_json` / `report_json` → set to `NULL`
4. Local JSON files → `os.unlink()`

### Retry strategy

Each cleanup attempt uses exponential backoff:
- Attempt 1: immediate
- Attempt 2: after 5 seconds
- Attempt 3: after 15 seconds

If all 3 attempts fail, a `CRITICAL`-level structured log is emitted and the audit log records a `failed` status. The safety-net sweep will pick up the session on its next run.

### Safety-net sweep

A background `asyncio` task runs every 30 minutes within the FastAPI lifespan. It queries for sessions where:
- `interview_sessions.completed_at` or `interview_sessions.updated_at` is older than 10 minutes ago
- Related `interview_transcript_turns` rows still exist

Any matching sessions get cleaned up immediately, with audit entries noting they were caught by the sweep rather than the primary path.

### Deletion audit log

#### Database table: `data_deletion_audit_logs`

```python
class DataDeletionAuditLog(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "data_deletion_audit_logs"

    session_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    interview_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    deletion_type: Mapped[str] = mapped_column(String(50), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # success | failed
    triggered_by: Mapped[str] = mapped_column(String(30), nullable=False)  # timer | sweep
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

**Deletion types:**
- `transcript_turns` — rows deleted from `interview_transcript_turns`
- `transcript_header` — row deleted from `interview_transcripts`
- `session_transcript_json` — `transcript_json` field nullified on `interview_sessions`
- `session_report_json` — `report_json` field nullified on `interview_sessions`
- `local_transcript_file` — JSON file deleted from disk

**Example audit entries for a single session cleanup:**

| session_id | deletion_type | item_count | detail | status | triggered_by |
|---|---|---|---|---|---|
| abc-123 | transcript_turns | 24 | 24 rows deleted | success | timer |
| abc-123 | transcript_header | 1 | 1 row deleted | success | timer |
| abc-123 | session_transcript_json | 1 | field nullified | success | timer |
| abc-123 | session_report_json | 1 | field nullified | success | timer |
| abc-123 | local_transcript_file | 1 | abc-123-1717500000.json | success | timer |

#### Structured logs

In addition to DB entries, each deletion operation emits a structured log at `INFO` level:

```json
{
  "event": "data_deletion",
  "session_id": "abc-123",
  "deletion_type": "transcript_turns",
  "item_count": 24,
  "status": "success",
  "triggered_by": "timer"
}
```

Failures emit at `CRITICAL` level for alerting via OpenTelemetry.

## API contract

### GET /api/v1/admin/deletion-audits

Read-only endpoint for compliance checks. Returns audit log entries with filtering support.

**Query parameters:**
- `session_id` (optional) — filter by session
- `status` (optional) — filter by `success` or `failed`
- `triggered_by` (optional) — filter by `timer` or `sweep`
- `from_date` / `to_date` (optional) — date range filter
- `limit` (default: 50, max: 200)
- `offset` (default: 0)

**Response:**
```json
{
  "success": true,
  "message": "Deletion audit logs retrieved",
  "data": {
    "total": 120,
    "audits": [
      {
        "id": "uuid",
        "session_id": "abc-123",
        "interview_id": "uuid",
        "deletion_type": "transcript_turns",
        "item_count": 24,
        "detail": "24 rows deleted",
        "status": "success",
        "triggered_by": "timer",
        "deleted_at": "2026-06-04T15:45:00Z"
      }
    ]
  }
}
```

**Auth:** Requires admin role (reuse existing auth guard pattern).

## Implementation details

### New files

| File | Purpose |
|---|---|
| `app/services/session_cleanup.py` | `SessionCleanupService` — purge logic, retry, scheduling |
| `app/models/audit.py` | `DataDeletionAuditLog` model |
| `app/schemas/audit.py` | Pydantic response schemas for audit endpoint |
| `app/api/v1/routes/admin.py` | Admin audit query endpoint |
| `alembic/versions/xxx_add_deletion_audit_logs.py` | Migration for the new table |

### Modified files

| File | Change |
|---|---|
| `app/agent/interviewer.py` | Add `schedule_cleanup()` call at end of `on_shutdown` |
| `app/main.py` | Start Redis keyspace listener + sweep cron in lifespan |
| `app/core/redis.py` | Add keyspace notification subscription helper |
| `app/api/v1/router.py` | Mount admin routes |
| `docker-compose.yml` | Add Redis `notify-keyspace-events Ex` config |

### Redis keyspace listener (in `main.py` lifespan)

```python
@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Starting %s", settings.PROJECT_NAME)
    
    # Start cleanup listener and sweep
    cleanup_listener_task = asyncio.create_task(
        SessionCleanupService.listen_for_expirations()
    )
    sweep_task = asyncio.create_task(
        SessionCleanupService.run_periodic_sweep()
    )
    
    yield
    
    # Shutdown
    cleanup_listener_task.cancel()
    sweep_task.cancel()
    await engine.dispose()
    await redis_client.aclose()
```

### Agent integration (in `interviewer.py`)

Add to the end of `on_shutdown`:
```python
async def on_shutdown():
    # ... existing transcript save + report generation ...
    await post_result(session_id, turns, report)
    
    # Schedule privacy cleanup after 10-minute window
    await SessionCleanupService.schedule_cleanup(session_id, interview_id)
```

## Testing

### Unit tests (`tests/test_session_cleanup.py`)

- Transcript turns are deleted after cleanup executes
- Transcript header is deleted after turns are removed
- Session context fields (`transcript_json`, `report_json`) are nullified
- Local JSON files are deleted
- Audit log entries are created for each deletion type
- Failed deletions are logged with `status=failed`
- Retry logic attempts up to 3 times on transient failure
- Sweep catches sessions that escaped primary cleanup
- Assessment/grading data is NOT deleted

### Integration tests

- Redis key expiration triggers cleanup within ~10 minutes
- Full end-to-end: session end → key set → key expires → data purged → audit logged
- Concurrent cleanup requests for the same session are idempotent

### Admin endpoint tests (`tests/test_admin_audit.py`)

- `GET /deletion-audits` returns paginated results
- Filtering by `session_id`, `status`, `triggered_by`, date range works
- Non-admin users receive 403
- 401 without token

## Migration notes

### Redis configuration
The `notify-keyspace-events` setting must be applied to all Redis instances (dev, staging, production). Add to `docker-compose.yml`:
```yaml
redis:
  image: redis:7-alpine
  command: redis-server --notify-keyspace-events Ex
```

### Database migration
Run `alembic upgrade head` after deploying to create the `data_deletion_audit_logs` table.

### Rollback plan
- The cleanup service is additive — disabling it returns to current behavior (data retained indefinitely)
- Drop the `data_deletion_audit_logs` table via a down migration
- Remove the Redis keyspace listener from lifespan
- Remove the `schedule_cleanup()` call from `on_shutdown`
