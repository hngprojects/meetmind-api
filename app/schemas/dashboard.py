"""Pydantic schemas for the dashboard endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import UUID4, BaseModel


class DashboardLiveResponse(BaseModel):
    """Response schema for GET /dashboard/live.

    Returns a count breakdown of all interviews in the workspace grouped
    by status. Powers the summary cards at the top of the dashboard.
    """

    total: int
    in_progress: int
    scheduled: int
    completed: int
    needs_attention: int


class LiveInterviewItem(BaseModel):
    """A single in-progress interview entry for the Live Now panel."""

    interview_id: UUID4
    candidate_name: str
    role_title: str | None
    elapsed_seconds: int | None  # None when scheduled_start is null
    questions_asked: int | None
    questions_total: int | None


class DashboardStatsResponse(BaseModel):
    """Response schema for GET /dashboard/stats.

    Returns the list of currently in-progress interviews.
    Powers the Live Now section of the dashboard.
    """

    live_interviews: list[LiveInterviewItem]


class CompletedInterviewItem(BaseModel):
    interview_id: str
    candidate_name: str
    role: str | None
    score: int | None
    completed_at: str | None
    status: str


class ScheduledInterviewItem(BaseModel):
    interview_id: str
    candidate_name: str
    role: str | None
    start_time: str | None
    end_time: str | None


class DashboardLiveInterviewItem(BaseModel):
    id: str
    interview_id: str
    candidate_name: str
    role_title: str | None
    title: str | None
    scheduled_at: datetime | None
    status: str


class DashboardOverviewResponse(BaseModel):
    has_sessions: bool
    stats: DashboardLiveResponse
