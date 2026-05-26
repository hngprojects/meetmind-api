"""Tests for GET /api/v1/interviews/{id}/summary"""

import json
import uuid

import pytest
from httpx import AsyncClient

from app.models.interview import Interview, InterviewSummary
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.auth import AuthService


SUMMARY_URL = "/api/v1/interviews/{id}/summary"
RETRY_URL = "/api/v1/interviews/{id}/summary/retry"
SESSION_URL = "/api/v1/interviews/{id}/session"


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def create_user_with_workspace(db_session) -> tuple[User, Workspace]:
    user = User(
        name="Test User",
        email=f"test-{uuid.uuid4()}@example.com",
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    workspace = Workspace(name="Test Workspace", created_by=user.id)
    db_session.add(workspace)
    await db_session.flush()

    db_session.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role="owner",
        )
    )
    await db_session.commit()
    return user, workspace


async def create_interview(
    db_session, user, workspace, status="completed"
) -> Interview:
    interview = Interview(
        workspace_id=workspace.id,
        interviewer_id=user.id,
        status=status,
    )
    db_session.add(interview)
    await db_session.commit()
    await db_session.refresh(interview)
    return interview


async def create_summary(
    db_session, interview, status="completed", with_assessment=True
) -> InterviewSummary:
    assessment = None
    if with_assessment:
        assessment = json.dumps(
            {
                "observation": "Strong candidate",
                "highlights": ["Clear communication", "Structured thinking"],
                "red_flags": ["Struggled with ambiguity"],
            }
        )

    summary = InterviewSummary(
        interview_id=interview.id,
        status=status,
        ai_assessment=assessment,
        custom_question="Tell me about a challenge you faced.",
        key_skills="Python,FastAPI,PostgreSQL",
    )
    db_session.add(summary)
    await db_session.commit()
    await db_session.refresh(summary)
    return summary


# ── GET /summary ───────────────────────────────────────────────────────────────


class TestGetSummary:
    @pytest.mark.anyio
    async def test_returns_200_with_structured_summary(
        self, client: AsyncClient, db_session
    ):
        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)
        interview = await create_interview(db_session, user, workspace)
        await create_summary(db_session, interview)

        response = await client.get(
            SUMMARY_URL.format(id=interview.id),
            headers=auth_header(token),
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["status"] == "completed"
        assert data["observation"] == "Strong candidate"
        assert data["highlights"] == ["Clear communication", "Structured thinking"]
        assert data["red_flags"] == ["Struggled with ambiguity"]
        assert data["key_skills"] == ["Python", "FastAPI", "PostgreSQL"]

    @pytest.mark.anyio
    async def test_returns_pending_when_no_summary_exists(
        self, client: AsyncClient, db_session
    ):
        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)
        interview = await create_interview(db_session, user, workspace)

        response = await client.get(
            SUMMARY_URL.format(id=interview.id),
            headers=auth_header(token),
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["status"] == "pending"
        assert data["highlights"] == []
        assert data["red_flags"] == []
        assert data["key_skills"] == []

    @pytest.mark.anyio
    async def test_returns_404_for_nonexistent_interview(
        self, client: AsyncClient, db_session
    ):
        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)

        response = await client.get(
            SUMMARY_URL.format(id=uuid.uuid4()),
            headers=auth_header(token),
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "interview_not_found"

    @pytest.mark.anyio
    async def test_returns_404_for_another_users_interview(
        self, client: AsyncClient, db_session
    ):
        user_a, workspace_a = await create_user_with_workspace(db_session)
        user_b, _ = await create_user_with_workspace(db_session)
        token_b = await AuthService.create_access_token(user_b)
        interview = await create_interview(db_session, user_a, workspace_a)

        response = await client.get(
            SUMMARY_URL.format(id=interview.id),
            headers=auth_header(token_b),
        )

        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_returns_401_without_token(self, client: AsyncClient):
        response = await client.get(SUMMARY_URL.format(id=uuid.uuid4()))
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_handles_corrupted_assessment_gracefully(
        self, client: AsyncClient, db_session
    ):
        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)
        interview = await create_interview(db_session, user, workspace)
        summary = InterviewSummary(
            interview_id=interview.id,
            status="completed",
            ai_assessment="this is not valid json",
        )
        db_session.add(summary)
        await db_session.commit()

        response = await client.get(
            SUMMARY_URL.format(id=interview.id),
            headers=auth_header(token),
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["highlights"] == []
        assert data["red_flags"] == []
        assert data["observation"] is None


# ── POST /summary/retry ────────────────────────────────────────────────────────


class TestRetrySummary:
    @pytest.mark.anyio
    async def test_returns_200_and_sets_generating(
        self, client: AsyncClient, db_session
    ):
        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)
        interview = await create_interview(db_session, user, workspace)
        await create_summary(
            db_session, interview, status="failed", with_assessment=False
        )

        response = await client.post(
            RETRY_URL.format(id=interview.id),
            headers=auth_header(token),
        )

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "generating"

    @pytest.mark.anyio
    async def test_returns_409_when_summary_not_failed(
        self, client: AsyncClient, db_session
    ):
        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)
        interview = await create_interview(db_session, user, workspace)
        await create_summary(db_session, interview, status="completed")

        response = await client.post(
            RETRY_URL.format(id=interview.id),
            headers=auth_header(token),
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "summary_not_failed"

    @pytest.mark.anyio
    async def test_returns_404_for_nonexistent_interview(
        self, client: AsyncClient, db_session
    ):
        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)

        response = await client.post(
            RETRY_URL.format(id=uuid.uuid4()),
            headers=auth_header(token),
        )

        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_returns_401_without_token(self, client: AsyncClient):
        response = await client.post(RETRY_URL.format(id=uuid.uuid4()))
        assert response.status_code == 401


# ── GET /session ───────────────────────────────────────────────────────────────


class TestGetSession:
    @pytest.mark.anyio
    async def test_returns_200_with_session_status(
        self, client: AsyncClient, db_session
    ):
        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)
        interview = await create_interview(
            db_session, user, workspace, status="in_progress"
        )

        response = await client.get(
            SESSION_URL.format(id=interview.id),
            headers=auth_header(token),
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["status"] == "in_progress"
        assert data["session_phase"] == "live_transcript"
        assert data["connection_status"] == "connected"

    @pytest.mark.anyio
    async def test_elapsed_is_none_when_not_in_progress(
        self, client: AsyncClient, db_session
    ):
        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)
        interview = await create_interview(
            db_session, user, workspace, status="scheduled"
        )

        response = await client.get(
            SESSION_URL.format(id=interview.id),
            headers=auth_header(token),
        )

        assert response.status_code == 200
        assert response.json()["data"]["elapsed"] is None

    @pytest.mark.anyio
    async def test_session_phase_maps_correctly_for_completed(
        self, client: AsyncClient, db_session
    ):
        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)
        interview = await create_interview(
            db_session, user, workspace, status="completed"
        )

        response = await client.get(
            SESSION_URL.format(id=interview.id),
            headers=auth_header(token),
        )

        assert response.status_code == 200
        assert response.json()["data"]["session_phase"] == "summary_ready"
        assert response.json()["data"]["connection_status"] == "idle"

    @pytest.mark.anyio
    async def test_returns_404_for_nonexistent_interview(
        self, client: AsyncClient, db_session
    ):
        user, workspace = await create_user_with_workspace(db_session)
        token = await AuthService.create_access_token(user)

        response = await client.get(
            SESSION_URL.format(id=uuid.uuid4()),
            headers=auth_header(token),
        )

        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_returns_401_without_token(self, client: AsyncClient):
        response = await client.get(SESSION_URL.format(id=uuid.uuid4()))
        assert response.status_code == 401
