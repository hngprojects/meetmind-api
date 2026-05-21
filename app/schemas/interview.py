"""Pydantic schemas for interview session management."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, field_validator

# ── Shared validators ──────────────────────────────────────────────────────────


def _validate_criteria(v: list[str]) -> list[str]:
    """Strip whitespace, reject blanks, enforce 80-char max per criterion."""
    cleaned: list[str] = []
    for item in v:
        stripped = item.strip()
        if not stripped:
            raise ValueError("Criteria must not be blank")
        if len(stripped) > 80:
            raise ValueError(
                f"Each criterion must be at most 80 characters, got {len(stripped)}"
            )
        cleaned.append(stripped)
    return cleaned


# ── Request schemas ────────────────────────────────────────────────────────────


class CreateInterviewRequest(BaseModel):
    candidate_name: str = Field(..., min_length=1, max_length=120)
    platform: Literal["zoom", "google_meet"] | None = Field(default=None)
    call_link: HttpUrl | None = Field(default=None)
    scheduled_start: datetime | None = Field(default=None)
    scheduled_end: datetime | None = Field(default=None)
    # Kept optional for backward compat
    title: str | None = Field(default=None, max_length=200)
    candidate_email: str | None = Field(default=None)
    job_description: str | None = Field(default=None)
    scoring_rubric: str | None = Field(default=None)
    role_title: str | None = Field(default=None, max_length=120)
    ai_tone: str | None = Field(default=None, max_length=20)
    criteria: list[str] | None = Field(default=None, max_length=10)

    @field_validator("criteria")
    @classmethod
    def validate_criteria(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        return _validate_criteria(v)


class UpdateCriteriaRequest(BaseModel):
    """Payload for updating scorecard criteria on a draft interview."""

    criteria: list[str] = Field(..., min_length=1, max_length=10)

    @field_validator("criteria")
    @classmethod
    def validate_criteria(cls, v: list[str]) -> list[str]:
        return _validate_criteria(v)


class UpdateContextRequest(BaseModel):
    role_title: str | None = Field(default=None, max_length=120)
    job_description: str | None = Field(default=None)
    key_skills: list[str] | None = Field(default=None)
    custom_questions: str | None = Field(default=None)


class UpdateAIConfigRequest(BaseModel):
    participation_mode: Literal["passive", "standard", "proactive"] | None = Field(
        default=None
    )
    platform: Literal["zoom", "google_meet"] | None = Field(default=None)
    call_link: str | None = Field(default=None)
    scheduled_start: datetime | None = Field(default=None)
    scheduled_end: datetime | None = Field(default=None)


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
    summary: InterviewSummaryResponse | None
    criteria: list[str] | None = Field(default_factory=None)
    created_at: datetime | None

    model_config = {"from_attributes": True}


class InterviewListItem(BaseModel):
    id: UUID
    candidate_name: str | None
    role_title: str | None
    platform: str | None
    status: str | None
    scheduled_start: datetime | None
    participation_mode: str | None
    created_at: datetime | None

    model_config = {"from_attributes": True}
