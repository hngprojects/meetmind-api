"""Tests for Milestone 2: Session Setup and Context Loading."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

SIGNUP_URL = "/api/v1/auth/signup"
INTERVIEWS_URL = "/api/v1/interviews"
DASHBOARD_URL = "/api/v1/dashboard"


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


VALID_STEP1_PAYLOAD = {
    "candidate_name": "Temi Balogun",
    "platform": "zoom",
    "call_link": "https://zoom.us/j/123456789",
    "scheduled_start": "2026-06-01T17:30:00Z",
    "scheduled_end": "2026-06-01T18:30:00Z",
}


class TestCreateInterviewStep1:
    @pytest.mark.anyio
    async def test_creates_draft_interview_with_valid_payload(
        self, client: AsyncClient
    ):
        token = await signup_and_get_token(client, unique_user())
        response = await client.post(
            INTERVIEWS_URL,
            json=VALID_STEP1_PAYLOAD,
            headers=auth_headers(token),
        )
        assert response.status_code == 201
        data = response.json()["data"]
        assert data["status"] == "draft"
        assert data["candidate_name"] == "Temi Balogun"
        assert "id" in data

    @pytest.mark.anyio
    async def test_returns_401_without_token(self, client: AsyncClient):
        response = await client.post(INTERVIEWS_URL, json=VALID_STEP1_PAYLOAD)
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_returns_422_when_candidate_name_missing(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())
        payload = {
            k: v for k, v in VALID_STEP1_PAYLOAD.items() if k != "candidate_name"
        }
        response = await client.post(
            INTERVIEWS_URL, json=payload, headers=auth_headers(token)
        )
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_returns_422_for_invalid_platform(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())
        response = await client.post(
            INTERVIEWS_URL,
            json={**VALID_STEP1_PAYLOAD, "platform": "teams"},
            headers=auth_headers(token),
        )
        assert response.status_code == 422


class TestUpdateContext:
    @pytest.mark.anyio
    async def test_updates_context_on_draft_interview(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())
        create = await client.post(
            INTERVIEWS_URL, json=VALID_STEP1_PAYLOAD, headers=auth_headers(token)
        )
        interview_id = create.json()["data"]["id"]

        response = await client.put(
            f"{INTERVIEWS_URL}/{interview_id}/context",
            json={
                "role_title": "Senior Product Manager",
                "job_description": "Looking for a PM with 3+ years experience.",
                "key_skills": ["Communication", "Technical depth", "Ownership"],
                "custom_questions": (
                    "Validate product judgement and engineering tradeoffs."
                ),
            },
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["interview_id"] == interview_id
        assert data["status"] == "draft"

    @pytest.mark.anyio
    async def test_context_returns_404_for_another_users_interview(
        self, client: AsyncClient
    ):
        token_a = await signup_and_get_token(client, unique_user("ctx_a"))
        token_b = await signup_and_get_token(client, unique_user("ctx_b"))
        create = await client.post(
            INTERVIEWS_URL, json=VALID_STEP1_PAYLOAD, headers=auth_headers(token_a)
        )
        interview_id = create.json()["data"]["id"]

        response = await client.put(
            f"{INTERVIEWS_URL}/{interview_id}/context",
            json={"job_description": "Test"},
            headers=auth_headers(token_b),
        )
        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_context_returns_401_without_token(self, client: AsyncClient):
        response = await client.put(f"{INTERVIEWS_URL}/{uuid.uuid4()}/context", json={})
        assert response.status_code == 401


class TestUpdateSessionConfig:
    @pytest.mark.anyio
    async def test_updates_participation_mode_on_draft(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())
        create = await client.post(
            INTERVIEWS_URL, json=VALID_STEP1_PAYLOAD, headers=auth_headers(token)
        )
        interview_id = create.json()["data"]["id"]

        response = await client.put(
            f"{INTERVIEWS_URL}/{interview_id}/session-config",
            json={"participation_mode": "proactive"},
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        assert response.json()["data"]["participation_mode"] == "proactive"

    @pytest.mark.anyio
    async def test_returns_422_for_invalid_participation_mode(
        self, client: AsyncClient
    ):
        token = await signup_and_get_token(client, unique_user())
        create = await client.post(
            INTERVIEWS_URL, json=VALID_STEP1_PAYLOAD, headers=auth_headers(token)
        )
        interview_id = create.json()["data"]["id"]

        response = await client.put(
            f"{INTERVIEWS_URL}/{interview_id}/session-config",
            json={"participation_mode": "aggressive"},
            headers=auth_headers(token),
        )
        assert response.status_code == 422


class TestConfirmInterview:
    @pytest.mark.anyio
    async def test_confirm_transitions_to_scheduled(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())
        create = await client.post(
            INTERVIEWS_URL, json=VALID_STEP1_PAYLOAD, headers=auth_headers(token)
        )
        interview_id = create.json()["data"]["id"]

        await client.put(
            f"{INTERVIEWS_URL}/{interview_id}/context",
            json={
                "job_description": "Looking for a PM.",
                "key_skills": ["Communication"],
            },
            headers=auth_headers(token),
        )

        response = await client.post(
            f"{INTERVIEWS_URL}/{interview_id}/confirm",
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "scheduled"

    @pytest.mark.anyio
    async def test_confirm_returns_400_when_job_description_missing(
        self, client: AsyncClient
    ):
        token = await signup_and_get_token(client, unique_user())
        create = await client.post(
            INTERVIEWS_URL, json=VALID_STEP1_PAYLOAD, headers=auth_headers(token)
        )
        interview_id = create.json()["data"]["id"]

        response = await client.post(
            f"{INTERVIEWS_URL}/{interview_id}/confirm",
            headers=auth_headers(token),
        )
        assert response.status_code == 400

    @pytest.mark.anyio
    async def test_confirm_returns_409_if_already_confirmed(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())
        create = await client.post(
            INTERVIEWS_URL, json=VALID_STEP1_PAYLOAD, headers=auth_headers(token)
        )
        interview_id = create.json()["data"]["id"]

        await client.put(
            f"{INTERVIEWS_URL}/{interview_id}/context",
            json={"job_description": "Looking for a PM."},
            headers=auth_headers(token),
        )
        await client.post(
            f"{INTERVIEWS_URL}/{interview_id}/confirm", headers=auth_headers(token)
        )
        response = await client.post(
            f"{INTERVIEWS_URL}/{interview_id}/confirm", headers=auth_headers(token)
        )
        assert response.status_code == 409


class TestListInterviews:
    @pytest.mark.anyio
    async def test_returns_paginated_interviews(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())
        await client.post(
            INTERVIEWS_URL, json=VALID_STEP1_PAYLOAD, headers=auth_headers(token)
        )

        response = await client.get(INTERVIEWS_URL, headers=auth_headers(token))
        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "meta" in body
        assert body["meta"]["pagination"]["total"] >= 1

    @pytest.mark.anyio
    async def test_returns_empty_list_when_no_interviews(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())
        response = await client.get(INTERVIEWS_URL, headers=auth_headers(token))
        assert response.status_code == 200
        assert response.json()["data"] == []

    @pytest.mark.anyio
    async def test_returns_401_without_token(self, client: AsyncClient):
        response = await client.get(INTERVIEWS_URL)
        assert response.status_code == 401


class TestDashboardOverview:
    @pytest.mark.anyio
    async def test_returns_overview_with_stats(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())
        await client.post(
            INTERVIEWS_URL, json=VALID_STEP1_PAYLOAD, headers=auth_headers(token)
        )

        response = await client.get(
            f"{DASHBOARD_URL}/overview", headers=auth_headers(token)
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert "has_sessions" in data
        assert "stats" in data
        assert data["has_sessions"] is True
        assert "total" in data["stats"]
        assert "scheduled" in data["stats"]
        assert "completed" in data["stats"]
        assert "in_progress" in data["stats"]
        assert "needs_attention" in data["stats"]

    @pytest.mark.anyio
    async def test_has_sessions_false_when_no_interviews(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())
        response = await client.get(
            f"{DASHBOARD_URL}/overview", headers=auth_headers(token)
        )
        assert response.status_code == 200
        assert response.json()["data"]["has_sessions"] is False

    @pytest.mark.anyio
    async def test_returns_401_without_token(self, client: AsyncClient):
        response = await client.get(f"{DASHBOARD_URL}/overview")
        assert response.status_code == 401


class TestDashboardSchedule:
    @pytest.mark.anyio
    async def test_returns_scheduled_sessions_in_date_range(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())
        await client.post(
            INTERVIEWS_URL, json=VALID_STEP1_PAYLOAD, headers=auth_headers(token)
        )

        response = await client.get(
            f"{DASHBOARD_URL}/schedule",
            params={"start_date": "2026-01-01", "end_date": "2026-12-31"},
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert isinstance(data, list)

    @pytest.mark.anyio
    async def test_returns_401_without_token(self, client: AsyncClient):
        response = await client.get(f"{DASHBOARD_URL}/schedule")
        assert response.status_code == 401


class TestDashboardCompleted:
    @pytest.mark.anyio
    async def test_returns_completed_sessions(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())
        response = await client.get(
            f"{DASHBOARD_URL}/completed", headers=auth_headers(token)
        )
        assert response.status_code == 200
        assert isinstance(response.json()["data"], list)

    @pytest.mark.anyio
    async def test_returns_401_without_token(self, client: AsyncClient):
        response = await client.get(f"{DASHBOARD_URL}/completed")
        assert response.status_code == 401


class TestDashboardAlerts:
    @pytest.mark.anyio
    async def test_returns_alerts_list(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())
        response = await client.get(
            f"{DASHBOARD_URL}/alerts", headers=auth_headers(token)
        )
        assert response.status_code == 200
        assert isinstance(response.json()["data"], list)

    @pytest.mark.anyio
    async def test_returns_401_without_token(self, client: AsyncClient):
        response = await client.get(f"{DASHBOARD_URL}/alerts")
        assert response.status_code == 401
