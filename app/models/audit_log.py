import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    interview_id = Column(
        UUID(as_uuid=True), ForeignKey("interviews.id"), nullable=False
    )
    action = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
