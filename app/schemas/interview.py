"""Pydantic schemas for interview session management."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.interview import ParticipationMode

# ── Request schemas ────────────────────────────────────────────────────────────


class CreateInterviewRequest(BaseModel):
    """Payload for creating a new interview session."""

    title: str = Field(..., min_length=1, max_length=200)
    candidate_name: str = Field(..., min_length=1, max_length=120)
    candidate_email: str | None = Field(default=None)
    meeting_link: str = Field(..., min_length=1)
    scheduled_start: datetime
    job_description: str = Field(..., min_length=1)
    scoring_rubric: str = Field(..., min_length=1)
    role_title: str | None = Field(default=None, max_length=120)
    platform: str | None = Field(default=None, max_length=30)
    ai_tone: str | None = Field(default=None, max_length=20)
    participation_mode: ParticipationMode | None = None
    criteria: list[str] = Field(..., min_length=1, max_length=10)

    @field_validator("criteria")
    @classmethod
    def validate_criteria(cls, value: list[str]) -> list[str]:
        clean = [item.strip() for item in value if item and item.strip()]
        if len(clean) < 1 or len(clean) > 10:
            raise ValueError("criteria must contain between 1 and 10 non-empty items")
        return clean


# ── Response schemas ───────────────────────────────────────────────────────────


class InterviewSummaryResponse(BaseModel):
    """Context fields returned with an interview session."""

    job_description: str | None
    scoring_rubric: str | None
    cv_text: str | None
    ai_assessment: str | None
    status: str | None


class InterviewResponse(BaseModel):
    """Full interview session response."""

    id: UUID
    title: str | None
    status: str | None
    role_title: str | None
    platform: str | None
    meeting_link: str | None
    scheduled_start: datetime
    ai_tone: str | None
    participation_mode: ParticipationMode | None
    criteria: list[str] = Field(default_factory=list)
    candidate_name: str
    candidate_email: str | None
    summary: InterviewSummaryResponse | None
    created_at: datetime | None

    model_config = {"from_attributes": True}
