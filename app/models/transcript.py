import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class Transcript(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "transcripts"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id"), nullable=False
    )
    raw_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(20), default="processing")


class TranscriptSegment(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "transcript_segments"
    __table_args__ = (
        Index("ix_transcript_segments_transcript_seq", "transcript_id", "sequence_no"),
    )

    transcript_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transcripts.id"), nullable=False
    )
    participant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meeting_participants.id")
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp_sec: Mapped[int | None] = mapped_column(Integer)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)


class MeetingSummary(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "meeting_summaries"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id"), nullable=False
    )
    body: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(20), default="generating")
    generated_at: Mapped[datetime | None] = mapped_column(DateTime)


class SummaryKeypoint(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "summary_keypoints"

    summary_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meeting_summaries.id"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp_sec: Mapped[int | None] = mapped_column(Integer)
    sequence_no: Mapped[int | None] = mapped_column(Integer)


class SummaryDecision(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "summary_decisions"

    summary_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meeting_summaries.id"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp_sec: Mapped[int | None] = mapped_column(Integer)
    sequence_no: Mapped[int | None] = mapped_column(Integer)


class ActionItem(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "action_items"

    summary_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meeting_summaries.id"), nullable=False
    )
    assignee_name: Mapped[str | None] = mapped_column(String(120))
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp_sec: Mapped[int | None] = mapped_column(Integer)
    completed: Mapped[bool | None] = mapped_column(Boolean, default=False)
    sequence_no: Mapped[int | None] = mapped_column(Integer)
