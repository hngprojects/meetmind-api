"""Interview session management service."""

from __future__ import annotations

import uuid

from fastapi import UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import APIError
from app.models.interview import (
    Candidate,
    Interview,
    InterviewSkillToAssess,
    InterviewSummary,
)
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.schemas.interview import (
    CreateInterviewRequest,
    InterviewResponse,
    InterviewSummaryResponse,
)

def _extract_text_from_upload(upload: UploadFile) -> str:
    filename = (upload.filename or "").lower()
    data = upload.file.read()

    if filename.endswith(".txt"):
        return data.decode("utf-8", errors="ignore").strip()

    if filename.endswith(".pdf"):
        try:
            from pypdf import PdfReader
        except Exception as exc:  # pragma: no cover
            raise APIError(
                "PDF extraction dependency missing", code="pdf_dependency_missing"
            ) from exc
        from io import BytesIO

        reader = PdfReader(BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip()

    if filename.endswith(".docx"):
        try:
            from docx import Document
        except Exception as exc:  # pragma: no cover
            raise APIError(
                "DOCX extraction dependency missing", code="docx_dependency_missing"
            ) from exc
        from io import BytesIO

        doc = Document(BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs).strip()

    raise APIError(
        "Unsupported file type. Use PDF, DOCX, or TXT",
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        code="unsupported_file_type",
    )


async def _get_workspace(db: AsyncSession, user: User) -> uuid.UUID | None:
    workspace_id = await db.execute(
        select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user.id)
    )
    return workspace_id.scalar_one_or_none()


async def _get_or_create_workspace(db: AsyncSession, user: User) -> uuid.UUID:
    result = await db.execute(
        select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user.id)
    )
    workspace_id = result.scalar_one_or_none()
    if workspace_id:
        return workspace_id

    workspace = Workspace(
        name=f"{user.name or user.email}'s Workspace", created_by=user.id
    )
    db.add(workspace)
    await db.flush()

    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    await db.flush()
    return workspace.id


async def _hydrate_response(
    db: AsyncSession, interview: Interview
) -> InterviewResponse:
    candidate = (
        await db.execute(
            select(Candidate).where(Candidate.id == interview.candidate_id)
        )
    ).scalar_one_or_none()
    summary = (
        await db.execute(
            select(InterviewSummary).where(
                InterviewSummary.interview_id == interview.id
            )
        )
    ).scalar_one_or_none()
    skills = (
        (
            await db.execute(
                select(InterviewSkillToAssess)
                .where(InterviewSkillToAssess.summary_id == summary.id)
                .order_by(InterviewSkillToAssess.sort_order.asc())
                if summary
                else select(InterviewSkillToAssess).where(False)
            )
        )
        .scalars()
        .all()
    )

    return InterviewResponse(
        id=interview.id,
        title=interview.role_title,
        status=interview.status,
        role_title=interview.role_title,
        platform=interview.platform,
        meeting_link=interview.meeting_link,
        scheduled_start=interview.scheduled_start,
        ai_tone=interview.ai_tone,
        participation_mode=interview.participation_mode,
        criteria=[s.skill for s in skills],
        candidate_name=candidate.full_name if candidate else "Unknown",
        candidate_email=candidate.email if candidate else None,
        summary=InterviewSummaryResponse(
            job_description=summary.job_description if summary else None,
            scoring_rubric=summary.scoring_rubric if summary else None,
            cv_text=summary.cv_text if summary else None,
            ai_assessment=summary.ai_assessment if summary else None,
            status=summary.status if summary else None,
        )
        if summary
        else None,
        created_at=interview.created_at,
    )


class InterviewService:
    """Encapsulate interview session creation and retrieval."""

    @staticmethod
    async def create_interview(
        request: CreateInterviewRequest,
        db: AsyncSession,
        user: User,
    ) -> InterviewResponse:
        """Create an interview session with its context.

        Steps:
        1. Resolve or create the user's workspace.
        2. Create a Candidate record.
        3. Create an Interview record in ``draft`` status.
        4. Create an InterviewSummary record holding the context fields.

        Args:
            request: Validated interview creation payload.
            db: Active async database session.
            user: The authenticated user (becomes the interviewer).

        Returns:
            A populated :class:`InterviewResponse`.
        """
        workspace_id = await _get_or_create_workspace(db, user)

        # 1. Create candidate
        candidate = Candidate(
            workspace_id=workspace_id,
            full_name=request.candidate_name,
            email=request.candidate_email,
        )
        db.add(candidate)
        await db.flush()

        # 2. Create interview — status starts as "draft" per RFC scope
        interview = Interview(
            workspace_id=workspace_id,
            candidate_id=candidate.id,
            interviewer_id=user.id,
            role_title=request.role_title,
            platform=request.platform,
            meeting_link=str(request.meeting_link),
            scheduled_start=request.scheduled_start,
            ai_tone=request.ai_tone,
            participation_mode=request.participation_mode,
            status="draft",
        )
        db.add(interview)
        await db.flush()

        # 3. Create summary to hold context fields
        summary = InterviewSummary(
            interview_id=interview.id,
            job_description=request.job_description,
            scoring_rubric=request.scoring_rubric,
            status="pending",
        )
        db.add(summary)
        await db.flush()

        for idx, skill in enumerate(request.criteria, start=1):
            db.add(
                InterviewSkillToAssess(
                    summary_id=summary.id, skill=skill, sort_order=idx
                )
            )

        await db.commit()
        response = await _hydrate_response(db, interview)
        response.title = request.title
        return response

    @staticmethod
    async def get_interview(
        interview_id: uuid.UUID,
        db: AsyncSession,
        user: User,
    ) -> InterviewResponse:
        """Retrieve an interview session by ID.

        Only returns interviews where the authenticated user is the interviewer,
        preventing cross-user data leakage.

        Args:
            interview_id: UUID of the interview to retrieve.
            db: Active async database session.
            user: The authenticated user.

        Returns:
            A populated :class:`InterviewResponse`.

        Raises:
            APIError: 404 if the interview does not exist or does not belong
                to the requesting user.
        """
        interview = (
            await db.execute(
                select(Interview).where(
                    Interview.id == interview_id,
                    Interview.interviewer_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if not interview:
            raise APIError(
                "Interview not found",
                status_code=status.HTTP_404_NOT_FOUND,
                code="interview_not_found",
            )

        await db.refresh(interview)
        response = await _hydrate_response(db, interview)

        response.title = interview.role_title
        return response

    @staticmethod
    async def confirm_interview(
        interview_id: uuid.UUID, db: AsyncSession, user: User
    ) -> InterviewResponse:
        interview = (
            await db.execute(
                select(Interview).where(
                    Interview.id == interview_id, Interview.interviewer_id == user.id
                )
            )
        ).scalar_one_or_none()
        if not interview:
            raise APIError(
                "Interview not found",
                status_code=status.HTTP_404_NOT_FOUND,
                code="interview_not_found",
            )
        if interview.status != "draft":
            raise APIError(
                "Only draft interviews can be confirmed",
                code="invalid_status_transition",
            )
        interview.status = "scheduled"
        await db.commit()
        return await _hydrate_response(db, interview)

    @staticmethod
    async def list_interviews(
        db: AsyncSession, user: User, status_filter: str | None
    ) -> list[InterviewResponse]:
        query = (
            select(Interview)
            .where(Interview.interviewer_id == user.id)
            .order_by(
                Interview.scheduled_start.desc().nullslast(),
                Interview.created_at.desc(),
            )
        )
        if status_filter:
            query = query.where(Interview.status == status_filter)
        interviews = (await db.execute(query)).scalars().all()
        return [await _hydrate_response(db, interview) for interview in interviews]

    @staticmethod
    async def upload_interview_document(
        interview_id: uuid.UUID, upload: UploadFile, db: AsyncSession, user: User
    ) -> InterviewResponse:
        interview = (
            await db.execute(
                select(Interview).where(
                    Interview.id == interview_id, Interview.interviewer_id == user.id
                )
            )
        ).scalar_one_or_none()
        if not interview:
            raise APIError(
                "Interview not found",
                status_code=status.HTTP_404_NOT_FOUND,
                code="interview_not_found",
            )
        summary = (
            await db.execute(
                select(InterviewSummary).where(
                    InterviewSummary.interview_id == interview.id
                )
            )
        ).scalar_one_or_none()
        if not summary:
            raise APIError(
                "Interview summary not found",
                status_code=status.HTTP_404_NOT_FOUND,
                code="summary_not_found",
            )
        extracted_text = _extract_text_from_upload(upload)
        summary.cv_text = (
            summary.cv_text + "\n\n" if summary.cv_text else ""
        ) + extracted_text
        await db.commit()
        return await _hydrate_response(db, interview)
