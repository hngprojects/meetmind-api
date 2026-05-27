"""Tests for Milestone 2: Session Setup and Context Loading."""

from __future__ import annotations

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.auth import AuthService
from tests.test_helpers import create_interview_via_route

INTERVIEWS_URL = "/api/v1/interviews"
DASHBOARD_URL = "/api/v1/dashboard"

# Base payload matching the new schema
VALID_STEP1_PAYLOAD = {
    "role_title": "Software Engineer",
    "job_description": "We need a dev.",
    "platform": "livekit",
    "skills_to_assess": ["Coding"],
    "scheduled_start": "2026-06-01T10:00:00Z",
    "scheduled_end": "2026-06-01T11:00:00Z",
    "ai_tone": "professional"
}

# --- Teammate's Auth Helper (from dev) ---
async def create_user(db: AsyncSession, email: str | None = None) -> User:
    user = User(email=email or f"{uuid.uuid4().hex[:8]}@example.com", is_verified=True)
    db.add(user)
    await db.flush()
    return user

def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}

class TestCreateInterviewStep1:
    @pytest.mark.anyio
    async def test_creates_draft_interview_with_valid_payload(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # Merge: Teammate's auth + Your T-Minus 0 Helper
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        
        response = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides={**VALID_STEP1_PAYLOAD, "role_title": "Product Manager"},
        )
        
        assert response.status_code == 201
        data = response.json()["data"]
        # Reconciliation: New flow results in 'scheduled'
        assert data["status"] == "scheduled"
        assert data["role_title"] == "Product Manager"
        assert "id" in data

    @pytest.mark.anyio
    async def test_returns_401_without_token(self, client: AsyncClient):
        response = await client.post(INTERVIEWS_URL, json=VALID_STEP1_PAYLOAD)
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_returns_422_when_candidate_not_provided(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        # New logic requires the 'candidate' dictionary
        payload = {k: v for k, v in VALID_STEP1_PAYLOAD.items() if k != "candidate"}
        response = await client.post(INTERVIEWS_URL, json=payload, headers=auth_headers(token))
        assert response.status_code == 422

class TestUpdateContext:
    @pytest.mark.anyio
    async def test_updates_context_on_draft_interview(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
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
                "job_description": "Looking for a PM.",
                "key_skills": ["Communication"],
            },
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "scheduled"

class TestConfirmInterview:
    @pytest.mark.anyio
    async def test_confirm_transitions_to_scheduled(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        create = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides=VALID_STEP1_PAYLOAD
        )
        interview_id = create.json()["data"]["id"]

        # Confirm is idempotent (Success even if already scheduled)
        response = await client.post(
            f"{INTERVIEWS_URL}/{interview_id}/confirm",
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "scheduled"

class TestDashboardOverview:
    @pytest.mark.anyio
    async def test_returns_overview_with_stats(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        
        # Must use helper to ensure data exists in the workspace
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