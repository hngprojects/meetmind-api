"""Pydantic response schemas for the deletion audit admin endpoint."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class DeletionAuditResponse(BaseModel):
    """Single deletion audit log entry."""

    id: uuid.UUID
    session_id: str
    interview_id: uuid.UUID | None = None
    deletion_type: str
    item_count: int
    detail: str | None = None
    status: str
    triggered_by: str
    deleted_at: datetime

    model_config = {"from_attributes": True}


class DeletionAuditListResponse(BaseModel):
    """Paginated list of deletion audit entries."""

    total: int
    audits: list[DeletionAuditResponse]
