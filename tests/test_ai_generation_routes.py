"""
Tests for AI generation HTTP endpoints (route layer).

Endpoints under test
--------------------
POST /api/v1/interviews/{id}/generate-question
POST /api/v1/interviews/{id}/respond
POST /api/v1/interviews/{id}/complete
POST /api/v1/interviews/{id}/ask
POST /api/v1/interviews/{id}/summary/generate
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_helpers import create_interview_via_route

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
    "role_title": "Senior Backend Engineer",
    "platform": "zoom",
    "call_link": "https://zoom.us/j/123456789",
    "scheduled_start": "2026-06-01T17:30:00Z",
    "scheduled_end": "2026-06-01T18:30:00Z",
    "ai_tone": "professional",
    "skills_to_assess": ["Communication", "API Design", "Problem Solving"],
    "custom_question": "Validate backend architecture thinking.",
}


async def create_interview(client: AsyncClient, db_session: AsyncSession, token: str) -> str:
    response = await create_interview_via_route(
        client=client,
        db_session=db_session,
        token=token,
        interview_overrides=VALID_INTERVIEW_PAYLOAD,
    )
    assert response.status_code == 201
    return str(response.json()["data"]["id"])


MOCK_QUESTION = "What is your experience with Python?"
MOCK_ANSWER = "The candidate demonstrated strong Python skills."

PATCH_TARGET = "app.api.v1.routes.ai_generation.AIGenerationService"


class TestGenerateQuestion:
    """POST /interviews/{id}/generate-question"""

    @pytest.mark.anyio
    async def test_returns_question(self, client: AsyncClient, db_session: AsyncSession):
        token = await signup_and_get_token(client, unique_user())
        iid = await create_interview(client, db_session, token)

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
        self, client: AsyncClient, db_session: AsyncSession
    ):
        token = await signup_and_get_token(client, unique_user())
        iid = await create_interview(client, db_session, token)

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
        self, client: AsyncClient, db_session: AsyncSession
    ):
        token_a = await signup_and_get_token(client, unique_user("r_a"))
        token_b = await signup_and_get_token(client, unique_user("r_b"))
        iid = await create_interview(client, db_session, token_a)

        response = await client.post(
            f"{INTERVIEWS_URL}/{iid}/respond",
            json={"content": "Hello"},
            headers=auth_headers(token_b),
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "interview_not_found"

    @pytest.mark.anyio
    async def test_returns_422_for_empty_content(self, client: AsyncClient, db_session: AsyncSession):
        token = await signup_and_get_token(client, unique_user())
        iid = await create_interview(client, db_session, token)

        response = await client.post(
            f"{INTERVIEWS_URL}/{iid}/respond",
            json={"content": ""},
            headers=auth_headers(token),
        )
        assert response.status_code == 422


class TestComplete:
    """POST /interviews/{id}/complete"""

    @pytest.mark.anyio
    async def test_marks_interview_completed(self, client: AsyncClient, db_session: AsyncSession):
        token = await signup_and_get_token(client, unique_user())
        iid = await create_interview(client, db_session, token)

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
        self, client: AsyncClient, db_session: AsyncSession
    ):
        token_a = await signup_and_get_token(client, unique_user("c_a"))
        token_b = await signup_and_get_token(client, unique_user("c_b"))
        iid = await create_interview(client, db_session, token_a)

        response = await client.post(
            f"{INTERVIEWS_URL}/{iid}/complete",
            headers=auth_headers(token_b),
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "interview_not_found"


class TestChat:
    """POST /interviews/{id}/chat"""

    MOCK_CHAT_RESPONSE = {
        "role": "assistant",
        "content": "The candidate showed strong problem-solving skills.",
        "sent_at": "2026-05-24T22:00:00",
        "sequence_no": 2,
    }

    @pytest.mark.anyio
    async def test_returns_chat_response(self, client: AsyncClient, db_session: AsyncSession):
        token = await signup_and_get_token(client, unique_user())
        iid = await create_interview(client, db_session, token)

        with patch(
            f"{PATCH_TARGET}.send_chat_message",
            new=AsyncMock(return_value=self.MOCK_CHAT_RESPONSE),
        ):
            response = await client.post(
                f"{INTERVIEWS_URL}/{iid}/chat",
                json={"query": "How did the candidate do?"},
                headers=auth_headers(token),
            )

        body = response.json()
        assert response.status_code == 200
        assert body["data"]["role"] == "assistant"
        assert body["data"]["content"] == self.MOCK_CHAT_RESPONSE["content"]
        assert body["data"]["sequence_no"] == 2
        assert body["message"] == "Query answered"

    @pytest.mark.anyio
    async def test_returns_401_without_token(self, client: AsyncClient):
        response = await client.post(
            f"{INTERVIEWS_URL}/{uuid.uuid4()}/chat",
            json={"content": "Hello"},
        )
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_returns_422_for_empty_query(self, client: AsyncClient, db_session: AsyncSession):
        token = await signup_and_get_token(client, unique_user())
        iid = await create_interview(client, db_session, token)

        response = await client.post(
            f"{INTERVIEWS_URL}/{iid}/chat",
            json={"query": ""},
            headers=auth_headers(token),
        )
        assert response.status_code == 422


class TestSummaryGenerate:
    """POST /interviews/{id}/summary/generate"""

    @pytest.mark.anyio
    async def test_returns_accepted(self, client: AsyncClient, db_session: AsyncSession):
        token = await signup_and_get_token(client, unique_user())
        iid = await create_interview(client, db_session, token)

        with patch(
            f"{PATCH_TARGET}._get_interview_or_404",
            new=AsyncMock(),
        ):
            response = await client.post(
                f"{INTERVIEWS_URL}/{iid}/summary/generate",
                headers=auth_headers(token),
            )

        body = response.json()
        assert response.status_code == 202
        assert body["data"]["status"] == "generating"
        assert body["message"] == "Assessment generation started"

    @pytest.mark.anyio
    async def test_returns_401_without_token(self, client: AsyncClient):
        response = await client.post(
            f"{INTERVIEWS_URL}/{uuid.uuid4()}/summary/generate"
        )
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_returns_404_for_nonexistent_interview(
        self, client: AsyncClient
    ):
        token = await signup_and_get_token(client, unique_user())
        fake_id = str(uuid.uuid4())

        response = await client.post(
            f"{INTERVIEWS_URL}/{fake_id}/summary/generate",
            headers=auth_headers(token),
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "interview_not_found"


class TestSummaryRetry:
    """POST /interviews/{id}/summary/retry"""

    @pytest.mark.anyio
    async def test_retries_failed_summary(self, client: AsyncClient, db_session: AsyncSession):
        token = await signup_and_get_token(client, unique_user())
        iid = await create_interview(client, db_session, token)

        with patch(
            "app.api.v1.routes.ai_generation.InterviewService.retry_summary",
            new=AsyncMock(return_value={"status": "generating"}),
        ):
            response = await client.post(
                f"{INTERVIEWS_URL}/{iid}/summary/retry",
                headers=auth_headers(token),
            )

        body = response.json()
        assert response.status_code == 200
        assert body["data"]["status"] == "generating"
        assert body["message"] == "Summary retry started"

    @pytest.mark.anyio
    async def test_returns_401_without_token(self, client: AsyncClient):
        response = await client.post(
            f"{INTERVIEWS_URL}/{uuid.uuid4()}/summary/retry"
        )
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_returns_404_for_nonexistent_interview(
        self, client: AsyncClient
    ):
        token = await signup_and_get_token(client, unique_user())
        fake_id = str(uuid.uuid4())

        response = await client.post(
            f"{INTERVIEWS_URL}/{fake_id}/summary/retry",
            headers=auth_headers(token),
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "interview_not_found"
