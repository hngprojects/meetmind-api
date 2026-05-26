"""
Tests for GET /api/v1/interviews/{interview_id}/chat/history
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.models.user import User
from app.services.auth import AuthService


# ── URLs ─────────────────────────────────────────────────────────────


INTERVIEWS_URL = "/api/v1/interviews"
CHAT_HISTORY_URL = "/api/v1/interviews/{id}/chat/history"


# ── helpers ──────────────────────────────────────────────────────────
async def create_user(db, email: str | None = None) -> User:
    user = User(email=email or f"{uuid.uuid4().hex[:8]}@example.com")
    user.is_verified = True
    db.add(user)
    await db.flush()
    return user


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


VALID_INTERVIEW_PAYLOAD = {
    "title": "Chat Interview",
    "candidate_name": "Jane Doe",
    "job_description": "Build APIs",
    "scoring_rubric": "Communication",
    "criteria": ["Communication"],
}


# ── tests ────────────────────────────────────────────────────────────


class TestGetChatHistory:
    @pytest.mark.anyio
    async def test_returns_empty_when_no_transcript(
        self, client: AsyncClient, db_session
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)

        create = await client.post(
            INTERVIEWS_URL,
            json=VALID_INTERVIEW_PAYLOAD,
            headers=auth_headers(token),
        )
        interview_id = create.json()["data"]["id"]

        res = await client.get(
            CHAT_HISTORY_URL.format(id=interview_id),
            headers=auth_headers(token),
        )

        assert res.status_code == 200
        body = res.json()
        assert body["data"]["total_messages"] == 0
        assert body["data"]["messages"] == []

    @pytest.mark.anyio
    async def test_returns_404_for_unknown_id(self, client: AsyncClient, db_session):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)

        res = await client.get(
            CHAT_HISTORY_URL.format(id=str(uuid.uuid4())),
            headers=auth_headers(token),
        )

        assert res.status_code == 404

    @pytest.mark.anyio
    async def test_returns_404_for_other_users_interview(
        self, client: AsyncClient, db_session
    ):
        user_a = await create_user(db_session)
        token_a = await AuthService.create_access_token(user_a)
        user_b = await create_user(db_session)
        token_b = await AuthService.create_access_token(user_b)

        create = await client.post(
            INTERVIEWS_URL,
            json=VALID_INTERVIEW_PAYLOAD,
            headers=auth_headers(token_a),
        )
        interview_id = create.json()["data"]["id"]

        res = await client.get(
            CHAT_HISTORY_URL.format(id=interview_id),
            headers=auth_headers(token_b),
        )

        assert res.status_code == 404

    @pytest.mark.anyio
    async def test_returns_401_unauthenticated(self, client: AsyncClient):
        res = await client.get(CHAT_HISTORY_URL.format(id=str(uuid.uuid4())))
        assert res.status_code == 401

    @pytest.mark.anyio
    async def test_message_fields_present_when_messages_exist(
        self, client: AsyncClient, db_session
    ):
        """
        NOTE:
        This assumes your system eventually creates transcript messages.
        If not, this test will fail — which is correct.
        """
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)

        create = await client.post(
            INTERVIEWS_URL,
            json=VALID_INTERVIEW_PAYLOAD,
            headers=auth_headers(token),
        )
        interview_id = create.json()["data"]["id"]

        res = await client.get(
            CHAT_HISTORY_URL.format(id=interview_id),
            headers=auth_headers(token),
        )

        assert res.status_code == 200
        body = res.json()

        if body["data"]["messages"]:
            msg = body["data"]["messages"][0]
            for field in ("id", "role", "content", "sent_at", "sequence_no"):
                assert field in msg

    @pytest.mark.anyio
    async def test_roles_are_valid(self, client: AsyncClient, db_session):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)

        create = await client.post(
            INTERVIEWS_URL,
            json=VALID_INTERVIEW_PAYLOAD,
            headers=auth_headers(token),
        )
        interview_id = create.json()["data"]["id"]

        res = await client.get(
            CHAT_HISTORY_URL.format(id=interview_id),
            headers=auth_headers(token),
        )

        assert res.status_code == 200
        for msg in res.json()["data"]["messages"]:
            assert msg["role"] in ("agent", "interviewer")
