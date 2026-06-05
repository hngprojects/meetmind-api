"""Data deletion audit log model for privacy compliance."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey


class DataDeletionAuditLog(Base, UUIDPrimaryKey, TimestampMixin):
    """Records each data-deletion action for compliance auditing.

    One row is written per data category deleted (e.g. transcript turns,
    local files, session context fields).  This gives granular
    accountability while remaining easy to query via the admin endpoint.
    """

    __tablename__ = "data_deletion_audit_logs"
    __table_args__ = (
        Index("ix_deletion_audit_session_id", "session_id"),
        Index("ix_deletion_audit_status", "status"),
    )

    session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    interview_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    deletion_type: Mapped[str] = mapped_column(String(50), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # success | failed
    triggered_by: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # timer | sweep
    deleted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
