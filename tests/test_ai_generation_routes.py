"""
Tests for AI generation HTTP endpoints (route layer).

Endpoints under test
--------------------
POST /api/v1/interviews/{id}/generate-question
POST /api/v1/interviews/{id}/respond
POST /api/v1/interviews/{id}/complete
POST /api/v1/interviews/{id}/ask
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

SIGNUP_URL = "/api/v1/auth/signup"
INTERVIEWS_URL = "/api/v1/interviews"


def unique_user(tag: str | None = None) -> dict:
    suffix = tag or uuid.uuid4().hex[:8]
    return {
        "name": "AI Gen Tester",
        "email": f"ai_gen_{suffix}@example.com",
        "password": "SecurePass1!",
    }


async def signup_and_get_token(client: AsyncClient, user: dict) -> str:
    response = await client.post(SIGNUP_URL, json=user)
    assert response.status_code == 201
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
    response = await client.post(
        INTERVIEWS_URL,
        json=VALID_INTERVIEW_PAYLOAD,
        headers=auth_headers(token),
    )
    assert response.status_code == 201
    return response.json()["data"]["id"]


MOCK_QUESTION = "What is your experience with Python?"
MOCK_ANSWER = "The candidate demonstrated strong Python skills."

PATCH_TARGET = "app.api.v1.routes.ai_generation.AIGenerationService"


class TestGenerateQuestion:
    """POST /interviews/{id}/generate-question"""

    @pytest.mark.anyio
    async def test_returns_question(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())
        iid = await create_interview(client, token)

        with patch(
            f"{PATCH_TARGET}.generate_next_question",
            new=AsyncMock(return_value=MOCK_QUESTION),
        ):
            response = await client.post(
                f"{INTERVIEWS_URL}/{iid}/generate-question",
                headers=auth_headers(token),
            )

        body = response.json()
        assert response.status_code == 200
        assert body["data"]["question"] == MOCK_QUESTION
        assert body["message"] == "Question generated"

    @pytest.mark.anyio
    async def test_returns_401_without_token(self, client: AsyncClient):
        response = await client.post(
            f"{INTERVIEWS_URL}/{uuid.uuid4()}/generate-question"
        )
        assert response.status_code == 401


class TestRespond:
    """POST /interviews/{id}/respond"""

    @pytest.mark.anyio
    async def test_records_response_and_returns_next_question(
        self, client: AsyncClient
    ):
        token = await signup_and_get_token(client, unique_user())
        iid = await create_interview(client, token)

        with patch(
            f"{PATCH_TARGET}.generate_next_question",
            new=AsyncMock(return_value=MOCK_QUESTION),
        ):
            response = await client.post(
                f"{INTERVIEWS_URL}/{iid}/respond",
                json={"content": "I have 5 years of experience."},
                headers=auth_headers(token),
            )

        body = response.json()
        assert response.status_code == 200
        assert body["data"]["response"] == MOCK_QUESTION
        assert body["message"] == "Response recorded"

    @pytest.mark.anyio
    async def test_returns_401_without_token(self, client: AsyncClient):
        response = await client.post(
            f"{INTERVIEWS_URL}/{uuid.uuid4()}/respond",
            json={"content": "Hello"},
        )
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_returns_404_for_nonexistent_interview(
        self, client: AsyncClient
    ):
        token = await signup_and_get_token(client, unique_user())
        fake_id = str(uuid.uuid4())

        response = await client.post(
            f"{INTERVIEWS_URL}/{fake_id}/respond",
            json={"content": "Hello"},
            headers=auth_headers(token),
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "interview_not_found"

    @pytest.mark.anyio
    async def test_returns_404_for_other_users_interview(
        self, client: AsyncClient
    ):
        token_a = await signup_and_get_token(client, unique_user("r_a"))
        token_b = await signup_and_get_token(client, unique_user("r_b"))
        iid = await create_interview(client, token_a)

        response = await client.post(
            f"{INTERVIEWS_URL}/{iid}/respond",
            json={"content": "Hello"},
            headers=auth_headers(token_b),
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "interview_not_found"

    @pytest.mark.anyio
    async def test_returns_422_for_empty_content(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())
        iid = await create_interview(client, token)

        response = await client.post(
            f"{INTERVIEWS_URL}/{iid}/respond",
            json={"content": ""},
            headers=auth_headers(token),
        )
        assert response.status_code == 422


class TestComplete:
    """POST /interviews/{id}/complete"""

    @pytest.mark.anyio
    async def test_marks_interview_completed(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())
        iid = await create_interview(client, token)

        response = await client.post(
            f"{INTERVIEWS_URL}/{iid}/complete",
            headers=auth_headers(token),
        )

        body = response.json()
        assert response.status_code == 200
        assert body["data"]["status"] == "completed"
        assert body["message"] == "Interview completed, assessment generation started"

        get = await client.get(
            f"{INTERVIEWS_URL}/{iid}", headers=auth_headers(token)
        )
        assert get.json()["data"]["status"] == "completed"

    @pytest.mark.anyio
    async def test_returns_401_without_token(self, client: AsyncClient):
        response = await client.post(
            f"{INTERVIEWS_URL}/{uuid.uuid4()}/complete"
        )
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_returns_404_for_nonexistent_interview(
        self, client: AsyncClient
    ):
        token = await signup_and_get_token(client, unique_user())
        fake_id = str(uuid.uuid4())

        response = await client.post(
            f"{INTERVIEWS_URL}/{fake_id}/complete",
            headers=auth_headers(token),
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "interview_not_found"

    @pytest.mark.anyio
    async def test_returns_404_for_other_users_interview(
        self, client: AsyncClient
    ):
        token_a = await signup_and_get_token(client, unique_user("c_a"))
        token_b = await signup_and_get_token(client, unique_user("c_b"))
        iid = await create_interview(client, token_a)

        response = await client.post(
            f"{INTERVIEWS_URL}/{iid}/complete",
            headers=auth_headers(token_b),
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "interview_not_found"


class TestAsk:
    """POST /interviews/{id}/ask"""

    @pytest.mark.anyio
    async def test_returns_answer(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())
        iid = await create_interview(client, token)

        with patch(
            f"{PATCH_TARGET}.answer_query",
            new=AsyncMock(return_value=MOCK_ANSWER),
        ):
            response = await client.post(
                f"{INTERVIEWS_URL}/{iid}/ask",
                json={"query": "How did the candidate do?"},
                headers=auth_headers(token),
            )

        body = response.json()
        assert response.status_code == 200
        assert body["data"]["answer"] == MOCK_ANSWER
        assert body["message"] == "Query answered"

    @pytest.mark.anyio
    async def test_returns_401_without_token(self, client: AsyncClient):
        response = await client.post(
            f"{INTERVIEWS_URL}/{uuid.uuid4()}/ask",
            json={"query": "How did they do?"},
        )
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_returns_422_for_empty_query(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())
        iid = await create_interview(client, token)

        response = await client.post(
            f"{INTERVIEWS_URL}/{iid}/ask",
            json={"query": ""},
            headers=auth_headers(token),
        )
        assert response.status_code == 422
