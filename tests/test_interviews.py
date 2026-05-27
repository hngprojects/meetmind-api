"""
Tests for Interview Session Management & Context Injection API.

Endpoints under test
--------------------
POST /api/v1/interviews       — create interview session with context
GET  /api/v1/interviews/{id}  — retrieve interview session by ID

Each test registers a unique user so sessions never collide across the
shared in-memory SQLite database.

Run with:
    pytest tests/test_interviews.py -v -s
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

logger = logging.getLogger(__name__)

# ── URL constants ──────────────────────────────────────────────────────────────

SIGNUP_URL = "/api/v1/auth/signup"
INTERVIEWS_URL = "/api/v1/interviews"
CRITERIA_URL = lambda iid: f"{INTERVIEWS_URL}/{iid}/criteria"  # noqa: E731


def cancel_url(interview_id: str) -> str:
    return f"{INTERVIEWS_URL}/{interview_id}/cancel"


# ── helpers ────────────────────────────────────────────────────────────────────


def unique_user(tag: str | None = None) -> dict:
    """Return a signup payload with a guaranteed-unique email."""
    suffix = tag or uuid.uuid4().hex[:8]
    return {
        "name": "Interview Tester",
        "email": f"interview_{suffix}@example.com",
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


async def build_interview_payload_for_user(
    db_session: AsyncSession,
    token: str,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a candidate and return a valid interview payload for that user."""
    candidate = await create_candidate_for_user(
        db_session=db_session,
        token=token,
        full_name="Jane Doe",
        email=f"candidate_{uuid.uuid4().hex[:8]}@example.com",
    )
    return build_interview_payload(candidate, overrides)


async def create_interview(
    client: AsyncClient, db_session: AsyncSession, token: str
) -> dict[str, Any]:
    """Create an interview via the current API contract and return its response data."""
    response = await create_interview_via_route(
        client=client,
        db_session=db_session,
        token=token,
    )
    return response.json()["data"]


# In tests/test_interviews.py

VALID_INTERVIEW_PAYLOAD = {
    "role_title": "Senior Backend Engineer",
    "job_description": "Build and maintain distributed APIs...",
    "scoring_rubric": "Code Quality, Architecture, Communication", # For assertion
    "skills_to_assess": ["Communication", "API Design", "Problem Solving"],
    "platform": "google_meet",
    "ai_tone": "professional",
    "scheduled_start": "2026-06-01T17:30:00Z",
    "scheduled_end": "2026-06-01T18:30:00Z"
}

# ── POST /interviews ───────────────────────────────────────────────────────────


class TestCreateInterview:
    @pytest.mark.anyio
    async def test_creates_interview_and_returns_201(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        token = await signup_and_get_token(client, unique_user())
        
        # We pass the metadata we want for the candidate
        candidate_kwargs = {
            "full_name": "John Doe",
            "email": "john.doe@example.com",
            "skills": ["Python", "FastAPI"]
        }
        
        # This helper now correctly patches and posts
        response = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            candidate_kwargs=candidate_kwargs,
            interview_overrides=VALID_INTERVIEW_PAYLOAD,
        )
        
        body = response.json()
        assert response.status_code == 201, body
        
        data = body["data"]
        # Assertions
        assert data["status"] == "scheduled"
        assert data["candidate_name"] == "John Doe"
        assert data["summary"]["job_description"] == VALID_INTERVIEW_PAYLOAD["job_description"]
        assert data["questions_total"] > 0


    @pytest.mark.anyio
    async def test_create_returns_401_without_token(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """
        GIVEN no Authorization header
        WHEN  POST /interviews is called
        THEN  the response is 401

        Expected:
            POST /interviews (no auth) → 401
        """
        token = await signup_and_get_token(client, unique_user())
        candidate_payload = await build_interview_payload_for_user(db_session, token)
        response = await client.post(INTERVIEWS_URL, json=candidate_payload)
        logger.info("[no auth] POST /interviews → %d", response.status_code)

        assert response.status_code == 401, (
            f"Expected 401 without token but got {response.status_code}."
            f"Body: {response.json()}"
        )
        logger.info("[result]  Unauthenticated requestcorrectly rejected  ✓")

    @pytest.mark.anyio
    async def test_optional_fields_default_correctly(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """
        GIVEN a payload with only required fields (no platform, ai_tone, role_title)
        WHEN  POST /interviews is called
        THEN  the response is 201 and optional fields are null

        Expected:
            POST /interviews (minimal payload) → 201
            data.platform == null
            data.ai_tone  == null
        """
        token = await signup_and_get_token(client, unique_user())
        minimal_payload = await build_interview_payload_for_user(
            db_session,
            token,
            overrides={
                "platform": None,
                "ai_tone": None,
                "role_title": None,
                "skills_to_assess": ["Code Quality"],
            },
        )
        response = await client.post(
            INTERVIEWS_URL,
            json=minimal_payload,
            headers=auth_headers(token),
        )
        body = response.json()
        logger.info("[minimal payload] POST /interviews → %d", response.status_code)

        assert response.status_code == 201, (
            "Expected 201 for minimal payload but got"
            f"{response.status_code}. Body: {body}"
        )
        data = body["data"]
        assert data["platform"] is None
        assert data["ai_tone"] is None
        logger.info("[result]          Optional fields correctly default to null  ✓")

    @pytest.mark.anyio
    async def test_default_participation_mode(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """
        GIVEN a payload without participation_mode
        WHEN  POST /interviews is called
        THEN  the response defaults to "standard"
        """
        token = await signup_and_get_token(client, unique_user())
        response = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides=VALID_INTERVIEW_PAYLOAD,
        )
        body = response.json()
        assert response.status_code == 201, body
        assert body["data"]["participation_mode"] == "standard"


# ── GET /interviews/{id} ───────────────────────────────────────────────────────


class TestGetInterview:
    @pytest.mark.anyio
    async def test_retrieves_interview_with_participation_mode(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        token = await signup_and_get_token(client, unique_user())
        create = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides={
                **VALID_INTERVIEW_PAYLOAD,
                "participation_mode": "proactive",
            },
        )
        assert create.status_code == 201
        interview_id = create.json()["data"]["id"]

        get = await client.get(
            f"{INTERVIEWS_URL}/{interview_id}", headers=auth_headers(token)
        )
        body = get.json()
        assert get.status_code == 200, body
        assert body["data"]["participation_mode"] == "proactive"

    @pytest.mark.anyio
    async def test_retrieves_interview_by_id(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        token = await signup_and_get_token(client, unique_user())
        
        # FIX: Use the route-based helper to ensure Summary and Session are created
        create_res = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides=VALID_INTERVIEW_PAYLOAD,
        )
        assert create_res.status_code == 201
        interview_id = create_res.json()["data"]["id"]

        # Now test the GET endpoint
        get = await client.get(
            f"{INTERVIEWS_URL}/{interview_id}",
            headers=auth_headers(token),
        )
        body = get.json()
        assert get.status_code == 200, body
        
        data = body["data"]
        assert str(data["id"]) == interview_id
        assert data["status"] == "scheduled"
        
        # FIX: Check that the rubric exists and is structured (from our Mock)
        # We no longer compare it to the raw input string because the AI shaped it.
        rubric = data["summary"]["scoring_rubric"]
        assert "API Design" in rubric
        assert "Communication" in rubric
        assert "weight" in rubric  # Proves it's the structured AI version


    @pytest.mark.anyio
    async def test_get_returns_404_for_nonexistent_interview(self, client: AsyncClient):
        """
        GIVEN a random UUID that does not exist in the database
        WHEN  GET /interviews/{id} is called
        THEN  the response is 404

        Expected:
            GET /interviews/{random_uuid} → 404
            error.code == "interview_not_found"
        """
        token = await signup_and_get_token(client, unique_user())
        fake_id = str(uuid.uuid4())
        response = await client.get(
            f"{INTERVIEWS_URL}/{fake_id}",
            headers=auth_headers(token),
        )
        body = response.json()
        logger.info(
            "[not found] GET /interviews/%s → %d", fake_id, response.status_code
        )

        assert response.status_code == 404, (
            "Expected 404 for nonexistent interview but got"
            f"{response.status_code}. Body: {body}"
        )
        assert body["error"]["code"] == "interview_not_found", (
            f"Expected code 'interview_not_found' but got '{body.get('error')}'"
        )
        logger.info("[result]    Nonexistent interview correctly returns 404  ✓")

    @pytest.mark.anyio
    async def test_get_returns_404_for_another_users_interview(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """
        GIVEN user A creates an interview
        WHEN  user B tries to retrieve it
        THEN  the response is 404 — cross-user data leakage prevented

        Expected:
            POST /interviews (user A)      → 201
            GET  /interviews/{id} (user B) → 404
        """
        token_a = await signup_and_get_token(client, unique_user("iso_a"))
        token_b = await signup_and_get_token(client, unique_user("iso_b"))

        create = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token_a,
            interview_overrides=VALID_INTERVIEW_PAYLOAD,
        )
        assert create.status_code == 201
        interview_id = create.json()["data"]["id"]
        logger.info("[user A create] POST /interviews → 201  id=%s  ✓", interview_id)

        get = await client.get(
            f"{INTERVIEWS_URL}/{interview_id}",
            headers=auth_headers(token_b),
        )
        body = get.json()
        logger.info(
            "[user B get]    GET /interviews/%s → %d  body=%s",
            interview_id,
            get.status_code,
            body,
        )

        assert get.status_code == 404, (
            "Expected 404 when user B accesses user A's interview, got "
            f"{get.status_code}. Body: {body}"
        )
        logger.info("[result]        Cross-user access correctly blocked with 404  ✓")

    @pytest.mark.anyio
    async def test_get_returns_401_without_token(self, client: AsyncClient):
        """
        GIVEN no Authorization header
        WHEN  GET /interviews/{id} is called
        THEN  the response is 401

        Expected:
            GET /interviews/{id} (no auth) → 401
        """
        fake_id = str(uuid.uuid4())
        response = await client.get(f"{INTERVIEWS_URL}/{fake_id}")
        logger.info("[no auth] GET /interviews/%s → %d", fake_id, response.status_code)

        assert response.status_code == 401, (
            "Expected 401 without token but got {response.status_code}."
            f"Body: {response.json()}"
        )
        logger.info("[result]  Unauthenticated retrieval correctly rejected  ✓")


# ── Criteria validation on POST /interviews ────────────────────────────────────


class TestCreateInterviewCriteria:
    @pytest.mark.anyio
    async def test_create_with_valid_criteria(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        token = await signup_and_get_token(client, unique_user())
        response = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides=VALID_INTERVIEW_PAYLOAD,
        )
        assert response.status_code == 201
        data = response.json()["data"]
        assert data["criteria"] == ["Communication", "API Design", "Problem Solving"]

    @pytest.mark.anyio
    async def test_create_rejects_more_than_10_criteria(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        token = await signup_and_get_token(client, unique_user())
        response = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides={
                **VALID_INTERVIEW_PAYLOAD,
                "skills_to_assess": [f"Criterion {i}" for i in range(11)],
            },
            expect_status=422,
        )
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_create_rejects_blank_criterion(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        token = await signup_and_get_token(client, unique_user())
        response = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides={
                **VALID_INTERVIEW_PAYLOAD,
                "skills_to_assess": ["Valid", "   "],
            },
            expect_status=422,
        )
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_create_rejects_criterion_over_80_chars(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        token = await signup_and_get_token(client, unique_user())
        response = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides={
                **VALID_INTERVIEW_PAYLOAD,
                "skills_to_assess": ["x" * 81],
            },
            expect_status=422,
        )
        assert response.status_code == 422


# ── GET /interviews/{id} returns criteria ──────────────────────────────────────


class TestGetInterviewCriteria:
    @pytest.mark.anyio
    async def test_get_returns_criteria(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        token = await signup_and_get_token(client, unique_user())
        
        # CHANGE: Use the route-based helper so the Summary is actually created
        response = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides=VALID_INTERVIEW_PAYLOAD,
        )
        assert response.status_code == 201
        interview_id = response.json()["data"]["id"]

        # Now fetch it
        get = await client.get(
            f"{INTERVIEWS_URL}/{interview_id}", headers=auth_headers(token)
        )
        assert get.status_code == 200
        data = get.json()["data"]
        
        # This will now pass because the route-based helper triggered the AI shaping
        assert data["criteria"] == ["Communication", "API Design", "Problem Solving"]

# ── PUT /interviews/{id}/criteria ──────────────────────────────────────────────


class TestUpdateCriteria:
    @pytest.mark.anyio
    async def test_update_criteria_on_draft(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        token = await signup_and_get_token(client, unique_user())
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

    @pytest.mark.anyio
    async def test_update_criteria_reflected_in_get(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        token = await signup_and_get_token(client, unique_user())
        create = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides=VALID_INTERVIEW_PAYLOAD,
        )
        iid = create.json()["data"]["id"]

        await client.put(
            CRITERIA_URL(iid),
            json={"criteria": ["Updated Skill"]},
            headers=auth_headers(token),
        )

        get = await client.get(f"{INTERVIEWS_URL}/{iid}", headers=auth_headers(token))
        assert get.json()["data"]["criteria"] == ["Updated Skill"]

    @pytest.mark.anyio
    async def test_update_returns_404_for_other_user(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        token_a = await signup_and_get_token(client, unique_user("crit_a"))
        token_b = await signup_and_get_token(client, unique_user("crit_b"))

        create = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token_a,
            interview_overrides=VALID_INTERVIEW_PAYLOAD,
        )
        iid = create.json()["data"]["id"]

        response = await client.put(
            CRITERIA_URL(iid),
            json={"criteria": ["Hacked"]},
            headers=auth_headers(token_b),
        )
        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_update_returns_401_without_token(self, client: AsyncClient):
        fake_id = str(uuid.uuid4())
        response = await client.put(CRITERIA_URL(fake_id), json={"criteria": ["Test"]})
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_update_rejects_empty_criteria(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        token = await signup_and_get_token(client, unique_user())
        create = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides=VALID_INTERVIEW_PAYLOAD,
        )
        iid = create.json()["data"]["id"]

        response = await client.put(
            CRITERIA_URL(iid),
            json={"criteria": []},
            headers=auth_headers(token),
        )
        assert response.status_code == 422


class TestCancelInterview:
    @pytest.mark.anyio
    async def test_cancel_draft_interview_returns_200(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """
        GIVEN a draft interview
        WHEN  POST /interviews/{id}/cancel is called by the owner
        THEN  the response is 200 and status transitions to "cancelled"

        Expected:
            POST /interviews           → 201  status="scheduled"
            POST /interviews/{id}/cancel → 200  status="cancelled"
        """
        token = await signup_and_get_token(client, unique_user())
        data = await create_interview(client, db_session, token)
        iid = data["id"]

        response = await client.patch(cancel_url(iid), headers=auth_headers(token))
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
    async def test_cancel_returns_correct_interview_fields(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """
        GIVEN a draft interview with known fields
        WHEN  POST /interviews/{id}/cancel is called
        THEN  the response body includes all expected interview fields
        """
        token = await signup_and_get_token(client, unique_user())
        candidate_kwargs = {
            "full_name": "Jane Smith",
            "email": "jane.smith@example.com",
        }
        create = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            candidate_kwargs=candidate_kwargs,
            interview_overrides=VALID_INTERVIEW_PAYLOAD,
        )
        iid = create.json()["data"]["id"]

        response = await client.patch(cancel_url(iid), headers=auth_headers(token))
        assert response.status_code == 200
        data = response.json()["data"]

        assert data["status"] == "cancelled"
        assert data["candidate_name"] == candidate_kwargs["full_name"]
        assert data["platform"] == VALID_INTERVIEW_PAYLOAD["platform"]
        assert data["participation_mode"] == "standard"
        assert "criteria" in data
        assert "id" in data
        assert "created_at" in data
        logger.info("[result] Cancelled response body has correct fields  [OK]")

    @pytest.mark.anyio
    async def test_cancel_is_reflected_in_get(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """
        GIVEN a cancelled interview
        WHEN  GET /interviews/{id} is called afterward
        THEN  the status is "cancelled"
        """
        token = await signup_and_get_token(client, unique_user())
        data = await create_interview(client, db_session, token)
        iid = data["id"]

        cancel = await client.patch(cancel_url(iid), headers=auth_headers(token))
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

        response = await client.patch(cancel_url(fake_id), headers=auth_headers(token))
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
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """
        GIVEN user A creates an interview
        WHEN  user B tries to cancel it
        THEN  the response is 404 — cross-user data leakage prevented
        """
        token_a = await signup_and_get_token(client, unique_user("canc_a"))
        token_b = await signup_and_get_token(client, unique_user("canc_b"))

        data = await create_interview(client, db_session, token_a)
        iid = data["id"]

        response = await client.patch(cancel_url(iid), headers=auth_headers(token_b))
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
        response = await client.patch(cancel_url(fake_id))
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
    async def test_cancel_already_cancelled_returns_409(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """
        GIVEN an interview that has already been cancelled
        WHEN  POST /interviews/{id}/cancel is called again
        THEN  the response is 409 with code "already_cancelled"
        """
        token = await signup_and_get_token(client, unique_user())
        data = await create_interview(client, db_session, token)
        iid = data["id"]

        # First cancel — should succeed
        first = await client.patch(cancel_url(iid), headers=auth_headers(token))
        assert first.status_code == 200

        # Second cancel — should conflict
        second = await client.patch(cancel_url(iid), headers=auth_headers(token))
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

class TestListInterviewsFiltered:
    @pytest.mark.anyio
    async def test_filter_by_status_returns_matching_interviews(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        token = await signup_and_get_token(client, unique_user())
        await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides=VALID_INTERVIEW_PAYLOAD,
        )

        response = await client.get(
            INTERVIEWS_URL,
            params={"status": "scheduled"},
            headers=auth_headers(token),
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert all(i["status"] == "scheduled" for i in data)

    @pytest.mark.anyio
    async def test_filter_by_multiple_statuses(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        token = await signup_and_get_token(client, unique_user())
        await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides=VALID_INTERVIEW_PAYLOAD,
        )

        response = await client.get(
            INTERVIEWS_URL,
            params={"status": "draft,scheduled"},
            headers=auth_headers(token),
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert all(i["status"] in ("draft", "scheduled") for i in data)

    @pytest.mark.anyio
    async def test_search_by_role_title(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        token = await signup_and_get_token(client, unique_user())
        await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides=VALID_INTERVIEW_PAYLOAD,
        )

        response = await client.get(
            INTERVIEWS_URL,
            params={"search": "Senior Backend"},
            headers=auth_headers(token),
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) >= 1

    @pytest.mark.anyio
    async def test_search_returns_empty_when_no_match(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())

        response = await client.get(
            INTERVIEWS_URL,
            params={"search": "zxqwerty99notarole"},
            headers=auth_headers(token),
        )

        assert response.status_code == 200
        assert response.json()["data"] == []

    @pytest.mark.anyio
    async def test_returns_401_without_token(self, client: AsyncClient):
        response = await client.get(INTERVIEWS_URL, params={"status": "draft"})
        assert response.status_code == 401