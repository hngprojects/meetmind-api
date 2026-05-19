"""
Tests for GET /api/v1/interviews/{interview_id}/chat/history
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

# ── URLs ─────────────────────────────────────────────────────────────

SIGNUP_URL = "/api/v1/auth/signup"
INTERVIEWS_URL = "/api/v1/interviews"
CHAT_HISTORY_URL = "/api/v1/interviews/{id}/chat/history"


# ── helpers ──────────────────────────────────────────────────────────


def unique_user(tag: str | None = None) -> dict:
    suffix = tag or uuid.uuid4().hex[:8]
    return {
        "name": "Chat Tester",
        "email": f"chat_{suffix}@example.com",
        "password": "SecurePass1!",
    }


async def signup_and_get_token(client: AsyncClient, user: dict) -> str:
    res = await client.post(SIGNUP_URL, json=user)
    assert res.status_code == 201
    return res.json()["data"]["access_token"]


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
    async def test_returns_empty_when_no_transcript(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())

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
    async def test_returns_404_for_unknown_id(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())

        res = await client.get(
            CHAT_HISTORY_URL.format(id=str(uuid.uuid4())),
            headers=auth_headers(token),
        )

        assert res.status_code == 404

    @pytest.mark.anyio
    async def test_returns_404_for_other_users_interview(self, client: AsyncClient):
        token_a = await signup_and_get_token(client, unique_user("a"))
        token_b = await signup_and_get_token(client, unique_user("b"))

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
        self, client: AsyncClient
    ):
        """
        NOTE:
        This assumes your system eventually creates transcript messages.
        If not, this test will fail — which is correct.
        """
        token = await signup_and_get_token(client, unique_user())

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
    async def test_roles_are_valid(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())

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
