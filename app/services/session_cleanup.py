"""Privacy cleanup service — purges raw session data after a 10-minute window.

Scheduling uses Redis key TTL + keyspace notifications.  A periodic sweep
acts as a safety net for sessions that escape the primary cleanup path.
"""

from __future__ import annotations

import asyncio
import glob
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import redis.asyncio as aioredis
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import redis_client
from app.db.session import AsyncSessionLocal
from app.models.audit import DataDeletionAuditLog
from app.models.interview import (
    InterviewSession,
    InterviewTranscript,
    InterviewTranscriptTurn,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLEANUP_DELAY_SECONDS = 600  # 10-minute privacy window
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = [0, 5, 15]  # immediate, 5s, 15s
SWEEP_INTERVAL_SECONDS = 1800  # safety-net sweep every 30 min
REDIS_CLEANUP_PREFIX = "cleanup:"
TRANSCRIPTS_DIR = Path(__file__).resolve().parent.parent / "agent" / "transcripts"


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------


async def schedule_cleanup(session_id: str, interview_id: str | None = None) -> None:
    """Set a Redis key with a 600-second TTL to trigger cleanup on expiry."""
    key = f"{REDIS_CLEANUP_PREFIX}{session_id}"
    value = interview_id or ""
    try:
        await redis_client.setex(key, CLEANUP_DELAY_SECONDS, value)
        logger.info(
            "Scheduled cleanup for session %s in %ds",
            session_id,
            CLEANUP_DELAY_SECONDS,
        )
    except aioredis.RedisError:
        logger.exception("Failed to schedule cleanup for session %s", session_id)


# ---------------------------------------------------------------------------
# Cleanup orchestration
# ---------------------------------------------------------------------------


async def execute_cleanup(
    session_id: str,
    interview_id: str | None = None,
    triggered_by: str = "timer",
) -> None:
    """Run the full cleanup pipeline with retries."""
    for attempt in range(MAX_RETRIES):
        try:
            if attempt > 0:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS[attempt])

            async with AsyncSessionLocal() as db:
                # Resolve interview_id from session if not provided
                resolved_interview_id = await _resolve_interview_id(
                    session_id, interview_id, db
                )

                # 1. Purge transcript turns (child rows first)
                turns_deleted = await _purge_transcript_turns(resolved_interview_id, db)
                await _log_deletion(
                    db,
                    session_id=session_id,
                    interview_id=resolved_interview_id,
                    deletion_type="transcript_turns",
                    item_count=turns_deleted,
                    detail=f"{turns_deleted} rows deleted",
                    status="success",
                    triggered_by=triggered_by,
                )

                # 2. Purge transcript header (parent row)
                headers_deleted = await _purge_transcript_header(
                    resolved_interview_id, db
                )
                await _log_deletion(
                    db,
                    session_id=session_id,
                    interview_id=resolved_interview_id,
                    deletion_type="transcript_header",
                    item_count=headers_deleted,
                    detail=f"{headers_deleted} row deleted",
                    status="success",
                    triggered_by=triggered_by,
                )

                # 3. Nullify session context fields
                context_cleared = await _purge_session_context(session_id, db)
                if context_cleared:
                    await _log_deletion(
                        db,
                        session_id=session_id,
                        interview_id=resolved_interview_id,
                        deletion_type="session_transcript_json",
                        item_count=1,
                        detail="field nullified",
                        status="success",
                        triggered_by=triggered_by,
                    )
                    await _log_deletion(
                        db,
                        session_id=session_id,
                        interview_id=resolved_interview_id,
                        deletion_type="session_report_json",
                        item_count=1,
                        detail="field nullified",
                        status="success",
                        triggered_by=triggered_by,
                    )

                # 4. Delete local JSON transcript files
                deleted_files = _purge_local_files(session_id)
                for fname in deleted_files:
                    await _log_deletion(
                        db,
                        session_id=session_id,
                        interview_id=resolved_interview_id,
                        deletion_type="local_transcript_file",
                        item_count=1,
                        detail=fname,
                        status="success",
                        triggered_by=triggered_by,
                    )

                await db.commit()

            logger.info(
                "Cleanup completed for session %s (triggered_by=%s)",
                session_id,
                triggered_by,
            )
            return  # Success — exit retry loop

        except Exception:
            logger.exception(
                "Cleanup attempt %d/%d failed for session %s",
                attempt + 1,
                MAX_RETRIES,
                session_id,
            )

    # All retries exhausted
    logger.critical(
        "Cleanup FAILED after %d attempts for session %s", MAX_RETRIES, session_id
    )
    try:
        async with AsyncSessionLocal() as db:
            await _log_deletion(
                db,
                session_id=session_id,
                interview_id=None,
                deletion_type="full_cleanup",
                item_count=0,
                detail=f"All {MAX_RETRIES} attempts failed",
                status="failed",
                triggered_by=triggered_by,
            )
            await db.commit()
    except Exception:
        logger.exception("Failed to log cleanup failure for session %s", session_id)


# ---------------------------------------------------------------------------
# Individual purge operations
# ---------------------------------------------------------------------------


async def _resolve_interview_id(
    session_id: str,
    interview_id: str | None,
    db: AsyncSession,
) -> uuid.UUID | None:
    """Resolve the interview UUID from either the provided id or session lookup."""
    if interview_id:
        try:
            return uuid.UUID(interview_id)
        except ValueError:
            pass

    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        return None

    from app.models.interview import Interview

    result = await db.execute(
        select(Interview.id).where(Interview.session_id == session_uuid)
    )
    row = result.scalar_one_or_none()
    return row


async def _purge_transcript_turns(
    interview_id: uuid.UUID | None, db: AsyncSession
) -> int:
    """Delete all transcript turn rows for the given interview."""
    if not interview_id:
        return 0

    # Find transcript(s) for this interview
    result = await db.execute(
        select(InterviewTranscript.id).where(
            InterviewTranscript.interview_id == interview_id
        )
    )
    transcript_ids = [row[0] for row in result.all()]

    if not transcript_ids:
        return 0

    del_result = await db.execute(
        delete(InterviewTranscriptTurn).where(
            InterviewTranscriptTurn.transcript_id.in_(transcript_ids)
        )
    )
    return del_result.rowcount  # type: ignore[return-value]


async def _purge_transcript_header(
    interview_id: uuid.UUID | None, db: AsyncSession
) -> int:
    """Delete transcript header rows for the given interview."""
    if not interview_id:
        return 0

    del_result = await db.execute(
        delete(InterviewTranscript).where(
            InterviewTranscript.interview_id == interview_id
        )
    )
    return del_result.rowcount  # type: ignore[return-value]


async def _purge_session_context(session_id: str, db: AsyncSession) -> bool:
    """Nullify transcript_json and report_json on the interview session row."""
    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        return False

    result = await db.execute(
        update(InterviewSession)
        .where(InterviewSession.id == session_uuid)
        .values(transcript_json=None, report_json=None)
    )
    return result.rowcount > 0  # type: ignore[return-value]


def _purge_local_files(session_id: str) -> list[str]:
    """Delete local JSON transcript backups matching the session id."""
    deleted: list[str] = []
    pattern = str(TRANSCRIPTS_DIR / f"{session_id}-*.json")
    for filepath in glob.glob(pattern):
        try:
            os.unlink(filepath)
            deleted.append(os.path.basename(filepath))
            logger.info("Deleted local transcript file: %s", filepath)
        except OSError:
            logger.exception("Failed to delete local file: %s", filepath)
    return deleted


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------


async def _log_deletion(
    db: AsyncSession,
    *,
    session_id: str,
    interview_id: uuid.UUID | None,
    deletion_type: str,
    item_count: int,
    detail: str | None,
    status: str,
    triggered_by: str,
) -> None:
    """Write a deletion audit row and emit a structured log."""
    now = datetime.now(timezone.utc)

    audit_entry = DataDeletionAuditLog(
        session_id=session_id,
        interview_id=interview_id,
        deletion_type=deletion_type,
        item_count=item_count,
        detail=detail,
        status=status,
        triggered_by=triggered_by,
        deleted_at=now,
    )
    db.add(audit_entry)

    # Structured log for real-time observability
    log_level = logging.CRITICAL if status == "failed" else logging.INFO
    logger.log(
        log_level,
        "data_deletion event=%s session_id=%s deletion_type=%s "
        "item_count=%d status=%s triggered_by=%s",
        "data_deletion",
        session_id,
        deletion_type,
        item_count,
        status,
        triggered_by,
    )


# ---------------------------------------------------------------------------
# Redis keyspace notification listener
# ---------------------------------------------------------------------------


async def listen_for_expirations() -> None:
    """Subscribe to Redis keyspace expired events and dispatch cleanup jobs.

    Runs as a long-lived background task within the FastAPI lifespan.
    """
    # Ensure keyspace notifications are enabled
    try:
        await redis_client.config_set("notify-keyspace-events", "Ex")
    except aioredis.RedisError:
        logger.warning(
            "Could not set notify-keyspace-events — ensure Redis is configured "
            "with 'notify-keyspace-events Ex'"
        )

    pubsub = redis_client.pubsub()
    # Subscribe to expired events on DB 0
    channel = "__keyevent@0__:expired"
    await pubsub.subscribe(channel)
    logger.info("Listening for Redis keyspace expiration events on %s", channel)

    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue

            key = message["data"]
            if isinstance(key, bytes):
                key = key.decode("utf-8")

            if not key.startswith(REDIS_CLEANUP_PREFIX):
                continue

            session_id = key[len(REDIS_CLEANUP_PREFIX) :]
            logger.info("Expiration event received for session %s", session_id)

            # Dispatch cleanup as a fire-and-forget task so we don't
            # block the listener on slow DB operations
            asyncio.create_task(execute_cleanup(session_id, triggered_by="timer"))
    except asyncio.CancelledError:
        logger.info("Keyspace listener shutting down")
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()


# ---------------------------------------------------------------------------
# Safety-net periodic sweep
# ---------------------------------------------------------------------------


async def run_periodic_sweep() -> None:
    """Every SWEEP_INTERVAL_SECONDS, find stale sessions and clean them up.

    A session is considered stale if it completed more than
    CLEANUP_DELAY_SECONDS ago but still has transcript data.
    """
    logger.info(
        "Periodic sweep started (interval=%ds, cleanup_window=%ds)",
        SWEEP_INTERVAL_SECONDS,
        CLEANUP_DELAY_SECONDS,
    )
    try:
        while True:
            await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
            try:
                await _sweep_stale_sessions()
            except Exception:
                logger.exception("Periodic sweep iteration failed")
    except asyncio.CancelledError:
        logger.info("Periodic sweep shutting down")


async def _sweep_stale_sessions() -> None:
    """Find and clean sessions that escaped the primary cleanup path."""
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=CLEANUP_DELAY_SECONDS)

    async with AsyncSessionLocal() as db:
        # Find sessions that completed before the cutoff and still have
        # transcript data linked to their interview
        result = await db.execute(
            select(InterviewSession.id, InterviewTranscript.interview_id)
            .join(
                InterviewTranscript,
                InterviewTranscript.interview_id == InterviewSession.id,
                isouter=False,
            )
            .where(
                InterviewSession.completed_at.isnot(None),
                InterviewSession.completed_at < cutoff,
            )
        )
        stale = result.all()

    if not stale:
        logger.debug("Sweep: no stale sessions found")
        return

    logger.warning("Sweep: found %d stale session(s) to clean", len(stale))
    for session_id, _interview_id in stale:
        await execute_cleanup(str(session_id), triggered_by="sweep")
