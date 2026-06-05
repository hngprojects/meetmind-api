import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class ScorecardCategory(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "scorecard_categories"

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id")
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    sort_order: Mapped[int | None] = mapped_column(Integer)


class InterviewScorecard(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "interview_scorecards"

    interview_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interviews.id"), nullable=False
    )


class ScorecardScore(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "scorecard_scores"
    __table_args__ = (UniqueConstraint("scorecard_id", "category_id"),)

    scorecard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interview_scorecards.id"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scorecard_categories.id"), nullable=False
    )
    score_pct: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[int | None] = mapped_column(Integer, default=0)
    justification: Mapped[str | None] = mapped_column(Text)
    completed: Mapped[bool | None] = mapped_column(Boolean, default=False)


class ScorecardQuestion(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "scorecard_questions"

    score_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scorecard_scores.id"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int | None] = mapped_column(Integer)


class ScorecardSignal(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "scorecard_signals"

    score_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scorecard_scores.id"), nullable=False
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int | None] = mapped_column(Integer)


class ScorecardSubRubric(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "scorecard_sub_rubrics"

    score_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scorecard_scores.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    score_pct: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[int | None] = mapped_column(Integer, default=0)
    justification: Mapped[str | None] = mapped_column(Text)
    strengths: Mapped[list[str] | None] = mapped_column(JSON, default=list)
    weaknesses: Mapped[list[str] | None] = mapped_column(JSON, default=list)
    sort_order: Mapped[int | None] = mapped_column(Integer)


class ScorecardEvidence(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "scorecard_evidence"

    score_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scorecard_scores.id"), nullable=True
    )
    sub_rubric_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scorecard_sub_rubrics.id"), nullable=True
    )
    question_turn_id: Mapped[str] = mapped_column(Text, nullable=False)
    response_turn_id: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
