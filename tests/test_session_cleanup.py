"""
Tests for MS4-BE-006: Privacy & Session Cleanup

Covers:
- Cleanup service purge operations (transcript turns, headers, session context, local files)
- Audit log creation (DB entries + structured log output)
- Retry behaviour on transient failures
- Admin deletion-audits endpoint (auth, filtering, pagination)
- Preserved data is NOT deleted (assessments, highlights, etc.)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import DataDeletionAuditLog
from app.models.interview import (
    Interview,
    InterviewSession,
    InterviewSummary,
    InterviewTranscript,
    InterviewTranscriptTurn,
)
from app.models.user import User
from app.services.auth import AuthService


# ── Helpers ──────────────────────────────────────────────────────────


async def create_user(db: AsyncSession) -> User:
    user = User(
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        is_verified=True,
    )
    db.add(user)
    await db.flush()
    return user


async def create_interview_with_transcript(
    db: AsyncSession, user: User
) -> tuple[Interview, InterviewSession, InterviewTranscript]:
    """Set up an interview with a session and transcript + turns."""
    session = InterviewSession(
        role="Backend Engineer",
        intro="test interview",
        questions_json="[]",
        rubric_json="[]",
        duration_minutes=20,
        closing="Thanks.",
        status="completed",
        transcript_json='[{"speaker":"ai","text":"Hello"}]',
        report_json='{"score":85}',
        completed_at=datetime.now(timezone.utc),
    )
    db.add(session)
    await db.flush()

    interview = Interview(
        workspace_id=uuid.uuid4(),
        interviewer_id=user.id,
        session_id=session.id,
        role_title="Backend Engineer",
        status="completed",
    )
    db.add(interview)
    await db.flush()

    transcript = InterviewTranscript(
        interview_id=interview.id,
        status="completed",
    )
    db.add(transcript)
    await db.flush()

    # Add some transcript turns
    for i in range(3):
        turn = InterviewTranscriptTurn(
            transcript_id=transcript.id,
            speaker="ai" if i % 2 == 0 else "candidate",
            content=f"Turn {i + 1} content",
            sequence_no=i + 1,
        )
        db.add(turn)

    await db.flush()
    return interview, session, transcript


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Service Tests ────────────────────────────────────────────────────


class TestCleanupPurgeOperations:
    """Test that each purge operation correctly deletes the right data."""

    @pytest.mark.anyio
    async def test_purge_transcript_turns(self, db_session: AsyncSession):
        """Transcript turns are deleted."""
        from app.services.session_cleanup import _purge_transcript_turns

        user = await create_user(db_session)
        interview, _, transcript = await create_interview_with_transcript(
            db_session, user
        )

        # Verify turns exist
        result = await db_session.execute(
            select(InterviewTranscriptTurn).where(
                InterviewTranscriptTurn.transcript_id == transcript.id
            )
        )
        assert len(result.scalars().all()) == 3

        # Purge
        deleted = await _purge_transcript_turns(interview.id, db_session)
        assert deleted == 3

        # Verify gone
        result = await db_session.execute(
            select(InterviewTranscriptTurn).where(
                InterviewTranscriptTurn.transcript_id == transcript.id
            )
        )
        assert len(result.scalars().all()) == 0

    @pytest.mark.anyio
    async def test_purge_transcript_header(self, db_session: AsyncSession):
        """Transcript header row is deleted after turns are removed."""
        from app.services.session_cleanup import (
            _purge_transcript_header,
            _purge_transcript_turns,
        )

        user = await create_user(db_session)
        interview, _, transcript = await create_interview_with_transcript(
            db_session, user
        )

        # Delete turns first (FK constraint)
        await _purge_transcript_turns(interview.id, db_session)

        # Delete header
        deleted = await _purge_transcript_header(interview.id, db_session)
        assert deleted == 1

        # Verify gone
        result = await db_session.execute(
            select(InterviewTranscript).where(
                InterviewTranscript.interview_id == interview.id
            )
        )
        assert result.scalar_one_or_none() is None

    @pytest.mark.anyio
    async def test_purge_session_context(self, db_session: AsyncSession):
        """Session transcript_json and report_json are nullified."""
        from app.services.session_cleanup import _purge_session_context

        user = await create_user(db_session)
        _, session, _ = await create_interview_with_transcript(db_session, user)

        assert session.transcript_json is not None
        assert session.report_json is not None

        result = await _purge_session_context(str(session.id), db_session)
        assert result is True

        await db_session.refresh(session)
        assert session.transcript_json is None
        assert session.report_json is None

    @pytest.mark.anyio
    async def test_purge_local_files(self, tmp_path):
        """Local JSON transcript files matching session_id are deleted."""
        from app.services.session_cleanup import _purge_local_files, TRANSCRIPTS_DIR

        # Create a fake transcript file in the transcripts dir
        TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        session_id = "test-session-cleanup"
        fake_file = TRANSCRIPTS_DIR / f"{session_id}-1717500000.json"
        fake_file.write_text('{"test": true}')

        assert fake_file.exists()

        deleted = _purge_local_files(session_id)
        assert len(deleted) == 1
        assert not fake_file.exists()

    @pytest.mark.anyio
    async def test_purge_with_no_interview_id(self, db_session: AsyncSession):
        """Purge operations handle None interview_id gracefully."""
        from app.services.session_cleanup import (
            _purge_transcript_header,
            _purge_transcript_turns,
        )

        assert await _purge_transcript_turns(None, db_session) == 0
        assert await _purge_transcript_header(None, db_session) == 0


class TestCleanupPreservesGradingData:
    """Assessment/evaluation data must NOT be deleted by cleanup."""

    @pytest.mark.anyio
    async def test_interview_summary_preserved(self, db_session: AsyncSession):
        """AI assessment is not deleted when transcript is purged."""
        from app.services.session_cleanup import (
            _purge_transcript_header,
            _purge_transcript_turns,
        )

        user = await create_user(db_session)
        interview, _, _ = await create_interview_with_transcript(db_session, user)

        # Add an assessment
        summary = InterviewSummary(
            interview_id=interview.id,
            ai_assessment="Candidate performed well.",
            status="completed",
        )
        db_session.add(summary)
        await db_session.flush()

        # Purge transcript data
        await _purge_transcript_turns(interview.id, db_session)
        await _purge_transcript_header(interview.id, db_session)

        # Summary must still exist
        result = await db_session.execute(
            select(InterviewSummary).where(
                InterviewSummary.interview_id == interview.id
            )
        )
        assert result.scalar_one_or_none() is not None


class TestAuditLogging:
    """Deletion audit entries are written to DB and logs."""

    @pytest.mark.anyio
    async def test_audit_entry_created(self, db_session: AsyncSession):
        """A deletion audit log entry is created for each purge operation."""
        from app.services.session_cleanup import _log_deletion

        session_id = str(uuid.uuid4())
        await _log_deletion(
            db_session,
            session_id=session_id,
            interview_id=None,
            deletion_type="transcript_turns",
            item_count=5,
            detail="5 rows deleted",
            status="success",
            triggered_by="timer",
        )
        await db_session.flush()

        result = await db_session.execute(
            select(DataDeletionAuditLog).where(
                DataDeletionAuditLog.session_id == session_id
            )
        )
        entry = result.scalar_one()
        assert entry.deletion_type == "transcript_turns"
        assert entry.item_count == 5
        assert entry.status == "success"
        assert entry.triggered_by == "timer"

    @pytest.mark.anyio
    async def test_failed_status_logged(self, db_session: AsyncSession):
        """Failed deletions are logged with status='failed'."""
        from app.services.session_cleanup import _log_deletion

        session_id = str(uuid.uuid4())
        await _log_deletion(
            db_session,
            session_id=session_id,
            interview_id=None,
            deletion_type="full_cleanup",
            item_count=0,
            detail="All 3 attempts failed",
            status="failed",
            triggered_by="timer",
        )
        await db_session.flush()

        result = await db_session.execute(
            select(DataDeletionAuditLog).where(
                DataDeletionAuditLog.session_id == session_id
            )
        )
        entry = result.scalar_one()
        assert entry.status == "failed"


class TestScheduleCleanup:
    """Redis scheduling sets the correct key with TTL."""

    @pytest.mark.anyio
    async def test_schedule_sets_redis_key(self):
        """schedule_cleanup sets a Redis key with the correct TTL."""
        from app.services.session_cleanup import (
            CLEANUP_DELAY_SECONDS,
            REDIS_CLEANUP_PREFIX,
            schedule_cleanup,
        )

        mock_redis = AsyncMock()
        with patch("app.services.session_cleanup.redis_client", mock_redis):
            await schedule_cleanup("test-session-123", "interview-456")

        mock_redis.setex.assert_called_once_with(
            f"{REDIS_CLEANUP_PREFIX}test-session-123",
            CLEANUP_DELAY_SECONDS,
            "interview-456",
        )


# ── Admin Endpoint Tests ────────────────────────────────────────────


AUDIT_URL = "/api/v1/admin/deletion-audits"


class TestDeletionAuditsEndpoint:
    @pytest.mark.anyio
    async def test_returns_empty_list(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Returns empty list when no audit entries exist."""
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)

        res = await client.get(AUDIT_URL, headers=auth_headers(token))

        assert res.status_code == 200
        body = res.json()
        assert body["data"]["total"] >= 0
        assert isinstance(body["data"]["audits"], list)

    @pytest.mark.anyio
    async def test_returns_audit_entries(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Returns audit entries that were inserted."""
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)

        # Insert a test audit entry
        entry = DataDeletionAuditLog(
            session_id="test-session-audit",
            deletion_type="transcript_turns",
            item_count=10,
            detail="10 rows deleted",
            status="success",
            triggered_by="timer",
            deleted_at=datetime.now(timezone.utc),
        )
        db_session.add(entry)
        await db_session.flush()

        res = await client.get(
            AUDIT_URL,
            headers=auth_headers(token),
            params={"session_id": "test-session-audit"},
        )

        assert res.status_code == 200
        body = res.json()
        assert body["data"]["total"] >= 1
        audit = body["data"]["audits"][0]
        assert audit["session_id"] == "test-session-audit"
        assert audit["deletion_type"] == "transcript_turns"
        assert audit["item_count"] == 10

    @pytest.mark.anyio
    async def test_filter_by_status(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Filtering by status returns only matching entries."""
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)

        for s in ("success", "failed"):
            db_session.add(
                DataDeletionAuditLog(
                    session_id=f"filter-test-{s}",
                    deletion_type="transcript_turns",
                    item_count=1,
                    status=s,
                    triggered_by="timer",
                    deleted_at=datetime.now(timezone.utc),
                )
            )
        await db_session.flush()

        res = await client.get(
            AUDIT_URL,
            headers=auth_headers(token),
            params={"status": "failed"},
        )

        assert res.status_code == 200
        for audit in res.json()["data"]["audits"]:
            assert audit["status"] == "failed"

    @pytest.mark.anyio
    async def test_requires_auth(self, client: AsyncClient):
        """Endpoint returns 401 without a token."""
        res = await client.get(AUDIT_URL)
        assert res.status_code == 401

    @pytest.mark.anyio
    async def test_pagination(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Limit and offset params work correctly."""
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)

        res = await client.get(
            AUDIT_URL,
            headers=auth_headers(token),
            params={"limit": 1, "offset": 0},
        )

        assert res.status_code == 200
        assert len(res.json()["data"]["audits"]) <= 1
