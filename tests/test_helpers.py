from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.interview import Candidate
from app.models.user import User
from httpx import AsyncClient
from app.services.auth import AuthService
from app.services.interview import _get_or_create_workspace
from app.schemas.interview import (
    InterviewPlanOutput,
    InterviewQuestionSchema,
    RubricCriterion,
)


DEFAULT_INTERVIEW_CONFIG: dict[str, Any] = {
    "role_title": "Senior Backend Engineer",
    "platform": "zoom",
    "call_link": "https://zoom.us/j/123456789",
    "scheduled_start": "2026-06-01T17:30:00Z",
    "scheduled_end": "2026-06-01T18:30:00Z",
    "ai_tone": "professional",
    "skills_to_assess": ["Communication", "API Design", "Problem Solving"],
    "custom_question": "Validate backend architecture thinking.",
}


def patch_generate_interview_plan():
    # UPDATED PATH: Point to the new location in InterviewService
    return patch(
        "app.services.interview.InterviewService.generate_interview_plan",
        new=AsyncMock(return_value=get_default_interview_plan()),
    )


async def get_user_from_token(db_session: AsyncSession, token: str) -> User:
    claims = await AuthService.decode_access_token(token)
    return await db_session.get(User, uuid.UUID(claims["sub"]))


async def create_candidate_for_user(
    db_session: AsyncSession,
    token: str,
    **kwargs
) -> Candidate:
    user = await get_user_from_token(db_session, token)
    workspace_id = await _get_or_create_workspace(db_session, user)
    
    # Convert list to string if provided
    skills = kwargs.get("skills")
    skills_str = ", ".join(skills) if isinstance(skills, list) else skills

    candidate = Candidate(
        workspace_id=workspace_id,
        full_name=kwargs.get("full_name", "Test Candidate"),
        email=kwargs.get("email", "test@example.com"),
        phone=kwargs.get("phone", "+1555000111"),
        current_role=kwargs.get("current_role", "Engineer"),
        years_of_experience=kwargs.get("years_of_experience", 5),
        skills=skills_str,
        location=kwargs.get("location", "Remote"),
    )
    db_session.add(candidate)
    await db_session.flush() # Use flush so we don't end the transaction early
    await db_session.refresh(candidate)
    return candidate

async def create_interview_via_route(
    client: AsyncClient,
    db_session: AsyncSession,
    token: str,
    candidate_kwargs: dict[str, Any] | None = None,
    interview_overrides: dict[str, Any] | None = None,
    expect_status: int = 201,
):
    # 1. Create the candidate in the DB first
    candidate = await create_candidate_for_user(
        db_session=db_session,
        token=token,
        ** (candidate_kwargs or {})
    )
    
    # 2. Build the payload using that candidate's REAL ID
    payload = build_interview_payload(candidate, interview_overrides)
    
    # 3. Patch the AI call so it doesn't hit Gemini
    with patch_generate_interview_plan():
        response = await client.post(
            "/api/v1/interviews",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
    
    # We remove the hard assertion here so the test can handle the status check
    return response


def build_interview_payload(
    candidate: Candidate,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "candidate": {
            "candidate_id": str(candidate.id),
            "full_name": candidate.full_name,
            "email": candidate.email,
            "phone": candidate.phone,
            "current_role": candidate.current_role,
            "years_of_experience": candidate.years_of_experience or 0,
            "skills": [s.strip() for s in candidate.skills.split(",")]
            if candidate.skills
            else [],
            "location": candidate.location,
            "portfolio_url": candidate.portfolio_url,
        },
        **DEFAULT_INTERVIEW_CONFIG,
    }
    if overrides:
        payload.update(overrides)
    return payload


def get_default_interview_plan() -> InterviewPlanOutput:
    return InterviewPlanOutput(
        intro="Welcome to the interview. I will ask questions to assess your fit.",
        questions=[
            InterviewQuestionSchema(
                text="Tell me about a time you solved a hard engineering problem.",
                followUpHint="Look for clarity, tradeoffs, and impact.",
                maxFollowUps=2,
            )
        ],
        rubric=[
            RubricCriterion(
                name="Communication",
                description="Answers are clear, structured, and concise.",
                weight=1,
            )
        ],
        closing="Thank you for your time. We'll follow up with next steps.",
    )


def patch_generate_interview_plan():
    return patch(
        "app.services.ai_generation_service.AIGenerationService.generate_interview_plan",
        new=AsyncMock(return_value=get_default_interview_plan()),
    )
