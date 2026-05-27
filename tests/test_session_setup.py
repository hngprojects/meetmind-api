"""Tests for Milestone 2: Session Setup and Context Loading."""

from __future__ import annotations

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# Import the helper and the patcher
from tests.test_helpers import create_interview_via_route, patch_generate_interview_plan

SIGNUP_URL = "/api/v1/auth/signup"
INTERVIEWS_URL = "/api/v1/interviews"
DASHBOARD_URL = "/api/v1/dashboard"

# --- FIX 1: Remove the hardcoded 'candidate' object from the base payload ---
# The helper 'create_interview_via_route' will provide a real candidate.
VALID_STEP1_PAYLOAD = {
    "role_title": "Software Engineer",
    "job_description": "We need a dev.",
    "platform": "livekit",
    "skills_to_assess": ["Coding"],
    "scheduled_start": "2026-06-01T10:00:00Z",
    "scheduled_end": "2026-06-01T11:00:00Z",
    "ai_tone": "professional"
}

def unique_user(tag: str | None = None) -> dict:
    suffix = tag or uuid.uuid4().hex[:8]
    return {
        "name": "Session Tester",
        "email": f"session_{suffix}@example.com",
        "password": "SecurePass1!",
    }

async def signup_and_get_token(client: AsyncClient, user: dict) -> str:
    res = await client.post(SIGNUP_URL, json=user)
    assert res.status_code == 201
    return res.json()["data"]["access_token"]

def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}

class TestCreateInterviewStep1:
    @pytest.mark.anyio
    async def test_creates_draft_interview_with_valid_payload(self, client: AsyncClient, db_session: AsyncSession):
        token = await signup_and_get_token(client, unique_user())
        
        # Use the helper with the Product Manager override as required by the assertion below
        response = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides={**VALID_STEP1_PAYLOAD, "role_title": "Product Manager"},
        )
        
        assert response.status_code == 201
        data = response.json()["data"]
        # In T-Minus 0 flow, creation results in 'scheduled'
        assert data["status"] == "scheduled"
        assert data["role_title"] == "Product Manager"
        assert "id" in data

    @pytest.mark.anyio
    async def test_returns_422_when_candidate_not_provided(self, client: AsyncClient, db_session: AsyncSession):
        token = await signup_and_get_token(client, unique_user())
        # The new schema requires the 'candidate' key
        payload = {k: v for k, v in VALID_STEP1_PAYLOAD.items() if k != "candidate"}
        response = await client.post(INTERVIEWS_URL, json=payload, headers=auth_headers(token))
        assert response.status_code == 422

class TestUpdateContext:
    @pytest.mark.anyio
    async def test_updates_context_on_draft_interview(self, client: AsyncClient, db_session: AsyncSession):
        token = await signup_and_get_token(client, unique_user())
        create = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides=VALID_STEP1_PAYLOAD,
        )
        interview_id = create.json()["data"]["id"]

        response = await client.put(
            f"{INTERVIEWS_URL}/{interview_id}/context",
            json={
                "role_title": "Senior Product Manager",
                "job_description": "Looking for a PM with 3+ years experience.",
                "key_skills": ["Communication", "Technical depth"],
                "custom_questions": "Validate tradeoffs.",
            },
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["interview_id"] == interview_id

class TestConfirmInterview:
    @pytest.mark.anyio
    async def test_confirm_transitions_to_scheduled(self, client: AsyncClient, db_session: AsyncSession):
        token = await signup_and_get_token(client, unique_user())
        create = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides=VALID_STEP1_PAYLOAD
        )
        interview_id = create.json()["data"]["id"]

        # Confirm should be idempotent (return 200 even if already scheduled)
        response = await client.post(
            f"{INTERVIEWS_URL}/{interview_id}/confirm",
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "scheduled"

class TestDashboardOverview:
    @pytest.mark.anyio
    async def test_returns_overview_with_stats(self, client: AsyncClient, db_session: AsyncSession):
        token = await signup_and_get_token(client, unique_user())
        
        # We must successfully create an interview for stats to show True
        await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides=VALID_STEP1_PAYLOAD,
        )

        response = await client.get(f"{DASHBOARD_URL}/overview", headers=auth_headers(token))
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["has_sessions"] is True
        assert data["stats"]["total"] >= 1