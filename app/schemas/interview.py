"""Pydantic schemas for interview session management."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, Field



class ParticipationMode(str, Enum):
    passive = "passive"
    standard = "standard"
    proactive = "proactive"
    

# ── Request schemas ────────────────────────────────────────────────────────────


class CreateInterviewRequest(BaseModel):
    """Payload for creating a new interview session."""

    title: str = Field(..., min_length=1, max_length=200)
    candidate_name: str = Field(..., min_length=1, max_length=120)
    candidate_email: str | None = Field(default=None)
    job_description: str = Field(..., min_length=1)
    scoring_rubric: str = Field(..., min_length=1)
    role_title: str | None = Field(default=None, max_length=120)
    platform: str | None = Field(default=None, max_length=30)
    ai_tone: str | None = Field(default=None, max_length=20)
    participation_mode: ParticipationMode = ParticipationMode.standard


# ── Response schemas ───────────────────────────────────────────────────────────


class InterviewSummaryResponse(BaseModel):
    """Context fields returned with an interview session."""

    job_description: str | None
    scoring_rubric: str | None
    ai_assessment: str | None
    status: str | None


class InterviewResponse(BaseModel):
    """Full interview session response."""

    id: UUID
    title: str | None
    status: str | None
    role_title: str | None
    platform: str | None
    ai_tone: str | None
    candidate_name: str
    candidate_email: str | None
    participation_mode: str | None
    summary: InterviewSummaryResponse | None
    created_at: datetime | None

    model_config = {"from_attributes": True}
