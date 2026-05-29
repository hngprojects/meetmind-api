import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.interview import Interview, InterviewSession
from app.models.notification import Notification
from app.models.user import User
from app.services.auth import AuthService
from app.services.notification_service import NotificationService
from tests.test_helpers import create_interview_via_route


async def _create_user(db: AsyncSession) -> User:
    user = User(email=f"{uuid.uuid4().hex[:8]}@example.com", is_verified=True)
    db.add(user)
    await db.flush()
    return user


async def _auth_header(user: User) -> dict:
    token = await AuthService.create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


class TestHook1LiveKitResult:

    @pytest.mark.anyio
    async def test_completing_interview_creates_report_notification(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        user = await _create_user(db_session)
        session = InterviewSession(
            role="Engineer",
            candidate_name="Test",
            intro="Intro",
            questions_json="[]",
            rubric_json="[]",
            duration_minutes=20,
            closing="Thanks",
            status="created",
        )
        db_session.add(session)
        await db_session.flush()

        interview = Interview(
            workspace_id=uuid.uuid4(),
            candidate_id=None,
            interviewer_id=user.id,
            session_id=session.id,
            role_title="Engineer",
            status="scheduled",
            participation_mode="standard",
        )
        db_session.add(interview)
        await db_session.commit()

        resp = await client.post(
            f"/api/v1/livekit/{session.id}/result",
            json={"transcript": [], "report": "Great"},
        )

        assert resp.status_code == 200

        result = await db_session.execute(
            select(Notification).where(Notification.user_id == user.id)
        )
        notif = result.scalar_one_or_none()
        assert notif is not None
        assert notif.type == "report"
        assert notif.title == "Interview Summary Ready"
        assert notif.action_url == f"/interviews/{interview.id}"

    @pytest.mark.anyio
    async def test_notification_failure_does_not_break_result(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        user = await _create_user(db_session)
        session = InterviewSession(
            role="Engineer",
            candidate_name="Test",
            intro="Intro",
            questions_json="[]",
            rubric_json="[]",
            duration_minutes=20,
            closing="Thanks",
            status="created",
        )
        db_session.add(session)
        await db_session.flush()

        interview = Interview(
            workspace_id=uuid.uuid4(),
            candidate_id=None,
            interviewer_id=user.id,
            session_id=session.id,
            role_title="Engineer",
            status="scheduled",
            participation_mode="standard",
        )
        db_session.add(interview)
        await db_session.commit()

        with patch.object(
            NotificationService, "create", side_effect=Exception("DB error")
        ):
            resp = await client.post(
                f"/api/v1/livekit/{session.id}/result",
                json={"transcript": [], "report": "Great"},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "success"


class TestHook2InterviewCreated:

    @pytest.mark.anyio
    async def test_creating_interview_creates_meeting_notification(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        user = await _create_user(db_session)
        token = await AuthService.create_access_token(user)

        resp = await create_interview_via_route(client, db_session, token)
        assert resp.status_code == 201

        result = await db_session.execute(
            select(Notification).where(Notification.user_id == user.id)
        )
        notif = result.scalar_one_or_none()
        assert notif is not None
        assert notif.type == "meeting"
        assert notif.title == "Interview Scheduled"

    @pytest.mark.anyio
    async def test_notification_failure_does_not_break_creation(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        user = await _create_user(db_session)
        token = await AuthService.create_access_token(user)

        with patch.object(
            NotificationService, "create", side_effect=Exception("DB error")
        ):
            resp = await create_interview_via_route(client, db_session, token)

        assert resp.status_code == 201


class TestHook3IntegrationConnected:

    @pytest.mark.anyio
    async def test_connecting_integration_creates_integration_notification(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        user = await _create_user(db_session)
        headers = await _auth_header(user)

        resp = await client.post(
            "/api/v1/onboarding/integrations",
            json={"integrations": "google"},
            headers=headers,
        )
        assert resp.status_code == 200

        result = await db_session.execute(
            select(Notification).where(Notification.user_id == user.id)
        )
        notif = result.scalar_one_or_none()
        assert notif is not None
        assert notif.type == "integration"
        assert notif.title == "Integration Connected"
        assert "google" in notif.description

    @pytest.mark.anyio
    async def test_notification_failure_does_not_break_integration(
        self, client: AsyncClient, db_session: AsyncSession,
    ):
        user = await _create_user(db_session)
        headers = await _auth_header(user)

        with patch.object(
            NotificationService, "create", side_effect=Exception("DB error")
        ):
            resp = await client.post(
                "/api/v1/onboarding/integrations",
                json={"integrations": "google"},
                headers=headers,
            )

        assert resp.status_code == 200