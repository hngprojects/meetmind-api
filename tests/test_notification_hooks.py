import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.interview import (
    Candidate,
    Interview,
    InterviewSession,
    InterviewSummary,
)
from app.models.notification import Notification
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.schemas.assessment import AssessmentOutput
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


async def _create_workspace_user(db: AsyncSession) -> tuple[User, str, uuid.UUID]:
    user = await _create_user(db)
    token = await AuthService.create_access_token(user)
    ws = Workspace(name="Test WS", created_by=user.id)
    db.add(ws)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role="owner"))
    await db.commit()
    return user, token, ws.id


async def _seed_interview(
    db: AsyncSession,
    user_id: uuid.UUID,
    ws_id: uuid.UUID,
    status: str = "scheduled",
) -> Interview:
    candidate = Candidate(workspace_id=ws_id, full_name="John", email="john@test.com")
    db.add(candidate)
    await db.flush()
    start = datetime.now(timezone.utc) + timedelta(hours=24)
    interview = Interview(
        workspace_id=ws_id,
        candidate_id=candidate.id,
        interviewer_id=user_id,
        role_title="Engineer",
        status=status,
        scheduled_start=start,
        scheduled_end=start + timedelta(minutes=30),
    )
    db.add(interview)
    await db.commit()
    return interview


class TestHook1LiveKitResult:
    @pytest.mark.anyio
    async def test_completing_interview_creates_report_notification(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
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
        self,
        client: AsyncClient,
        db_session: AsyncSession,
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
        self,
        client: AsyncClient,
        db_session: AsyncSession,
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
        self,
        client: AsyncClient,
        db_session: AsyncSession,
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
        self,
        client: AsyncClient,
        db_session: AsyncSession,
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
        self,
        client: AsyncClient,
        db_session: AsyncSession,
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


class TestHook4CancelInterview:
    @pytest.mark.anyio
    async def test_cancel_interview_creates_cancel_notification(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        user, token, ws_id = await _create_workspace_user(db_session)
        interview = await _seed_interview(db_session, user.id, ws_id)

        resp = await client.patch(
            f"/api/v1/interviews/{interview.id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

        result = await db_session.execute(
            select(Notification).where(Notification.user_id == user.id)
        )
        notif = result.scalar_one_or_none()
        assert notif is not None
        assert notif.type == "meeting"
        assert notif.title == "Interview Cancelled"
        assert notif.action_url == f"/interviews/{interview.id}"

    @pytest.mark.anyio
    async def test_notification_failure_does_not_break_cancel(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        user, token, ws_id = await _create_workspace_user(db_session)
        interview = await _seed_interview(db_session, user.id, ws_id)

        with patch.object(
            NotificationService, "create", side_effect=Exception("DB error")
        ):
            resp = await client.patch(
                f"/api/v1/interviews/{interview.id}/cancel",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200


class TestHook5CompleteInterview:
    @pytest.mark.anyio
    async def test_complete_interview_creates_notification(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        user, token, ws_id = await _create_workspace_user(db_session)
        interview = await _seed_interview(db_session, user.id, ws_id)

        with (
            patch(
                "app.services.ai_generation_service.AIGenerationService.complete_interview",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.ai_generation_service.AIGenerationService.generate_assessment",
                new=AsyncMock(return_value=None),
            ),
        ):
            resp = await client.post(
                f"/api/v1/interviews/{interview.id}/complete",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200

        result = await db_session.execute(
            select(Notification).where(
                Notification.user_id == user.id,
                Notification.type == "report",
            )
        )
        notif = result.scalar_one_or_none()
        assert notif is not None
        assert notif.type == "report"
        assert notif.title == "Interview Completed"
        assert notif.action_url == f"/interviews/{interview.id}"

    @pytest.mark.anyio
    async def test_notification_failure_does_not_break_complete(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        user, token, ws_id = await _create_workspace_user(db_session)
        interview = await _seed_interview(db_session, user.id, ws_id)

        with (
            patch(
                "app.services.ai_generation_service.AIGenerationService.complete_interview",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.ai_generation_service.AIGenerationService.generate_assessment",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                NotificationService, "create", side_effect=Exception("DB error")
            ),
        ):
            resp = await client.post(
                f"/api/v1/interviews/{interview.id}/complete",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200


class TestHook6SummaryRetry:
    @pytest.mark.anyio
    async def test_summary_retry_creates_notification(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        user, token, ws_id = await _create_workspace_user(db_session)
        interview = await _seed_interview(db_session, user.id, ws_id)
        summary = InterviewSummary(
            interview_id=interview.id,
            status="failed",
            job_description="Test role",
        )
        db_session.add(summary)
        await db_session.commit()

        with patch(
            "app.services.ai_generation_service.AIGenerationService.generate_assessment",
            new=AsyncMock(return_value=None),
        ):
            resp = await client.post(
                f"/api/v1/interviews/{interview.id}/summary/retry",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200

        result = await db_session.execute(
            select(Notification).where(Notification.user_id == user.id)
        )
        notif = result.scalar_one_or_none()
        assert notif is not None
        assert notif.type == "report"
        assert notif.title == "Summary Regeneration Started"
        assert notif.action_url == f"/interviews/{interview.id}"

    @pytest.mark.anyio
    async def test_notification_failure_does_not_break_retry(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        user, token, ws_id = await _create_workspace_user(db_session)
        interview = await _seed_interview(db_session, user.id, ws_id)
        summary = InterviewSummary(
            interview_id=interview.id,
            status="failed",
            job_description="Test role",
        )
        db_session.add(summary)
        await db_session.commit()

        with (
            patch(
                "app.services.ai_generation_service.AIGenerationService.generate_assessment",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                NotificationService, "create", side_effect=Exception("DB error")
            ),
        ):
            resp = await client.post(
                f"/api/v1/interviews/{interview.id}/summary/retry",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200


class TestHook7SummaryGenerate:
    @pytest.mark.anyio
    async def test_summary_generate_creates_notification(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        user, token, ws_id = await _create_workspace_user(db_session)
        interview = await _seed_interview(db_session, user.id, ws_id)

        with patch(
            "app.services.ai_generation_service.AIGenerationService.generate_assessment",
            new=AsyncMock(return_value=None),
        ):
            resp = await client.post(
                f"/api/v1/interviews/{interview.id}/summary/generate",
                json={"job_description": "Senior dev role"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 202

        result = await db_session.execute(
            select(Notification).where(Notification.user_id == user.id)
        )
        notif = result.scalar_one_or_none()
        assert notif is not None
        assert notif.type == "report"
        assert notif.title == "Summary Generation Started"
        assert notif.action_url == f"/interviews/{interview.id}"

    @pytest.mark.anyio
    async def test_notification_failure_does_not_break_generate(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        user, token, ws_id = await _create_workspace_user(db_session)
        interview = await _seed_interview(db_session, user.id, ws_id)

        with (
            patch(
                "app.services.ai_generation_service.AIGenerationService.generate_assessment",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                NotificationService, "create", side_effect=Exception("DB error")
            ),
        ):
            resp = await client.post(
                f"/api/v1/interviews/{interview.id}/summary/generate",
                json={"job_description": "Senior dev role"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 202


class TestHook8CancelAppointment:
    @pytest.mark.anyio
    async def test_cancel_appointment_creates_cancel_notification(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        user, token, ws_id = await _create_workspace_user(db_session)
        interview = await _seed_interview(
            db_session, user.id, ws_id, status="scheduled"
        )

        resp = await client.delete(
            f"/api/v1/calendar/appointments/{interview.id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

        result = await db_session.execute(
            select(Notification).where(Notification.user_id == user.id)
        )
        notif = result.scalar_one_or_none()
        assert notif is not None
        assert notif.type == "meeting"
        assert notif.title == "Interview Cancelled"
        assert notif.action_url == f"/interviews/{interview.id}"

    @pytest.mark.anyio
    async def test_notification_failure_does_not_break_cancel_appointment(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        user, token, ws_id = await _create_workspace_user(db_session)
        interview = await _seed_interview(
            db_session, user.id, ws_id, status="scheduled"
        )

        with patch.object(
            NotificationService, "create", side_effect=Exception("DB error")
        ):
            resp = await client.delete(
                f"/api/v1/calendar/appointments/{interview.id}",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200


class TestHook9RescheduleAppointment:
    @pytest.mark.anyio
    async def test_reschedule_appointment_creates_notification(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        user, token, ws_id = await _create_workspace_user(db_session)
        interview = await _seed_interview(
            db_session, user.id, ws_id, status="scheduled"
        )
        now_utc = datetime.now(timezone.utc)
        new_start = (now_utc + timedelta(hours=48)).isoformat()
        new_end = (now_utc + timedelta(hours=48, minutes=30)).isoformat()

        resp = await client.patch(
            f"/api/v1/calendar/appointments/{interview.id}/reschedule",
            json={"scheduled_start": new_start, "scheduled_end": new_end},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

        result = await db_session.execute(
            select(Notification).where(Notification.user_id == user.id)
        )
        notif = result.scalar_one_or_none()
        assert notif is not None
        assert notif.type == "meeting"
        assert notif.title == "Interview Rescheduled"
        assert notif.action_url == f"/interviews/{interview.id}"

    @pytest.mark.anyio
    async def test_notification_failure_does_not_break_reschedule(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        user, token, ws_id = await _create_workspace_user(db_session)
        interview = await _seed_interview(
            db_session, user.id, ws_id, status="scheduled"
        )
        now_utc = datetime.now(timezone.utc)
        new_start = (now_utc + timedelta(hours=48)).isoformat()
        new_end = (now_utc + timedelta(hours=48, minutes=30)).isoformat()

        with patch.object(
            NotificationService, "create", side_effect=Exception("DB error")
        ):
            resp = await client.patch(
                f"/api/v1/calendar/appointments/{interview.id}/reschedule",
                json={"scheduled_start": new_start, "scheduled_end": new_end},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200


class TestHook10AssessmentSummaryReady:
    @pytest.mark.anyio
    async def test_generate_assessment_notif_failure_does_not_raise(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        user, token, ws_id = await _create_workspace_user(db_session)
        interview = await _seed_interview(db_session, user.id, ws_id)
        summary = InterviewSummary(
            interview_id=interview.id,
            status="pending",
            job_description="Senior engineer role",
        )
        db_session.add(summary)
        await db_session.commit()

        mock_llm = AsyncMock(
            return_value=AssessmentOutput(
                observation="Good",
                highlights=["okay"],
                red_flags=[],
            )
        )

        with (
            patch(
                "app.core.llm.generate_structured_output",
                new=mock_llm,
            ),
            patch.object(
                NotificationService, "create", side_effect=Exception("DB error")
            ),
        ):
            from app.services.ai_generation_service import AIGenerationService

            await AIGenerationService.generate_assessment(
                interview_id=interview.id,
            )
