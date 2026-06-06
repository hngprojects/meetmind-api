"""
Tests for Interview Session Management & Context Injection API.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_helpers import (
    build_interview_payload,
    create_candidate_for_user,
    create_interview_via_route,
)

from app.models.user import User
from app.services.auth import AuthService
from app.services.interview import InterviewService

logger = logging.getLogger(__name__)

# ── URL constants ──────────────────────────────────────────────────────────────
INTERVIEWS_URL = "/api/v1/interviews"
CRITERIA_URL = lambda iid: f"{INTERVIEWS_URL}/{iid}/criteria"


def cancel_url(interview_id: str) -> str:
    return f"{INTERVIEWS_URL}/{interview_id}/cancel"


# ── Helpers (Merged) ──────────────────────────────────────────────────────────


async def create_user(db: AsyncSession, email: str | None = None) -> User:
    """Direct DB user creation for testing speed."""
    user = User(email=email or f"{uuid.uuid4().hex[:8]}@example.com", is_verified=True)
    db.add(user)
    await db.flush()
    return user


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def create_interview(
    client: AsyncClient, db_session: AsyncSession, token: str
) -> dict[str, Any]:
    """Helper using reconciled route logic."""
    response = await create_interview_via_route(
        client=client,
        db_session=db_session,
        token=token,
    )
    return response.json()["data"]


VALID_INTERVIEW_PAYLOAD = {
    "role_title": "Senior Backend Engineer",
    "job_description": "Build and maintain distributed APIs...",
    "scoring_rubric": "Code Quality, Architecture, Communication",
    "skills_to_assess": ["Communication", "API Design", "Problem Solving"],
    "platform": "google_meet",
    "ai_tone": "professional",
    "scheduled_start": "2026-06-01T17:30:00Z",
    "scheduled_end": "2026-06-01T18:30:00Z",
}

# ── Tests (Reconciled) ─────────────────────────────────────────────────────────


class TestCreateInterview:
    @pytest.mark.anyio
    async def test_creates_interview_and_returns_201(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # Auth from dev
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)

        # Logic from HEAD (Atomic creation)
        candidate_kwargs = {
            "full_name": "John Doe",
            "email": "john.doe@example.com",
        }

        response = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            candidate_kwargs=candidate_kwargs,
            interview_overrides=VALID_INTERVIEW_PAYLOAD,
        )

        body = response.json()
        assert response.status_code == 201
        data = body["data"]
        assert data["status"] == "scheduled"
        assert data["candidate_name"] == "John Doe"

@pytest.mark.anyio
async def test_generate_interview_plan_fallback_matches_design_role():
    from app.services.interview import _fallback_interview_plan

    plan = _fallback_interview_plan(
        role_title="Product Designer",
        skills_to_assess=["UX Research", "Visual Design"],
    )

    assert "Product Designer" in plan.intro
    assert "Welcome to the interview" in plan.intro

    question_text = " ".join(q.text.lower() for q in plan.questions)
    assert "design" in question_text
    assert "backend" not in question_text
    assert "database" not in question_text
    assert len(plan.questions) == 5
    assert [r.name for r in plan.rubric] == ["UX Research", "Visual Design"]

class TestGetInterview:
    @pytest.mark.anyio
    async def test_retrieves_interview_by_id(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)

        # Create using the reconciled helper
        create_res = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides=VALID_INTERVIEW_PAYLOAD,
        )
        interview_id = create_res.json()["data"]["id"]

        get = await client.get(
            f"{INTERVIEWS_URL}/{interview_id}",
            headers=auth_headers(token),
        )
        body = get.json()
        assert get.status_code == 200

        data = body["data"]
        assert data["status"] == "scheduled"
        # Check that AI shaping was applied (JSON rubric)
        assert "weight" in data["summary"]["scoring_rubric"]


class TestUpdateCriteria:
    @pytest.mark.anyio
    async def test_update_criteria_on_draft(
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
        iid = create.json()["data"]["id"]

        response = await client.put(
            CRITERIA_URL(iid),
            json={"criteria": ["Leadership", "Teamwork"]},
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        assert response.json()["data"]["criteria"] == ["Leadership", "Teamwork"]


class TestCancelInterview:
    @pytest.mark.anyio
    async def test_cancel_draft_interview_returns_200(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)

        # iid setup
        create_res = await create_interview_via_route(client, db_session, token)
        iid = create_res.json()["data"]["id"]

        response = await client.patch(cancel_url(iid), headers=auth_headers(token))
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "cancelled"


class TestListInterviewsFiltered:
    @pytest.mark.anyio
    async def test_filter_by_status_returns_matching_interviews(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)

        await create_interview_via_route(
            client, db_session, token, interview_overrides=VALID_INTERVIEW_PAYLOAD
        )

        response = await client.get(
            INTERVIEWS_URL,
            params={"status": "scheduled"},
            headers=auth_headers(token),
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert all(i["status"] == "scheduled" for i in data)


class TestCreateInterviewDuration:
    @pytest.mark.anyio
    async def test_create_interview_derives_duration_from_schedule(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        from app.models.interview import Interview, InterviewSession

        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)

        response = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides={
                **VALID_INTERVIEW_PAYLOAD,
                "scheduled_start": "2026-06-01T09:00:00Z",
                "scheduled_end": "2026-06-01T10:30:00Z",
            },
        )

        interview_id = response.json()["data"]["id"]
        interview = await db_session.get(Interview, uuid.UUID(interview_id))
        session = await db_session.get(InterviewSession, interview.session_id)

        assert session.duration_minutes == 90

    @pytest.mark.anyio
    async def test_create_interview_defaults_duration_to_45(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        from app.models.interview import Interview, InterviewSession

        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)

        response = await create_interview_via_route(
            client=client,
            db_session=db_session,
            token=token,
            interview_overrides={
                **VALID_INTERVIEW_PAYLOAD,
                "scheduled_start": None,
                "scheduled_end": None,
            },
        )

        interview_id = response.json()["data"]["id"]
        interview = await db_session.get(Interview, uuid.UUID(interview_id))
        session = await db_session.get(InterviewSession, interview.session_id)

        assert session.duration_minutes == 45


class TestMissingFrontendEndpoints:
    @pytest.mark.anyio
    async def test_scorecard_404_for_unknown_interview(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        response = await client.get(
            f"{INTERVIEWS_URL}/{uuid.uuid4()}/scorecard",
            headers=auth_headers(token),
        )
        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_scorecard_returns_sections(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        create_res = await create_interview_via_route(client, db_session, token)
        interview_id = uuid.UUID(create_res.json()["data"]["id"])

        from app.models.interview import Interview
        interview = await db_session.get(Interview, interview_id)
        workspace_id = interview.workspace_id

        # setup: interview with scorecard, 2 scored criteria
        from app.models.scorecard import (
            InterviewScorecard,
            ScorecardCategory,
            ScorecardQuestion,
            ScorecardScore,
            ScorecardSignal,
        )

        scorecard = InterviewScorecard(interview_id=interview_id)
        db_session.add(scorecard)
        await db_session.flush()

        cat1 = ScorecardCategory(
            name="Communication",
            workspace_id=workspace_id,
            sort_order=0,
        )
        cat2 = ScorecardCategory(
            name="Technical Depth",
            workspace_id=workspace_id,
            sort_order=1,
        )
        db_session.add_all([cat1, cat2])
        await db_session.flush()

        score1 = ScorecardScore(
            scorecard_id=scorecard.id,
            category_id=cat1.id,
            score_pct=80,
            completed=True,
        )
        score2 = ScorecardScore(
            scorecard_id=scorecard.id,
            category_id=cat2.id,
            score_pct=60,
            completed=True,
        )
        db_session.add_all([score1, score2])
        await db_session.flush()

        db_session.add(
            ScorecardQuestion(
                score_id=score1.id,
                content="Tell me about yourself.",
                sort_order=0,
            )
        )
        db_session.add(
            ScorecardSignal(
                score_id=score1.id,
                label="Clear answers",
                sort_order=0,
            )
        )
        await db_session.commit()

        response = await client.get(
            f"{INTERVIEWS_URL}/{interview_id}/scorecard",
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert "sections" in data
        assert len(data["sections"]) == 2
        section = data["sections"][0]
        assert section["title"] == "Communication"
        assert section["score"] == 80
        assert section["score_bar_percent"] == 80
        assert section["questions_asked"] == ["Tell me about yourself."]
        assert section["signals_detected"] == ["Clear answers"]

    @pytest.mark.anyio
    async def test_profile_returns_candidate_and_interview_data(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        create_res = await create_interview_via_route(client, db_session, token)
        interview_id = uuid.UUID(create_res.json()["data"]["id"])

        from app.models.interview import Candidate, Interview
        interview = await db_session.get(Interview, interview_id)
        candidate = await db_session.get(Candidate, interview.candidate_id)

        response = await client.get(
            f"{INTERVIEWS_URL}/{interview_id}/profile",
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert "candidate" in data
        assert "interview" in data
        assert data["candidate"]["name"] == candidate.full_name
        assert data["candidate"]["email"] == candidate.email
        assert data["interview"]["platform"] == interview.platform
        assert data["interview"]["questions_answered"] == (interview.questions_asked or 0)
        assert data["interview"]["questions_total"] == (interview.questions_total or 0)

    @pytest.mark.anyio
    async def test_chat_get_returns_history(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        create_res = await create_interview_via_route(client, db_session, token)
        interview_id = uuid.UUID(create_res.json()["data"]["id"])

        response = await client.get(
            f"{INTERVIEWS_URL}/{interview_id}/chat",
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert "messages" in data
        assert "total_messages" in data

    @pytest.mark.anyio
    async def test_rejoin_returns_reconnecting(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        create_res = await create_interview_via_route(client, db_session, token)
        interview_id = uuid.UUID(create_res.json()["data"]["id"])

        from app.models.interview import Interview
        interview = await db_session.get(Interview, interview_id)
        interview.status = "in_progress"
        await db_session.commit()

        response = await client.post(
            f"{INTERVIEWS_URL}/{interview_id}/session/rejoin",
            headers=auth_headers(token),
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["session_status"] == "reconnecting"
        assert data["success"] is True


class TestDeadSessionsRoute:
    @pytest.mark.anyio
    async def test_sessions_route_is_gone(self, client: AsyncClient):
        response = await client.get("/api/v1/sessions/")
        assert response.status_code == 404  # route not registered

    @pytest.mark.anyio
    async def test_interview_creation_still_creates_session_row(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        from app.models.interview import Interview, InterviewSession
        user = await create_user(db_session)
        token = await AuthService.create_access_token(user)
        response = await create_interview_via_route(client, db_session, token)
        interview_id = response.json()["data"]["id"]
        interview = await db_session.get(Interview, uuid.UUID(interview_id))
        assert interview.session_id is not None
        session = await db_session.get(InterviewSession, interview.session_id)
        assert session is not None
        assert session.questions_json is not None



