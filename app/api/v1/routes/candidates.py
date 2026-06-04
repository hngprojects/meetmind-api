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

from app.api.deps import DBSession, VerifiedUser
from app.core.responses import APIError, APIResponse, success
from app.core.utils import INTERVIEW_STATUS_MAP, get_user_workspace
from app.models.document import CandidateDocument, DocumentStatus
from app.models.interview import Candidate, Interview
from app.models.workspace import WorkspaceMember
from app.schemas.candidate import CandidateListItem, CandidateSearchResult
from app.services.candidate import CandidateService
from app.services.document_service import DocumentService

router = APIRouter()

MAX_FILE_SIZE = 10 * 1024 * 1024


@router.get(
    "/search",
    response_model=APIResponse[list[CandidateSearchResult]],
)
async def search_candidates(
    db: DBSession,
    current_user: VerifiedUser,
    q: str = Query(..., min_length=1, description="Search term"),
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Results per page"),
):
    """
    Search candidates by name or email.

    GET /api/v1/candidates/search?q=john&page=1&page_size=20
    """
    # Get the user's workspace to scope the query
    # Every candidate belongs to a workspace — we never leak cross-workspace data
    workspace_id = await get_user_workspace(db, current_user.id)

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
    current_user: VerifiedUser,
    q: str | None = Query(
        default=None, min_length=1, description="Optional search filter"
    ),
):

    workspace_id = await get_user_workspace(db, current_user.id)

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


@router.get(
    "",
    response_model=APIResponse[list[CandidateListItem]],
)
async def list_candidates(
    db: DBSession,
    current_user: VerifiedUser,
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    sort_by: str | None = Query(default="date", alias="sort_by"),
    sort_direction: str | None = Query(default="desc", alias="sort_direction"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="page_size"),
):
    workspace_id = await get_user_workspace(db, current_user.id)
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


@router.get(
    "/{candidate_id}",
    response_model=APIResponse[CandidateListItem],
)
async def get_candidate(
    candidate_id: UUID,
    db: DBSession,
    current_user: VerifiedUser,
):
    """
    Get a single candidate's profile.

    GET /api/v1/candidates/{candidate_id}

    Returns all fields from the Candidate model — no nested interviews or
    computed stats. Use the dedicated /interviews endpoints for that data.
    """
    workspace_id = await get_user_workspace(db, current_user.id)

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

    return success(
        CandidateListItem(
            id=str(candidate.id),
            name=candidate.full_name,
            email=candidate.email,
            role=latest_interview.role_title
            if latest_interview
            else candidate.current_role,
            status=INTERVIEW_STATUS_MAP.get(latest_interview.status, "ongoing")
            if latest_interview
            else "ongoing",
            score=latest_interview.rating if latest_interview else None,
            action="none",
            created_at=candidate.created_at.isoformat()
            if candidate.created_at
            else None,
            updated_at=candidate.updated_at.isoformat()
            if candidate.updated_at
            else None,
            avatarUrl=candidate.avatar_initials,
            notes=None,
        ),
        message="Candidate profile retrieved",
    )


@router.post("/upload-resume")
async def upload_candidate_document(
    current_user: VerifiedUser,
    db: DBSession,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="The document file (PDF, DOCX, TXT)"),
):
    workspace_query = select(WorkspaceMember.workspace_id).where(
        WorkspaceMember.user_id == current_user.id
    )
    workspace_res = await db.execute(workspace_query)
    workspace_id = workspace_res.scalar_one_or_none()

    if not workspace_id:
        raise APIError(
            "User is not a member of any workspace",
            status_code=status.HTTP_403_FORBIDDEN,
            code="no_workspace_found",
        )
    content = await file.read()

    if len(content) > MAX_FILE_SIZE:
        raise APIError(
            "File too large",
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            code="file_too_large",
        )

    try:
        raw_text = await DocumentService.extract_text(file.filename, content)
    except ValueError as e:
        raise APIError(
            str(e), status_code=status.HTTP_400_BAD_REQUEST, code="invalid_file"
        )

    extracted_data = await DocumentService.extract_candidate_info(raw_text)

    candidate = Candidate(
        workspace_id=workspace_id,
        full_name=extracted_data.full_name,
        email=extracted_data.email,
        phone=extracted_data.phone,
        current_role=extracted_data.current_role,
        years_of_experience=extracted_data.years_of_experience,
        skills=", ".join(extracted_data.skills),
        location=extracted_data.location,
        portfolio_url=extracted_data.portfolio_url,
    )

    db.add(candidate)
    await db.commit()
    await db.refresh(candidate)

    document = CandidateDocument(
        candidate_id=candidate.id,
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
        data={
            "candidate_id": candidate.id,
            "extracted_details": extracted_data.model_dump(),
        }
    )
