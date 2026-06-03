"""Onboarding step endpoints."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import VerifiedUser
from app.core.responses import APIResponse, success
from app.core.utils import safe_notify
from app.db.session import get_session
from app.schemas.onboarding import (
    OnboardingIntegrationsRequest,
    OnboardingPreferencesRequest,
    OnboardingRoleRequest,
    OnboardingSubmissionResponse,
)
from app.services.onboarding import OnboardingService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/role", response_model=APIResponse[None])
async def set_role(
    payload: OnboardingRoleRequest,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    await OnboardingService.set_role(db, user, payload)
    return success(message="Role saved")


@router.post("/preferences", response_model=APIResponse[None])
async def set_preferences(
    payload: OnboardingPreferencesRequest,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    await OnboardingService.set_meeting_preferences(db, user, payload)
    return success(message="Preferences saved")


@router.post("/integrations", response_model=APIResponse[None])
async def save_integrations(
    payload: OnboardingIntegrationsRequest,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    await OnboardingService.save_integrations(db, user, payload)

    if payload.integrations:
        await safe_notify(
            db,
            user_id=user.id,
            type="integration",
            title="Integration Connected",
            description=f"{payload.integrations} has been connected to your workspace.",
            label="integration notification",
        )

    return success(message="Integrations saved")


@router.post("/submission", response_model=APIResponse[OnboardingSubmissionResponse])
async def submission(user: VerifiedUser, db: AsyncSession = Depends(get_session)):
    await OnboardingService.complete_submission(db, user)
    return success(
        {"success": True, "onboardingCompleted": True}, message="Onboarding completed"
    )
