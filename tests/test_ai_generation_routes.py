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
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.models.user import User
from app.services.auth import AuthService

INTERVIEWS_URL = "/api/v1/interviews"


async def create_user(db, email: str | None = None) -> User:
    user = User(email=email or f"{uuid.uuid4().hex[:8]}@example.com", is_verified=True,)
    db.add(user)
    await db.flush()
    return user


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
    async def test_returns_question(self, client: AsyncClient, db_session):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
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
        self, client: AsyncClient, db_session
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
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
        self, client: AsyncClient, db_session
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
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
        self, client: AsyncClient, db_session
    ):
        user_a = await create_user(db_session)
        token_a = await AuthService.create_access_token(user_a)
        user_b = await create_user(db_session)
        token_b = await AuthService.create_access_token(user_b)
        iid = await create_interview(client, token_a)

        response = await client.post(
            f"{INTERVIEWS_URL}/{iid}/respond",
            json={"content": "Hello"},
            headers=auth_headers(token_b),
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "interview_not_found"

    @pytest.mark.anyio
    async def test_returns_422_for_empty_content(self, client: AsyncClient, db_session):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
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
    async def test_marks_interview_completed(self, client: AsyncClient, db_session):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        iid = await create_interview(client, token)

        response = await client.post(
            f"{INTERVIEWS_URL}/{iid}/complete",
            headers=auth_headers(token),
        )

        body = response.json()
        assert response.status_code == 200
        assert body["data"]["status"] == "completed"
        assert body["message"] == "Interview completed, assessment generation started"

        get = await client.get(f"{INTERVIEWS_URL}/{iid}", headers=auth_headers(token))
        assert get.json()["data"]["status"] == "completed"

    @pytest.mark.anyio
    async def test_returns_401_without_token(self, client: AsyncClient):
        response = await client.post(f"{INTERVIEWS_URL}/{uuid.uuid4()}/complete")
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_returns_404_for_nonexistent_interview(
        self, client: AsyncClient, db_session
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        fake_id = str(uuid.uuid4())

        response = await client.post(
            f"{INTERVIEWS_URL}/{fake_id}/complete",
            headers=auth_headers(token),
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "interview_not_found"

    @pytest.mark.anyio
    async def test_returns_404_for_other_users_interview(
        self, client: AsyncClient, db_session
    ):
        user_a = await create_user(db_session)
        token_a = await AuthService.create_access_token(user_a)
        user_b = await create_user(db_session)
        token_b = await AuthService.create_access_token(user_b)
        iid = await create_interview(client, token_a)

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
    async def test_returns_chat_response(self, client: AsyncClient, db_session):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        iid = await create_interview(client, token)

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
    async def test_returns_422_for_empty_query(self, client: AsyncClient, db_session):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        iid = await create_interview(client, token)

        response = await client.post(
            f"{INTERVIEWS_URL}/{iid}/chat",
            json={"query": ""},
            headers=auth_headers(token),
        )
        assert response.status_code == 422


class TestSummaryGenerate:
    """POST /interviews/{id}/summary/generate"""

    @pytest.mark.anyio
    async def test_returns_accepted(self, client: AsyncClient, db_session):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        iid = await create_interview(client, token)

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
        self, client: AsyncClient, db_session
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
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
    async def test_retries_failed_summary(self, client: AsyncClient, db_session):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        iid = await create_interview(client, token)

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
        response = await client.post(f"{INTERVIEWS_URL}/{uuid.uuid4()}/summary/retry")
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_returns_404_for_nonexistent_interview(
        self, client: AsyncClient, db_session
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        fake_id = str(uuid.uuid4())

        response = await client.post(
            f"{INTERVIEWS_URL}/{fake_id}/summary/retry",
            headers=auth_headers(token),
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "interview_not_found"
