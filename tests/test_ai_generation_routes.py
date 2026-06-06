"""
Tests for AI generation HTTP endpoints (route layer).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.auth import AuthService
from tests.test_helpers import create_interview_via_route

INTERVIEWS_URL = "/api/v1/interviews"


# --- Teammate's Auth Helpers ---
async def create_user(db: AsyncSession, email: str | None = None) -> User:
    user = User(
        email=email or f"{uuid.uuid4().hex[:8]}@example.com",
        is_verified=True,
    )
    db.add(user)
    await db.flush()
    return user


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- Shared Test Data ---
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


# Fix: Ensure db_session is passed so create_interview_via_route can create a candidate
async def create_interview(
    client: AsyncClient, db_session: AsyncSession, token: str
) -> str:
    response = await create_interview_via_route(
        client=client,
        db_session=db_session,
        token=token,
        interview_overrides=VALID_INTERVIEW_PAYLOAD,
    )
    assert response.status_code == 201
    return str(response.json()["data"]["id"])


MOCK_QUESTION = "What is your experience with Python?"
PATCH_TARGET = "app.api.v1.routes.ai_generation.AIGenerationService"


class TestGenerateQuestion:
    @pytest.mark.anyio
    async def test_returns_question(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
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


class TestRespond:
    @pytest.mark.anyio
    async def test_records_response_and_returns_next_question(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
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

        assert response.status_code == 200
        assert response.json()["data"]["response"] == MOCK_QUESTION

    @pytest.mark.anyio
    async def test_returns_404_for_other_users_interview(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_a = await create_user(db_session)
        token_a = await AuthService.create_access_token(user_a)
        user_b = await create_user(db_session)
        token_b = await AuthService.create_access_token(user_b)
        iid = await create_interview(client, db_session, token_a)

        response = await client.post(
            f"{INTERVIEWS_URL}/{iid}/respond",
            json={"content": "Hello"},
            headers=auth_headers(token_b),
        )
        assert response.status_code == 404


class TestComplete:
    @pytest.mark.anyio
    async def test_marks_interview_completed(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        iid = await create_interview(client, db_session, token)

        response = await client.post(
            f"{INTERVIEWS_URL}/{iid}/complete",
            headers=auth_headers(token),
        )

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "completed"


class TestChat:
    MOCK_CHAT_RESPONSE = {
        "role": "assistant",
        "content": "The candidate showed strong problem-solving skills.",
        "sent_at": "2026-05-24T22:00:00",
        "sequence_no": 2,
    }

    @pytest.mark.anyio
    async def test_returns_chat_response(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
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

        assert response.status_code == 200
        assert response.json()["data"]["content"] == self.MOCK_CHAT_RESPONSE["content"]


class TestSummaryRetry:
    @pytest.mark.anyio
    async def test_retries_failed_summary(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        iid = await create_interview(client, db_session, token)

        with patch(
            "app.api.v1.routes.ai_generation.InterviewService.retry_summary",
            new=AsyncMock(return_value={"status": "generating"}),
        ):
            response = await client.post(
                f"{INTERVIEWS_URL}/{iid}/summary/retry",
                headers=auth_headers(token),
            )

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "generating"
