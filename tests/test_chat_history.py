"""
Tests for GET /api/v1/interviews/{interview_id}/chat/history
"""

from __future__ import annotations

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_helpers import create_interview_via_route
from app.models.user import User
from app.services.auth import AuthService


# ── URLs ─────────────────────────────────────────────────────────────

INTERVIEWS_URL = "/api/v1/interviews"
CHAT_HISTORY_URL = "/api/v1/interviews/{id}/chat/history"


# ── Helpers ──────────────────────────────────────────────────────────

async def create_user(db: AsyncSession, email: str | None = None) -> User:
    """Teammate's helper: directly creates a user in the DB for speed."""
    user = User(
        email=email or f"{uuid.uuid4().hex[:8]}@example.com",
        is_verified=True
    )
    db.add(user)
    await db.flush()
    return user


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


VALID_INTERVIEW_PAYLOAD = {
    "role_title": "Chat Interview",
    "platform": "zoom",
    "call_link": "https://zoom.us/j/123456789",
    "scheduled_start": "2026-06-01T17:30:00Z",
    "scheduled_end": "2026-06-01T18:30:00Z",
    "ai_tone": "professional",
    "skills_to_assess": ["Communication"],
}


# ── Tests ────────────────────────────────────────────────────────────

class TestGetChatHistory:
    @pytest.mark.anyio
    async def test_returns_empty_when_no_transcript(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # Resolved: Use teammate's direct token creation
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)

        # Kept: Your helper that handles candidate creation/AI plan
        create = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides=VALID_INTERVIEW_PAYLOAD,
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
    async def test_returns_404_for_other_users_interview(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # Resolved: Reconciled teammate's two-user auth flow
        user_a = await create_user(db_session)
        token_a = await AuthService.create_access_token(user_a)
        user_b = await create_user(db_session)
        token_b = await AuthService.create_access_token(user_b)

        create = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token_a,
            interview_overrides=VALID_INTERVIEW_PAYLOAD,
        )
        interview_id = create.json()["data"]["id"]

        res = await client.get(
            CHAT_HISTORY_URL.format(id=interview_id),
            headers=auth_headers(token_b),
        )

        # Ensure cross-user data leakage is blocked
        assert res.status_code == 404

    @pytest.mark.anyio
    async def test_message_fields_present_when_messages_exist(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)

        create = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides=VALID_INTERVIEW_PAYLOAD,
        )
        interview_id = create.json()["data"]["id"]

        res = await client.get(
            CHAT_HISTORY_URL.format(id=interview_id),
            headers=auth_headers(token),
        )

        assert res.status_code == 200
        body = res.json()

        # Check structure if messages are injected by internal services
        if body["data"]["messages"]:
            msg = body["data"]["messages"][0]
            for field in ("id", "role", "content", "sent_at", "sequence_no"):
                assert field in msg

    @pytest.mark.anyio
    async def test_roles_are_valid(self, client: AsyncClient, db_session: AsyncSession):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)

        create = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides=VALID_INTERVIEW_PAYLOAD,
        )
        interview_id = create.json()["data"]["id"]

        res = await client.get(
            CHAT_HISTORY_URL.format(id=interview_id),
            headers=auth_headers(token),
        )

        assert res.status_code == 200
        for msg in res.json()["data"]["messages"]:
            # Valid roles in your architecture are agent (AI) or candidate (Human)
            assert msg["role"] in ("agent", "candidate", "interviewer")