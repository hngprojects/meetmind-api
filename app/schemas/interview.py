"""Pydantic schemas for interview session management."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
    field_validator,
    model_serializer,
    model_validator,
)

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


class InterviewQuestionSchema(BaseModel):
    text: str = Field(description="The actual question to ask the candidate")
    followUpHint: str = Field(
        description="Guidance for the bot on what to listen for or probe further"
    )
    maxFollowUps: int = Field(
        default=2, description="Maximum number of follow-up questions for this topic"
    )


class RubricCriterion(BaseModel):
    name: str = Field(
        description="The name of the skill or attribute (e.g., Python Proficiency)"
    )
    description: str = Field(description="What a good answer looks like")
    weight: int = Field(default=1, description="Importance from 1 to 5")


class InterviewPlanOutput(BaseModel):
    intro: str = Field(description="A warm, professional opening greeting")
    questions: list[InterviewQuestionSchema]
    rubric: list[RubricCriterion]
    closing: str = Field(description="A friendly closing statement with next steps")


class CandidateProfile(BaseModel):
    candidate_id: UUID = Field(..., description="Unique identifier for the candidate")
    full_name: str = Field(..., min_length=1, max_length=120)
    email: str = Field(..., description="Candidate email address")
    phone: str = Field(..., description="Candidate phone number with country code")
    current_role: str | None = Field(default=None, max_length=120)
    years_of_experience: int = Field(default=0, ge=0)
    skills: list[str] = Field(default_factory=list)
    location: str | None = Field(default=None, max_length=100)
    portfolio_url: str | None = Field(default=None)

    @model_serializer(mode="wrap")
    def serialize_for_db(self, handler) -> dict[str, Any]:
        """
        Automatically prepares Pydantic types for flat SQLAlchemy columns
        when calling model_dump()
        """
        data = handler(self)

        if isinstance(data.get("skills"), list):
            data["skills"] = ", ".join(data["skills"]) if data["skills"] else None

        # 3. Coerce HttpUrl object into a plain string so asyncpg doesn't reject it
        if data.get("portfolio_url"):
            data["portfolio_url"] = str(data["portfolio_url"])

        return data


class CreateInterviewRequest(BaseModel):
    candidate: CandidateProfile = Field(
        ..., description="Complete profile details of the candidate"
    )

    platform: Literal["zoom", "google_meet", "livekit"] | None = Field(default=None)
    call_link: HttpUrl | None = Field(default=None)
    scheduled_start: datetime | None = Field(default=None)
    scheduled_end: datetime | None = Field(default=None)

    role_title: str = Field(..., min_length=1, max_length=200)
    custom_question: str | None = Field(default=None, max_length=200)
    job_description: str | None = Field(default=None)
    ai_tone: str | None = Field(default=None, max_length=20)
    participation_mode: ParticipationMode = Field(default=ParticipationMode.standard)
    skills_to_assess: list[str] | None = Field(default=None, max_length=10)

    @field_validator("skills_to_assess")
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
    call_link: HttpUrl | None = Field(default=None)
    scheduled_start: datetime | None = Field(default=None)
    scheduled_end: datetime | None = Field(default=None)


# ── Response schemas ───────────────────────────────────────────────────────────


class InterviewSummaryResponse(BaseModel):
    """Context fields returned with an interview session."""

    job_description: str | None
    scoring_rubric: str | None
    ai_assessment: str | None
    status: str | None
    key_skills: str | None = None

    model_config = {"from_attributes": True}


class InterviewResponse(BaseModel):
    id: UUID
    title: str | None
    status: str | None
    role_title: str | None
    platform: str | None
    ai_tone: str | None
    candidate_name: str
    candidate_email: str | None
    phone: str | None = None
    resume_url: str | None = None
    portfolio_url: str | None = None
    scheduled_date: str | None = None
    scheduled_time: str | None = None
    duration: int | None = None
    question_progress: str | None = None
    questions_asked: int | None = None
    questions_total: int | None = None
    rating: int | None = None
    session_phase: str | None = None
    list_status: str | None = None
    elapsed: int | None = None
    participants: int | None = None
    participation_mode: ParticipationMode | None
    summary: InterviewSummaryResponse | None
    custom_question: str | None = None
    key_skills: list[str] = []
    observation: str | None = None
    highlights: list[str] = []
    red_flags: list[str] = []
    criteria: list[str] = []
    created_at: datetime | None

    @model_validator(mode="after")
    def sync_criteria_from_summary(self) -> "InterviewResponse":
        """
        Post-initialization: Sync the flat string from the DB summary
        into the list fields expected by the UI and tests.
        """
        if self.summary and self.summary.key_skills:
            # Split "Skill A, Skill B" -> ["Skill A", "Skill B"]
            skills_list = [
                s.strip() for s in self.summary.key_skills.split(",") if s.strip()
            ]
            self.criteria = skills_list
            self.key_skills = skills_list
        return self

    model_config = {"from_attributes": True}


class InterviewListItem(BaseModel):
    id: UUID
    interview_id: UUID | None = None
    candidate_name: str | None
    role_title: str | None
    title: str | None = None
    platform: str | None
    status: str | None
    scheduled_start: datetime | None
    scheduled_time: str | None = None
    participation_mode: str | None
    created_at: datetime | None

    model_config = {"from_attributes": True}


class InterviewSummaryDetailResponse(BaseModel):
    interview_id: UUID
    status: str | None
    summary: str | None = None
    observation: str | None
    highlights: list[str]
    red_flags: list[str]
    confidence: float | None = None
    custom_question: str | None
    key_skills: list[str]


class InterviewSessionStatusResponse(BaseModel):
    interview_id: UUID
    status: str | None
    session_phase: str | None
    elapsed: int | None
    participants: int | None
    platform: str | None
    connection_status: str


class ScorecardEvidence(BaseModel):
    question_turn_id: int | str
    response_turn_id: int | str
    reason: str


class ScorecardSubRubric(BaseModel):
    id: str
    title: str
    score: int
    confidence: int = 0
    score_bar_percent: int
    strengths: list[str] = []
    weaknesses: list[str] = []
    justification: str | None = None
    evidence: list[ScorecardEvidence] = []
    expanded: bool = False


class ScorecardSection(BaseModel):
    id: str
    title: str
    score: int
    confidence: int = 0
    score_bar_percent: int
    questions_asked: list[str]
    signals_detected: list[str]
    strengths: list[str] = []
    weaknesses: list[str] = []
    justification: str | None = None
    evidence: list[ScorecardEvidence] = []
    expanded: bool
    sub_rubrics: list[ScorecardSubRubric] = []


class InterviewScorecardResponse(BaseModel):
    interview_id: UUID
    total_score: int = 0
    overall_confidence: int = 0
    sections: list[ScorecardSection]


class CandidateProfileDetail(BaseModel):
    name: str
    email: str | None
    phone: str | None
    resume_url: str | None
    portfolio_url: str | None


class InterviewProfileDetail(BaseModel):
    platform: str
    duration: str
    questions_answered: int
    questions_total: int
    status: str


class InterviewProfileResponse(BaseModel):
    candidate: CandidateProfileDetail
    interview: InterviewProfileDetail


class InterviewConfirmResponse(BaseModel):
    interview_id: UUID
    status: str
    confirmed_at: datetime | None


class TranscriptStopResponse(BaseModel):
    interview_id: UUID
    status: str


class CriteriaUpdateResponse(BaseModel):
    criteria: list[str]


class ContextUpdateResponse(BaseModel):
    interview_id: UUID
    status: str
    updated_at: datetime | None


class AIConfigUpdateResponse(BaseModel):
    interview_id: UUID
    status: str
    participation_mode: str | None
    updated_at: datetime | None


class RejoinSessionResponse(BaseModel):
    success: bool
    session_status: str
    interview_id: UUID
    message: str
