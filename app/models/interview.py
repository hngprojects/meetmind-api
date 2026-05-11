import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class Candidate(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "candidates"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(30))
    avatar_initials: Mapped[str | None] = mapped_column(String(3))
    resume_url: Mapped[str | None] = mapped_column(Text)
    portfolio_url: Mapped[str | None] = mapped_column(Text)


class Interview(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "interviews"
    __table_args__ = (
        Index("ix_interviews_workspace_candidate", "workspace_id", "candidate_id"),
        Index("ix_interviews_interviewer_start", "interviewer_id", "scheduled_start"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidates.id"), nullable=False
    )
    interviewer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id")
    )
    role_title: Mapped[str | None] = mapped_column(String(120))
    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime)
    scheduled_end: Mapped[datetime | None] = mapped_column(DateTime)
    duration_min: Mapped[int | None] = mapped_column(Integer)
    platform: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str | None] = mapped_column(String(20), default="draft")
    ai_tone: Mapped[str | None] = mapped_column(String(20))
    questions_asked: Mapped[int | None] = mapped_column(Integer)
    questions_total: Mapped[int | None] = mapped_column(Integer)
    rating: Mapped[int | None] = mapped_column(Integer)


class InterviewTranscript(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "interview_transcripts"

    interview_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interviews.id"), nullable=False
    )
    status: Mapped[str | None] = mapped_column(String(20), default="processing")


class InterviewTranscriptTurn(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "interview_transcript_turns"
    __table_args__ = (
        Index("ix_interview_turns_transcript_seq", "transcript_id", "sequence_no"),
    )

    transcript_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interview_transcripts.id"), nullable=False
    )
    speaker: Mapped[str] = mapped_column(String(20), nullable=False)
    speaker_name: Mapped[str | None] = mapped_column(String(120))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp_sec: Mapped[int | None] = mapped_column(Integer)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    is_ai_question: Mapped[bool | None] = mapped_column(Boolean, default=False)


class InterviewSummary(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "interview_summaries"

    interview_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interviews.id"), nullable=False
    )
    # Context injection fields — added for interview session management (Stage 5)
    job_description: Mapped[str | None] = mapped_column(Text)
    scoring_rubric: Mapped[str | None] = mapped_column(Text)
    # Pre-existing fields
    custom_question: Mapped[str | None] = mapped_column(Text)
    ai_assessment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(20), default="generating")
    generated_at: Mapped[datetime | None] = mapped_column(DateTime)


class InterviewSkillToAssess(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "interview_skills_to_assess"

    summary_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interview_summaries.id"), nullable=False
    )
    skill: Mapped[str] = mapped_column(String(80), nullable=False)
    sort_order: Mapped[int | None] = mapped_column(Integer)


class InterviewHighlight(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "interview_highlights"

    summary_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interview_summaries.id"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int | None] = mapped_column(Integer)


class InterviewRedFlag(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "interview_red_flags"

    summary_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interview_summaries.id"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int | None] = mapped_column(Integer)
