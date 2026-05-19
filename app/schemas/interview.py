"""Pydantic schemas for interview session management."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, Field, field_validator


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
    criteria: list[str] = Field(..., min_length=1, max_length=10)

    @field_validator("criteria")
    @classmethod
    def validate_criteria(cls, v: list[str]) -> list[str]:
        return _validate_criteria(v)


class UpdateCriteriaRequest(BaseModel):
    """Payload for updating scorecard criteria on a draft interview."""

    criteria: list[str] = Field(..., min_length=1, max_length=10)

    @field_validator("criteria")
    @classmethod
    def validate_criteria(cls, v: list[str]) -> list[str]:
        return _validate_criteria(v)


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
    participation_mode: ParticipationMode | None
    summary: InterviewSummaryResponse | None
    criteria: list[str] = Field(default_factory=list)
    created_at: datetime | None

    model_config = {"from_attributes": True}