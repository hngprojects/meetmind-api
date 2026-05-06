import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class AskMindSession(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "ask_mind_sessions"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )


class AskMindMessage(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "ask_mind_messages"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ask_mind_sessions.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(15), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)


class AskMindSuggestedPrompt(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "ask_mind_suggested_prompts"

    meeting_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id")
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int | None] = mapped_column(Integer)
