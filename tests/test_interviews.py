"""
Tests for Interview Session Management & Context Injection API.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_helpers import (
    build_interview_payload,
    create_candidate_for_user,
    create_interview_via_route,
)

from app.models.user import User
from app.models.interview import Interview, InterviewSession
from app.services.auth import AuthService

logger = logging.getLogger(__name__)

# ── URL constants ──────────────────────────────────────────────────────────────
INTERVIEWS_URL = "/api/v1/interviews"
CRITERIA_URL = lambda iid: f"{INTERVIEWS_URL}/{iid}/criteria"


def cancel_url(interview_id: str) -> str:
    return f"{INTERVIEWS_URL}/{interview_id}/cancel"


# ── Helpers (Merged) ──────────────────────────────────────────────────────────

async def create_user(db: AsyncSession, email: str | None = None) -> User:
    """Direct DB user creation for testing speed."""
    user = User(email=email or f"{uuid.uuid4().hex[:8]}@example.com", is_verified=True)
    db.add(user)
    await db.flush()
    return user


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def create_interview(
    client: AsyncClient, db_session: AsyncSession, token: str
) -> dict[str, Any]:
    """Helper using reconciled route logic."""
    response = await create_interview_via_route(
        client=client,
        db_session=db_session,
        token=token,
    )
    return response.json()["data"]


VALID_INTERVIEW_PAYLOAD = {
    "role_title": "Senior Backend Engineer",
    "job_description": "Build and maintain distributed APIs...",
    "scoring_rubric": "Code Quality, Architecture, Communication",
    "skills_to_assess": ["Communication", "API Design", "Problem Solving"],
    "platform": "google_meet",
    "ai_tone": "professional",
    "scheduled_start": "2026-06-01T17:30:00Z",
    "scheduled_end": "2026-06-01T18:30:00Z"
}

# ── Tests (Reconciled) ─────────────────────────────────────────────────────────

class TestCreateInterview:
    @pytest.mark.anyio
    async def test_creates_interview_and_returns_201(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # Auth from dev
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        
        # Logic from HEAD (Atomic creation)
        candidate_kwargs = {
            "full_name": "John Doe",
            "email": "john.doe@example.com",
        }
        
        response = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            candidate_kwargs=candidate_kwargs,
            interview_overrides=VALID_INTERVIEW_PAYLOAD,
        )
        
        body = response.json()
        assert response.status_code == 201
        data = body["data"]
        assert data["status"] == "scheduled"
        assert data["candidate_name"] == "John Doe"

class TestGetInterview:
    @pytest.mark.anyio
    async def test_retrieves_interview_by_id(self, client: AsyncClient, db_session: AsyncSession):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        
        # Create using the reconciled helper
        create_res = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides=VALID_INTERVIEW_PAYLOAD,
        )
        interview_id = create_res.json()["data"]["id"]

        get = await client.get(
            f"{INTERVIEWS_URL}/{interview_id}",
            headers=auth_headers(token),
        )
        body = get.json()
        assert get.status_code == 200
        
        data = body["data"]
        assert data["status"] == "scheduled"
        # Check that AI shaping was applied (JSON rubric)
        assert "weight" in data["summary"]["scoring_rubric"]

class TestUpdateCriteria:
    @pytest.mark.anyio
    async def test_update_criteria_on_draft(self, client: AsyncClient, db_session: AsyncSession):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        
        create = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides=VALID_INTERVIEW_PAYLOAD,
        )
        iid = create.json()["data"]["id"]

        response = await client.put(
            CRITERIA_URL(iid),
            json={"criteria": ["Leadership", "Teamwork"]},
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        assert response.json()["data"]["criteria"] == ["Leadership", "Teamwork"]

class TestCancelInterview:
    @pytest.mark.anyio
    async def test_cancel_draft_interview_returns_200(self, client: AsyncClient, db_session: AsyncSession):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        
        # iid setup
        create_res = await create_interview_via_route(client, db_session, token)
        iid = create_res.json()["data"]["id"]

        response = await client.patch(cancel_url(iid), headers=auth_headers(token))
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "cancelled"

class TestListInterviewsFiltered:
    @pytest.mark.anyio
    async def test_filter_by_status_returns_matching_interviews(self, client: AsyncClient, db_session: AsyncSession):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        
        await create_interview_via_route(client, db_session, token, interview_overrides=VALID_INTERVIEW_PAYLOAD)

        response = await client.get(
            INTERVIEWS_URL,
            params={"status": "scheduled"},
            headers=auth_headers(token),
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert all(i["status"] == "scheduled" for i in data)

class TestInterviewSessionDuration:
    @pytest.mark.anyio
    async def test_create_interview_derives_duration_from_schedule(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        
        response = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides={
                "scheduled_start": "2026-06-01T09:00:00Z",
                "scheduled_end": "2026-06-01T10:30:00Z",
            },
        )
        
        interview_id = response.json()["data"]["id"]
        interview = await db_session.get(Interview, uuid.UUID(interview_id))
        session = await db_session.get(InterviewSession, interview.session_id)
        assert session.duration_minutes == 90

    @pytest.mark.anyio
    async def test_create_interview_defaults_duration_to_45(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        
        response = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides={
                "scheduled_start": None,
                "scheduled_end": None,
            },
        )
        
        interview_id = response.json()["data"]["id"]
        interview = await db_session.get(Interview, uuid.UUID(interview_id))
        session = await db_session.get(InterviewSession, interview.session_id)
        assert session.duration_minutes == 45