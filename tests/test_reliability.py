import asyncio
import json
import uuid
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import retry_async
from app.models.interview import Interview, InterviewSession, InterviewTranscript
from app.models.user import User
from app.services.chat_history import ChatHistoryService
from app.services.ai_generation_service import AIGenerationService


# --- Helper to create a user ---
async def create_test_user(db: AsyncSession) -> User:
    user = User(
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        is_verified=True
    )
    db.add(user)
    await db.flush()
    return user


# ── Retry Utility Tests ──────────────────────────────────────────────

@pytest.mark.anyio
async def test_retry_async_success_immediately():
    calls = 0

    async def dummy_func(x):
        nonlocal calls
        calls += 1
        return x * 2

    res = await retry_async(
        dummy_func,
        5,
        max_retries=3,
        initial_delay=0.01,
        backoff_factor=1.5,
        task_name="test_immediate_success"
    )

    assert res == 10
    assert calls == 1


@pytest.mark.anyio
async def test_retry_async_success_after_failure():
    calls = 0

    async def dummy_func():
        nonlocal calls
        calls += 1
        if calls < 2:
            raise ValueError("Transient error")
        return "Success"

    res = await retry_async(
        dummy_func,
        max_retries=3,
        initial_delay=0.01,
        backoff_factor=1.5,
        exceptions=(ValueError,),
        task_name="test_success_after_failure"
    )

    assert res == "Success"
    assert calls == 2


@pytest.mark.anyio
async def test_retry_async_failure_exhaustion():
    calls = 0

    async def dummy_func():
        nonlocal calls
        calls += 1
        raise KeyError("Persistent failure")

    with pytest.raises(KeyError):
        await retry_async(
            dummy_func,
            max_retries=3,
            initial_delay=0.01,
            backoff_factor=1.5,
            exceptions=(KeyError,),
            task_name="test_exhaustion"
        )

    assert calls == 3


# ── Transcript Fallback Tests ────────────────────────────────────────

@pytest.mark.anyio
async def test_transcript_fallback_chat_history(db_session: AsyncSession):
    user = await create_test_user(db_session)

    # 1. Create a session with transcript JSON populated
    session = InterviewSession(
        role="Fallback Engineer",
        intro="Intro",
        questions_json="[]",
        rubric_json="[]",
        closing="Closing",
        status="completed",
        transcript_json=json.dumps([
            {"speaker": "ai", "content": "Welcome to MeetMind.", "sequence_no": 1, "timestamp_sec": 10},
            {"speaker": "candidate", "content": "Thanks!", "sequence_no": 2, "timestamp_sec": 25}
        ])
    )
    db_session.add(session)
    await db_session.flush()

    # 2. Create Interview linking to that session, but NO turns in DB
    interview = Interview(
        workspace_id=uuid.uuid4(),
        candidate_id=None,
        interviewer_id=user.id,
        session_id=session.id,
        role_title="Fallback Engineer",
        status="completed"
    )
    db_session.add(interview)
    await db_session.commit()

    # 3. Request Chat History - it should fetch from session JSON
    history = await ChatHistoryService.get_chat_history(
        interview_id=interview.id,
        db=db_session,
        user=user
    )

    assert history.total_messages == 2
    assert history.messages[0].role == "ai"
    assert history.messages[0].content == "Welcome to MeetMind."
    assert history.messages[0].sequence_no == 1
    assert history.messages[1].role == "candidate"
    assert history.messages[1].content == "Thanks!"
    assert history.messages[1].sequence_no == 2


@pytest.mark.anyio
async def test_transcript_fallback_get_transcript(db_session: AsyncSession):
    user = await create_test_user(db_session)

    session = InterviewSession(
        role="Fallback Engineer",
        intro="Intro",
        questions_json="[]",
        rubric_json="[]",
        closing="Closing",
        status="completed",
        transcript_json=json.dumps([
            {"speaker": "ai", "content": "Welcome.", "sequence_no": 1, "timestamp_sec": 60},
            {"speaker": "candidate", "content": "Hello.", "sequence_no": 2, "timestamp_sec": 90}
        ])
    )
    db_session.add(session)
    await db_session.flush()

    interview = Interview(
        workspace_id=uuid.uuid4(),
        candidate_id=None,
        interviewer_id=user.id,
        session_id=session.id,
        role_title="Fallback Engineer",
        status="completed"
    )
    db_session.add(interview)
    await db_session.commit()

    # Request Transcript
    resp = await ChatHistoryService.get_transcript(
        interview_id=interview.id,
        db=db_session,
        user=user
    )

    assert resp.total_turns == 2
    assert resp.turns[0].speaker == "meet_mind"
    assert resp.turns[0].timestamp == "00:00:00"  # Relativized
    assert resp.turns[1].speaker == "candidate"
    assert resp.turns[1].timestamp == "00:00:30"  # Relativized (90s - 60s)


@pytest.mark.anyio
async def test_transcript_fallback_get_transcript_export(db_session: AsyncSession):
    user = await create_test_user(db_session)

    session = InterviewSession(
        role="Fallback Engineer",
        intro="Intro",
        questions_json="[]",
        rubric_json="[]",
        closing="Closing",
        status="completed",
        transcript_json=json.dumps([
            {"speaker": "ai", "content": "Welcome.", "sequence_no": 1, "timestamp_sec": 10},
            {"speaker": "candidate", "content": "Hello.", "sequence_no": 2, "timestamp_sec": 40}
        ])
    )
    db_session.add(session)
    await db_session.flush()

    interview = Interview(
        workspace_id=uuid.uuid4(),
        candidate_id=None,
        interviewer_id=user.id,
        session_id=session.id,
        role_title="Fallback Engineer",
        status="completed"
    )
    db_session.add(interview)
    await db_session.commit()

    # Request export lines
    lines = await ChatHistoryService.get_transcript_export(
        interview_id=interview.id,
        db=db_session,
        user=user
    )

    assert len(lines) == 2
    assert "[00:00:00] Meet Mind: Welcome.\n" in lines
    assert "[00:00:30] Candidate: Hello.\n" in lines


@pytest.mark.anyio
async def test_transcript_fallback_format_turns_text(db_session: AsyncSession):
    session = InterviewSession(
        role="Fallback Engineer",
        intro="Intro",
        questions_json="[]",
        rubric_json="[]",
        closing="Closing",
        status="completed",
        transcript_json=json.dumps([
            {"speaker": "ai", "content": "Welcome.", "sequence_no": 1, "timestamp_sec": 10},
            {"speaker": "candidate", "content": "Hello.", "sequence_no": 2, "timestamp_sec": 40}
        ])
    )
    db_session.add(session)
    await db_session.flush()

    interview = Interview(
        workspace_id=uuid.uuid4(),
        candidate_id=None,
        interviewer_id=uuid.uuid4(),
        session_id=session.id,
        role_title="Fallback Engineer",
        status="completed"
    )
    db_session.add(interview)
    await db_session.commit()

    # Format turns text
    text = await AIGenerationService._format_turns_text(
        interview_id=interview.id,
        db=db_session
    )

    assert text == "Interviewer: Welcome.\nCandidate: Hello."
