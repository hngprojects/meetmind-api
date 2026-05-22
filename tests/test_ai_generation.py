"""
Tests for AI HTTP endpoints.

Endpoints under test
--------------------
POST /api/v1/interviews/{id}/ai/reply
POST /api/v1/interviews/{id}/ai/summary
POST /api/v1/interviews/{id}/ai/ask
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient

SIGNUP_URL = "/api/v1/auth/signup"
INTERVIEWS_URL = "/api/v1/interviews"

PATCH_TARGET = "app.services.ai_integration_service.generate_with_gemini"


def unique_user(tag: str | None = None) -> dict:
    suffix = tag or uuid.uuid4().hex[:8]
    return {
        "name": "AI Tester",
        "email": f"ai_tester_{suffix}@example.com",
        "password": "SecurePass1!",
    }


async def signup_and_get_token(client: AsyncClient, user: dict) -> str:
    response = await client.post(SIGNUP_URL, json=user)
    assert response.status_code == 201
    return response.json()["data"]["access_token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def create_interview(client: AsyncClient, token: str) -> tuple[str, str]:
    """Create a draft interview and return (interview_id, candidate_id)."""
    response = await client.post(
        INTERVIEWS_URL,
        json=VALID_INTERVIEW_PAYLOAD,
        headers=auth_headers(token),
    )
    assert response.status_code == 201
    data = response.json()["data"]
    return data["id"], data["candidate_id"]


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


class TestGenerateAIReply:
    @pytest.mark.anyio
    async def test_generate_ai_reply_returns_200_with_valid_payload(
        self, client: AsyncClient
    ):
        token = await signup_and_get_token(client, unique_user())
        iid, candidate_id = await create_interview(client, token)

        payload = {
            "transcript_text": "Candidate discussed their experience with Python.",
            "candidate_id": candidate_id,
            "job_description": VALID_INTERVIEW_PAYLOAD["job_description"],
            "scoring_rubric": VALID_INTERVIEW_PAYLOAD["scoring_rubric"],
            "session_id": "test-session-id",
        }

        mock_response = MagicMock()
        mock_response.candidates[0].content.parts[0].text = json.dumps(
            {
                "reply": "Tell me about your experience.",
                "highlights": [],
                "red_flags": [],
            }
        )

        with patch(PATCH_TARGET, return_value=mock_response):
            response = await client.post(
                f"{INTERVIEWS_URL}/{iid}/ai/reply",
                json=payload,
                headers=auth_headers(token),
            )

        body = response.json()
        assert response.status_code == 200, (
            f"Expected 200 but got {response.status_code}. Body: {body}"
        )
        assert "reply" in body["data"]
        assert "highlights" in body["data"]
        assert "red_flags" in body["data"]


class TestGenerateAISummary:
    @pytest.mark.anyio
    async def test_generate_ai_summary_returns_200_with_valid_payload(
        self, client: AsyncClient
    ):
        token = await signup_and_get_token(client, unique_user())
        iid, candidate_id = await create_interview(client, token)

        payload = {
            "candidate_id": candidate_id,
            "job_description": VALID_INTERVIEW_PAYLOAD["job_description"],
            "scoring_rubric": VALID_INTERVIEW_PAYLOAD["scoring_rubric"],
            "transcript_text": (
                "Candidate explained how they optimized database queries."
            ),
        }

        mock_response = MagicMock()
        mock_response.candidates[0].content.parts[0].text = json.dumps(
            {
                "summary": "Strong candidate.",
                "keypoints": [],
                "decisions": [],
                "action_items": [],
            }
        )

        with patch(PATCH_TARGET, return_value=mock_response):
            response = await client.post(
                f"{INTERVIEWS_URL}/{iid}/ai/summary",
                json=payload,
                headers=auth_headers(token),
            )

        body = response.json()
        assert response.status_code == 200, (
            f"Expected 200 but got {response.status_code}. Body: {body}"
        )
        assert "summary" in body["data"]
        assert "keypoints" in body["data"]
        assert "decisions" in body["data"]
        assert "action_items" in body["data"]


class TestAskMind:
    @pytest.mark.anyio
    async def test_ask_mind_returns_200_with_valid_query(self, client: AsyncClient):
        token = await signup_and_get_token(client, unique_user())
        iid, candidate_id = await create_interview(client, token)

        payload = {
            "candidate_id": candidate_id,
            "query": "What are the candidate's strengths?",
            "transcript_text": (
                "Candidate highlighted problem-solving and adaptability."
            ),
        }

        mock_response = MagicMock()
        mock_response.candidates[0].content.parts[0].text = json.dumps(
            {
                "query": payload["query"],
                "answer": "Good problem solver.",
            }
        )

        with patch(PATCH_TARGET, return_value=mock_response):
            response = await client.post(
                f"{INTERVIEWS_URL}/{iid}/ai/ask",
                json=payload,
                headers=auth_headers(token),
            )

        body = response.json()
        assert response.status_code == 200, (
            f"Expected 200 but got {response.status_code}. Body: {body}"
        )
        assert body["data"]["query"] == payload["query"]
        assert "answer" in body["data"]
