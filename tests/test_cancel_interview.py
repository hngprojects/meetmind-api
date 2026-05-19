"""
Tests for POST /api/v1/interviews/:id/cancel

Endpoint under test
-------------------
POST /api/v1/interviews/{id}/cancel  — cancel a scheduled interview

Each test registers a unique user so sessions never collide across the
shared in-memory SQLite database.

Run with:
    pytest tests/test_cancel_interview.py -v -s
"""

from __future__ import annotations

import logging
import uuid

import pytest
from httpx import AsyncClient

logger = logging.getLogger(__name__)

# ── URL constants ──────────────────────────────────────────────────────────────

SIGNUP_URL = "/api/v1/auth/signup"
INTERVIEWS_URL = "/api/v1/interviews"


def cancel_url(interview_id: str) -> str:
    return f"{INTERVIEWS_URL}/{interview_id}/cancel"


# ── helpers ────────────────────────────────────────────────────────────────────


def unique_user(tag: str | None = None) -> dict:
    """Return a signup payload with a guaranteed-unique email."""
    suffix = tag or uuid.uuid4().hex[:8]
    return {
        "name": "Cancel Tester",
        "email": f"cancel_{suffix}@example.com",
        "password": "SecurePass1!",
    }


async def signup_and_get_token(client: AsyncClient, user: dict) -> str:
    """Register a user and return their access token."""
    response = await client.post(SIGNUP_URL, json=user)
    assert response.status_code == 201, (
        f"Signup failed: {response.status_code} — {response.json()}"
    )
    return response.json()["data"]["access_token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


VALID_INTERVIEW_PAYLOAD = {
    "title": "Backend Engineer Interview",
    "candidate_name": "Jane Doe",
    "candidate_email": "jane@example.com",
    "job_description": "Build scalable APIs using FastAPI and PostgreSQL.",
    "scoring_rubric": "Communication, API design, problem-solving, scalability.",
    "role_title": "Senior Backend Engineer",
    "platform": "zoom",
    "ai_tone": "professional",
    "criteria": ["Communication", "API Design", "Problem Solving"],
}


async def create_interview(client: AsyncClient, token: str) -> str:
    """Create a draft interview and return its ID."""
    response = await client.post(
        INTERVIEWS_URL,
        json=VALID_INTERVIEW_PAYLOAD,
        headers=auth_headers(token),
    )
    assert response.status_code == 201, (
        f"Create failed: {response.status_code} — {response.json()}"
    )
    return response.json()["data"]["id"]


# ── POST /interviews/{id}/cancel ─────────────────────────────────────────────


class TestCancelInterview:
    @pytest.mark.anyio
    async def test_cancel_draft_interview_returns_200(self, client: AsyncClient):
        """
        GIVEN a draft interview
        WHEN  POST /interviews/{id}/cancel is called by the owner
        THEN  the response is 200 and status transitions to "cancelled"

        Expected:
            POST /interviews           → 201  status="draft"
            POST /interviews/{id}/cancel → 200  status="cancelled"
        """
        token = await signup_and_get_token(client, unique_user())
        iid = await create_interview(client, token)

        response = await client.post(cancel_url(iid), headers=auth_headers(token))
        body = response.json()
        logger.info(
            "[cancel] POST /interviews/%s/cancel → %d", iid, response.status_code
        )

        assert response.status_code == 200, (
            f"Expected 200 but got {response.status_code}. Body: {body}"
        )
        data = body["data"]
        assert data["status"] == "cancelled", (
            f"Expected status 'cancelled' but got '{data['status']}'"
        )
        assert str(data["id"]) == iid
        logger.info("[result] Interview successfully cancelled  [OK]")

    @pytest.mark.anyio
    async def test_cancel_returns_correct_interview_fields(self, client: AsyncClient):
        """
        GIVEN a draft interview with known fields
        WHEN  POST /interviews/{id}/cancel is called
        THEN  the response body includes all expected interview fields
        """
        token = await signup_and_get_token(client, unique_user())
        iid = await create_interview(client, token)

        response = await client.post(cancel_url(iid), headers=auth_headers(token))
        assert response.status_code == 200
        data = response.json()["data"]

        assert data["status"] == "cancelled"
        assert data["candidate_name"] == VALID_INTERVIEW_PAYLOAD["candidate_name"]
        assert data["platform"] == VALID_INTERVIEW_PAYLOAD["platform"]
        assert "criteria" in data
        assert "id" in data
        assert "created_at" in data
        logger.info("[result] Cancelled response body has correct fields  [OK]")

    @pytest.mark.anyio
    async def test_cancel_is_reflected_in_get(self, client: AsyncClient):
        """
        GIVEN a cancelled interview
        WHEN  GET /interviews/{id} is called afterward
        THEN  the status is "cancelled"
        """
        token = await signup_and_get_token(client, unique_user())
        iid = await create_interview(client, token)

        cancel = await client.post(cancel_url(iid), headers=auth_headers(token))
        assert cancel.status_code == 200

        get = await client.get(f"{INTERVIEWS_URL}/{iid}", headers=auth_headers(token))
        assert get.status_code == 200
        assert get.json()["data"]["status"] == "cancelled"
        logger.info("[result] Cancellation persisted and visible via GET  [OK]")

    @pytest.mark.anyio
    async def test_cancel_returns_404_for_nonexistent_interview(
        self, client: AsyncClient
    ):
        """
        GIVEN a random UUID that does not exist
        WHEN  POST /interviews/{id}/cancel is called
        THEN  the response is 404 with code "interview_not_found"
        """
        token = await signup_and_get_token(client, unique_user())
        fake_id = str(uuid.uuid4())

        response = await client.post(cancel_url(fake_id), headers=auth_headers(token))
        body = response.json()
        logger.info(
            "[not found] POST /interviews/%s/cancel → %d",
            fake_id,
            response.status_code,
        )

        assert response.status_code == 404, (
            f"Expected 404 but got {response.status_code}. Body: {body}"
        )
        assert body["error"]["code"] == "interview_not_found"
        logger.info("[result] Nonexistent interview returns 404  [OK]")

    @pytest.mark.anyio
    async def test_cancel_returns_404_for_another_users_interview(
        self, client: AsyncClient
    ):
        """
        GIVEN user A creates an interview
        WHEN  user B tries to cancel it
        THEN  the response is 404 — cross-user data leakage prevented
        """
        token_a = await signup_and_get_token(client, unique_user("canc_a"))
        token_b = await signup_and_get_token(client, unique_user("canc_b"))

        iid = await create_interview(client, token_a)

        response = await client.post(cancel_url(iid), headers=auth_headers(token_b))
        body = response.json()
        logger.info(
            "[cross-user] POST /interviews/%s/cancel (user B) → %d",
            iid,
            response.status_code,
        )

        assert response.status_code == 404, (
            f"Expected 404 when user B cancels user A's interview, "
            f"got {response.status_code}. Body: {body}"
        )
        logger.info("[result] Cross-user cancel correctly blocked with 404  [OK]")

    @pytest.mark.anyio
    async def test_cancel_returns_401_without_token(self, client: AsyncClient):
        """
        GIVEN no Authorization header
        WHEN  POST /interviews/{id}/cancel is called
        THEN  the response is 401
        """
        fake_id = str(uuid.uuid4())
        response = await client.post(cancel_url(fake_id))
        logger.info(
            "[no auth] POST /interviews/%s/cancel → %d",
            fake_id,
            response.status_code,
        )

        assert response.status_code == 401, (
            f"Expected 401 without token but got {response.status_code}. "
            f"Body: {response.json()}"
        )
        logger.info("[result] Unauthenticated cancel correctly rejected  [OK]")

    @pytest.mark.anyio
    async def test_cancel_already_cancelled_returns_409(self, client: AsyncClient):
        """
        GIVEN an interview that has already been cancelled
        WHEN  POST /interviews/{id}/cancel is called again
        THEN  the response is 409 with code "already_cancelled"
        """
        token = await signup_and_get_token(client, unique_user())
        iid = await create_interview(client, token)

        # First cancel — should succeed
        first = await client.post(cancel_url(iid), headers=auth_headers(token))
        assert first.status_code == 200

        # Second cancel — should conflict
        second = await client.post(cancel_url(iid), headers=auth_headers(token))
        body = second.json()
        logger.info(
            "[double cancel] POST /interviews/%s/cancel (2nd) → %d",
            iid,
            second.status_code,
        )

        assert second.status_code == 409, (
            f"Expected 409 on double cancel but got {second.status_code}. Body: {body}"
        )
        assert body["error"]["code"] == "already_cancelled"
        logger.info("[result] Double-cancel correctly returns 409  [OK]")
