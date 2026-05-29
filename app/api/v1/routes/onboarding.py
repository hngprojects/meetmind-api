"""Onboarding step endpoints."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import VerifiedUser
from app.core.responses import success
from app.db.session import get_session
from app.schemas.onboarding import (
    OnboardingIntegrationsRequest,
    OnboardingPreferencesRequest,
    OnboardingRoleRequest,
)
from app.services.notification_service import NotificationService
from app.services.onboarding import OnboardingService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/role")
async def set_role(
    payload: OnboardingRoleRequest,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    await OnboardingService.set_role(db, user, payload)
    return success(message="Role saved")


@router.post("/preferences")
async def set_preferences(
    payload: OnboardingPreferencesRequest,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    await OnboardingService.set_meeting_preferences(db, user, payload)
    return success(message="Preferences saved")


@router.post("/integrations")
async def save_integrations(
    payload: OnboardingIntegrationsRequest,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    await OnboardingService.save_integrations(db, user, payload)

    try:
        if payload.integrations:
            await NotificationService.create(
                db=db,
                user_id=user.id,
                type="integration",
                title="Integration Connected",
                description=(
                    f"{payload.integrations} has been connected to your workspace."
                ),
            )
    except Exception:
        logger.exception("Failed to create integration notification")

    return success(message="Integrations saved")


@router.post("/submission")
async def submission(user: VerifiedUser, db: AsyncSession = Depends(get_session)):
    await OnboardingService.complete_submission(db, user)
    return success(
        {"success": True, "onboardingCompleted": True}, message="Onboarding completed"
    )


@router.post("/language")
async def language():
    return success(message="Language saved")


@router.post("/invite")
async def invite():
    return success(message="Invite sent")


@router.post("/trial")
async def trial(user: VerifiedUser, db: AsyncSession = Depends(get_session)):
    await OnboardingService.complete_submission(db, user)
    return success(
        {"success": True, "onboardingCompleted": True}, message="Onboarding completed"
    )
