import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class Meeting(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "meetings"

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id")
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    language: Mapped[str | None] = mapped_column(String(10), default="en")
    locale: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str | None] = mapped_column(String(20), default="pending")
    duration_sec: Mapped[int | None] = mapped_column(Integer)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)


class MeetingParticipant(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "meeting_participants"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    display_name: Mapped[str | None] = mapped_column(String(120))
    speaker_label: Mapped[str | None] = mapped_column(String(5))
    joined_at: Mapped[datetime | None] = mapped_column(DateTime)


class MeetingComment(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "meeting_comments"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
