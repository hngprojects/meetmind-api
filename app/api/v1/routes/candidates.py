# app/api/v1/routes/candidates.py

import math
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.core.responses import success, APIError
from app.models.interview import Candidate
from app.schemas.candidate import CandidateSearchResult, CandidateProfile
from app.services.candidate import CandidateService
from app.services.interview import _get_workspace

router = APIRouter()


@router.get("/search")
async def search_candidates(
    db: DBSession,
    current_user: CurrentUser,
    q: str = Query(..., min_length=1, description="Search term"),
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Results per page"),
):
    """
    Search candidates by name or email.

    GET /api/v1/candidates/search?q=john&page=1&page_size=20

    WHY Query(...) with min_length=1?
    The ... means the parameter is required — FastAPI returns 422 automatically
    if it is missing. min_length=1 prevents empty string searches like ?q=
    which would match everything and is not a real search.

    WHY ge=1 on page?
    ge means "greater than or equal to". Page 0 makes no sense — pages start
    at 1. FastAPI validates this automatically and returns 422 if violated.

    WHY le=100 on page_size?
    We cap the maximum page size at 100. Without this cap, a malicious or
    careless client could send page_size=999999 and load the entire database
    into memory in one query. This is a denial-of-service protection.
    """

    # Get the user's workspace to scope the query
    # Every candidate belongs to a workspace — we never leak cross-workspace data
    workspace_id = await _get_workspace(db, current_user)

    if not workspace_id:
        raise APIError(
            "Candidate not found",
            status_code=status.HTTP_404_NOT_FOUND,
            code="candidate_not_found",
        )

    candidates, total = await CandidateService.search(
        db=db,
        q=q,
        workspace_id=workspace_id,
        page=page,
        page_size=page_size,
    )

    # Serialize SQLAlchemy ORM objects into Pydantic schemas
    # model_validate reads from ORM attributes because from_attributes=True
    # is set in CandidateSearchResult's model_config
    results = [CandidateSearchResult.model_validate(c) for c in candidates]

    total_pages = math.ceil(total / page_size) if total > 0 else 0

    return success(
        data=[r.model_dump(mode="json") for r in results],
        message=f"Found {total} candidate(s) matching '{q}'",
        meta={
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages,
            }
        },
    )


@router.get("/export")
async def export_candidates(
    db: DBSession,
    current_user: CurrentUser,
    q: str | None = Query(default=None, description="Optional search filter"),
):

    workspace_id = await _get_workspace(db, current_user)

    if not workspace_id:
        raise APIError(
            "Candidate not found",
            status_code=status.HTTP_404_NOT_FOUND,
            code="candidate_not_found",
        )

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    filename = f"candidates_{timestamp}.csv"

    # The generator is created here but NOT awaited yet
    # StreamingResponse will consume it lazily as it streams the response
    csv_generator = CandidateService.export_csv_generator(
        db=db,
        workspace_id=workspace_id,
        q=q,
    )

    return StreamingResponse(
        content=csv_generator,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
        },
    )


@router.get("/{candidate_id}")
async def get_candidate(
    candidate_id: UUID,
    db: DBSession,
    current_user: CurrentUser,
):
    """
    Get a single candidate's profile.

    GET /api/v1/candidates/{candidate_id}

    Returns all fields from the Candidate model — no nested interviews or
    computed stats. Use the dedicated /interviews endpoints for that data.

    WHY UUID for candidate_id?
    FastAPI validates UUID path parameters automatically and returns 422 for
    non-UUID values before the handler runs — garbage IDs never hit the DB.

    WHY db.scalar()?
    Unwraps the first column of the first row and returns None if no results
    without raising. Idential to scalar_one_or_none() for the single-PK case.

    WHY workspace scoping?
    Every candidate belongs to a workspace. _get_workspace resolves the
    current user's workspace via WorkspaceMember. Cross-workspace candidates
    are invisible — prevents data leakage.

    WHY CandidateProfile.model_validate(candidate)?
    model_validate reads ORM attributes because from_attributes=True is set
    in the schema. This avoids manually mapping every field.
    """

    workspace_id = await _get_workspace(db, current_user)

    if not workspace_id:
        raise APIError(
            "Candidate not found",
            status_code=status.HTTP_404_NOT_FOUND,
            code="candidate_not_found",
        )

    candidate = await db.scalar(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.workspace_id == workspace_id,
        )
    )

    if not candidate:
        raise APIError(
            "Candidate not found",
            status_code=status.HTTP_404_NOT_FOUND,
            code="candidate_not_found",
        )

    return success(
        CandidateProfile.model_validate(candidate),
        message="Candidate profile retrieved",
    )