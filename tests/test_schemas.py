"""Smoke tests: every new response schema validates against real-shaped data."""
import uuid
from datetime import datetime

import pytest

from app.schemas.dashboard import (
    CompletedInterviewItem,
    DashboardLiveInterviewItem,
    ScheduledInterviewItem,
)
from app.schemas.calendar import AvailabilitySlot, CalendarUserItem
from app.schemas.candidate import CandidateListItem
from app.schemas.interview import (
    AIConfigUpdateResponse,
    ContextUpdateResponse,
    CriteriaUpdateResponse,
    InterviewConfirmResponse,
    InterviewProfileResponse,
    InterviewScorecardResponse,
    InterviewSessionStatusResponse,
    InterviewSummaryDetailResponse,
    RejoinSessionResponse,
    ScorecardSection,
    TranscriptStopResponse,
)


def test_completed_interview_item():
    item = CompletedInterviewItem(
        interview_id=str(uuid.uuid4()),
        candidate_name="Jane Doe",
        role="Backend Engineer",
        score=85,
        completed_at="2026-05-30T10:00:00",
    )
    assert item.score == 85


def test_scheduled_interview_item():
    item = ScheduledInterviewItem(
        interview_id=str(uuid.uuid4()),
        candidate_name="John",
        role="Designer",
        start_time="10:00AM",
        end_time="10:30AM",
    )
    assert item.start_time == "10:00AM"


def test_dashboard_live_interview_item():
    item = DashboardLiveInterviewItem(
        id=str(uuid.uuid4()),
        interview_id=str(uuid.uuid4()),
        candidate_name="Ada",
        role_title="SRE",
        title="SRE",
        scheduled_at=None,
        status="live",
    )
    assert item.status == "live"


def test_calendar_user_item():
    item = CalendarUserItem(
        id=str(uuid.uuid4()),
        name="Alice",
        email="alice@example.com",
        role="owner",
        avatar_initials="AL",
        avatar_color="#FF5733",
    )
    assert item.avatar_initials == "AL"


def test_availability_slot():
    slot = AvailabilitySlot(
        start_time="10:00",
        end_time="10:30",
        period_start="AM",
        period_end="AM",
    )
    assert slot.period_start == "AM"


def test_candidate_list_item():
    item = CandidateListItem(
        id=str(uuid.uuid4()),
        name="Bob",
        email="bob@example.com",
        role="Engineer",
        status="completed",
        score=90,
        action="none",
        created_at="2026-01-01T00:00:00",
        updated_at=None,
        avatarUrl="BO",
        notes=None,
    )
    assert item.status == "completed"


def test_interview_summary_detail_response():
    resp = InterviewSummaryDetailResponse(
        interview_id=uuid.uuid4(),
        status="completed",
        observation="Strong candidate",
        highlights=["Good communication"],
        red_flags=[],
        custom_question=None,
        key_skills=["Python", "FastAPI"],
    )
    assert len(resp.highlights) == 1


def test_scorecard_section_and_response():
    section = ScorecardSection(
        title="Technical Depth",
        score=80,
        score_bar_percent=80,
        questions_asked=["Tell me about X"],
        signals_detected=["Strong signal"],
        expanded=True,
    )
    resp = InterviewScorecardResponse(
        interview_id=uuid.uuid4(),
        sections=[section],
    )
    assert resp.sections[0].score == 80


def test_interview_profile_response():
    resp = InterviewProfileResponse.model_validate({
        "candidate": {
            "name": "Jane",
            "email": "jane@example.com",
            "phone": "+1234",
            "resume_url": None,
            "portfolio_url": None,
        },
        "interview": {
            "platform": "zoom",
            "duration": "45min",
            "questions_answered": 3,
            "questions_total": 5,
            "status": "in_progress",
        },
    })
    assert resp.interview.platform == "zoom"


def test_interview_confirm_response():
    resp = InterviewConfirmResponse(
        interview_id=uuid.uuid4(),
        status="scheduled",
        confirmed_at=datetime.now(),
    )
    assert resp.status == "scheduled"


def test_criteria_update_response():
    resp = CriteriaUpdateResponse(criteria=["Python", "FastAPI"])
    assert len(resp.criteria) == 2


def test_context_update_response():
    resp = ContextUpdateResponse(
        interview_id=uuid.uuid4(),
        status="scheduled",
        updated_at=None,
    )
    assert resp.status == "scheduled"


def test_ai_config_update_response():
    resp = AIConfigUpdateResponse(
        interview_id=uuid.uuid4(),
        status="scheduled",
        participation_mode="standard",
        updated_at=None,
    )
    assert resp.participation_mode == "standard"


def test_transcript_stop_response():
    resp = TranscriptStopResponse(
        interview_id=uuid.uuid4(),
        status="completed",
    )
    assert resp.status == "completed"


def test_session_status_response():
    resp = InterviewSessionStatusResponse(
        interview_id=uuid.uuid4(),
        status="in_progress",
        session_phase="live_transcript",
        elapsed=120,
        participants=None,
        platform="zoom",
        connection_status="connected",
    )
    assert resp.elapsed == 120


def test_rejoin_session_response():
    resp = RejoinSessionResponse(
        success=True,
        session_status="reconnecting",
        interview_id=uuid.uuid4(),
        message="Reconnecting to session...",
    )
    assert resp.success is True