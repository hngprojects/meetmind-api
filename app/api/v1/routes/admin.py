"""Admin endpoints for compliance and system management."""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import VerifiedUser
from app.core.responses import success
from app.db.session import get_session
from app.models.audit import DataDeletionAuditLog
from app.schemas.audit import DeletionAuditListResponse, DeletionAuditResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get(
    "/deletion-audits",
    response_model=None,
    status_code=status.HTTP_200_OK,
)
async def list_deletion_audits(
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
    session_id: str | None = Query(default=None),
    audit_status: str | None = Query(default=None, alias="status"),
    triggered_by: str | None = Query(default=None),
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Query deletion audit logs for compliance verification.

    Supports filtering by session_id, status, triggered_by, and date range.
    """
    # Base query
    query = select(DataDeletionAuditLog).order_by(
        DataDeletionAuditLog.deleted_at.desc()
    )
    count_query = select(func.count(DataDeletionAuditLog.id))

    # Apply filters
    if session_id:
        query = query.where(DataDeletionAuditLog.session_id == session_id)
        count_query = count_query.where(
            DataDeletionAuditLog.session_id == session_id
        )

    if audit_status:
        query = query.where(DataDeletionAuditLog.status == audit_status)
        count_query = count_query.where(
            DataDeletionAuditLog.status == audit_status
        )

    if triggered_by:
        query = query.where(DataDeletionAuditLog.triggered_by == triggered_by)
        count_query = count_query.where(
            DataDeletionAuditLog.triggered_by == triggered_by
        )

    if from_date:
        query = query.where(DataDeletionAuditLog.deleted_at >= from_date)
        count_query = count_query.where(
            DataDeletionAuditLog.deleted_at >= from_date
        )

    if to_date:
        query = query.where(DataDeletionAuditLog.deleted_at <= to_date)
        count_query = count_query.where(
            DataDeletionAuditLog.deleted_at <= to_date
        )

    # Execute count
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Execute paginated query
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    rows = result.scalars().all()

    audits = [
        DeletionAuditResponse.model_validate(row).model_dump(mode="json")
        for row in rows
    ]

    data = DeletionAuditListResponse(total=total, audits=audits).model_dump(
        mode="json"
    )
    return success(data, message="Deletion audit logs retrieved")
