"""Interview session management service."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from google import genai
from google.genai import types

from fastapi import status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import APIError
from app.models.interview import Candidate, Interview, InterviewSummary, InterviewSession
from app.models.scorecard import InterviewScorecard, ScorecardCategory, ScorecardScore
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.schemas.interview import (
    CreateInterviewRequest,
    InterviewResponse,
    InterviewSummaryResponse,
    UpdateAIConfigRequest,
    UpdateContextRequest,
    UpdateCriteriaRequest,
    InterviewPlanOutput
)
from app.services.ai_generation_service import AIGenerationService
from app.core.config import settings


async def _get_workspace(db: AsyncSession, user: User) -> uuid.UUID | None:
    """Return the user's first workspace, or None if they don't have one.

    Read-only — no side effects. Use this in GET endpoints where creating a
    workspace on a read request would violate HTTP idempotency rules.

    Args:
        db: Active async database session.
        user: The authenticated user.

    Returns:
        The workspace UUID, or None if the user has no workspace.
    """
    workspace_id = await db.execute(
        select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user.id)
    )
    return workspace_id.scalar_one_or_none()


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


async def _find_or_create_category(
    db: AsyncSession, workspace_id: uuid.UUID, name: str, sort_order: int
) -> ScorecardCategory:
    """Find an existing ScorecardCategory by name in the workspace, or create one."""
    result = await db.execute(
        select(ScorecardCategory).where(
            ScorecardCategory.workspace_id == workspace_id,
            ScorecardCategory.name == name,
        )
    )
    category = result.scalar_one_or_none()

    if category:
        return category

    category = ScorecardCategory(
        workspace_id=workspace_id,
        name=name,
        sort_order=sort_order,
    )
    db.add(category)
    await db.flush()
    return category


async def _persist_criteria(
    db: AsyncSession,
    scorecard: InterviewScorecard,
    workspace_id: uuid.UUID,
    criteria: list[str],
) -> None:
    """Create ScorecardScore rows linking a scorecard to categories."""
    for idx, criterion_name in enumerate(criteria):
        category = await _find_or_create_category(db, workspace_id, criterion_name, idx)
        score = ScorecardScore(
            scorecard_id=scorecard.id,
            category_id=category.id,
        )
        db.add(score)
    await db.flush()


async def _fetch_criteria(db: AsyncSession, interview_id: uuid.UUID) -> list[str]:
    """Fetch the criteria names for an interview, ordered by category sort_order."""
    result = await db.execute(
        select(ScorecardCategory.name)
        .join(ScorecardScore, ScorecardScore.category_id == ScorecardCategory.id)
        .join(
            InterviewScorecard,
            InterviewScorecard.id == ScorecardScore.scorecard_id,
        )
        .where(InterviewScorecard.interview_id == interview_id)
        .order_by(ScorecardCategory.sort_order)
    )
    return list(result.scalars().all())


def _derive_interview_meta(interview: Interview) -> dict:
    session_phase_map = {
        "draft": "connecting",
        "scheduled": "connecting",
        "in_progress": "live_transcript",
        "completed": "summary_ready",
        "cancelled": "none",
        "needs_attention": "listening",
    }
    list_status_map = {
        "in_progress": "live",
        "scheduled": "upcoming",
    }

    elapsed = None
    if interview.status == "in_progress" and interview.scheduled_start:
        now = datetime.now(timezone.utc)
        start = interview.scheduled_start
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        elapsed = int((now - start).total_seconds())

    question_progress = None
    if interview.questions_asked is not None and interview.questions_total is not None:
        question_progress = f"{interview.questions_asked}/{interview.questions_total}"

    return {
        "session_phase": session_phase_map.get(interview.status, "none"),
        "list_status": list_status_map.get(interview.status, "none"),
        "elapsed": elapsed,
        "question_progress": question_progress,
        "scheduled_date": interview.scheduled_start.date().isoformat()
        if interview.scheduled_start
        else None,
        "scheduled_time": interview.scheduled_start.time().strftime("%H:%M")
        if interview.scheduled_start
        else None,
    }


def _parse_assessment(summary: InterviewSummary | None) -> dict:
    if not summary or not summary.ai_assessment:
        return {"observation": None, "highlights": [], "red_flags": []}
    try:
        return json.loads(summary.ai_assessment)
    except (json.JSONDecodeError, ValueError):
        return {"observation": None, "highlights": [], "red_flags": []}


class InterviewService:
    """Encapsulate interview session creation and retrieval."""
    @classmethod
    def _client(cls):
        if not getattr(cls, "_client_instance", None):
            cls._client_instance = genai.Client(
                api_key=settings.GEMINI_API_KEY or "dummy_key"
            ).aio
        return cls._client_instance
    
    @classmethod
    async def generate_interview_plan(
        cls,
        role_title: str,
        job_description: str,
        skills_to_assess: list[str],
        custom_question: str | None = None,
    ) -> InterviewPlanOutput:
            """
            AI Shaping: Generates a structured interview plan (intro, questions, rubric) 
            from raw inputs. Used during Interview Creation (T-Minus 0).
            """
            prompt = f"""
You are an expert Technical Recruiter. Your task is to design a high-quality 
structured interview plan for the role of '{role_title}'.

# JOB DESCRIPTION
{job_description}

# CORE SKILLS TO EVALUATE
{", ".join(skills_to_assess)}

# SPECIFIC REQUESTS
{f"Ensure you include this question/topic: {custom_question}" if custom_question else "None"}

# INSTRUCTIONS
1. Design 5 specific, high-signal interview questions.
2. For each question, provide a 'followUpHint' to help the AI bot probe deeper.
3. Create a weighted scoring rubric based on the core skills.
4. Write a concise, warm intro and a professional closing.

Keep all text suitable for a live audio call (concise and natural).
"""

            response = await cls._client().models.generate_content(
                model="gemini-flash-lite-latest", # Use Flash for low latency extraction
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=InterviewPlanOutput
                )
            )
            return InterviewPlanOutput.model_validate_json(response.text)

    @classmethod
    async def create_interview(
        cls,
        request: CreateInterviewRequest,
        db: AsyncSession,
        user: User,
    ) -> InterviewResponse:
        """
        Standardized creation flow:
        1. Resolve Workspace.
        2. Sync Candidate metadata.
        3. AI Shaping (Generate bot instructions).
        4. Create InterviewSession (Bot Brain).
        5. Create Interview (Business Record).
        6. Create InterviewSummary (Result Placeholder).
        """
        # 1. Resolve Workspace
        workspace_id = await _get_or_create_workspace(db, user)

        candidate_id = request.candidate.candidate_id
        candidate = await db.get(Candidate, candidate_id)
        
        if not candidate:
            raise APIError("Candidate not found", status_code=404)
        
        candidate.full_name = request.candidate.full_name
        candidate.phone = request.candidate.phone
        candidate.location = request.candidate.location
        candidate.email = request.candidate.email
        candidate.current_role = request.candidate.current_role
        candidate.years_of_experience = request.candidate.years_of_experience

        if isinstance(request.candidate.skills, list):
            candidate.skills = ", ".join(request.candidate.skills) if request.candidate.skills else None
        else:
            candidate.skills = request.candidate.skills

        # FIX: Ensure portfolio_url is a string (asyncpg rejects Pydantic Url objects)
        if request.candidate.portfolio_url:
            candidate.portfolio_url = str(request.candidate.portfolio_url)

        plan = await cls.generate_interview_plan(
            role_title=request.role_title or "Candidate",
            job_description=request.job_description or "",
            skills_to_assess=request.skills_to_assess or [],
            custom_question=request.custom_question
        )

        session = InterviewSession(
            role=request.role_title or "Candidate",
            candidate_name=candidate.full_name,
            intro=plan.intro,
            questions_json=json.dumps([q.model_dump() for q in plan.questions]),
            rubric_json=json.dumps([r.model_dump() for r in plan.rubric]),
            closing=plan.closing,
            duration_minutes=0,
            status="created"
        )

        db.add(session)
        await db.flush()

        interview = Interview(
            workspace_id=workspace_id,
            candidate_id=candidate.id,
            interviewer_id=user.id,
            session_id=session.id,
            meeting_id=None, 
            role_title=request.role_title,
            scheduled_start=request.scheduled_start,
            scheduled_end=request.scheduled_end,
            platform=request.platform,
            call_link=str(request.call_link) if request.call_link else None,
            ai_tone=request.ai_tone,
            status="scheduled", # It is ready to be joined
            participation_mode=request.participation_mode.value,
        )
        db.add(interview)
        await db.flush()

        summary = InterviewSummary(
            interview_id=interview.id,
            job_description=request.job_description,
            scoring_rubric=session.rubric_json, # Mirror the rubric for easy access
            key_skills=", ".join(request.skills_to_assess) if request.skills_to_assess else None,
            custom_question=request.custom_question,
            status="pending",
        )
        db.add(summary)

        await db.commit()
        await db.refresh(interview)

        scheduled_date = None
        scheduled_time = None
        if interview.scheduled_start:
            scheduled_date = interview.scheduled_start.strftime("%Y-%m-%d")
            scheduled_time = interview.scheduled_start.strftime("%H:%M")

        # Construct the nested Summary Response
        # During creation, status is 'pending' and assessments are empty
        summary_resp = InterviewSummaryResponse(
            job_description=summary.job_description,
            scoring_rubric=summary.scoring_rubric,
            ai_assessment=None,
            status=summary.status,
        )

        return InterviewResponse(
            id=interview.id,
            title=interview.role_title, # or role_title
            status=interview.status,
            role_title=interview.role_title,
            platform=interview.platform,
            ai_tone=interview.ai_tone,
            candidate_name=candidate.full_name,
            candidate_email=candidate.email,
            phone=candidate.phone,
            resume_url=candidate.resume_url,
            portfolio_url=candidate.portfolio_url,
            scheduled_date=scheduled_date,
            scheduled_time=scheduled_time,
            duration=interview.duration_min or 20,
            
            # Progress counters start at 0
            questions_asked=0,
            questions_total=len(json.loads(session.questions_json)), # From AI Plan
            question_progress="0%",
            rating=None,
            
            # Technical fields
            participation_mode=request.participation_mode,
            session_phase="pre_interview",
            
            # Post-interview placeholders (currently empty)
            summary=summary_resp,
            custom_question=summary.custom_question,
            key_skills=request.skills_to_assess or [],
            criteria=request.skills_to_assess or [],
            observation=None,
            highlights=[],
            red_flags=[],
            created_at=interview.created_at,
        )


    @staticmethod
    async def get_interview(
        interview_id: uuid.UUID,
        db: AsyncSession,
        user: User,
    ) -> InterviewResponse:
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

        candidate_result = await db.execute(
            select(Candidate).where(Candidate.id == interview.candidate_id)
        )
        candidate = candidate_result.scalar_one_or_none()

        summary_result = await db.execute(
            select(InterviewSummary).where(
                InterviewSummary.interview_id == interview.id
            )
        )
        summary = summary_result.scalar_one_or_none()

        criteria = await _fetch_criteria(db, interview.id)
        meta = _derive_interview_meta(interview)
        assessment = _parse_assessment(summary)

        return InterviewResponse(
            id=interview.id,
            title=interview.role_title,
            status=interview.status,
            role_title=interview.role_title,
            platform=interview.platform,
            ai_tone=interview.ai_tone,
            participation_mode=interview.participation_mode,
            candidate_name=candidate.full_name if candidate else "Unknown",
            candidate_email=candidate.email if candidate else None,
            phone=candidate.phone if candidate else None,
            resume_url=candidate.resume_url if candidate else None,
            portfolio_url=candidate.portfolio_url if candidate else None,
            duration=interview.duration_min,
            questions_asked=interview.questions_asked,
            questions_total=interview.questions_total,
            rating=interview.rating,
            participants=None,
            summary=InterviewSummaryResponse(
                job_description=summary.job_description if summary else None,
                scoring_rubric=summary.scoring_rubric if summary else None,
                ai_assessment=assessment.get("observation"),
                status=summary.status if summary else None,
                key_skills=summary.key_skills if summary else None, 
            ) if summary else None,
            custom_question=summary.custom_question if summary else None,
            observation=assessment.get("observation"),
            highlights=assessment.get("highlights", []),
            red_flags=assessment.get("red_flags", []),
            criteria=[s.strip() for s in summary.key_skills.split(",")] if summary and summary.key_skills else [],
            key_skills=[s.strip() for s in summary.key_skills.split(",")] if summary and summary.key_skills else [],
            created_at=interview.created_at,
            **meta,
        )

    @staticmethod
    async def update_interview_criteria(
        interview_id: uuid.UUID,
        request: UpdateCriteriaRequest,
        db: AsyncSession,
        user: User,
    ) -> dict:
        """Replace scorecard criteria for a draft interview.

        Args:
            interview_id: UUID of the interview to update.
            request: Validated criteria payload.
            db: Active async database session.
            user: The authenticated user.

        Returns:
            A dict with the updated criteria list.

        Raises:
            APIError: 404 if the interview does not exist or belong to user.
            APIError: 400 if the interview is not in draft status.
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

        if interview.status not in ["draft", "scheduled"]:
            raise APIError(
                "Criteria can only be updated for draft interviews",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="bad_request",
            )

        # Resolve workspace
        workspace_id = interview.workspace_id

        summary_result = await db.execute(
            select(InterviewSummary).where(InterviewSummary.interview_id == interview.id)
        )
        summary = summary_result.scalar_one_or_none()
        if summary:
            summary.key_skills = ", ".join(request.criteria)

        # Get or create scorecard
        sc_result = await db.execute(
            select(InterviewScorecard).where(
                InterviewScorecard.interview_id == interview.id
            )
        )
        scorecard = sc_result.scalar_one_or_none()

        if not scorecard:
            scorecard = InterviewScorecard(interview_id=interview.id)
            db.add(scorecard)
            await db.flush()
        else:
            # Delete existing scores for this scorecard
            await db.execute(
                delete(ScorecardScore).where(
                    ScorecardScore.scorecard_id == scorecard.id
                )
            )
            await db.flush()

        # Persist new criteria
        await _persist_criteria(db, scorecard, workspace_id, request.criteria)
        await db.commit()

        return {"criteria": request.criteria}

    @staticmethod
    async def update_context(
        interview_id: uuid.UUID,
        request: UpdateContextRequest,
        db: AsyncSession,
        user: User,
    ) -> dict:
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
    
        if interview.status not in ["draft", "scheduled"]:
            raise APIError("Cannot update an active or completed interview", status_code=400)

        if interview.role_title is None and request.role_title:
            interview.role_title = request.role_title

        summary_result = await db.execute(
            select(InterviewSummary).where(
                InterviewSummary.interview_id == interview.id
            )
        )
        summary = summary_result.scalar_one_or_none()
        if not summary:
            summary = InterviewSummary(interview_id=interview.id)
            db.add(summary)

        if request.job_description:
            summary.job_description = request.job_description
        if request.key_skills:
            summary.key_skills = ",".join(request.key_skills)
        if request.custom_questions:
            summary.custom_question = request.custom_questions

        await db.commit()
        await db.refresh(interview)
        return {
            "interview_id": str(interview.id),
            "status": interview.status,
            "updated_at": interview.updated_at,
        }

    @staticmethod
    async def update_session_config(
        interview_id: uuid.UUID,
        request: UpdateAIConfigRequest,
        db: AsyncSession,
        user: User,
    ) -> dict:
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
        
        if interview.status not in ["draft", "scheduled"]:
            raise APIError("Cannot update an active or completed interview", status_code=400)

        if request.participation_mode:
            interview.participation_mode = request.participation_mode
        if request.platform:
            interview.platform = request.platform
        if request.call_link:
            interview.call_link = request.call_link
        if request.scheduled_start:
            interview.scheduled_start = request.scheduled_start
        if request.scheduled_end:
            interview.scheduled_end = request.scheduled_end

        await db.commit()
        await db.refresh(interview)
        return {
            "interview_id": str(interview.id),
            "status": interview.status,
            "participation_mode": interview.participation_mode,
            "updated_at": interview.updated_at,
        }

    @staticmethod
    async def confirm_interview(
        interview_id: uuid.UUID,
        db: AsyncSession,
        user: User,
    ) -> dict:
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

        if interview.status == "scheduled":
            return {
                "interview_id": str(interview.id),
                "status": interview.status,
                "confirmed_at": interview.updated_at,
            }

        if interview.status in ("cancelled", "completed"):
            raise APIError(
                f"Cannot confirm a {interview.status} interview",
                status_code=status.HTTP_409_CONFLICT,
                code="invalid_status",
            )

        summary_result = await db.execute(
            select(InterviewSummary).where(
                InterviewSummary.interview_id == interview.id
            )
        )
        summary = summary_result.scalar_one_or_none()

        if not summary or not summary.job_description:
            raise APIError(
                "Cannot confirm without job description. Complete context setup first.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="incomplete_context",
            )

        interview.status = "scheduled"
        await db.commit()
        await db.refresh(interview)
        return {
            "interview_id": str(interview.id),
            "status": interview.status,
            "confirmed_at": interview.updated_at,
        }

    @staticmethod
    async def stop_transcript(
        interview_id: uuid.UUID,
        db: AsyncSession,
        user: User,
    ) -> dict:
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

        if interview.status == "completed":
            raise APIError(
                "Interview is already completed",
                status_code=status.HTTP_409_CONFLICT,
                code="already_completed",
            )

        if interview.status == "cancelled":
            raise APIError(
                "Interview has been cancelled",
                status_code=status.HTTP_409_CONFLICT,
                code="already_cancelled",
            )

        if interview.status != "in_progress":
            raise APIError(
                "Transcript can only be stopped while the interview is in progress",
                status_code=status.HTTP_409_CONFLICT,
                code="invalid_status",
            )

        interview.status = "completed"
        await db.commit()
        await db.refresh(interview)

        return {
            "interview_id": str(interview.id),
            "status": interview.status,
        }

    @staticmethod
    async def list_interviews(
        db: AsyncSession,
        user: User,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        search: str | None = None,
    ) -> tuple[list, int]:

        filters = [Interview.interviewer_id == user.id]

        if status:
            status_list = [s.strip() for s in status.split(",")]
            filters.append(Interview.status.in_(status_list))

        if search:
            pattern = f"%{search.strip()}%"
            filters.append(
                or_(
                    Interview.role_title.ilike(pattern),
                    Candidate.full_name.ilike(pattern),
                )
            )

        count_result = await db.execute(
            select(func.count(Interview.id))
            .outerjoin(Candidate, Candidate.id == Interview.candidate_id)
            .where(*filters)
        )
        total = count_result.scalar() or 0

        result = await db.execute(
            select(Interview, Candidate.full_name)
            .outerjoin(Candidate, Candidate.id == Interview.candidate_id)
            .where(*filters)
            .order_by(Interview.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.all()), total

    @staticmethod
    async def cancel_interview(
        interview_id: uuid.UUID,
        db: AsyncSession,
        user: User,
    ) -> InterviewResponse:
        """Cancel a scheduled or draft interview.

        Transitions the interview status to ``cancelled``. Only the owning
        interviewer may cancel an interview. Interviews that are already
        ``cancelled`` or ``completed`` cannot be cancelled again.

        Args:
            interview_id: UUID of the interview to cancel.
            db: Active async database session.
            user: The authenticated user.

        Returns:
            A populated :class:`InterviewResponse` with status ``cancelled``.

        Raises:
            APIError: 404 if the interview does not exist or does not belong
                to the requesting user.
            APIError: 409 if the interview is already cancelled or completed.
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

        if interview.status == "cancelled":
            raise APIError(
                "Interview is already cancelled",
                status_code=status.HTTP_409_CONFLICT,
                code="already_cancelled",
            )

        if interview.status == "completed":
            raise APIError(
                "Completed interviews cannot be cancelled",
                status_code=status.HTTP_409_CONFLICT,
                code="interview_completed",
            )

        interview.status = "cancelled"
        await db.flush()

        # Fetch candidate
        candidate_result = await db.execute(
            select(Candidate).where(Candidate.id == interview.candidate_id)
        )
        candidate = candidate_result.scalar_one_or_none()

        # Fetch summary
        summary_result = await db.execute(
            select(InterviewSummary).where(
                InterviewSummary.interview_id == interview.id
            )
        )
        summary = summary_result.scalar_one_or_none()

        # Fetch criteria
        criteria = await _fetch_criteria(db, interview.id)

        await db.commit()

        return InterviewResponse(
            id=interview.id,
            title=interview.role_title,
            status=interview.status,
            role_title=interview.role_title,
            platform=interview.platform,
            ai_tone=interview.ai_tone,
            participation_mode=interview.participation_mode,
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
            criteria=criteria,
            created_at=interview.created_at,
        )

    @staticmethod
    async def get_summary(
        interview_id: uuid.UUID,
        db: AsyncSession,
        user: User,
    ) -> dict:
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

        result = await db.execute(
            select(InterviewSummary).where(
                InterviewSummary.interview_id == interview_id
            )
        )
        summary = result.scalar_one_or_none()

        if not summary:
            return {
                "interview_id": str(interview_id),
                "status": "pending",
                "observation": None,
                "highlights": [],
                "red_flags": [],
                "custom_question": None,
                "key_skills": [],
            }

        assessment = {}
        if summary.ai_assessment:
            try:
                assessment = json.loads(summary.ai_assessment)
            except (json.JSONDecodeError, ValueError):
                assessment = {}

        return {
            "interview_id": str(interview_id),
            "status": summary.status,
            "observation": assessment.get("observation"),
            "highlights": assessment.get("highlights", []),
            "red_flags": assessment.get("red_flags", []),
            "custom_question": summary.custom_question,
            "key_skills": summary.key_skills.split(",") if summary.key_skills else [],
        }

    @staticmethod
    async def retry_summary(
        interview_id: uuid.UUID,
        db: AsyncSession,
        user: User,
    ) -> dict:
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

        result = await db.execute(
            select(InterviewSummary).where(
                InterviewSummary.interview_id == interview_id
            )
        )
        summary = result.scalar_one_or_none()

        if not summary or summary.status != "failed":
            raise APIError(
                "Summary is not in a failed state",
                status_code=status.HTTP_409_CONFLICT,
                code="summary_not_failed",
            )

        summary.status = "generating"
        await db.commit()

        return {
            "interview_id": str(interview_id),
            "status": "generating",
        }

    @staticmethod
    async def get_session_status(
        interview_id: uuid.UUID,
        db: AsyncSession,
        user: User,
    ) -> dict:
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

        session_phase_map = {
            "draft": "connecting",
            "scheduled": "connecting",
            "in_progress": "live_transcript",
            "completed": "summary_ready",
            "cancelled": "none",
            "needs_attention": "listening",
        }

        elapsed = None
        if interview.status == "in_progress" and interview.scheduled_start:
            now = datetime.now(timezone.utc)
            start = interview.scheduled_start
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            elapsed = int((now - start).total_seconds())

        return {
            "interview_id": str(interview_id),
            "status": interview.status,
            "session_phase": session_phase_map.get(interview.status, "none"),
            "elapsed": elapsed,
            "participants": None,
            "platform": interview.platform,
            "connection_status": "connected"
            if interview.status == "in_progress"
            else "idle",
        }
