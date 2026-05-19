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

import pytest
from httpx import AsyncClient

logger = logging.getLogger(__name__)

# ── URL constants ──────────────────────────────────────────────────────────────

SIGNUP_URL = "/api/v1/auth/signup"
INTERVIEWS_URL = "/api/v1/interviews"

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


# ── POST /interviews ───────────────────────────────────────────────────────────


class TestCreateInterview:
    @pytest.mark.anyio
    async def test_creates_interview_and_returns_201(self, client: AsyncClient):
        """
        GIVEN a valid interview payload
        WHEN  POST /interviews is called by an authenticated user
        THEN  the response is 201 with the created session data

        Expected:
            POST /interviews → 201
            data.status      == "draft"
            data.summary.job_description and scoring_rubric persisted correctly
        """
        token = await signup_and_get_token(client, unique_user())
        response = await client.post(
            INTERVIEWS_URL,
            json=VALID_INTERVIEW_PAYLOAD,
            headers=auth_headers(token),
        )
        body = response.json()
        logger.info(
            "[create] POST /interviews → %d  id=%s",
            response.status_code,
            body.get("data", {}).get("id"),
        )

        assert response.status_code == 201, (
            f"Expected 201 but got {response.status_code}. Body: {body}"
        )
        data = body["data"]
        assert data["status"] == "draft", (
            f"Expected status 'draft' but got '{data['status']}'"
        )
        assert data["title"] == VALID_INTERVIEW_PAYLOAD["title"]
        assert data["candidate_name"] == VALID_INTERVIEW_PAYLOAD["candidate_name"]
        assert data["candidate_email"] == VALID_INTERVIEW_PAYLOAD["candidate_email"]
        assert (
            data["summary"]["job_description"]
            == VALID_INTERVIEW_PAYLOAD["job_description"]
        )
        assert (
            data["summary"]["scoring_rubric"]
            == VALID_INTERVIEW_PAYLOAD["scoring_rubric"]
        )
        assert data["summary"]["status"] == "pending"
        assert "id" in data
        assert "created_at" in data
        logger.info("[result] Interview created with correct status and context  ✓")

    @pytest.mark.anyio
    async def test_create_returns_401_without_token(self, client: AsyncClient):
        """
        GIVEN no Authorization header
        WHEN  POST /interviews is called
        THEN  the response is 401

        Expected:
            POST /interviews (no auth) → 401
        """
        response = await client.post(INTERVIEWS_URL, json=VALID_INTERVIEW_PAYLOAD)
        logger.info("[no auth] POST /interviews → %d", response.status_code)

        assert response.status_code == 401, (
            f"Expected 401 without token but got {response.status_code}."
            f"Body: {response.json()}"
        )
        logger.info("[result]  Unauthenticated requestcorrectly rejected  ✓")

    @pytest.mark.anyio
    async def test_create_returns_422_when_title_missing(self, client: AsyncClient):
        """
        GIVEN a payload missing the required 'title' field
        WHEN  POST /interviews is called
        THEN  the response is 422

        Expected:
            POST /interviews (no title) → 422
        """
        token = await signup_and_get_token(client, unique_user())
        payload = {k: v for k, v in VALID_INTERVIEW_PAYLOAD.items() if k != "title"}
        response = await client.post(
            INTERVIEWS_URL,
            json=payload,
            headers=auth_headers(token),
        )
        logger.info("[missing title] POST /interviews → %d", response.status_code)

        assert response.status_code == 422, (
            "Expected 422 for missing title but got "
            f"{response.status_code}. Body: {response.json()}"
        )
        logger.info("[result]        Missing required field correctly rejected  ✓")

    @pytest.mark.anyio
    async def test_create_returns_422_when_job_description_missing(
        self, client: AsyncClient
    ):
        """
        GIVEN a payload missing 'job_description'
        WHEN  POST /interviews is called
        THEN  the response is 422

        Expected:
            POST /interviews (no job_description) → 422
        """
        token = await signup_and_get_token(client, unique_user())
        payload = {
            k: v for k, v in VALID_INTERVIEW_PAYLOAD.items() if k != "job_description"
        }
        response = await client.post(
            INTERVIEWS_URL,
            json=payload,
            headers=auth_headers(token),
        )
        logger.info(
            "[missing job_description] POST /interviews → %d", response.status_code
        )

        assert response.status_code == 422, (
            f"Expected 422 for missing job_description but got"
            f"{response.status_code}. Body: {response.json()}"
        )
        logger.info(
            "[result]                  Missing context field correctly rejected  ✓"
        )

    @pytest.mark.anyio
    async def test_create_returns_422_when_scoring_rubric_missing(
        self, client: AsyncClient
    ):
        """
        GIVEN a payload missing 'scoring_rubric'
        WHEN  POST /interviews is called
        THEN  the response is 422

        Expected:
            POST /interviews (no scoring_rubric) → 422
        """
        token = await signup_and_get_token(client, unique_user())
        payload = {
            k: v for k, v in VALID_INTERVIEW_PAYLOAD.items() if k != "scoring_rubric"
        }
        response = await client.post(
            INTERVIEWS_URL,
            json=payload,
            headers=auth_headers(token),
        )
        logger.info(
            "[missing scoring_rubric] POST /interviews → %d", response.status_code
        )

        assert response.status_code == 422, (
            f"Expected 422 for missing scoring_rubric but got {response.status_code}."
            f"Body: {response.json()}"
        )
        logger.info(
            "[result]                 Missing scoring rubric correctly rejected  ✓"
        )

    @pytest.mark.anyio
    async def test_optional_fields_default_correctly(self, client: AsyncClient):
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
        minimal = {
            "title": "Minimal Interview",
            "candidate_name": "John Smith",
            "job_description": "Write Python services.",
            "scoring_rubric": "Code quality, communication.",
            "criteria": ["Code Quality"],
        }
        response = await client.post(
            INTERVIEWS_URL,
            json=minimal,
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
        assert data["candidate_email"] is None
        logger.info("[result]          Optional fields correctly default to null  ✓")


# ── GET /interviews/{id} ───────────────────────────────────────────────────────


class TestGetInterview:
    @pytest.mark.anyio
    async def test_retrieves_interview_by_id(self, client: AsyncClient):
        """
        GIVEN an interview was created by the authenticated user
        WHEN  GET /interviews/{id} is called
        THEN  the response is 200 with full session and context data

        Expected:
            POST /interviews       → 201  (create)
            GET  /interviews/{id}  → 200  (retrieve)
            context fields match what was submitted
        """
        token = await signup_and_get_token(client, unique_user())

        create = await client.post(
            INTERVIEWS_URL,
            json=VALID_INTERVIEW_PAYLOAD,
            headers=auth_headers(token),
        )
        assert create.status_code == 201
        interview_id = create.json()["data"]["id"]
        logger.info("[create] POST /interviews → 201  id=%s  ✓", interview_id)

        get = await client.get(
            f"{INTERVIEWS_URL}/{interview_id}",
            headers=auth_headers(token),
        )
        body = get.json()
        logger.info("[get]    GET /interviews/%s → %d", interview_id, get.status_code)

        assert get.status_code == 200, (
            f"Expected 200 but got {get.status_code}. Body: {body}"
        )
        data = body["data"]
        assert str(data["id"]) == interview_id
        assert (
            data["summary"]["job_description"]
            == VALID_INTERVIEW_PAYLOAD["job_description"]
        )
        assert (
            data["summary"]["scoring_rubric"]
            == VALID_INTERVIEW_PAYLOAD["scoring_rubric"]
        )
        assert data["status"] == "draft"
        logger.info("[result] Interview retrieved with correct context  ✓")

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
        self, client: AsyncClient
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

        create = await client.post(
            INTERVIEWS_URL,
            json=VALID_INTERVIEW_PAYLOAD,
            headers=auth_headers(token_a),
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
    async def test_create_with_valid_criteria(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())
        response = await client.post(
            INTERVIEWS_URL,
            json=VALID_INTERVIEW_PAYLOAD,
            headers=auth_headers(token),
        )
        assert response.status_code == 201
        data = response.json()["data"]
        assert data["criteria"] == ["Communication", "API Design", "Problem Solving"]

    @pytest.mark.anyio
    async def test_create_rejects_empty_criteria(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())
        payload = {**VALID_INTERVIEW_PAYLOAD, "criteria": []}
        response = await client.post(
            INTERVIEWS_URL, json=payload, headers=auth_headers(token)
        )
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_create_rejects_more_than_10_criteria(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())
        payload = {
            **VALID_INTERVIEW_PAYLOAD,
            "criteria": [f"Criterion {i}" for i in range(11)],
        }
        response = await client.post(
            INTERVIEWS_URL, json=payload, headers=auth_headers(token)
        )
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_create_rejects_blank_criterion(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())
        payload = {**VALID_INTERVIEW_PAYLOAD, "criteria": ["Valid", "   "]}
        response = await client.post(
            INTERVIEWS_URL, json=payload, headers=auth_headers(token)
        )
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_create_rejects_criterion_over_80_chars(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())
        payload = {**VALID_INTERVIEW_PAYLOAD, "criteria": ["x" * 81]}
        response = await client.post(
            INTERVIEWS_URL, json=payload, headers=auth_headers(token)
        )
        assert response.status_code == 422


# ── GET /interviews/{id} returns criteria ──────────────────────────────────────


class TestGetInterviewCriteria:
    @pytest.mark.anyio
    async def test_get_returns_criteria(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())
        create = await client.post(
            INTERVIEWS_URL,
            json=VALID_INTERVIEW_PAYLOAD,
            headers=auth_headers(token),
        )
        assert create.status_code == 201
        interview_id = create.json()["data"]["id"]

        get = await client.get(
            f"{INTERVIEWS_URL}/{interview_id}", headers=auth_headers(token)
        )
        assert get.status_code == 200
        data = get.json()["data"]
        assert data["criteria"] == ["Communication", "API Design", "Problem Solving"]


# ── PUT /interviews/{id}/criteria ──────────────────────────────────────────────

CRITERIA_URL = lambda iid: f"{INTERVIEWS_URL}/{iid}/criteria"  # noqa: E731


class TestUpdateCriteria:
    @pytest.mark.anyio
    async def test_update_criteria_on_draft(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())
        create = await client.post(
            INTERVIEWS_URL,
            json=VALID_INTERVIEW_PAYLOAD,
            headers=auth_headers(token),
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
    async def test_update_criteria_reflected_in_get(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())
        create = await client.post(
            INTERVIEWS_URL,
            json=VALID_INTERVIEW_PAYLOAD,
            headers=auth_headers(token),
        )
        iid = create.json()["data"]["id"]

        await client.put(
            CRITERIA_URL(iid),
            json={"criteria": ["Updated Skill"]},
            headers=auth_headers(token),
        )

        get = await client.get(
            f"{INTERVIEWS_URL}/{iid}", headers=auth_headers(token)
        )
        assert get.json()["data"]["criteria"] == ["Updated Skill"]

    @pytest.mark.anyio
    async def test_update_returns_404_for_other_user(self, client: AsyncClient):
        token_a = await signup_and_get_token(client, unique_user("crit_a"))
        token_b = await signup_and_get_token(client, unique_user("crit_b"))

        create = await client.post(
            INTERVIEWS_URL,
            json=VALID_INTERVIEW_PAYLOAD,
            headers=auth_headers(token_a),
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
        response = await client.put(
            CRITERIA_URL(fake_id), json={"criteria": ["Test"]}
        )
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_update_rejects_empty_criteria(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())
        create = await client.post(
            INTERVIEWS_URL,
            json=VALID_INTERVIEW_PAYLOAD,
            headers=auth_headers(token),
        )
        iid = create.json()["data"]["id"]

        response = await client.put(
            CRITERIA_URL(iid),
            json={"criteria": []},
            headers=auth_headers(token),
        )
        assert response.status_code == 422
