"""Tests for transcript endpoints under /api/v1/interviews."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.interview import (
    Interview,
    InterviewTranscript,
    InterviewTranscriptTurn,
)
from app.models.user import User
from app.services.auth import AuthService


INTERVIEWS_URL = "/api/v1/interviews"


async def create_user(db, email: str | None = None) -> User:
    user = User(email=email or f"{uuid.uuid4().hex[:8]}@example.com", is_verified=True)
    db.add(user)
    await db.flush()
    return user


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def create_interview(client: AsyncClient, token: str) -> str:
    payload = {
        "title": "QA Interview",
        "candidate_name": "Alex Rivera",
        "candidate_email": "alex@example.com",
        "job_description": "Test APIs and edge cases.",
        "scoring_rubric": "Communication, debugging, clarity.",
        "role_title": "QA Engineer",
        "platform": "zoom",
        "ai_tone": "professional",
        "criteria": ["Communication", "Problem Solving"],
    }
    response = await client.post(
        INTERVIEWS_URL,
        json=payload,
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


class TestTranscriptEndpoints:
    @pytest.mark.anyio
    async def test_get_transcript_returns_empty_when_no_transcript(
        self, client: AsyncClient, db_session
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        interview_id = await create_interview(client, token)

        response = await client.get(
            f"{INTERVIEWS_URL}/{interview_id}/transcript",
            headers=auth_headers(token),
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["data"]["interview_id"] == interview_id
        assert body["data"]["total_turns"] == 0
        assert body["data"]["turns"] == []

    @pytest.mark.anyio
    async def test_get_transcript_and_export_formatting(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Create a small transcript and validate both /transcript and /transcript/export."""
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        interview_id = await create_interview(client, token)

        # Update interview status and add transcript turns without starting a nested transaction
        interview = await db_session.get(Interview, uuid.UUID(interview_id))
        interview.status = "in_progress"
        transcript = InterviewTranscript(interview_id=interview.id)
        db_session.add(transcript)
        await db_session.flush()
        db_session.add_all(
            [
                InterviewTranscriptTurn(
                    transcript_id=transcript.id,
                    speaker="ai",
                    content="Tell me about your approach.",
                    timestamp_sec=60,
                    sequence_no=1,
                ),
                InterviewTranscriptTurn(
                    transcript_id=transcript.id,
                    speaker="candidate",
                    content="I start by clarifying requirements.",
                    timestamp_sec=125,
                    sequence_no=2,
                ),
            ]
        )
        await db_session.flush()

        # Check JSON transcript
        response = await client.get(
            f"{INTERVIEWS_URL}/{interview_id}/transcript",
            headers=auth_headers(token),
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["total_turns"] == 2
        assert data["turns"][0]["speaker"] == "meet_mind"
        assert data["turns"][0]["speaker_label"] == "Meet Mind"
        assert data["turns"][0]["timestamp"] == "00:00"
        assert data["turns"][1]["timestamp"] == "01:05"

        # Check export endpoint
        response_export = await client.get(
            f"{INTERVIEWS_URL}/{interview_id}/transcript/export",
            headers=auth_headers(token),
        )
        assert response_export.status_code == 200, response_export.text
        assert response_export.headers["content-type"].startswith("text/plain")
        assert response_export.headers["content-disposition"] == (
            f"attachment; filename=transcript_{interview_id}.txt"
        )
        assert "[00:00] Meet Mind: Tell me about your approach." in response_export.text
        assert (
            "[01:05] Candidate: I start by clarifying requirements."
            in response_export.text
        )

    @pytest.mark.anyio
    async def test_get_transcript_access_control(self, client: AsyncClient, db_session):
        # Non-owner should get 404
        owner = await create_user(db_session)
        owner_token = await AuthService.create_access_token(owner)
        other = await create_user(db_session)
        other_token = await AuthService.create_access_token(other)
        interview_id = await create_interview(client, owner_token)

        resp = await client.get(
            f"{INTERVIEWS_URL}/{interview_id}/transcript",
            headers=auth_headers(other_token),
        )
        assert resp.status_code == 404, resp.text

        # No token should get 401
        resp2 = await client.get(f"{INTERVIEWS_URL}/{uuid.uuid4()}/transcript")
        assert resp2.status_code == 401, resp2.text

    @pytest.mark.anyio
    # removed standalone 401 test - covered by `test_get_transcript_access_control`

    @pytest.mark.anyio
    async def test_stop_transcript_success_and_errors(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # Success case: in_progress -> completed
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        interview_id = await create_interview(client, token)

        interview = await db_session.get(Interview, uuid.UUID(interview_id))
        interview.status = "in_progress"
        await db_session.flush()

        resp = await client.post(
            f"{INTERVIEWS_URL}/{interview_id}/transcript/stop",
            headers=auth_headers(token),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["status"] == "completed"

        # Already completed -> 409
        interview2 = await db_session.get(Interview, uuid.UUID(interview_id))
        interview2.status = "completed"
        await db_session.flush()
        resp409 = await client.post(
            f"{INTERVIEWS_URL}/{interview_id}/transcript/stop",
            headers=auth_headers(token),
        )
        assert resp409.status_code == 409, resp409.text

        # Cancelled -> 409
        interview2.status = "cancelled"
        await db_session.flush()
        resp409b = await client.post(
            f"{INTERVIEWS_URL}/{interview_id}/transcript/stop",
            headers=auth_headers(token),
        )
        assert resp409b.status_code == 409, resp409b.text

        # Non-owner -> 404
        owner = await create_user(db_session)
        owner_token = await AuthService.create_access_token(owner)
        new_interview = await create_interview(client, owner_token)
        other = await create_user(db_session)
        other_token = await AuthService.create_access_token(other)
        resp404 = await client.post(
            f"{INTERVIEWS_URL}/{new_interview}/transcript/stop",
            headers=auth_headers(other_token),
        )
        assert resp404.status_code == 404, resp404.text

        # No token -> 401
        resp401 = await client.post(f"{INTERVIEWS_URL}/{uuid.uuid4()}/transcript/stop")
        assert resp401.status_code == 401, resp401.text

    # Removed older duplicate stop-transcript tests; covered by
    # `test_stop_transcript_success_and_errors` above.
