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
# Import the shared helpers
from tests.test_helpers import create_interview_via_route, patch_generate_interview_plan

SIGNUP_URL = "/api/v1/auth/signup"
INTERVIEWS_URL = "/api/v1/interviews"

def unique_user(tag: str | None = None) -> dict:
    rand = uuid.uuid4().hex[:8]
    suffix = f"{tag}-{rand}" if tag else rand
    return {
        "name": "Transcript Tester",
        "email": f"transcript_{suffix}@example.com",
        "password": "SecurePass1!",
    }

def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}

async def signup_and_get_token(client: AsyncClient, user: dict) -> str:
    response = await client.post(SIGNUP_URL, json=user)
    assert response.status_code == 201, response.text
    return response.json()["data"]["access_token"]

# --- FIX 1: Update local helper to use the common route helper ---
async def create_interview(client: AsyncClient, db: AsyncSession, token: str) -> str:
    # This ensures a real candidate and AI plan are created
    payload = {
        "role_title": "QA Engineer",
        "job_description": "Test APIs and edge cases.",
        "skills_to_assess": ["Communication", "Problem Solving"],
        "platform": "zoom",
        "ai_tone": "professional"
    }
    response = await create_interview_via_route(
        client=client,
        db_session=db,
        token=token,
        interview_overrides=payload
    )
    assert response.status_code == 201
    return response.json()["data"]["id"]


class TestTranscriptEndpoints:
    @pytest.mark.anyio
    async def test_get_transcript_returns_empty_when_no_transcript(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        token = await signup_and_get_token(client, unique_user())
        # Pass db_session to the updated helper
        interview_id = await create_interview(client, db_session, token)

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
        token = await signup_and_get_token(client, unique_user())
        interview_id = await create_interview(client, db_session, token)

        interview = await db_session.get(Interview, uuid.UUID(interview_id))
        interview.status = "in_progress"
        transcript = InterviewTranscript(interview_id=interview.id)
        db_session.add(transcript)
        await db_session.flush()
        
        db_session.add_all([
            InterviewTranscriptTurn(
                transcript_id=transcript.id,
                speaker="ai",
                speaker_name="MeetMind",
                content="Tell me about your approach.",
                timestamp_sec=60,
                sequence_no=1,
            ),
            InterviewTranscriptTurn(
                transcript_id=transcript.id,
                speaker="candidate",
                speaker_name="Candidate",
                content="I start by clarifying requirements.",
                timestamp_sec=125,
                sequence_no=2,
            ),
        ])
        await db_session.flush()

        response = await client.get(
            f"{INTERVIEWS_URL}/{interview_id}/transcript",
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        data = response.json()["data"]
        
        assert data["total_turns"] == 2
        # FIX: The first turn is always normalized to 00:00
        assert data["turns"][0]["timestamp"] == "00:00" 
        # FIX: The second turn is 65 seconds later
        assert data["turns"][1]["timestamp"] == "01:05" 

        # Check export endpoint
        response_export = await client.get(
            f"{INTERVIEWS_URL}/{interview_id}/transcript/export",
            headers=auth_headers(token),
        )
        assert response_export.status_code == 200
        # Update export assertions to match relative timing
        assert "[00:00]" in response_export.text
        assert "[01:05]" in response_export.text

    @pytest.mark.anyio
    async def test_get_transcript_access_control(self, client: AsyncClient, db_session: AsyncSession):
        owner_token = await signup_and_get_token(client, unique_user("owner"))
        interview_id = await create_interview(client, db_session, owner_token)
        other_token = await signup_and_get_token(client, unique_user("other"))

        resp = await client.get(
            f"{INTERVIEWS_URL}/{interview_id}/transcript",
            headers=auth_headers(other_token),
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_stop_transcript_success_and_errors(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        token = await signup_and_get_token(client, unique_user())
        interview_id = await create_interview(client, db_session, token)

        interview = await db_session.get(Interview, uuid.UUID(interview_id))
        interview.status = "in_progress"
        await db_session.commit()

        resp = await client.post(
            f"{INTERVIEWS_URL}/{interview_id}/transcript/stop",
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "completed"