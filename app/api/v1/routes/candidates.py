# app/api/v1/routes/candidates.py
import math
from datetime import datetime, timezone
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.core.responses import APIError, success
from app.models.document import CandidateDocument, DocumentStatus
from app.models.interview import Candidate, Interview
from app.schemas.candidate import CandidateSearchResult
from app.services.candidate import CandidateService
from app.services.document_service import DocumentService
from app.services.interview import _get_workspace

router = APIRouter()

MAX_FILE_SIZE = 10 * 1024 * 1024


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
            "No workspace found",
            status_code=status.HTTP_404_NOT_FOUND,
            code="no_workspace_found",
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
            "No workspace found",
            status_code=status.HTTP_404_NOT_FOUND,
            code="no_workspace_found",
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


@router.get("")
async def list_candidates(
    db: DBSession,
    current_user: CurrentUser,
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    sort_by: str | None = Query(default="date", alias="sort_by"),
    sort_direction: str | None = Query(default="desc", alias="sort_direction"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="page_size"),
):
    workspace_id = await _get_workspace(db, current_user)
    if not workspace_id:
        return success(
            data=[],
            meta={
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total": 0,
                    "total_pages": 0,
                }
            },
        )

    candidates, total = await CandidateService.list_candidates(
        db=db,
        workspace_id=workspace_id,
        q=q,
        status=status,
        sort_by=sort_by,
        sort_direction=sort_direction,
        page=page,
        page_size=page_size,
    )

    import math

    total_pages = math.ceil(total / page_size) if total > 0 else 0

    return success(
        data=candidates,
        meta={
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages,
            }
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
    """

    workspace_id = await _get_workspace(db, current_user)

    if not workspace_id:
        raise APIError(
            "No workspace found",
            status_code=status.HTTP_404_NOT_FOUND,
            code="no_workspace_found",
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

    latest_interview_result = await db.execute(
        select(Interview)
        .where(Interview.candidate_id == candidate_id)
        .order_by(Interview.created_at.desc())
        .limit(1)
    )
    latest_interview = latest_interview_result.scalar_one_or_none()

    interview_status_map = {
        "in_progress": "ongoing",
        "completed": "completed",
        "needs_attention": "needs_review",
    }

    return success(
        {
            "id": str(candidate.id),
            "name": candidate.full_name,
            "email": candidate.email,
            "role": latest_interview.role_title if latest_interview else None,
            "status": interview_status_map.get(latest_interview.status, "ongoing")
            if latest_interview
            else "ongoing",
            "score": latest_interview.rating if latest_interview else None,
            "action": "none",
            "created_at": candidate.created_at.isoformat()
            if candidate.created_at
            else None,
            "updated_at": candidate.updated_at.isoformat()
            if candidate.updated_at
            else None,
            "avatarUrl": candidate.avatar_initials,
            "notes": None,
        },
        message="Candidate profile retrieved",
    )


@router.post("/{candidate_id}/documents/upload")
async def upload_candidate_document(
    current_user: CurrentUser,
    candidate_id: UUID,
    db: DBSession,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="The document file (PDF, DOCX, TXT)"),
):
    content = await file.read()

    if len(content) > MAX_FILE_SIZE:
        raise APIError(
            "File too large",
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            code="file_too_large",
        )

    document = CandidateDocument(
        candidate_id=candidate_id,
        filename=file.filename,
        status=DocumentStatus.PENDING.value,
    )

    try:
        db.add(document)
        await db.commit()
        await db.refresh(document)

    except Exception:
        await db.rollback()
        raise APIError(
            "Database insertion failed",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="database_insertion_failed",
        )

    background_tasks.add_task(
        DocumentService.process_document,
        document_id=document.id,
        filename=file.filename,
        content=content,
    )

    return success(
        message="Document uploaded successfully. Processing started.",
    )
