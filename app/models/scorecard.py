import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKey


class ScorecardCategory(Base, UUIDPrimaryKey):
    __tablename__ = "scorecard_categories"

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id")
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    sort_order: Mapped[int | None] = mapped_column(Integer)


class InterviewScorecard(Base, UUIDPrimaryKey):
    __tablename__ = "interview_scorecards"

    interview_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interviews.id"), nullable=False
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class ScorecardScore(Base, UUIDPrimaryKey):
    __tablename__ = "scorecard_scores"
    __table_args__ = (
        UniqueConstraint("scorecard_id", "category_id"),
    )

    scorecard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interview_scorecards.id"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scorecard_categories.id"), nullable=False
    )
    score_pct: Mapped[int | None] = mapped_column(Integer)
    completed: Mapped[bool | None] = mapped_column(Boolean, default=False)


class ScorecardQuestion(Base, UUIDPrimaryKey):
    __tablename__ = "scorecard_questions"

    score_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scorecard_scores.id"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int | None] = mapped_column(Integer)


class ScorecardSignal(Base, UUIDPrimaryKey):
    __tablename__ = "scorecard_signals"

    score_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scorecard_scores.id"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    sort_order: Mapped[int | None] = mapped_column(Integer)
