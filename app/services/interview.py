"""Interview session management service."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import status
from google import genai
from google.genai import types
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.responses import APIError
from app.core.utils import get_user_workspace, retry_async, safe_notify
from app.models.interview import (
    Candidate,
    Interview,
    InterviewSession,
    InterviewSummary,
    InterviewTranscript,
    InterviewTranscriptTurn,
)
from app.models.scorecard import (
    InterviewScorecard,
    ScorecardCategory,
    ScorecardEvidence,
    ScorecardQuestion,
    ScorecardScore,
    ScorecardSignal,
    ScorecardSubRubric,
)
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.schemas.interview import (
    AIConfigUpdateResponse,
    CandidateProfileDetail,
    ContextUpdateResponse,
    CreateInterviewRequest,
    CriteriaUpdateResponse,
    InterviewConfirmResponse,
    InterviewPlanOutput,
    InterviewProfileDetail,
    InterviewProfileResponse,
    InterviewResponse,
    InterviewScorecardResponse,
    InterviewSummaryDetailResponse,
    InterviewSummaryResponse,
    RejoinSessionResponse,
    ScorecardSection,
    TranscriptStopResponse,
    UpdateAIConfigRequest,
    UpdateContextRequest,
    UpdateCriteriaRequest,
)

_gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY or "dummy_key").aio


def _join_non_empty(parts: list[str | None]) -> str:
    return "\n".join(part for part in parts if part)


def _build_candidate_context(candidate: Candidate) -> str:
    """Summarize candidate profile fields extracted from CV/upload payload."""
    return _join_non_empty(
        [
            f"Name: {candidate.full_name}" if candidate.full_name else None,
            f"Current role: {candidate.current_role}"
            if candidate.current_role
            else None,
            (
                f"Years of experience: {candidate.years_of_experience}"
                if candidate.years_of_experience is not None
                else None
            ),
            f"Skills: {candidate.skills}" if candidate.skills else None,
            f"Location: {candidate.location}" if candidate.location else None,
            f"Portfolio: {candidate.portfolio_url}"
            if candidate.portfolio_url
            else None,
        ]
    )


def _infer_interview_track(role_title: str, skills_to_assess: list[str]) -> str:
    text = " ".join([role_title, *skills_to_assess]).lower()
    if any(
        keyword in text
        for keyword in (
            "design",
            "designer",
            "ux",
            "ui",
            "product design",
            "visual",
            "brand",
        )
    ):
        return "design"
    if any(keyword in text for keyword in ("product manager", "product management")):
        return "product"
    if any(
        keyword in text
        for keyword in ("frontend", "backend", "fullstack", "software", "engineer")
    ):
        return "engineering"
    return "general"


def _fallback_interview_plan(
    role_title: str,
    skills_to_assess: list[str],
    custom_question: str | None = None,
) -> InterviewPlanOutput:
    """Build a safe non-LLM plan that matches the requested role family."""
    from app.schemas.interview import InterviewQuestionSchema, RubricCriterion

    track = _infer_interview_track(role_title, skills_to_assess)
    role = role_title or "the role"

    if track == "design":
        question_specs = [
            (
                "Walk me through a design project from problem discovery to final solution.",
                "Probe their process, constraints, research inputs, iterations, and impact.",
            ),
            (
                "How do you decide whether a design is successful?",
                "Listen for user outcomes, usability signals, business goals, and trade-offs.",
            ),
            (
                "Tell me about a time you handled conflicting feedback from stakeholders.",
                "Probe collaboration, prioritization, communication, and rationale.",
            ),
            (
                "How do you use research, data, or user feedback to improve a design?",
                "Look for concrete examples and how insights changed the final work.",
            ),
            (
                "What is one portfolio piece you would improve today, and what would you change?",
                "Probe self-awareness, craft standards, and product thinking.",
            ),
        ]
        rubric_names = skills_to_assess or [
            "Design Process",
            "User Empathy",
            "Visual/Product Craft",
            "Collaboration",
            "Communication",
        ]
    elif track == "product":
        question_specs = [
            (
                "Tell me about a product decision you made with incomplete information.",
                "Probe customer insight, prioritization, risk, and outcome.",
            ),
            (
                "How do you choose what not to build?",
                "Listen for strategy, trade-offs, stakeholder alignment, and evidence.",
            ),
            (
                "Walk me through how you define success for a new feature.",
                "Probe metrics, qualitative signals, launch learning, and iteration.",
            ),
            (
                "Describe a time you aligned engineering, design, and business stakeholders.",
                "Look for clarity, influence, conflict handling, and follow-through.",
            ),
            (
                "How do you learn from a product launch that did not meet expectations?",
                "Probe accountability, analysis, and concrete changes.",
            ),
        ]
        rubric_names = skills_to_assess or [
            "Product Judgment",
            "Prioritization",
            "Customer Insight",
            "Stakeholder Management",
            "Communication",
        ]
    elif track == "engineering":
        question_specs = [
            (
                f"Walk me through a technical project relevant to {role} that you are proud of.",
                "Probe ownership, architecture, constraints, trade-offs, and impact.",
            ),
            (
                "Tell me about a difficult technical trade-off you had to make.",
                "Listen for reasoning, alternatives considered, and consequences.",
            ),
            (
                "How do you approach debugging a complex production issue?",
                "Probe method, observability, communication, and prevention.",
            ),
            (
                "Describe a time you improved quality, reliability, or maintainability.",
                "Look for measurable impact and practical engineering judgment.",
            ),
            (
                "How do you collaborate with teammates when requirements are unclear?",
                "Probe communication, assumptions, iteration, and delivery discipline.",
            ),
        ]
        rubric_names = skills_to_assess or [
            "Technical Depth",
            "Problem Solving",
            "Execution",
            "Collaboration",
            "Communication",
        ]
    else:
        question_specs = [
            (
                f"Walk me through work you have done that best prepares you for {role}.",
                "Probe scope, ownership, outcomes, and relevance to the role.",
            ),
            (
                "Tell me about a challenging project and how you approached it.",
                "Listen for problem solving, judgment, and follow-through.",
            ),
            (
                "Describe a time you had to learn something quickly to deliver results.",
                "Probe learning approach, resourcefulness, and impact.",
            ),
            (
                "How do you collaborate when priorities or expectations are unclear?",
                "Look for communication, alignment, and practical next steps.",
            ),
            (
                "What strengths would you bring to this role, and where are you still growing?",
                "Probe self-awareness, specificity, and fit.",
            ),
        ]
        rubric_names = skills_to_assess or [
            "Role Fit",
            "Problem Solving",
            "Execution",
            "Collaboration",
            "Communication",
        ]

    if custom_question:
        question_specs[-1] = (
            custom_question,
            "Ask concise follow-ups to clarify the candidate's experience and evidence.",
        )

    return InterviewPlanOutput(
        intro=(
            f"Welcome to the interview for {role}. "
            "I will ask a few focused questions about your experience and fit."
        ),
        questions=[
            InterviewQuestionSchema(
                text=text,
                followUpHint=follow_up,
                maxFollowUps=2,
            )
            for text, follow_up in question_specs
        ],
        rubric=[
            RubricCriterion(
                name=name,
                description=f"Evidence of {name.lower()} relevant to {role}.",
                weight=3 if idx == 0 else 2,
            )
            for idx, name in enumerate(rubric_names[:5])
        ],
        closing="Thanks for your time. A recruiter will follow up with next steps.",
    )


async def _get_or_create_workspace(db: AsyncSession, user: User) -> uuid.UUID:
    workspace_id = await get_user_workspace(db, user.id)
    if workspace_id:
        return workspace_id

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


class InterviewService:
    """Encapsulate interview session creation and retrieval."""

    @classmethod
    async def generate_interview_plan(
        cls,
        role_title: str,
        job_description: str,
        skills_to_assess: list[str],
        custom_question: str | None = None,
        candidate_context: str | None = None,
    ) -> InterviewPlanOutput:
        logger = logging.getLogger("app.services.interview")
        logger.info(f"\n🤖 GENERATING INTERVIEW PLAN FOR ROLE: {role_title}")
        logger.info(f"   Skills to assess: {', '.join(skills_to_assess)}")

        system_instruction = f"""
You are an expert Technical Recruiter. Your task is to design a high-quality 
structured interview plan for the role of '{role_title}'.

# JOB DESCRIPTION
{job_description}

# CORE SKILLS TO EVALUATE
{", ".join(skills_to_assess)}

# CANDIDATE CONTEXT FROM CV/PROFILE
{candidate_context or "No candidate CV/profile context was provided."}

# SPECIFIC REQUESTS
{f"Ensure you include this question:{custom_question}" if custom_question else "None"}

# INSTRUCTIONS
1. Design 5 specific, high-signal interview questions.
   The questions must match the role, job description, and candidate CV/profile.
2. For each question, provide a 'followUpHint' to help the AI bot probe deeper.
3. Create a weighted scoring rubric based on the core skills.
4. Write a concise, warm intro and a professional closing.

Keep all text suitable for a live audio call (concise and natural).
"""

        try:
            response = await retry_async(
                _gemini_client.models.generate_content,
                model="gemini-flash-lite-latest",
                contents=f"{system_instruction}\n\nGenerate the complete interview plan based on the provided context.",
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=InterviewPlanOutput,
                ),
                max_retries=3,
                initial_delay=1.0,
                backoff_factor=2.0,
                task_name=f"Generate interview plan for {role_title}",
            )
            plan = InterviewPlanOutput.model_validate_json(response.text)
            logger.info("✅ INTERVIEW PLAN GENERATED SUCCESSFULLY")
            logger.info(f"   Intro: {plan.intro}")
            logger.info(f"   Questions ({len(plan.questions)}):")
            for idx, q in enumerate(plan.questions, 1):
                logger.info(f"     {idx}. {q.text}")
                logger.info(f"        Follow-up hint: {q.followUpHint}")
            logger.info(
                f"   Rubric criteria: {', '.join([r.name for r in plan.rubric])}"
            )
            logger.info(f"   Closing: {plan.closing}\n")
            return plan
        except Exception as e:
            logger.warning(
                "Gemini API call failed or key invalid. "
                "Falling back to role-aware interview plan. Error: %s",
                e,
            )
            fallback = _fallback_interview_plan(
                role_title=role_title,
                skills_to_assess=skills_to_assess,
                custom_question=custom_question,
            )
            logger.info("✅ FALLBACK INTERVIEW PLAN USED")
            logger.info(f"   Questions ({len(fallback.questions)}):")
            for idx, q in enumerate(fallback.questions, 1):
                logger.info(f"     {idx}. {q.text}\n")
            return fallback

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
            candidate = Candidate(
                id=candidate_id,
                workspace_id=workspace_id,
                full_name=request.candidate.full_name or "Candidate",
            )
            db.add(candidate)

        candidate.full_name = request.candidate.full_name
        candidate.phone = request.candidate.phone
        candidate.location = request.candidate.location
        candidate.email = request.candidate.email
        candidate.current_role = request.candidate.current_role
        candidate.years_of_experience = request.candidate.years_of_experience

        if isinstance(request.candidate.skills, list):
            candidate.skills = (
                ", ".join(request.candidate.skills)
                if request.candidate.skills
                else None
            )
        else:
            candidate.skills = request.candidate.skills

        # FIX: Ensure portfolio_url is a string (asyncpg rejects Pydantic Url objects)
        if request.candidate.portfolio_url:
            candidate.portfolio_url = str(request.candidate.portfolio_url)

        logger = logging.getLogger("app.services.interview")
        plan = await cls.generate_interview_plan(
            role_title=request.role_title or "Candidate",
            job_description=request.job_description or "",
            skills_to_assess=request.skills_to_assess or [],
            custom_question=request.custom_question,
            candidate_context=_build_candidate_context(candidate),
        )
        logger.info(
            f"📋 CREATING INTERVIEW SESSION with {len(plan.questions)} questions"
        )

        if request.scheduled_start and request.scheduled_end:
            duration_minutes = int(
                (request.scheduled_end - request.scheduled_start).total_seconds() / 60
            )
        else:
            duration_minutes = 45

        session = InterviewSession(
            role=request.role_title or "Candidate",
            candidate_name=candidate.full_name,
            intro=plan.intro,
            questions_json=json.dumps([q.model_dump() for q in plan.questions]),
            rubric_json=json.dumps([r.model_dump() for r in plan.rubric]),
            closing=plan.closing,
            duration_minutes=duration_minutes,
            status="created",
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
            status="scheduled",  # It is ready to be joined
            participation_mode=request.participation_mode.value,
        )
        db.add(interview)
        await db.flush()

        summary = InterviewSummary(
            interview_id=interview.id,
            job_description=request.job_description,
            scoring_rubric=session.rubric_json,  # Mirror the rubric for easy access
            key_skills=", ".join(request.skills_to_assess)
            if request.skills_to_assess
            else None,
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
            title=interview.role_title,  # or role_title
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
            questions_total=len(json.loads(session.questions_json)),  # From AI Plan
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
        if (
            interview.questions_asked is not None
            and interview.questions_total is not None
        ):
            question_progress = (
                f"{interview.questions_asked}/{interview.questions_total}"
            )

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

    @staticmethod
    def _parse_assessment(summary: InterviewSummary | None) -> dict:
        if not summary or not summary.ai_assessment:
            return {"observation": None, "highlights": [], "red_flags": []}
        try:
            return json.loads(summary.ai_assessment)
        except (json.JSONDecodeError, ValueError):
            return {"observation": None, "highlights": [], "red_flags": []}

    @staticmethod
    def _assert_status_not_in(interview: Interview, *statuses: str) -> None:
        status_errors = {
            "completed": (
                "Interview is already completed",
                "already_completed",
                status.HTTP_409_CONFLICT,
            ),
            "cancelled": (
                "Interview has been cancelled",
                "already_cancelled",
                status.HTTP_409_CONFLICT,
            ),
            "in_progress": (
                "Interview is already in progress",
                "already_in_progress",
                status.HTTP_409_CONFLICT,
            ),
        }
        for s in statuses:
            if interview.status == s:
                message, code, status_code = status_errors[s]
                raise APIError(message, status_code=status_code, code=code)

    @staticmethod
    async def get_summary(
        interview_id: uuid.UUID, db: AsyncSession
    ) -> InterviewSummary | None:
        result = await db.execute(
            select(InterviewSummary).where(
                InterviewSummary.interview_id == interview_id
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _resolve_interview(
        interview_id: uuid.UUID,
        db: AsyncSession,
    ) -> Interview:
        """Resolve an interview by its ID or its session_id. Raises 404 if not found."""
        interview = await db.get(Interview, interview_id)

        if not interview:
            result = await db.execute(
                select(Interview).where(Interview.session_id == interview_id)
            )
            interview = result.scalar_one_or_none()

        if not interview:
            raise APIError(
                "Interview not found",
                status_code=status.HTTP_404_NOT_FOUND,
                code="interview_not_found",
            )

        return interview

    @staticmethod
    async def fetch_interview(
        interview_id: uuid.UUID,
        db: AsyncSession,
        user: User,
    ) -> Interview | None:
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

        return interview

    @staticmethod
    async def _fetch_criteria(db: AsyncSession, interview_id: uuid.UUID) -> list[str]:
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

    @staticmethod
    def _build_interview_response(
        interview: Interview,
        candidate: Candidate | None,
        summary: InterviewSummary | None,
        criteria: list[str] | None = None,
        **overrides,
    ) -> InterviewResponse:
        """Single place that constructs an InterviewResponse from DB objects."""
        meta = InterviewService._derive_interview_meta(interview)
        assessment = InterviewService._parse_assessment(summary)

        key_skills = (
            [s.strip() for s in summary.key_skills.split(",")]
            if summary and summary.key_skills
            else []
        )

        summary_resp = (
            InterviewSummaryResponse(
                job_description=summary.job_description if summary else None,
                scoring_rubric=summary.scoring_rubric if summary else None,
                ai_assessment=assessment.get("observation"),
                status=summary.status if summary else None,
                key_skills=summary.key_skills if summary else None,
            )
            if summary
            else None
        )

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
            summary=summary_resp,
            custom_question=summary.custom_question if summary else None,
            observation=assessment.get("observation"),
            highlights=assessment.get("highlights", []),
            red_flags=assessment.get("red_flags", []),
            criteria=criteria if criteria is not None else key_skills,
            key_skills=key_skills,
            created_at=interview.created_at,
            **meta,
            **overrides,
        )

    @staticmethod
    async def get_interview(
        interview_id: uuid.UUID,
        db: AsyncSession,
        user: User,
    ) -> InterviewResponse:
        interview = await InterviewService.fetch_interview(interview_id, db, user)

        candidate_result = await db.execute(
            select(Candidate).where(Candidate.id == interview.candidate_id)
        )
        candidate = candidate_result.scalar_one_or_none()

        summary = await InterviewService.get_summary(interview_id, db)

        return InterviewService._build_interview_response(interview, candidate, summary)

    @staticmethod
    async def update_interview_criteria(
        interview_id: uuid.UUID,
        request: UpdateCriteriaRequest,
        db: AsyncSession,
        user: User,
    ) -> CriteriaUpdateResponse:
        interview = await InterviewService.fetch_interview(interview_id, db, user)

        if interview.status not in ["draft", "scheduled"]:
            raise APIError(
                "Criteria can only be updated for draft interviews",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="bad_request",
            )

        workspace_id = interview.workspace_id
        summary = await InterviewService.get_summary(interview_id, db)
        if summary:
            summary.key_skills = ", ".join(request.criteria)

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
            await db.execute(
                delete(ScorecardScore).where(
                    ScorecardScore.scorecard_id == scorecard.id
                )
            )
            await db.flush()

        await _persist_criteria(db, scorecard, workspace_id, request.criteria)
        await db.commit()

        return CriteriaUpdateResponse(criteria=request.criteria)

    @staticmethod
    async def update_context(
        interview_id: uuid.UUID,
        request: UpdateContextRequest,
        db: AsyncSession,
        user: User,
    ) -> ContextUpdateResponse:
        interview = await InterviewService.fetch_interview(interview_id, db, user)
        if interview.status not in ["draft", "scheduled"]:
            raise APIError(
                "Cannot update an active or completed interview", status_code=400
            )

        if interview.role_title is None and request.role_title:
            interview.role_title = request.role_title

        summary = await InterviewService.get_summary(interview_id, db)
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
        return ContextUpdateResponse(
            interview_id=interview.id,
            status=interview.status,
            updated_at=interview.updated_at,
        )

    @staticmethod
    async def update_session_config(
        interview_id: uuid.UUID,
        request: UpdateAIConfigRequest,
        db: AsyncSession,
        user: User,
    ) -> AIConfigUpdateResponse:
        interview = await InterviewService.fetch_interview(interview_id, db, user)

        if interview.status not in ["draft", "scheduled"]:
            raise APIError(
                "Cannot update an active or completed interview", status_code=400
            )

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
        return AIConfigUpdateResponse(
            interview_id=interview.id,
            status=interview.status,
            participation_mode=interview.participation_mode,
            updated_at=interview.updated_at,
        )

    @staticmethod
    async def confirm_interview(
        interview_id: uuid.UUID,
        db: AsyncSession,
        user: User,
    ) -> dict:
        interview = await InterviewService.fetch_interview(interview_id, db, user)
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

        summary = await InterviewService.get_summary(interview.id, db)
        if not summary or not summary.job_description:
            raise APIError(
                "Cannot confirm without job description. Complete context setup first.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="incomplete_context",
            )

        interview.status = "scheduled"
        await db.commit()
        await db.refresh(interview)
        return InterviewConfirmResponse(
            interview_id=interview.id,
            status=interview.status,
            confirmed_at=interview.updated_at,
        )

    @staticmethod
    def _duration_from_schedule_or_session(
        interview: Interview, session: InterviewSession | None
    ) -> int:
        if interview.scheduled_start and interview.scheduled_end:
            return int(
                (interview.scheduled_end - interview.scheduled_start).total_seconds()
                / 60
            )
        if session and session.duration_minutes:
            return session.duration_minutes
        return 45

    @classmethod
    async def get_agent_config(cls, interview_id: uuid.UUID, db: AsyncSession) -> dict:
        """Return the full LiveKit agent context for an interview."""
        logger = logging.getLogger("app.services.interview")
        logger.info(f"\n🎙️ LIVEKIT AGENT CONFIG REQUEST for interview {interview_id}")

        interview = await cls._resolve_interview(interview_id, db)

        candidate = (
            await db.get(Candidate, interview.candidate_id)
            if interview.candidate_id
            else None
        )
        session = (
            await db.get(InterviewSession, interview.session_id)
            if interview.session_id
            else None
        )
        summary = await InterviewService.get_summary(interview.id, db)

        if interview.status == "scheduled":
            interview.status = "in_progress"
        if interview.started_at is None:
            interview.started_at = datetime.now(timezone.utc)

        transcript_result = await db.execute(
            select(InterviewTranscript).where(
                InterviewTranscript.interview_id == interview.id
            )
        )
        transcript = transcript_result.scalar_one_or_none()
        if transcript is None:
            db.add(InterviewTranscript(interview_id=interview.id, status="processing"))

        await db.commit()

        # Parse and log questions being sent to agent
        questions = (
            json.loads(session.questions_json)
            if session and session.questions_json
            else []
        )
        logger.info(f"   Candidate: {candidate.full_name if candidate else 'Unknown'}")
        logger.info(f"   Role: {interview.role_title}")
        logger.info(
            f"   Duration: {cls._duration_from_schedule_or_session(interview, session)} minutes"
        )
        logger.info(f"   Sending {len(questions)} questions to LiveKit agent:")
        for idx, q in enumerate(questions, 1):
            logger.info(f"     {idx}. {q.get('text', 'N/A')}")
        logger.info(f"   AI Tone: {interview.ai_tone}")
        logger.info(f"   LLM Model: {settings.INTERVIEWER_LLM}\n")

        return {
            "role": interview.role_title or (session.role if session else None),
            "intro": session.intro if session else "",
            "candidateName": (
                candidate.full_name
                if candidate
                else (session.candidate_name if session else "Candidate")
            ),
            "durationMinutes": cls._duration_from_schedule_or_session(
                interview, session
            ),
            "closing": session.closing if session else "",
            "questions": (
                json.loads(session.questions_json)
                if session and session.questions_json
                else []
            ),
            "rubric": (
                json.loads(session.rubric_json)
                if session and session.rubric_json
                else []
            ),
            "jobDescription": summary.job_description if summary else None,
            "keySkills": (
                [s.strip() for s in summary.key_skills.split(",") if s.strip()]
                if summary and summary.key_skills
                else []
            ),
            "participationMode": interview.participation_mode or "standard",
            "aiTone": interview.ai_tone,
            "model": settings.INTERVIEWER_LLM,
            "voice": settings.INTERVIEWER_TTS_VOICE,
            "language": settings.INTERVIEWER_STT_LANGUAGE,
            "tts": settings.INTERVIEWER_TTS,
            "stt": settings.INTERVIEWER_STT,
        }

    @staticmethod
    async def append_transcript_turn(
        interview_id: uuid.UUID, payload: dict, db: AsyncSession
    ) -> tuple[dict, int]:
        """Persist a single LiveKit transcript turn idempotently."""
        interview = await InterviewService._resolve_interview(interview_id, db)

        transcript_result = await db.execute(
            select(InterviewTranscript).where(
                InterviewTranscript.interview_id == interview.id
            )
        )
        transcript = transcript_result.scalar_one_or_none()
        if transcript is None:
            transcript = InterviewTranscript(
                interview_id=interview.id, status="processing"
            )
            db.add(transcript)
            await db.flush()

        existing_result = await db.execute(
            select(InterviewTranscriptTurn).where(
                InterviewTranscriptTurn.transcript_id == transcript.id,
                InterviewTranscriptTurn.sequence_no == payload["sequence_no"],
            )
        )
        existing = existing_result.scalar_one_or_none()
        if existing:
            return {
                "id": str(existing.id),
                "transcriptId": str(transcript.id),
                "deduplicated": True,
            }, status.HTTP_200_OK

        turn = InterviewTranscriptTurn(
            transcript_id=transcript.id,
            speaker=payload["speaker"],
            speaker_name=payload.get("speaker_name"),
            content=payload["content"],
            timestamp_sec=payload.get("timestamp_sec"),
            sequence_no=payload["sequence_no"],
            is_ai_question=payload.get("is_ai_question", False),
        )
        db.add(turn)
        await db.commit()
        await db.refresh(turn)
        return {
            "id": str(turn.id),
            "transcriptId": str(transcript.id),
            "deduplicated": False,
        }, status.HTTP_201_CREATED

    @staticmethod
    async def _persist_scorecard_report(
        interview: Interview,
        report: dict,
        db: AsyncSession,
    ) -> None:
        """Create or update scorecard, categories, scores, questions, and signals."""
        if not report.get("criteria"):
            return

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

        for idx, criterion in enumerate(report.get("criteria", [])):
            category = await _find_or_create_category(
                db, interview.workspace_id, criterion["name"], idx
            )

            score_result = await db.execute(
                select(ScorecardScore).where(
                    ScorecardScore.scorecard_id == scorecard.id,
                    ScorecardScore.category_id == category.id,
                )
            )
            score = score_result.scalar_one_or_none()

            score_pct = criterion.get("percentage")
            if score_pct is None and criterion.get("score") is not None:
                score_pct = criterion["score"] * 20
            confidence_val = criterion.get("confidence", 0)
            justification_val = criterion.get("justification")

            if not score:
                score = ScorecardScore(
                    scorecard_id=scorecard.id,
                    category_id=category.id,
                    score_pct=score_pct,
                    confidence=confidence_val,
                    justification=justification_val,
                    completed=True,
                )
                db.add(score)
                await db.flush()
            else:
                score.score_pct = score_pct
                score.confidence = confidence_val
                score.justification = justification_val
                score.completed = True
                await db.flush()

            await db.execute(
                delete(ScorecardQuestion).where(ScorecardQuestion.score_id == score.id)
            )
            await db.execute(
                delete(ScorecardSignal).where(ScorecardSignal.score_id == score.id)
            )
            await db.flush()

            for q_idx, q_content in enumerate(criterion.get("questions", [])):
                db.add(
                    ScorecardQuestion(
                        score_id=score.id,
                        content=q_content,
                        sort_order=q_idx,
                    )
                )

            signals_with_prefix = []
            for s_label in criterion.get("strengths", []):
                signals_with_prefix.append(f"[strength] {s_label}")
            for s_label in criterion.get("weaknesses", []):
                signals_with_prefix.append(f"[weakness] {s_label}")
            for s_label in criterion.get("signals", []):
                signals_with_prefix.append(s_label)

            for s_idx, s_label in enumerate(signals_with_prefix):
                db.add(
                    ScorecardSignal(
                        score_id=score.id,
                        label=s_label,
                        sort_order=s_idx,
                    )
                )

            # Delete old evidence first (FK depends on sub_rubrics), then sub-rubrics
            sr_ids = (
                (
                    await db.execute(
                        select(ScorecardSubRubric.id).where(
                            ScorecardSubRubric.score_id == score.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            await db.execute(
                delete(ScorecardEvidence).where(
                    ScorecardEvidence.sub_rubric_id.in_(sr_ids)
                )
            )
            await db.execute(
                delete(ScorecardEvidence).where(ScorecardEvidence.score_id == score.id)
            )
            await db.execute(
                delete(ScorecardSubRubric).where(
                    ScorecardSubRubric.score_id == score.id
                )
            )

            # Persist sub-rubrics
            for sr_idx, sub_rubric in enumerate(criterion.get("sub_rubrics", [])):
                sr = ScorecardSubRubric(
                    score_id=score.id,
                    name=sub_rubric["name"],
                    score_pct=sub_rubric.get("percentage")
                    or sub_rubric.get("score", 0),
                    confidence=sub_rubric.get("confidence", 0),
                    justification=sub_rubric.get("justification"),
                    strengths=sub_rubric.get("strengths", []),
                    weaknesses=sub_rubric.get("weaknesses", []),
                    sort_order=sr_idx,
                )
                db.add(sr)
                await db.flush()

                for ev in sub_rubric.get("evidence", []):
                    db.add(
                        ScorecardEvidence(
                            sub_rubric_id=sr.id,
                            question_turn_id=str(ev["question_turn_id"]).strip("[]"),
                            response_turn_id=str(ev["response_turn_id"]).strip("[]"),
                            reason=ev["reason"],
                        )
                    )

            # Persist section-level evidence
            for ev in criterion.get("evidence", []):
                db.add(
                    ScorecardEvidence(
                        score_id=score.id,
                        question_turn_id=str(ev["question_turn_id"]).strip("[]"),
                        response_turn_id=str(ev["response_turn_id"]).strip("[]"),
                        reason=ev["reason"],
                    )
                )

    @staticmethod
    async def _update_summary(
        interview: Interview,
        report: dict,
        db: AsyncSession,
    ) -> None:
        """Merge AI report data into the InterviewSummary and mark it completed."""
        summary = await InterviewService.get_summary(interview.id, db)
        if not summary:
            summary = InterviewSummary(interview_id=interview.id)
            db.add(summary)

        assessment = {}
        if summary.ai_assessment:
            try:
                assessment = json.loads(summary.ai_assessment)
            except Exception:
                assessment = {}

        summary_text = (
            report.get("summary") or report.get("overview") or report.get("observation")
        )

        if summary_text is not None:
            assessment["summary"] = summary_text
            assessment["overview"] = summary_text
            assessment["observation"] = summary_text

        if "highlights" in report:
            assessment["highlights"] = InterviewService._clean_string_list(
                report.get("highlights")
            )

        red_flags = (
            report.get("red_flags")
            if "red_flags" in report
            else report.get("redFlags", report.get("redflags"))
        )
        if red_flags is not None:
            assessment["red_flags"] = InterviewService._clean_string_list(red_flags)

        confidence = InterviewService._coerce_confidence(
            report.get("confidence", report.get("confidence_score"))
        )
        if confidence is not None:
            assessment["confidence"] = confidence

        assessment["overall_recommendation"] = report.get("overall")

        summary.ai_assessment = json.dumps(assessment)
        summary.status = "completed"
        summary.generated_at = datetime.now(timezone.utc)

    @staticmethod
    def _clean_string_list(value: object) -> list[str]:
        """Normalize LLM/list payloads into compact string arrays for the UI."""
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            return []

        cleaned: list[str] = []
        for item in value:
            if isinstance(item, dict):
                item = (
                    item.get("description") or item.get("content") or item.get("text")
                )
            if not isinstance(item, str):
                continue
            text = item.strip()
            if text:
                cleaned.append(text)
        return cleaned

    @staticmethod
    def _coerce_confidence(value: object) -> float | None:
        if value is None:
            return None
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return None
        if confidence > 1:
            confidence = confidence / 100
        return max(0.0, min(confidence, 1.0))

    @staticmethod
    async def _persist_transcript(
        interview: Interview,
        transcript: list[dict] | None,
        db: AsyncSession,
    ) -> InterviewTranscript:
        """Load or create the transcript record, then deduplicate and save turns."""
        transcript_result = await db.execute(
            select(InterviewTranscript).where(
                InterviewTranscript.interview_id == interview.id
            )
        )
        transcript_obj = transcript_result.scalar_one_or_none()
        if not transcript_obj:
            transcript_obj = InterviewTranscript(
                interview_id=interview.id, status="processing"
            )
            db.add(transcript_obj)
            await db.flush()

        for turn_data in transcript or []:
            existing_result = await db.execute(
                select(InterviewTranscriptTurn).where(
                    InterviewTranscriptTurn.transcript_id == transcript_obj.id,
                    InterviewTranscriptTurn.sequence_no == turn_data["sequence_no"],
                )
            )
            if not existing_result.scalar_one_or_none():
                db.add(
                    InterviewTranscriptTurn(
                        transcript_id=transcript_obj.id,
                        speaker=turn_data["speaker"],
                        speaker_name=turn_data.get("speaker_name"),
                        content=turn_data.get("content") or turn_data.get("text") or "",
                        timestamp_sec=turn_data.get("timestamp_sec"),
                        sequence_no=turn_data["sequence_no"],
                        is_ai_question=turn_data.get("is_ai_question", False),
                    )
                )

        return transcript_obj

    @staticmethod
    async def process_interview_result(
        interview_id: uuid.UUID,
        transcript: list[dict] | None,
        report: dict | None,
        db: AsyncSession,
    ) -> dict:
        interview = await InterviewService._resolve_interview(interview_id, db)

        await InterviewService._persist_transcript(interview, transcript, db)

        if report and not isinstance(report, dict):
            report = {"summary": str(report), "criteria": [], "overall": None}

        if report:
            await InterviewService._persist_scorecard_report(interview, report, db)
            await InterviewService._update_summary(interview, report, db)

        # Update status of Interview & associated InterviewSession
        interview.status = "completed"

        if interview.session_id:
            session = await db.get(InterviewSession, interview.session_id)
            if session:
                session.status = "completed"
                session.completed_at = datetime.now(timezone.utc)
                session.transcript_json = (
                    json.dumps(transcript) if transcript is not None else None
                )
                session.report_json = json.dumps(report) if report is not None else None

        await db.commit()

        await safe_notify(
            db,
            user_id=interview.interviewer_id,
            type="report",
            title="Interview Summary Ready",
            action_url=f"/interviews/{interview.id}",
            label="report notification",
        )

        return {"status": "success", "message": "Result saved successfully"}

    @staticmethod
    async def stop_transcript(
        interview_id: uuid.UUID,
        db: AsyncSession,
        user: User,
    ) -> TranscriptStopResponse:
        interview = await InterviewService.fetch_interview(interview_id, db, user)

        InterviewService._assert_status_not_in(interview, "completed", "cancelled")

        if interview.status != "in_progress":
            raise APIError(
                "Transcript can only be stopped while the interview is in progress",
                status_code=status.HTTP_409_CONFLICT,
                code="invalid_status",
            )

        interview.status = "completed"
        await db.commit()
        await db.refresh(interview)

        return TranscriptStopResponse(
            interview_id=interview.id,
            status=interview.status,
        )

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
        interview = await InterviewService.fetch_interview(interview_id, db, user)

        if interview.status in ("cancelled", "completed"):
            raise APIError(
                f"Cannot cancel a {interview.status} interview",
                status_code=status.HTTP_409_CONFLICT,
                code="invalid_status",
            )

        interview.status = "cancelled"
        await db.flush()

        candidate_result = await db.execute(
            select(Candidate).where(Candidate.id == interview.candidate_id)
        )
        candidate = candidate_result.scalar_one_or_none()

        summary = await InterviewService.get_summary(interview_id, db)
        criteria = await InterviewService._fetch_criteria(db, interview.id)
        await db.commit()

        return InterviewService._build_interview_response(
            interview, candidate, summary, criteria=criteria
        )

    @staticmethod
    async def get_summary_record(
        interview_id: uuid.UUID,
        db: AsyncSession,
        user: User,
    ) -> InterviewSummaryDetailResponse:
        await InterviewService.fetch_interview(interview_id, db, user)

        summary = await InterviewService.get_summary(interview_id, db)
        if not summary:
            return {
                "interview_id": str(interview_id),
                "status": "pending",
                "summary": None,
                "observation": None,
                "highlights": [],
                "red_flags": [],
                "confidence": None,
                "custom_question": None,
                "key_skills": [],
            }

        assessment = {}
        if summary.ai_assessment:
            try:
                assessment = json.loads(summary.ai_assessment)
            except (json.JSONDecodeError, ValueError):
                assessment = {}

        summary_text = (
            assessment.get("summary")
            or assessment.get("overview")
            or assessment.get("observation")
        )
        result_dict = {
            "interview_id": str(interview_id),
            "status": summary.status,
            "summary": summary_text,
            "observation": assessment.get("observation") or summary_text,
            "highlights": assessment.get("highlights", []),
            "red_flags": assessment.get("red_flags", []),
            "confidence": InterviewService._coerce_confidence(
                assessment.get("confidence")
            ),
            "custom_question": summary.custom_question,
            "key_skills": summary.key_skills.split(",") if summary.key_skills else [],
        }
        return InterviewSummaryDetailResponse(**result_dict)

    @staticmethod
    async def retry_summary(
        interview_id: uuid.UUID,
        db: AsyncSession,
        user: User,
    ) -> dict:
        await InterviewService.fetch_interview(interview_id, db, user)
        summary = await InterviewService.get_summary(interview_id, db)
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
        interview = await InterviewService.fetch_interview(interview_id, db, user)

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

    @staticmethod
    async def get_scorecard(
        interview_id: uuid.UUID,
        db: AsyncSession,
        user: User,
        view: str = "detailed",
    ) -> InterviewScorecardResponse:
        """Retrieve the evaluated scorecard with HSL scores, categories,
        questions, and signals.

        - `view=detailed` (default): full scorecard with questions, signals,
          justification.
        - `view=summary`: only scores, confidence, strengths, weaknesses, and
          evidence.
        """
        interview = await InterviewService.fetch_interview(interview_id, db, user)

        sc_result = await db.execute(
            select(InterviewScorecard).where(
                InterviewScorecard.interview_id == interview.id
            )
        )
        scorecard = sc_result.scalar_one_or_none()
        if not scorecard:
            return {
                "interview_id": str(interview_id),
                "sections": [],
            }

        scores_result = await db.execute(
            select(ScorecardScore)
            .join(ScorecardCategory, ScorecardScore.category_id == ScorecardCategory.id)
            .where(ScorecardScore.scorecard_id == scorecard.id)
            .order_by(ScorecardCategory.sort_order)
        )
        scores = scores_result.scalars().all()

        sections = []
        for idx, score in enumerate(scores):
            # Fetch Category
            category = await db.get(ScorecardCategory, score.category_id)
            category_name = category.name if category else "Unknown"

            # Fetch Questions
            questions_result = await db.execute(
                select(ScorecardQuestion)
                .where(ScorecardQuestion.score_id == score.id)
                .order_by(ScorecardQuestion.sort_order)
            )
            questions = [q.content for q in questions_result.scalars().all()]

            # Fetch Signals
            signals_result = await db.execute(
                select(ScorecardSignal)
                .where(ScorecardSignal.score_id == score.id)
                .order_by(ScorecardSignal.sort_order)
            )
            raw_signals = [s.label for s in signals_result.scalars().all()]

            strengths = []
            weaknesses = []
            clean_signals = []
            for label in raw_signals:
                lower = label.lower()
                if lower.startswith("[strength]"):
                    clean = label[len("[strength]") :].strip()
                    strengths.append(clean)
                    clean_signals.append(clean)
                elif lower.startswith("[weakness]"):
                    clean = label[len("[weakness]") :].strip()
                    weaknesses.append(clean)
                    clean_signals.append(clean)
                else:
                    clean_signals.append(label)

            # Load sub-rubrics
            sub_rubrics_result = await db.execute(
                select(ScorecardSubRubric)
                .where(ScorecardSubRubric.score_id == score.id)
                .order_by(ScorecardSubRubric.sort_order)
            )
            sub_rubrics_db = sub_rubrics_result.scalars().all()

            sub_rubrics = []
            for sr in sub_rubrics_db:
                sr_evidence_result = await db.execute(
                    select(ScorecardEvidence).where(
                        ScorecardEvidence.sub_rubric_id == sr.id
                    )
                )
                sr_evidence = [
                    {
                        "question_turn_id": e.question_turn_id,
                        "response_turn_id": e.response_turn_id,
                        "reason": e.reason,
                    }
                    for e in sr_evidence_result.scalars().all()
                ]

                sub_rubrics.append(
                    {
                        "id": sr.name.lower().replace(" ", "_"),
                        "title": sr.name,
                        "score": sr.score_pct or 0,
                        "confidence": sr.confidence or 0,
                        "score_bar_percent": sr.score_pct or 0,
                        "strengths": sr.strengths or [],
                        "weaknesses": sr.weaknesses or [],
                        "justification": sr.justification,
                        "evidence": sr_evidence,
                        "expanded": False,
                    }
                )

            # Load section-level evidence
            section_evidence_result = await db.execute(
                select(ScorecardEvidence).where(
                    ScorecardEvidence.score_id == score.id,
                    ScorecardEvidence.sub_rubric_id.is_(None),
                )
            )
            section_evidence = [
                {
                    "question_turn_id": e.question_turn_id,
                    "response_turn_id": e.response_turn_id,
                    "reason": e.reason,
                }
                for e in section_evidence_result.scalars().all()
            ]

            sections.append(
                {
                    "id": category_name.lower().replace(" ", "_"),
                    "title": category_name,
                    "score": score.score_pct or 0,
                    "confidence": score.confidence or 0,
                    "score_bar_percent": score.score_pct or 0,
                    "questions_asked": questions,
                    "signals_detected": clean_signals,
                    "strengths": strengths,
                    "weaknesses": weaknesses,
                    "justification": score.justification,
                    "evidence": section_evidence,
                    "expanded": idx == 0,
                    "sub_rubrics": sub_rubrics,
                }
            )

        if view == "summary":
            for section in sections:
                section["questions_asked"] = []
                section["signals_detected"] = []

        scores_list = [s.score_pct or 0 for s in scores]
        total_score = round(sum(scores_list) / len(scores_list)) if scores_list else 0
        confidences = [s.confidence or 0 for s in scores]
        overall_confidence = (
            round(sum(confidences) / len(confidences)) if confidences else 0
        )

        return InterviewScorecardResponse(
            interview_id=interview_id,
            total_score=total_score,
            overall_confidence=overall_confidence,
            sections=[ScorecardSection(**s) for s in sections],
        )

    @staticmethod
    async def get_profile(
        interview_id: uuid.UUID,
        db: AsyncSession,
        user: User,
    ) -> dict:
        interview = await InterviewService.fetch_interview(interview_id, db, user)

        candidate = None
        if interview.candidate_id:
            candidate = await db.get(Candidate, interview.candidate_id)

        # 3. Format duration string from scheduled start/end or fall back
        duration_str = "45min"
        if interview.scheduled_start and interview.scheduled_end:
            diff_seconds = (
                interview.scheduled_end - interview.scheduled_start
            ).total_seconds()
            hours = int(diff_seconds // 3600)
            minutes = int((diff_seconds % 3600) // 60)
            if hours > 0:
                duration_str = (
                    f"{hours}hr {minutes}min" if minutes > 0 else f"{hours}hr"
                )
            else:
                duration_str = f"{minutes}min"

        result = {
            "candidate": {
                "name": candidate.full_name if candidate else "Unknown",
                "email": candidate.email if candidate else None,
                "phone": candidate.phone if candidate else None,
                "resume_url": candidate.resume_url if candidate else None,
                "portfolio_url": candidate.portfolio_url if candidate else None,
            },
            "interview": {
                "platform": interview.platform or "livekit",
                "duration": duration_str,
                "questions_answered": interview.questions_asked or 0,
                "questions_total": interview.questions_total or 0,
                "status": interview.status or "scheduled",
            },
        }

        return InterviewProfileResponse(
            candidate=CandidateProfileDetail(**result["candidate"]),
            interview=InterviewProfileDetail(**result["interview"]),
        )

    @staticmethod
    async def rejoin_session(
        interview_id: uuid.UUID,
        db: AsyncSession,
        user: User,
    ) -> RejoinSessionResponse:
        """Idempotently reset interview state to reconnect an active session."""
        interview = await InterviewService.fetch_interview(interview_id, db, user)
        # Update status of Interview to in_progress
        interview.status = "in_progress"
        await db.commit()

        return RejoinSessionResponse(
            success=True,
            session_status="reconnecting",
            interview_id=interview_id,
            message="Reconnecting to session...",
        )
