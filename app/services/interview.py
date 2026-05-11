"""Interview session management service."""

from __future__ import annotations

import uuid

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import APIError
from app.models.interview import Candidate, Interview, InterviewSummary
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.schemas.interview import (
    CreateInterviewRequest,
    InterviewResponse,
    InterviewSummaryResponse,
)


async def _get_or_create_workspace(db: AsyncSession, user: User) -> uuid.UUID:
    """Return the user's first workspace, creating a default one if none exists.

    Args:
        db: Active async database session.
        user: The authenticated user.

    Returns:
        The workspace UUID to scope the interview under.
    """
    result = await db.execute(
        select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user.id)
    )
    workspace_id = result.scalar_one_or_none()

    if workspace_id:
        return workspace_id

    # No workspace yet — create a default one for this user.
    workspace = Workspace(
        name=f"{user.name or user.email}'s Workspace",
        created_by=user.id,
    )
    db.add(workspace)
    await db.flush()

    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="owner",
    )
    db.add(member)
    await db.flush()

    return workspace.id


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
            role_title=request.role_title or request.title,
            platform=request.platform,
            ai_tone=request.ai_tone,
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
        await db.commit()

        return InterviewResponse(
            id=interview.id,
            title=request.title,
            status=interview.status,
            role_title=interview.role_title,
            platform=interview.platform,
            ai_tone=interview.ai_tone,
            candidate_name=candidate.full_name,
            candidate_email=candidate.email,
            summary=InterviewSummaryResponse(
                job_description=summary.job_description,
                scoring_rubric=summary.scoring_rubric,
                ai_assessment=summary.ai_assessment,
                status=summary.status,
            ),
            created_at=interview.created_at,
        )

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
        result = await db.execute(
            select(Interview).where(
                Interview.id == interview_id,
                Interview.interviewer_id == user.id,
            )
        )
        interview = result.scalar_one_or_none()

        if not interview:
            raise APIError(
                "Interview not found",
                status_code=status.HTTP_404_NOT_FOUND,
                code="interview_not_found",
            )

        # Fetch candidate
        candidate_result = await db.execute(
            select(Candidate).where(Candidate.id == interview.candidate_id)
        )
        candidate = candidate_result.scalar_one_or_none()

        # Fetch summary (context)
        summary_result = await db.execute(
            select(InterviewSummary).where(
                InterviewSummary.interview_id == interview.id
            )
        )
        summary = summary_result.scalar_one_or_none()

        return InterviewResponse(
            id=interview.id,
            title=interview.role_title,
            status=interview.status,
            role_title=interview.role_title,
            platform=interview.platform,
            ai_tone=interview.ai_tone,
            candidate_name=candidate.full_name if candidate else "Unknown",
            candidate_email=candidate.email if candidate else None,
            summary=InterviewSummaryResponse(
                job_description=summary.job_description if summary else None,
                scoring_rubric=summary.scoring_rubric if summary else None,
                ai_assessment=summary.ai_assessment if summary else None,
                status=summary.status if summary else None,
            )
            if summary
            else None,
            created_at=interview.created_at,
        )
