from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.agent.interview import build_instructions, interview_from_api
from app.models.interview import (
    Interview,
    InterviewSummary,
    InterviewTranscript,
    InterviewTranscriptTurn,
)
from app.models.user import User
from app.services.auth import AuthService
from tests.test_helpers import create_interview_via_route

LIVEKIT_URL = "/api/v1/livekit"
INTERVIEWS_URL = "/api/v1/interviews"


async def create_user(db: AsyncSession, email: str | None = None) -> User:
    user = User(email=email or f"{uuid.uuid4().hex[:8]}@example.com", is_verified=True)
    db.add(user)
    await db.flush()
    return user


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def create_scheduled_interview(
    client: AsyncClient,
    db_session: AsyncSession,
    *,
    full_name: str = "John Doe",
    overrides: dict | None = None,
) -> tuple[User, str, Interview]:
    user = await create_user(db_session)
    token = await AuthService.create_access_token(user)
    response = await create_interview_via_route(
        client=client,
        db_session=db_session,
        token=token,
        candidate_kwargs={
            "full_name": full_name,
            "email": f"{uuid.uuid4().hex}@example.com",
        },
        interview_overrides={
            "role_title": "Senior Backend Engineer",
            "platform": "livekit",
            "scheduled_start": "2026-06-01T09:00:00Z",
            "scheduled_end": "2026-06-01T10:30:00Z",
            "skills_to_assess": ["Communication", "API Design"],
            "job_description": "Build APIs for a high-scale backend platform.",
            **(overrides or {}),
        },
    )
    interview = await db_session.get(
        Interview, uuid.UUID(response.json()["data"]["id"])
    )
    return user, token, interview


@pytest.fixture(autouse=True)
def livekit_settings(monkeypatch):
    monkeypatch.setattr(settings, "LIVEKIT_API_KEY", "devkey")
    monkeypatch.setattr(settings, "LIVEKIT_API_SECRET", "devsecret")
    monkeypatch.setattr(settings, "LIVEKIT_URL", "wss://livekit.example.test")


@pytest.mark.anyio
async def test_agent_config_returns_404_for_unknown_interview_id(
    client: AsyncClient, db_session: AsyncSession
):
    response = await client.get(f"{LIVEKIT_URL}/{uuid.uuid4()}/config")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "interview_not_found"


@pytest.mark.anyio
async def test_agent_config_returns_full_context(
    client: AsyncClient, db_session: AsyncSession
):
    _, _, interview = await create_scheduled_interview(client, db_session)

    response = await client.get(f"{LIVEKIT_URL}/{interview.id}/config")

    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "Senior Backend Engineer"
    assert data["candidateName"] == "John Doe"
    assert data["durationMinutes"] > 0
    assert len(data["questions"]) > 0
    assert len(data["rubric"]) > 0
    assert data["jobDescription"] is not None
    assert data["participationMode"] == "standard"


def test_livekit_agent_prompt_includes_context_and_avoids_backend_default():
    interview = interview_from_api(
        {
            "role": "Product Designer",
            "intro": "a design interview",
            "candidateName": "Ada Lovelace",
            "durationMinutes": 30,
            "closing": "Thanks for speaking with us.",
            "jobDescription": "Design accessible dashboards for analytics teams.",
            "keySkills": ["UX Research", "Interaction Design"],
            "aiTone": "warm",
            "questions": [
                {
                    "text": "Walk me through a design project.",
                    "followUpHint": "Probe process and impact.",
                    "maxFollowUps": 2,
                }
            ],
            "rubric": [
                {
                    "name": "Design Process",
                    "description": "Uses a clear user-centered process.",
                    "weight": 3,
                }
            ],
        }
    )

    instructions = build_instructions(interview)

    assert "Design accessible dashboards" in instructions
    assert "UX Research, Interaction Design" in instructions
    assert "backend system" not in instructions


@pytest.mark.anyio
async def test_agent_config_sets_interview_in_progress(
    client: AsyncClient, db_session: AsyncSession
):
    _, _, interview = await create_scheduled_interview(client, db_session)

    await client.get(f"{LIVEKIT_URL}/{interview.id}/config")
    await db_session.refresh(interview)

    assert interview.status == "in_progress"
    assert interview.started_at is not None


@pytest.mark.anyio
async def test_agent_config_derives_duration_from_schedule(
    client: AsyncClient, db_session: AsyncSession
):
    _, _, interview = await create_scheduled_interview(client, db_session)

    response = await client.get(f"{LIVEKIT_URL}/{interview.id}/config")

    assert response.json()["durationMinutes"] == 90


@pytest.mark.anyio
async def test_agent_config_fetch_is_idempotent(
    client: AsyncClient, db_session: AsyncSession
):
    _, _, interview = await create_scheduled_interview(client, db_session)

    await client.get(f"{LIVEKIT_URL}/{interview.id}/config")
    response = await client.get(f"{LIVEKIT_URL}/{interview.id}/config")
    await db_session.refresh(interview)

    assert response.status_code == 200
    assert interview.status == "in_progress"
    assert interview.started_at is not None


@pytest.mark.anyio
async def test_token_returns_404_for_unknown_interview(
    client: AsyncClient, db_session: AsyncSession
):
    response = await client.post(f"{LIVEKIT_URL}/{uuid.uuid4()}/token", json={})

    assert response.status_code == 404


@pytest.mark.anyio
async def test_token_returns_correct_shape(
    client: AsyncClient, db_session: AsyncSession
):
    _, _, interview = await create_scheduled_interview(client, db_session)

    response = await client.post(f"{LIVEKIT_URL}/{interview.id}/token", json={})

    assert response.status_code == 200
    data = response.json()
    assert "participantToken" in data
    assert data["roomName"] == str(interview.id)
    assert data["participantName"] == "John Doe"
    assert "serverUrl" in data


@pytest.mark.anyio
async def test_token_rejected_for_completed_interview(
    client: AsyncClient, db_session: AsyncSession
):
    _, _, interview = await create_scheduled_interview(client, db_session)
    interview.status = "completed"
    await db_session.commit()

    response = await client.post(f"{LIVEKIT_URL}/{interview.id}/token", json={})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "interview_already_completed"


@pytest.mark.anyio
async def test_token_test_room_bypass_works(
    client: AsyncClient, db_session: AsyncSession
):
    response = await client.post(
        f"{LIVEKIT_URL}/test-room/token", json={"participant_name": "Test User"}
    )

    assert response.status_code == 200
    assert response.json()["roomName"] == "test-room"


@pytest.mark.anyio
async def test_transcript_turn_is_persisted(
    client: AsyncClient, db_session: AsyncSession
):
    _, _, interview = await create_scheduled_interview(client, db_session)
    interview.status = "in_progress"
    transcript = InterviewTranscript(interview_id=interview.id, status="processing")
    db_session.add(transcript)
    await db_session.flush()

    response = await client.post(
        f"{LIVEKIT_URL}/{interview.id}/transcript/turn",
        json={
            "speaker": "ai",
            "speaker_name": "MeetMind",
            "content": "Tell me about yourself.",
            "sequence_no": 1,
        },
    )

    assert response.status_code == 201
    turns = await db_session.execute(
        select(InterviewTranscriptTurn).where(
            InterviewTranscriptTurn.transcript_id == transcript.id
        )
    )
    assert len(turns.scalars().all()) == 1


@pytest.mark.anyio
async def test_transcript_turn_404_for_unknown_interview(
    client: AsyncClient, db_session: AsyncSession
):
    response = await client.post(
        f"{LIVEKIT_URL}/{uuid.uuid4()}/transcript/turn",
        json={"speaker": "ai", "content": "Q", "sequence_no": 1},
    )

    assert response.status_code == 404


@pytest.mark.anyio
async def test_transcript_turn_creates_parent_if_missing(
    client: AsyncClient, db_session: AsyncSession
):
    _, _, interview = await create_scheduled_interview(client, db_session)
    interview.status = "in_progress"
    await db_session.commit()

    response = await client.post(
        f"{LIVEKIT_URL}/{interview.id}/transcript/turn",
        json={"speaker": "ai", "content": "Q", "sequence_no": 1},
    )

    assert response.status_code == 201
    transcript = await db_session.execute(
        select(InterviewTranscript).where(
            InterviewTranscript.interview_id == interview.id
        )
    )
    assert transcript.scalar_one_or_none() is not None


@pytest.mark.anyio
async def test_live_transcript_returns_turns_during_interview(
    client: AsyncClient, db_session: AsyncSession
):
    _, token, interview = await create_scheduled_interview(client, db_session)
    interview.status = "in_progress"
    transcript = InterviewTranscript(interview_id=interview.id, status="processing")
    db_session.add(transcript)
    await db_session.flush()
    db_session.add_all(
        [
            InterviewTranscriptTurn(
                transcript_id=transcript.id,
                speaker="ai",
                speaker_name="MeetMind",
                content="Question one",
                sequence_no=1,
            ),
            InterviewTranscriptTurn(
                transcript_id=transcript.id,
                speaker="candidate",
                speaker_name="John Doe",
                content="Answer one",
                sequence_no=2,
            ),
        ]
    )
    await db_session.commit()

    response = await client.get(
        f"{INTERVIEWS_URL}/{interview.id}/transcript?live=true",
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["is_live"] is True
    assert data["status"] == "transcribing"
    assert len(data["messages"]) == 2
    assert data["messages"][0]["text"] == "Question one"
    assert "speaker_type" in data["messages"][0]


@pytest.mark.anyio
async def test_duplicate_turn_sequence_is_ignored(
    client: AsyncClient, db_session: AsyncSession
):
    _, _, interview = await create_scheduled_interview(client, db_session)
    transcript = InterviewTranscript(interview_id=interview.id, status="processing")
    db_session.add(transcript)
    await db_session.flush()
    payload = {"speaker": "ai", "content": "Q", "sequence_no": 1}

    first = await client.post(
        f"{LIVEKIT_URL}/{interview.id}/transcript/turn", json=payload
    )
    second = await client.post(
        f"{LIVEKIT_URL}/{interview.id}/transcript/turn", json=payload
    )

    assert first.status_code == 201
    assert second.status_code == 200
    turns = await db_session.execute(
        select(InterviewTranscriptTurn).where(
            InterviewTranscriptTurn.transcript_id == transcript.id
        )
    )
    assert len(turns.scalars().all()) == 1


@pytest.mark.anyio
async def test_result_sets_interview_completed(
    client: AsyncClient, db_session: AsyncSession
):
    # setup: in_progress interview
    _, _, interview = await create_scheduled_interview(client, db_session)
    interview.status = "in_progress"
    await db_session.commit()

    payload = {"transcript": [], "report": None}
    response = await client.post(
        f"{LIVEKIT_URL}/{interview.id}/result", json=payload
    )
    assert response.status_code == 200
    await db_session.refresh(interview)
    assert interview.status == "completed"


@pytest.mark.anyio
async def test_result_writes_transcript_turns(
    client: AsyncClient, db_session: AsyncSession
):
    # setup: interview with 1 turn already in DB (seq 1)
    _, _, interview = await create_scheduled_interview(client, db_session)
    interview.status = "in_progress"
    transcript = InterviewTranscript(interview_id=interview.id, status="processing")
    db_session.add(transcript)
    await db_session.flush()

    db_session.add(
        InterviewTranscriptTurn(
            transcript_id=transcript.id,
            speaker="candidate",
            content="Hi",
            sequence_no=1,
        )
    )
    await db_session.commit()

    # result payload has 3 turns (seq 1, 2, 3)
    payload = {
        "transcript": [
            {"speaker": "candidate", "content": "Hi", "sequence_no": 1},
            {"speaker": "ai", "content": "Tell me about yourself", "sequence_no": 2},
            {"speaker": "candidate", "content": "I am...", "sequence_no": 3},
        ],
        "report": None,
    }
    await client.post(f"{LIVEKIT_URL}/{interview.id}/result", json=payload)

    turns = await db_session.execute(
        select(InterviewTranscriptTurn).where(
            InterviewTranscriptTurn.transcript_id == transcript.id
        )
    )
    # only 2 new rows created (seq 1 skipped, seq 2 and 3 inserted)
    assert len(turns.scalars().all()) == 3


@pytest.mark.anyio
async def test_result_writes_scorecard_scores(
    client: AsyncClient, db_session: AsyncSession
):
    _, _, interview = await create_scheduled_interview(client, db_session)
    interview.status = "in_progress"
    await db_session.commit()

    payload = {
        "transcript": [],
        "report": {
            "criteria": [
                {"name": "Communication", "score": 4, "justification": "Clear answers"},
                {
                    "name": "Technical depth",
                    "score": 3,
                    "justification": "Solid basics",
                },
            ],
            "overall": "yes",
            "summary": "Strong candidate overall.",
        },
    }
    await client.post(f"{LIVEKIT_URL}/{interview.id}/result", json=payload)

    from app.models.scorecard import InterviewScorecard, ScorecardScore

    scores = await db_session.execute(
        select(ScorecardScore)
        .join(InterviewScorecard)
        .where(InterviewScorecard.interview_id == interview.id)
    )
    score_list = scores.scalars().all()
    assert len(score_list) == 2
    score_pcts = {s.score_pct for s in score_list}
    assert 80 in score_pcts  # 4 * 20
    assert 60 in score_pcts  # 3 * 20


@pytest.mark.anyio
async def test_result_writes_summary_assessment(
    client: AsyncClient, db_session: AsyncSession
):
    _, _, interview = await create_scheduled_interview(client, db_session)
    interview.status = "in_progress"
    await db_session.commit()

    payload = {
        "transcript": [],
        "report": {
            "criteria": [],
            "overall": "strong_yes",
            "summary": "Excellent candidate who demonstrated clear thinking.",
            "highlights": ["Explained a complex API migration with clear tradeoffs."],
            "red_flags": ["Gave vague answers about day-to-day responsibilities."],
            "confidence": 0.91,
        },
    }
    await client.post(f"{LIVEKIT_URL}/{interview.id}/result", json=payload)

    summary_result = await db_session.execute(
        select(InterviewSummary).where(InterviewSummary.interview_id == interview.id)
    )
    summary = summary_result.scalar_one()

    import json

    assessment = json.loads(summary.ai_assessment)
    assert (
        assessment["overview"]
        == "Excellent candidate who demonstrated clear thinking."
    )
    assert (
        assessment["summary"]
        == "Excellent candidate who demonstrated clear thinking."
    )
    assert (
        assessment["observation"]
        == "Excellent candidate who demonstrated clear thinking."
    )
    assert assessment["highlights"] == [
        "Explained a complex API migration with clear tradeoffs."
    ]
    assert assessment["red_flags"] == [
        "Gave vague answers about day-to-day responsibilities."
    ]
    assert assessment["confidence"] == 0.91
    assert assessment["overall_recommendation"] == "strong_yes"
    assert summary.status == "completed"


@pytest.mark.anyio
async def test_result_404_for_unknown_interview(
    client: AsyncClient, db_session: AsyncSession
):
    response = await client.post(
        f"{LIVEKIT_URL}/{uuid.uuid4()}/result",
        json={"transcript": [], "report": None},
    )
    assert response.status_code == 404
