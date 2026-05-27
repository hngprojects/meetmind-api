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
from tests.test_helpers import create_interview_via_route, patch_generate_interview_plan

INTERVIEWS_URL = "/api/v1/interviews"

# --- Teammate's fast Auth Helper ---
async def create_user(db: AsyncSession, email: str | None = None) -> User:
    user = User(email=email or f"{uuid.uuid4().hex[:8]}@example.com", is_verified=True)
    db.add(user)
    await db.flush()
    return user

def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}

# --- Reconciled Creation Helper ---
async def create_interview(client: AsyncClient, db: AsyncSession, token: str) -> str:
    """Helper that uses the complex route-creation logic required by the new schema."""
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
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        interview_id = await create_interview(client, db_session, token)

        response = await client.get(
            f"{INTERVIEWS_URL}/{interview_id}/transcript",
            headers=auth_headers(token),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["interview_id"] == interview_id
        assert body["data"]["total_turns"] == 0
        assert body["data"]["turns"] == []

    @pytest.mark.anyio
    async def test_get_transcript_and_export_formatting(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Validates formatting and ensures relative timestamps (00:00 start)."""
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        interview_id = await create_interview(client, db_session, token)

        # Inject manual turns into DB for formatting check
        interview = await db_session.get(Interview, uuid.UUID(interview_id))
        interview.status = "in_progress"
        transcript = InterviewTranscript(interview_id=interview.id)
        db_session.add(transcript)
        await db_session.flush()
        
        db_session.add_all([
            InterviewTranscriptTurn(
                transcript_id=transcript.id,
                speaker="ai",
                content="Tell me about your approach.",
                timestamp_sec=60, # Start offset
                sequence_no=1,
            ),
            InterviewTranscriptTurn(
                transcript_id=transcript.id,
                speaker="candidate",
                content="I start by clarifying requirements.",
                timestamp_sec=125, # 65s after first turn
                sequence_no=2,
            ),
        ])
        await db_session.flush()

        response = await client.get(
            f"{INTERVIEWS_URL}/{interview_id}/transcript",
            headers=auth_headers(token),
        )
        data = response.json()["data"]
        
        # Kept: Your logic for relative timestamps
        assert data["turns"][0]["timestamp"] == "00:00" 
        assert data["turns"][1]["timestamp"] == "01:05" 

        # Kept: Export assertions
        response_export = await client.get(
            f"{INTERVIEWS_URL}/{interview_id}/transcript/export",
            headers=auth_headers(token),
        )
        assert "[00:00]" in response_export.text
        assert "[01:05]" in response_export.text

    @pytest.mark.anyio
    async def test_get_transcript_access_control(self, client: AsyncClient, db_session: AsyncSession):
        # Adopted teammate's two-user isolation check logic
        owner = await create_user(db_session)
        owner_token = await AuthService.create_access_token(owner)
        other = await create_user(db_session)
        other_token = await AuthService.create_access_token(other)
        
        interview_id = await create_interview(client, db_session, owner_token)

        resp = await client.get(
            f"{INTERVIEWS_URL}/{interview_id}/transcript",
            headers=auth_headers(other_token),
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_stop_transcript_success_and_errors(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # Kept: Teammate's exhaustive status-machine checks (409s)
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        interview_id = await create_interview(client, db_session, token)

        interview = await db_session.get(Interview, uuid.UUID(interview_id))
        interview.status = "in_progress"
        await db_session.commit()

        # Success case
        resp = await client.post(
            f"{INTERVIEWS_URL}/{interview_id}/transcript/stop",
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "completed"

        # Error: Already completed -> 409
        resp409 = await client.post(
            f"{INTERVIEWS_URL}/{interview_id}/transcript/stop",
            headers=auth_headers(token),
        )
        assert resp409.status_code == 409